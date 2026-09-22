"""Rotulagem fraca do corpus com a Gemini. OFFLINE — CLAUDE.md regra 3.

Lê os exemplos sem `rotulo_fraco`, manda em lotes para a Gemini com o prompt
versionado em `prompt_v1.md`, valida a resposta e grava casando por
`id_comentario`.

Decisões que importam para a banca:

- **Texto ORIGINAL**, nunca o `texto_modelo`. A conversão de emoji existe por
  limitação do tokenizer do BERTimbau; a Gemini lê emoji nativamente. Mandar o
  texto convertido daria à Gemini uma entrada diferente da que o avaliador humano
  vê, e a comparação entre os dois perderia o sentido.
- **Temperatura 0** e categoria fechada: rodar de novo o mesmo lote tem que dar o
  mesmo rótulo.
- **Casamento por `id_comentario`**, não por posição no array da resposta.
- **Retomável**: só busca quem ainda está com `rotulo_fraco` nulo, então uma queda
  no meio não obriga a refazer (nem a re-gastar cota).
- **Metadados gravados** em `ml/rotulagem/metadados_rotulagem.json`: modelo exato,
  data, versão do prompt, temperatura e número de chamadas. "Rotulado com Gemini"
  sem esses campos não é reproduzível.

Uso:
    python -m ml.rotulagem.rotular_fraco --id-execucao 4
    python -m ml.rotulagem.rotular_fraco --id-execucao 4 --limite 50   # ensaio
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from collections import Counter
from datetime import UTC, datetime

import asyncpg

from ml.config import CLASSES, carregar_env_ml, chave_gemini, dsn_postgres
from ml.rotulagem.gemini import ClienteGemini, ErroGemini

logger = logging.getLogger("rotular_fraco")

VERSAO_PROMPT = "v1"
ARQUIVO_PROMPT = "prompt_v1.md"
TEMPERATURA = 0.0

# ~25 por chamada: lote grande economiza cota e contexto, mas quanto maior, mais
# cara fica a repetição quando um item sai inválido e o lote inteiro é refeito.
TAMANHO_LOTE = 25

MODELO_PADRAO = "gemini-2.0-flash"

INSTRUCAO_SISTEMA = (
    "Você é um anotador de sentimento de comentários do YouTube em português do "
    "Brasil. Sua tarefa é classificar cada comentário em exatamente uma de três "
    "classes. Você responde SOMENTE com JSON válido, sem texto antes ou depois, "
    "sem markdown."
)

# Mantido em sincronia com prompt_v1.md — o teste
# `test_prompt_do_codigo_bate_com_o_arquivo` falha se divergirem.
PROMPT_TAREFA = """Classifique o sentimento de cada comentário abaixo em relação à campanha,
produto ou marca anunciada.

CLASSES (escolha exatamente uma por comentário):
- "positivo": aprovação, elogio, desejo de comprar, defesa da campanha/produto/marca.
- "negativo": reprovação, crítica, reclamação, decepção, hostilidade à campanha/produto/marca.
- "neutro": nem aprovação nem reprovação — pergunta, constatação, relato, off-topic ou ambíguo.

REGRAS:
1. Ironia e sarcasmo valem pelo sentido real, não pelo literal. Na dúvida entre
   ironia e elogio sincero, use "neutro".
2. Comentário misto: vence o que vem depois do "mas" (ou "porém", "só que",
   "no entanto").
3. Gíria e erro de escrita não mudam a classe.
4. Emoji conta como sinal de sentimento, no mesmo peso do texto. Só emoji de riso
   ("😂") sem mais nada é "neutro".
5. Pergunta é "neutro", a menos que carregue julgamento explícito.
6. Não invente contexto: classifique só pelo que está escrito. Se depender de algo
   que você não tem, use "neutro".

O sentimento é sobre a CAMPANHA, o PRODUTO ou a MARCA. Elogio ao ator, a outro
comentarista ou a assunto sem ligação com a marca não torna o comentário positivo.

COMENTÁRIOS:
{comentarios_json}

RESPONDA SOMENTE com um array JSON, um objeto por comentário, na mesma ordem,
sem markdown e sem texto fora do JSON:
[{{"id_comentario": <int>, "rotulo": "positivo"|"negativo"|"neutro"}}]

