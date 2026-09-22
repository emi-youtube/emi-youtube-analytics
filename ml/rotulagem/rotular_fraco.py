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
- **Modelo provado antes de começar.** `escolher_modelo` exige o nome no `ml/.env` e
  faz uma chamada real — o exercício de calibração da Seção 8 do manual — antes do
  primeiro lote. O `ListModels` não basta: ele lista modelos que respondem 404 e não
  diz nada sobre demanda.
- **Metadados gravados** em `ml/rotulagem/metadados_rotulagem.json`: modelo exato,
  data, versão do prompt, temperatura, número de chamadas, a nota da calibração
  medida na própria sessão e o comparativo que descartou os outros candidatos.
  "Rotulado com Gemini" sem esses campos não é reproduzível.

Uso:
    python -m ml.rotulagem.rotular_fraco --id-execucao 4
    python -m ml.rotulagem.rotular_fraco --id-execucao 4 --limite 50   # ensaio
"""

import argparse
import asyncio
import contextlib
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

from ml.config import CLASSES, carregar_env_ml, chave_gemini, dsn_postgres
from ml.rotulagem.calibracao import (
    ARQUIVO_MANUAL,
    CALIBRACAO,
    MAXIMO_ERROS,
    avaliar,
    lote_de_sonda,
)
from ml.rotulagem.gemini import (
    ClienteGemini,
    ErroGemini,
    ErroPermanente,
    ErroTransitorio,
    e_estavel,
    listar_modelos,
)

logger = logging.getLogger("rotular_fraco")

VERSAO_PROMPT = "v1"
ARQUIVO_PROMPT = "prompt_v1.md"
# `ARQUIVO_MANUAL` vem de `calibracao` (fonte unica dos criterios; o prompt e um
# espelho condensado dela, nao o contrario) e e reexportado aqui por conveniencia.
TEMPERATURA = 0.0

# ~25 por chamada: lote grande economiza cota e contexto, mas quanto maior, mais
# cara fica a repetição quando um item sai inválido e o lote inteiro é refeito.
TAMANHO_LOTE = 25

# O free tier devolve 503 "high demand" em surtos que duram DEZENAS DE MINUTOS, não
# segundos. Com as 5 tentativas padrão do cliente (4+8+16+32 ≈ 2 min de paciência) a
# rodada morreu no lote 31 de 102; com 8 (~6 min) ela sobreviveu, mas um lote só
# passou na oitava tentativa — ou seja, 8 é o limite, não uma margem.
#
# 20 tentativas, com o teto de 64s do cliente, dão ~17 min de paciência por lote.
# Isso é deliberadamente muito: a alternativa não é uma rodada mais rápida, é um
# operador reexecutando o comando a cada meia hora. A rodada é retomável
# (`rotulo_fraco IS NULL`), então esperar não re-gasta cota nenhuma.
MAX_TENTATIVAS_LOTE = 20

INSTRUCAO_SISTEMA = (
    "Você é um anotador de sentimento de comentários do YouTube em português do "
    "Brasil. Sua tarefa é classificar cada comentário em exatamente uma de três "
    "classes. Você responde SOMENTE com JSON válido, sem texto antes ou depois, "
    "sem markdown."
)

# Espelho condensado das Secoes 3, 4, 5 e 6 de `manual_rotulagem_v1.md`, que e a
# fonte unica dos criterios. Mantido em sincronia com `prompt_v1.md` e com o
# manual pelos testes `test_prompt_do_codigo_bate_com_o_arquivo_versionado` e
# `test_regra_chave_do_manual_sobrevive_no_prompt`.
PROMPT_TAREFA = """Classifique o sentimento de cada comentário abaixo em relação à campanha,
produto ou marca anunciada.

CLASSES (escolha exatamente uma por comentário):
- "positivo": o autor aprova, elogia ou demonstra vontade de comprar.
- "negativo": o autor reprova, reclama, critica ou desiste da compra.
- "neutro": o autor não expressa aprovação nem reprovação.

"neutro" NÃO é o lugar da dúvida. Neutro é ausência de avaliação, não incerteza:
comentário difícil de decidir entre positivo e negativo NÃO é neutro — aplique as
regras abaixo e escolha uma das duas.

SOBRE O QUE É O SENTIMENTO: sempre sobre a campanha, o produto ou a marca
anunciada, nunca sobre qualquer outra coisa que o comentário mencione.
- Elogio a um elemento da campanha conta como elogio à campanha: "a atriz é
  linda demais" é "positivo".
- Entrega, atendimento e preço contam como marca: "os Correios são uma vergonha,
  meu pedido tá parado" é "negativo".
- "odeio segunda-feira, mas esse comercial salvou meu dia" é "positivo": o ódio é
  pela segunda-feira; sobre o anúncio, é elogio.
- Comentário que não fala da campanha, do produto nem da marca é "neutro".

ORDEM DE DECISÃO (a primeira resposta "sim" decide o rótulo):
1. Fala da campanha, do produto ou da marca? Se não, "neutro".
2. Há ironia? Rotule pelo sentido pretendido (regra 1).
3. Tem elogio e reclamação juntos? Vence a parte depois do "mas" (regra 2).
4. Aprova, elogia ou quer comprar? "positivo".
5. Reprova, reclama ou desiste? "negativo".
6. Nenhum dos dois: "neutro".

REGRAS:
1. IRONIA E SARCASMO: rotule pelo que o autor quis dizer, não pelas palavras que
   usou. Sinais: elogio exagerado para algo ruim, palavras em MAIÚSCULAS, "né",
   "hein", "parabéns", aplausos (👏) depois de uma reclamação.
   "nossa que entrega RÁPIDA hein, só 3 semanas pra chegar 👏👏" → "negativo".
   "amei que o produto quebrou no segundo dia, qualidade top" → "negativo".
   Sem certeza de que é ironia, rotule pelo sentido literal.
2. ELOGIO E RECLAMAÇÃO NO MESMO COMENTÁRIO: vence a parte que encerra o
   comentário ou a que vem depois de "mas", "porém", "só que", "no entanto".
   "demorou pra chegar, mas o produto é maravilhoso" → "positivo".
   "bonito sim, mas 2 mil reais num anel banhado? tá de brincadeira" → "negativo".
   "gostei do anúncio. o preço é que não dá" → "negativo".
   Se as duas partes têm o mesmo peso e não há conectivo, vale a que fala do
   PRODUTO, não a que fala do anúncio.
3. GÍRIA: traduza a gíria antes de rotular. Gíria não é sentimento, é vocabulário.
   "brabo", "insano", "surreal", "top", "pica" → positivo.
   "mó paia", "flopou", "fraco", "deu ruim" → negativo.
   "kkkk", "rsrs", "mds" sozinhos → "neutro": risada sem objeto não avalia nada.
   "mds que anúncio brabo" é "positivo"; "mds que caro" é "negativo" — o "mds"
   não decide, o resto da frase decide.
   Erro de escrita e abreviação não mudam a classe.
4. SÓ EMOJI: emoji isolado vale o sentido dominante dele.
   😍 🔥 ❤️ 👏 (sem reclamação antes) → "positivo".
   😡 🤮 👎 → "negativo".
   😂 sozinho → "neutro": rir não diz se aprova ou não. 🤔 → "neutro".
5. PERGUNTA: pergunta só é neutra se não carregar avaliação.
   "tem pra entrega no Nordeste?" → "neutro".
   "alguém mais recebeu com defeito?" → "negativo": pressupõe o problema.
   "alguém mais achou caro demais?" → "negativo": carrega reclamação.
   "onde compro? quero muito" → "positivo": intenção de compra.
6. FORA DO TEMA → "neutro". Inclui marcar amigos ("@joao olha isso"), falar de
   outro assunto, "primeiro!" e pedido de inscrição no canal.
7. SPAM e propaganda de terceiros → "neutro". Exemplo: "ganhe 500 reais por dia
   trabalhando de casa, link na bio".
8. COMENTÁRIO SOBRE OUTRO COMENTÁRIO: rotule o que ele diz sobre a campanha.
   "concordo total, também achei caro" → "negativo": endossa a reclamação.
   "você tá louco, o anúncio é ótimo" → "positivo".
   "quem ta aqui em 2026?" → "neutro".
   Se ele só reage a outra pessoa, sem dizer nada da campanha, é "neutro".
9. NÃO INVENTE CONTEXTO: classifique só pelo que está escrito. Se o sentido
   depender de algo que você não tem (o vídeo, outro comentário), rotule pelo que
   o texto sozinho mostra; se o texto sozinho não aprova nem reprova, "neutro".

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