O array deve ter exatamente {quantidade} objetos."""


class RespostaInvalida(Exception):
    """A resposta não bate com o contrato; o lote é refeito."""


def extrair_json(bruto: str) -> list[dict]:
    """Converte a resposta em lista de objetos, tolerando cerca de markdown.

    `responseMimeType: application/json` já deveria bastar, mas um modelo que
    devolva ```json ... ``` não pode derrubar a rodada inteira.
    """
    texto = bruto.strip()
    cerca = re.match(r"^```(?:json)?\s*(.*?)\s*```$", texto, re.S)
    if cerca:
        texto = cerca.group(1)

    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise RespostaInvalida(f"nao e JSON valido: {erro}; inicio={texto[:120]!r}") from erro

    if not isinstance(dados, list):
        raise RespostaInvalida(f"esperado array, veio {type(dados).__name__}")
    return dados


def validar_lote(itens: list[dict], ids_enviados: set[int]) -> dict[int, str]:
    """Confere o contrato e devolve `{id_comentario: rotulo}`.

    Categoria fechada: rótulo fora das três classes é erro e refaz o lote, nunca
    vira um rótulo novo nem cai num "neutro" por omissão.
    """
    rotulos: dict[int, str] = {}

    for item in itens:
        if not isinstance(item, dict):
            raise RespostaInvalida(f"item nao e objeto: {item!r}")

        id_comentario = item.get("id_comentario")
        rotulo = item.get("rotulo")

        if not isinstance(id_comentario, int):
            raise RespostaInvalida(f"id_comentario ausente ou nao inteiro: {item!r}")
        if id_comentario not in ids_enviados:
            raise RespostaInvalida(f"id_comentario {id_comentario} nao estava no lote")
        if id_comentario in rotulos:
            raise RespostaInvalida(f"id_comentario {id_comentario} repetido na resposta")
        if rotulo not in CLASSES:
            raise RespostaInvalida(f"rotulo {rotulo!r} fora de {CLASSES} (id={id_comentario})")

        rotulos[id_comentario] = rotulo

    faltando = ids_enviados - set(rotulos)
    if faltando:
        raise RespostaInvalida(f"faltaram {len(faltando)} id(s): {sorted(faltando)[:10]}")

    return rotulos


def montar_prompt(lote: list[asyncpg.Record]) -> str:
    comentarios = [{"id_comentario": r["id_comentario"], "texto": r["texto"]} for r in lote]
    return PROMPT_TAREFA.format(
        comentarios_json=json.dumps(comentarios, ensure_ascii=False, indent=1),
        quantidade=len(lote),
    )


async def carregar_pendentes(
    conexao: asyncpg.Connection, id_execucao: int, limite: int | None
) -> list[asyncpg.Record]:
    """Exemplos ainda sem rótulo fraco, com o texto ORIGINAL.

    A retomada mora aqui: `rotulo_fraco IS NULL` é o que faz uma segunda execução
    pular o que já foi rotulado, sem gastar cota de novo.
    """
    sql = """
        SELECT e.id_comentario, e.texto
        FROM exemplos_treinamento e
        JOIN comentarios c ON c.id_comentario = e.id_comentario
        JOIN videos v ON v.id_video = c.id_video
        WHERE v.id_execucao = $1 AND e.rotulo_fraco IS NULL
        ORDER BY e.id_comentario
    """
    if limite is not None:
        sql += f" LIMIT {int(limite)}"
    return await conexao.fetch(sql, id_execucao)


async def gravar_rotulos(conexao: asyncpg.Connection, rotulos: dict[int, str]) -> int:
    """Grava casando por id_comentario — a chave estável do corpus.

    `executemany` do asyncpg não devolve contagem de linhas, então o retorno é o
    tamanho do lote pedido. Os ids vêm de `carregar_pendentes`, ou seja, do próprio
    banco: um id que não casasse já teria sido barrado por `validar_lote`.
    """
    await conexao.executemany(
        "UPDATE exemplos_treinamento SET rotulo_fraco = $2 WHERE id_comentario = $1",
        list(rotulos.items()),
    )
    return len(rotulos)


async def distribuicao(conexao: asyncpg.Connection, id_execucao: int) -> Counter:
    linhas = await conexao.fetch(
        """
        SELECT e.rotulo_fraco, count(*) AS n
        FROM exemplos_treinamento e
        JOIN comentarios c ON c.id_comentario = e.id_comentario
        JOIN videos v ON v.id_video = c.id_video
        WHERE v.id_execucao = $1
        GROUP BY e.rotulo_fraco
        """,
        id_execucao,
    )
    return Counter({linha["rotulo_fraco"]: linha["n"] for linha in linhas})


def gravar_metadados(cliente: ClienteGemini, total_rotulado: int, lotes: int, caminho) -> None:
    """Sem isto, "rotulado com Gemini" não é reproduzível nem defensável."""
    metadados = {
        "modelo": cliente.modelo,
        "data_utc": datetime.now(UTC).isoformat(),
        "versao_prompt": VERSAO_PROMPT,
        "arquivo_prompt": ARQUIVO_PROMPT,
        "temperatura": TEMPERATURA,
        "tamanho_lote": TAMANHO_LOTE,
        "chamadas_api": cliente.chamadas,
        "lotes": lotes,
        "exemplos_rotulados": total_rotulado,
        "texto_enviado": "original (coluna texto), nunca texto_modelo",
        "classes": list(CLASSES),
    }
    caminho.write_text(json.dumps(metadados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("metadados gravados em %s", caminho)


async def rotular(id_execucao: int, limite: int | None) -> Counter:
    from ml.config import DIRETORIO_ML

    env = carregar_env_ml()
    cliente = ClienteGemini(
        api_key=chave_gemini(),
        modelo=env.get("GEMINI_MODELO") or MODELO_PADRAO,
        temperatura=TEMPERATURA,
    )
    logger.info(
        "modelo=%s temperatura=%s prompt=%s lote=%s",
        cliente.modelo,
        TEMPERATURA,
        VERSAO_PROMPT,
        TAMANHO_LOTE,
    )

    conexao = await asyncpg.connect(dsn_postgres())
    total_rotulado = 0
    lotes = 0
    try:
        pendentes = await carregar_pendentes(conexao, id_execucao, limite)
        if not pendentes:
            logger.info("nada pendente: todos os exemplos ja tem rotulo_fraco")
            return await distribuicao(conexao, id_execucao)

        logger.info("pendentes=%s", len(pendentes))

        for inicio in range(0, len(pendentes), TAMANHO_LOTE):
            lote = pendentes[inicio : inicio + TAMANHO_LOTE]
            ids = {registro["id_comentario"] for registro in lote}
            lotes += 1

            for tentativa in range(3):
                try:
                    bruto = cliente.gerar(INSTRUCAO_SISTEMA, montar_prompt(lote))
                    rotulos = validar_lote(extrair_json(bruto), ids)
                    break
                except RespostaInvalida as erro:
                    # Rótulo fora da categoria fechada, item faltando ou id estranho:
                    # refaz o lote. Nunca "conserta" a resposta.
                    logger.warning(
                        "resposta invalida no lote %s (tentativa %s/3): %s",
                        lotes,
                        tentativa + 1,
                        erro,
                    )
                    if tentativa == 2:
                        raise
                except ErroGemini:
                    raise

            await gravar_rotulos(conexao, rotulos)
            total_rotulado += len(rotulos)
            logger.info(
                "lote %s: %s rotulos gravados (acumulado %s/%s)",
                lotes,
                len(rotulos),
                total_rotulado,
                len(pendentes),
            )

        gravar_metadados(
            cliente, total_rotulado, lotes, DIRETORIO_ML / "rotulagem" / "metadados_rotulagem.json"
        )
        return await distribuicao(conexao, id_execucao)
    finally:
        await conexao.close()


def relatar(dist: Counter) -> bool:
    """Imprime a distribuição e diz se o CHECKPOINT passou.

    Uma classe acima de 85% ou abaixo de 5% quase sempre é prompt ruim, não corpus
    desbalanceado: o prompt precisa de revisão antes de qualquer treino.
    """
    total = sum(dist.values())
    rotulados = total - dist.get(None, 0)

    logger.info("")
    logger.info("=" * 62)
    logger.info("DISTRIBUICAO DO ROTULO FRACO")
    logger.info("=" * 62)
    logger.info("  exemplos na execucao ... %5d", total)
    logger.info("  rotulados .............. %5d", rotulados)
    if dist.get(None):
        logger.info("  ainda sem rotulo ....... %5d", dist[None])

    problema = False
    if rotulados:
        logger.info("-" * 62)
        for classe in CLASSES:
            n = dist.get(classe, 0)
            pct = 100 * n / rotulados
            alerta = ""
            if pct > 85:
                alerta = "  <-- ACIMA DE 85%"
                problema = True
            elif pct < 5:
                alerta = "  <-- ABAIXO DE 5%"
                problema = True
            logger.info("  %-9s %5d (%5.1f%%)%s", classe, n, pct, alerta)

    logger.info("=" * 62)
    if problema:
        logger.error("CHECKPOINT REPROVADO: revise o prompt antes de seguir.")
    else:
        logger.info("CHECKPOINT OK: nenhuma classe acima de 85%% nem abaixo de 5%%.")
    return not problema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument(
        "--limite", type=int, default=None, help="rotula no maximo N exemplos (ensaio)"
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)
    # A chave vai no cabecalho, mas se algum dia entrar na URL o log em INFO a
    # exporia. Mesma protecao de segunda camada do worker de coleta.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    dist = asyncio.run(rotular(argumentos.id_execucao, argumentos.limite))
    if not relatar(dist):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