async def reconectar_se_caiu(conexao: asyncpg.Connection) -> asyncpg.Connection:
    """Devolve uma conexão viva, abrindo outra se a anterior morreu de ócio.

    A rodada espera até `MAX_TENTATIVAS_LOTE` chamadas por lote quando o free tier
    está em surto de 503 — dezenas de minutos sem tocar no banco. O Postgres do
    Supabase fecha a conexão ociosa nesse intervalo, e a gravação do lote seguinte
    morria com `ConnectionDoesNotExistError` levando consigo rótulos que a Gemini já
    tinha devolvido (cota gasta, nada gravado).

    O `SELECT 1` é a única forma confiável de saber: `is_closed()` só conhece o lado
    de cá e devolve False para uma conexão que o servidor já derrubou.
    """
    if not conexao.is_closed():
        try:
            await conexao.fetchval("SELECT 1")
            return conexao
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError) as erro:
            logger.warning("conexao com o banco caiu (%s); reconectando", type(erro).__name__)

    with contextlib.suppress(Exception):
        await conexao.close()
    return await asyncpg.connect(dsn_postgres())


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


# Comparativo que fechou a escolha do modelo, copiado para o metadado de cada rodada.
# "Usamos a Gemini" nao e uma decisao defensavel em banca; isto e. Refazer o
# experimento: `listar_modelos` da os candidatos estaveis, e `escolher_modelo()` com
# cada nome no `ml/.env` da a disponibilidade e a nota de calibracao de cada um.
#
# O que o comparativo mostrou: nesta chave, acerto na calibracao NAO foi o criterio
# que decidiu — os dois finalistas fizeram 12/12. Decidiu a disponibilidade.
ESCOLHA_DO_MODELO = {
    "data": "2026-09-22",
    "escolhido": "gemini-3.1-flash-lite",
    "criterio_de_desempate": "disponibilidade na chave do projeto (free tier)",
    "motivo": (
        "12/12 na calibracao da Secao 8 em todas as chamadas que completaram, e o "
        "unico candidato que respondeu de forma consistente: 4 de 5 chamadas, contra "
        "2 de 5 do gemini-3.5-flash-lite, que empatou em acerto (12/12) mas estourou "
        "o tempo de leitura duas vezes."
    ),
    "descartados": {
        "gemini-3.8-flash": "HTTP 503 'high demand' em 2 de 2 chamadas",
        "gemini-3.7-flash": "HTTP 503 'high demand' em 2 de 2 chamadas",
        "gemini-3.6-flash": "HTTP 503 'high demand' em 2 de 2 chamadas",
        "gemini-3.5-flash": "HTTP 503 'high demand' em 2 de 2 chamadas",
        "gemini-3.5-flash-lite": "12/12, mas so 2 de 5 chamadas completaram",
        "gemini-2.5-flash": "HTTP 404 'no longer available to new users'",
        "gemini-2.5-flash-lite": "HTTP 404 'no longer available to new users'",
        "gemini-flash-latest": "apelido: nao descreve o que rodou (ver e_estavel)",
        "gemini-3-flash-preview": "preview: pode mudar ou sair do ar sem aviso",
        "gemini-2.5-pro": "nao testado: pro gasta cota a mais sem ganho na tarefa",
    },
    "observacao": (
        "O 503 da linha -flash e da familia, nao do momento: numa mesma janela de "
        "chamadas, as quatro versoes -flash recusaram enquanto as duas -flash-lite "
        "responderam. Depois de ~12 chamadas seguidas o free tier passa a devolver "
        "503 para qualquer modelo — se a rodada morrer assim, ela retoma de onde "
        "parou (rotulo_fraco IS NULL) sem re-gastar cota."
    ),
}


@dataclass(frozen=True)
class ModeloEscolhido:
    """O modelo que passou por todas as checagens, e a prova de que passou."""

    cliente: ClienteGemini
    acertos_calibracao: int
    erros_calibracao: dict[int, str]


def _validar_no_catalogo(modelo: str, api_key: str) -> None:
    """Checagens que o `ListModels` resolve sem gastar cota de geração.

    Barra três erros: nome inexistente (digitação, ou modelo aposentado), modelo que
    não faz `generateContent` (TTS, imagem, embedding, Lyria) e nome instável
    (preview/experimental/`-latest`), que tornaria a rodada irreproduzível.
    """
    catalogo = {m["nome"]: m for m in listar_modelos(api_key)}

    if modelo not in catalogo:
        disponiveis = sorted(n for n in catalogo if e_estavel(n) and "flash" in n)
        raise ValueError(
            f"GEMINI_MODELO={modelo!r} nao existe para esta chave. "
            f"Estaveis com 'flash': {', '.join(disponiveis) or '(nenhum)'}. "
            "Veja a lista completa em `python -m ml.rotulagem.listar_modelos`."
        )

    if "generateContent" not in catalogo[modelo]["metodos"]:
        raise ValueError(
            f"GEMINI_MODELO={modelo!r} nao suporta generateContent "
            f"(metodos: {', '.join(catalogo[modelo]['metodos']) or 'nenhum'})."
        )

    if not e_estavel(modelo):
        raise ValueError(
            f"GEMINI_MODELO={modelo!r} e preview, experimental ou apelido '-latest'. "
            "O corpus rotulado vai para o TCC: o nome precisa descrever o que rodou "
            "e continuar valendo depois. Escolha um modelo estavel."
        )


def _sondar(cliente: ClienteGemini) -> tuple[int, dict[int, str]]:
    """Uma chamada real antes da rodada, com os 12 casos da Seção 8 do manual.

    O `ListModels` não prova que o modelo responde: ele lista modelos **fechados
    para chaves novas** (a família `gemini-2.5-*` aparece na listagem desta chave e
    devolve HTTP 404 "no longer available to new users" ao gerar) e modelos que
    devolvem 503 por demanda, que nesta chave é o caso de toda a linha `-flash`
    acima da `-flash-lite`. Sem a sonda, isso apareceria no primeiro lote — depois
    de o operador já ter saído de perto achando que a rodada começou.

    A sonda é o próprio exercício de calibração de propósito: uma chamada, e ela
    confirma de uma vez que o modelo existe para esta chave, que responde, que o
    modo JSON funciona, que ele obedece à categoria fechada e que acerta a régua que
    os avaliadores humanos usam.

    Ela é tão paciente quanto um lote (`MAX_TENTATIVAS_LOTE`): num surto de 503 do
    free tier a rodada espera o surto passar em vez de se recusar a começar.
    """
    lote = lote_de_sonda()
    ids = {item["id_comentario"] for item in lote}

    try:
        # A sonda tem a MESMA paciencia de um lote, e nao menos. Ser mais impaciente
        # aqui criava um absurdo: durante um surto de 503 do free tier a rodada se
        # recusava a comecar, embora cada lote fosse esperar o surto passar. E um
        # problema de verdade (nome errado, modelo fechado, contrato ignorado) nao
        # depende de paciencia — ErroPermanente nao tem repeticao e falha na hora.
        bruto = cliente.gerar(INSTRUCAO_SISTEMA, montar_prompt(lote), MAX_TENTATIVAS_LOTE)
    except ErroPermanente as erro:
        raise ValueError(
            f"GEMINI_MODELO={cliente.modelo!r} esta no catalogo mas nao responde: {erro}. "
            "O ListModels lista modelos fechados para chaves novas. "
            "Escolha outro em `python -m ml.rotulagem.listar_modelos`."
        ) from erro
    except ErroTransitorio as erro:
        raise ValueError(
            f"GEMINI_MODELO={cliente.modelo!r} nao atendeu em {MAX_TENTATIVAS_LOTE} "
            f"tentativas: {erro}. 503 depois de tanta espera nao e surto de demanda: "
            "e modelo que o free tier nao serve para esta chave. Toda a linha -flash "
            "acima da -flash-lite se comporta assim. Escolha um modelo menor em "
            "`python -m ml.rotulagem.listar_modelos`."
        ) from erro

    try:
        rotulos = validar_lote(extrair_json(bruto), ids)
    except RespostaInvalida as erro:
        raise ValueError(
            f"GEMINI_MODELO={cliente.modelo!r} respondeu fora do contrato na sonda: {erro}. "
            "Um modelo que nao devolve o JSON combinado em 12 comentarios nao vai "
            "aguentar o corpus inteiro."
        ) from erro

    return avaliar(rotulos)


def escolher_modelo(
    env: dict[str, str], api_key: str, temperatura: float = TEMPERATURA
) -> ModeloEscolhido:
    """Fecha o modelo da rodada: exige o nome no `ml/.env` e o prova antes de começar.

    Sem nome padrao de proposito. O catalogo da Gemini muda — `gemini-2.0-flash`, o
    padrao anterior deste arquivo, ja nao existe para a chave do projeto. Um padrao
    embutido so garante que o pipeline quebre num 404 no meio da rodada, ou pior:
    que os metadados registrem um modelo que nunca rodou.

    Tres portoes, do mais barato ao mais caro: o `.env` tem o nome; o `ListModels`
    conhece o nome e ele serve; e uma chamada real confirma que o modelo responde e
    acerta a calibracao do manual. Todos antes da primeira escrita no banco.
    """
    modelo = env.get("GEMINI_MODELO", "").strip()
    if not modelo:
        raise ValueError(
            "GEMINI_MODELO vazio em ml/.env. Rode `python -m ml.rotulagem.listar_modelos` "
            "e escreva o nome exato: 'Gemini' sem versao nao e reproduzivel."
        )

    _validar_no_catalogo(modelo, api_key)

    cliente = ClienteGemini(api_key=api_key, modelo=modelo, temperatura=temperatura)
    acertos, erros = _sondar(cliente)

    if len(erros) > MAXIMO_ERROS:
        detalhe = ", ".join(f"#{n} veio {r!r}" for n, r in sorted(erros.items()))
        raise ValueError(
            f"GEMINI_MODELO={modelo!r} acertou {acertos}/{acertos + len(erros)} na calibracao "
            f"da Secao 8 do manual ({detalhe}). O manual reprova o avaliador humano que erra "
            f"mais de {MAXIMO_ERROS}; aplicar regua mais frouxa a Gemini nao se defende em banca."
        )

    logger.info(
        "sonda do modelo %s: %s/%s na calibracao da Secao 8%s",
        modelo,
        acertos,
        acertos + len(erros),
        "" if not erros else f" (errou {sorted(erros)})",
    )
    return ModeloEscolhido(cliente=cliente, acertos_calibracao=acertos, erros_calibracao=erros)


def gravar_metadados(escolha: ModeloEscolhido, total_rotulado: int, lotes: int, caminho) -> None:
    """Sem isto, "rotulado com Gemini" não é reproduzível nem defensável."""
    cliente = escolha.cliente
    metadados = {
        "modelo": cliente.modelo,
        "data_utc": datetime.now(UTC).isoformat(),
        "versao_prompt": VERSAO_PROMPT,
        "arquivo_prompt": ARQUIVO_PROMPT,
        "arquivo_manual": ARQUIVO_MANUAL,
        "temperatura": TEMPERATURA,
        "tamanho_lote": TAMANHO_LOTE,
        "chamadas_api": cliente.chamadas,
        "lotes": lotes,
        "exemplos_rotulados": total_rotulado,
        "texto_enviado": "original (coluna texto), nunca texto_modelo",
        "classes": list(CLASSES),
        # Medido nesta sessao, pela sonda, antes do primeiro lote — nao e um numero
        # copiado de outra rodada.
        "calibracao_secao_8": {
            "acertos": escolha.acertos_calibracao,
            "total": len(CALIBRACAO),
            "erros": {str(n): r for n, r in sorted(escolha.erros_calibracao.items())},
            "maximo_erros_tolerado": MAXIMO_ERROS,
        },
        "escolha_do_modelo": ESCOLHA_DO_MODELO,
    }
    caminho.write_text(json.dumps(metadados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("metadados gravados em %s", caminho)


async def rotular(id_execucao: int, limite: int | None) -> Counter:
    from ml.config import DIRETORIO_ML

    env = carregar_env_ml()
    api_key = chave_gemini()
    # Tudo o que pode reprovar o modelo acontece aqui, antes da conexao com o banco.
    escolha = escolher_modelo(env, api_key, TEMPERATURA)
    cliente = escolha.cliente

    logger.info(
        "modelo=%s temperatura=%s prompt=%s manual=%s lote=%s",
        cliente.modelo,
        TEMPERATURA,
        VERSAO_PROMPT,
        ARQUIVO_MANUAL,
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
                    bruto = cliente.gerar(
                        INSTRUCAO_SISTEMA, montar_prompt(lote), MAX_TENTATIVAS_LOTE
                    )
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

            # A espera pelo lote pode ter durado mais que o ocio que o Supabase tolera.
            conexao = await reconectar_se_caiu(conexao)
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
            escolha, total_rotulado, lotes, DIRETORIO_ML / "rotulagem" / "metadados_rotulagem.json"
        )
        conexao = await reconectar_se_caiu(conexao)
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
