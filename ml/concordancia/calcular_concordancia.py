"""Lê as três planilhas preenchidas, calcula a concordância e grava o gabarito.

A matemática mora em `kappa.py`; aqui fica o que toca arquivo e banco.

**Ordem das etapas, e por que é essa.** Valida tudo → calcula o Kappa → só então
olha as divergências. O manual (Seção 9) é explícito: "o Kappa é calculado **antes**
de qualquer discussão". Inverter a ordem — discutir os casos difíceis e recalcular —
produziria um número que mede a conversa da equipe, não a régua do manual.

**Nada é gravado por padrão.** Sem `--gravar`, a execução só relata. E mesmo com
`--gravar`, se κ < 0,60 a escrita é recusada: abaixo da meta o gabarito não vale e a
amostra vai ser refeita (manual, Seção 9), então gravar `rotulo_humano` ali seria
carimbar como verdade um conjunto que a própria equipe já decidiu descartar.

Entrada: `ml/amostra/respostas/avaliador_{1,2,3}.xlsx` — as planilhas que saíram de
`gerar_planilhas_avaliadores.py` depois de preenchidas. O diretório está no
`.gitignore`: elas contêm texto de terceiros e o repositório é público.

Uso:
    python -m ml.concordancia.calcular_concordancia
    python -m ml.concordancia.calcular_concordancia --gravar
    python -m ml.concordancia.calcular_concordancia --respostas caminho/ --normalizar
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
from openpyxl import Workbook, load_workbook

from ml.concordancia.kappa import (
    META_KAPPA,
    ConcordanciaDegenerada,
    classificar_landis_koch,
    kappa_cohen,
    kappa_fleiss,
    kappa_fleiss_por_classe,
    matriz_confusao,
    matriz_de_contagem,
    matriz_divergencia,
    voto_majoritario,
)
from ml.config import CLASSES, DIRETORIO_ML, dsn_postgres

logger = logging.getLogger("concordancia")

AVALIADORES = ("avaliador_1", "avaliador_2", "avaliador_3")

DIRETORIO_RESPOSTAS = DIRETORIO_ML / "amostra" / "respostas"
DIRETORIO_SAIDA = DIRETORIO_ML / "concordancia"

ABA_ROTULAGEM = "rotulagem"

# Colunas da planilha gerada por `gerar_planilhas_avaliadores.py`, na ordem.
COLUNA_ID, COLUNA_TEXTO, COLUNA_ROTULO, COLUNA_DUVIDA, COLUNA_OBSERVACAO = range(1, 6)

DUVIDA_SIM = "sim"


@dataclass(frozen=True)
class Resposta:
    """Uma linha preenchida por um avaliador."""

    id_comentario: int
    texto: str
    rotulo: str
    duvida: bool
    observacao: str
    linha: int


@dataclass
class Problema:
    """Uma falha de validação, com endereço suficiente para consertar na planilha."""

    avaliador: str
    linha: int | None
    id_comentario: int | None
    descricao: str

    def __str__(self) -> str:
        onde = f"{self.avaliador}"
        if self.linha is not None:
            onde += f" linha {self.linha}"
        if self.id_comentario is not None:
            onde += f" (id {self.id_comentario})"
        return f"{onde}: {self.descricao}"


@dataclass
class Resultado:
    """O que a execução apurou — o que vira relatório e, com `--gravar`, gabarito."""

    fleiss: float | None
    cohen_por_par: dict[str, float]
    fleiss_por_classe: dict[str, float]
    confusao_por_par: dict[str, dict[str, dict[str, int]]]
    divergencia: dict[str, dict[str, int]]
    distribuicao_por_avaliador: dict[str, dict[str, int]]
    gabarito: dict[int, str]
    empates: list[int]
    duvidas_coletivas: list[int]
    unanimes: int
    maioria_simples: int
    total: int
    degenerado: str | None = None
    normalizacoes: list[str] = field(default_factory=list)

    @property
    def cohen_medio(self) -> float | None:
        if not self.cohen_por_par:
            return None
        return sum(self.cohen_por_par.values()) / len(self.cohen_por_par)

    @property
    def atingiu_meta(self) -> bool:
        return self.fleiss is not None and self.fleiss >= META_KAPPA

    @property
    def desempate(self) -> list[int]:
        """Pauta da reunião: empates totais mais dúvidas marcadas por 2+ avaliadores.

        União, não interseção — são dois sintomas diferentes. O empate diz que a régua
        não decide; a dúvida coletiva diz que ela decide, mas custa caro. A Seção 9 do
        manual manda revisar os dois, inclusive quando os três concordaram no rótulo.
        """
        return sorted(set(self.empates) | set(self.duvidas_coletivas))


def ler_planilha(
    caminho: Path, avaliador: str, normalizar: bool
) -> tuple[list[Resposta], list[Problema]]:
    """Lê uma planilha preenchida. Não interrompe no primeiro erro: junta todos.

    Parar no primeiro problema faria o avaliador consertar uma célula, rodar de novo,
    descobrir a próxima, e assim por diante. Com 334 linhas isso é um dia perdido.
    """
    if not caminho.exists():
        return [], [Problema(avaliador, None, None, f"arquivo nao encontrado: {caminho}")]

    livro = load_workbook(caminho, read_only=True, data_only=True)
    if ABA_ROTULAGEM not in livro.sheetnames:
        return [], [
            Problema(avaliador, None, None, f"planilha sem a aba '{ABA_ROTULAGEM}'")
        ]
    aba = livro[ABA_ROTULAGEM]

    respostas: list[Resposta] = []
    problemas: list[Problema] = []

    for numero, linha in enumerate(aba.iter_rows(min_row=2, max_col=5, values_only=True), start=2):
        bruto_id = linha[COLUNA_ID - 1]
        if bruto_id is None:
            continue  # linha em branco no fim do arquivo; o Excel gera várias

        try:
            id_comentario = int(bruto_id)
        except (TypeError, ValueError):
            problemas.append(
                Problema(avaliador, numero, None, f"id_comentario invalido: {bruto_id!r}")
            )
            continue

        bruto_rotulo = linha[COLUNA_ROTULO - 1]
        rotulo = "" if bruto_rotulo is None else str(bruto_rotulo)

        if not rotulo.strip():
            problemas.append(
                Problema(avaliador, numero, id_comentario, "rotulo vazio - nao pule linhas")
            )
            continue

        if rotulo not in CLASSES:
            canonico = rotulo.strip().lower()
            if canonico in CLASSES and normalizar:
                # Registrado, nunca silencioso: a planilha fica como está e o relatório
                # guarda o que foi corrigido na leitura.
                problemas.append(
                    Problema(
                        avaliador,
                        numero,
                        id_comentario,
                        f"NORMALIZADO {rotulo!r} -> {canonico!r}",
                    )
                )
                rotulo = canonico
            elif canonico in CLASSES:
                problemas.append(
                    Problema(
                        avaliador,
                        numero,
                        id_comentario,
                        f"rotulo {rotulo!r} difere de {canonico!r} so por espaco/maiuscula "
                        "- conserte na planilha ou rode com --normalizar",
                    )
                )
                continue
            else:
                problemas.append(
                    Problema(
                        avaliador,
                        numero,
                        id_comentario,
                        f"rotulo fora das classes: {rotulo!r} (use {', '.join(CLASSES)})",
                    )
                )
                continue

        bruto_duvida = linha[COLUNA_DUVIDA - 1]
        duvida = str(bruto_duvida).strip().lower() == DUVIDA_SIM if bruto_duvida else False

        bruto_observacao = linha[COLUNA_OBSERVACAO - 1]
        bruto_texto = linha[COLUNA_TEXTO - 1]

        respostas.append(
            Resposta(
                id_comentario=id_comentario,
                texto="" if bruto_texto is None else str(bruto_texto),
                rotulo=rotulo,
                duvida=duvida,
                observacao="" if bruto_observacao is None else str(bruto_observacao).strip(),
                linha=numero,
            )
        )

    livro.close()

    repetidos = [
        id_comentario
        for id_comentario, vezes in Counter(r.id_comentario for r in respostas).items()
        if vezes > 1
    ]
    for id_comentario in sorted(repetidos):
        problemas.append(
            Problema(avaliador, None, id_comentario, "id_comentario repetido na planilha")
        )

    return respostas, problemas


def validar_conjuntos(
    por_avaliador: dict[str, list[Resposta]],
) -> tuple[list[int], list[Problema]]:
    """Confere que as três planilhas cobrem exatamente os mesmos comentários.

    Devolve os ids em ordem — a ordem de cálculo, que é por `id_comentario` e não por
    linha: as três planilhas saem embaralhadas de propósito, então comparar por
    posição alinharia comentários diferentes e o Kappa mediria ruído.
    """
    problemas: list[Problema] = []
    conjuntos = {
        avaliador: {resposta.id_comentario for resposta in respostas}
        for avaliador, respostas in por_avaliador.items()
    }

    referencia: set[int] = set()
    for ids in conjuntos.values():
        referencia |= ids

    for avaliador, ids in conjuntos.items():
        for faltante in sorted(referencia - ids):
            problemas.append(
                Problema(avaliador, None, faltante, "comentario ausente nesta planilha")
            )

    comuns = set.intersection(*conjuntos.values()) if conjuntos else set()
    return sorted(comuns), problemas


def apurar(por_avaliador: dict[str, list[Resposta]], ids: list[int]) -> Resultado:
    """Calcula tudo sobre o conjunto de ids já validado."""
    indexado = {
        avaliador: {resposta.id_comentario: resposta for resposta in respostas}
        for avaliador, respostas in por_avaliador.items()
    }
    nomes = list(por_avaliador)

    rotulos_por_avaliador = [
        [indexado[avaliador][id_comentario].rotulo for id_comentario in ids] for avaliador in nomes
    ]
    votos_por_item = [
        [indexado[avaliador][id_comentario].rotulo for avaliador in nomes] for id_comentario in ids
    ]

    contagens = matriz_de_contagem(votos_por_item, CLASSES)

    degenerado: str | None = None
    try:
        fleiss: float | None = kappa_fleiss(contagens)
    except ConcordanciaDegenerada as erro:
        fleiss, degenerado = None, str(erro)

    cohen_por_par: dict[str, float] = {}
    confusao_por_par: dict[str, dict[str, dict[str, int]]] = {}
    for primeiro in range(len(nomes)):
        for segundo in range(primeiro + 1, len(nomes)):
            par = f"{nomes[primeiro]} x {nomes[segundo]}"
            # Par degenerado (os dois usaram uma classe so) fica fora da media em
            # vez de entrar como zero, que seria lido como discordancia total.
            with suppress(ConcordanciaDegenerada):
                cohen_por_par[par] = kappa_cohen(
                    rotulos_por_avaliador[primeiro], rotulos_por_avaliador[segundo]
                )
            confusao_por_par[par] = matriz_confusao(
                rotulos_por_avaliador[primeiro], rotulos_por_avaliador[segundo], CLASSES
            )

    gabarito: dict[int, str] = {}
    empates: list[int] = []
    unanimes = 0
    for id_comentario, votos in zip(ids, votos_por_item, strict=True):
        vencedor = voto_majoritario(votos)
        if vencedor is None:
            empates.append(id_comentario)
        else:
            gabarito[id_comentario] = vencedor
            if len(set(votos)) == 1:
                unanimes += 1

    duvidas_coletivas = [
        id_comentario
        for id_comentario in ids
        if sum(1 for avaliador in nomes if indexado[avaliador][id_comentario].duvida) >= 2
    ]

    return Resultado(
        fleiss=fleiss,
        cohen_por_par=cohen_por_par,
        fleiss_por_classe=kappa_fleiss_por_classe(contagens, CLASSES),
        confusao_por_par=confusao_por_par,
        divergencia=matriz_divergencia(rotulos_por_avaliador, CLASSES),
        distribuicao_por_avaliador={
            avaliador: dict(Counter(rotulos_por_avaliador[posicao]))
            for posicao, avaliador in enumerate(nomes)
        },
        gabarito=gabarito,
        empates=empates,
        duvidas_coletivas=duvidas_coletivas,
        unanimes=unanimes,
        maioria_simples=len(gabarito) - unanimes,
        total=len(ids),
        degenerado=degenerado,
    )


def relatar(resultado: Resultado) -> None:
    """Imprime o relatório. É o que vai para a Seção 4.1.2 do TC2."""
    logger.info("")
    logger.info("=" * 72)
    logger.info("CONCORDANCIA ENTRE AVALIADORES - %s comentarios", resultado.total)
    logger.info("=" * 72)

    logger.info("")
    if resultado.fleiss is None:
        logger.info("Kappa de Fleiss: INDEFINIDO - %s", resultado.degenerado)
    else:
        logger.info(
            "Kappa de FLEISS (numero principal): %.4f  [%s]",
            resultado.fleiss,
            classificar_landis_koch(resultado.fleiss),
        )
        situacao = "ATINGIU" if resultado.atingiu_meta else "ABAIXO DE"
        logger.info("  meta do manual (Secao 1): %.2f - %s a meta", META_KAPPA, situacao)

    logger.info("")
    logger.info("Kappa de COHEN, par a par:")
    for par, valor in resultado.cohen_por_par.items():
        logger.info("  %-28s %.4f  [%s]", par, valor, classificar_landis_koch(valor))
    if resultado.cohen_medio is not None:
        logger.info("  %-28s %.4f", "media", resultado.cohen_medio)

    logger.info("")
    logger.info("Kappa de Fleiss por classe (um-contra-resto) - onde a regua falha:")
    for classe, valor in sorted(resultado.fleiss_por_classe.items(), key=lambda par: par[1]):
        logger.info("  %-12s %.4f  [%s]", classe, valor, classificar_landis_koch(valor))

    logger.info("")
    logger.info("Matriz de divergencia (soma dos tres pares, simetrica):")
    largura = max(len(classe) for classe in CLASSES)
    logger.info("  %s %s", " " * largura, "  ".join(f"{classe:>10}" for classe in CLASSES))
    for linha in CLASSES:
        celulas = "  ".join(f"{resultado.divergencia[linha][coluna]:>10}" for coluna in CLASSES)
        logger.info("  %-*s %s", largura, linha, celulas)

    logger.info("")
    logger.info("Distribuicao de cada avaliador:")
    for avaliador, contagem in resultado.distribuicao_por_avaliador.items():
        partes = "  ".join(f"{classe}={contagem.get(classe, 0)}" for classe in CLASSES)
        logger.info("  %-14s %s", avaliador, partes)

    logger.info("")
    logger.info("Gabarito por voto majoritario:")
    logger.info("  unanimes (3-0):        %4d", resultado.unanimes)
    logger.info("  maioria  (2-1):        %4d", resultado.maioria_simples)
    logger.info("  empates  (1-1-1):      %4d  -> reuniao de desempate", len(resultado.empates))
    logger.info(
        "  duvida por 2+ aval.:   %4d  -> revisao conjunta", len(resultado.duvidas_coletivas)
    )
    logger.info(
        "  pauta da reuniao:      %4d comentarios (uniao)", len(resultado.desempate)
    )


def gravar_relatorio(resultado: Resultado, caminho: Path) -> None:
    """Grava o JSON de métricas. Só agregados: nenhum texto de terceiros.

    É por isso que este arquivo pode ser commitado enquanto as planilhas não podem —
    ele tem números e ids, e os ids sozinhos não identificam ninguém.
    """
    conteudo = {
        "data_utc": datetime.now(UTC).isoformat(),
        "total_comentarios": resultado.total,
        "avaliadores": list(resultado.distribuicao_por_avaliador),
        "kappa_fleiss": resultado.fleiss,
        "kappa_fleiss_indefinido": resultado.degenerado,
        "faixa_landis_koch": (
            classificar_landis_koch(resultado.fleiss) if resultado.fleiss is not None else None
        ),
        "meta_kappa": META_KAPPA,
        "atingiu_meta": resultado.atingiu_meta,
        "kappa_cohen_por_par": resultado.cohen_por_par,
        "kappa_cohen_medio": resultado.cohen_medio,
        "kappa_fleiss_por_classe": resultado.fleiss_por_classe,
        "matriz_divergencia": resultado.divergencia,
        "matriz_confusao_por_par": resultado.confusao_por_par,
        "distribuicao_por_avaliador": resultado.distribuicao_por_avaliador,
        "gabarito": {
            "unanimes": resultado.unanimes,
            "maioria_simples": resultado.maioria_simples,
            "empates": len(resultado.empates),
            "duvidas_coletivas": len(resultado.duvidas_coletivas),
        },
        "ids_para_desempate": resultado.desempate,
        "normalizacoes": resultado.normalizacoes,
    }
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("relatorio -> %s", caminho)


def gravar_pauta_desempate(
    resultado: Resultado,
    por_avaliador: dict[str, list[Resposta]],
    caminho: Path,
) -> None:
    """Planilha da reunião de consenso: um comentário por linha, com os três votos.

    Sai no diretório das respostas, que está no `.gitignore` — tem o texto original
    dos comentários, que é conteúdo de terceiros.
    """
    if not resultado.desempate:
        return

    indexado = {
        avaliador: {resposta.id_comentario: resposta for resposta in respostas}
        for avaliador, respostas in por_avaliador.items()
    }
    nomes = list(por_avaliador)

    livro = Workbook()
    aba = livro.active
    aba.title = "desempate"
    aba.append(
        ["id_comentario", "texto", *nomes, "motivo", "duvidas", "decisao", "regra_do_manual"]
    )

    for id_comentario in resultado.desempate:
        votos = [indexado[avaliador][id_comentario].rotulo for avaliador in nomes]
        quem_duvidou = [
            avaliador for avaliador in nomes if indexado[avaliador][id_comentario].duvida
        ]
        motivos = []
        if id_comentario in resultado.empates:
            motivos.append("empate 1-1-1")
        if id_comentario in resultado.duvidas_coletivas:
            motivos.append(f"duvida de {len(quem_duvidou)}")
        observacoes = "; ".join(
            f"{avaliador}: {indexado[avaliador][id_comentario].observacao}"
            for avaliador in quem_duvidou
            if indexado[avaliador][id_comentario].observacao
        )
        aba.append(
            [
                id_comentario,
                indexado[nomes[0]][id_comentario].texto,
                *votos,
                " + ".join(motivos),
                observacoes,
                "",
                "",
            ]
        )

    aba.column_dimensions["B"].width = 80
    aba.freeze_panes = "A2"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    livro.save(caminho)
    logger.info("pauta do desempate -> %s (%s comentarios)", caminho, len(resultado.desempate))


async def gravar_gabarito(gabarito: dict[int, str]) -> int:
    """Escreve `rotulo_humano` nos exemplos que tiveram maioria.

    Empates ficam NULOS de propósito: o gabarito deles nasce na reunião de consenso,
    não aqui.
    """
    conexao = await asyncpg.connect(dsn_postgres())
    try:
        resultado = await conexao.executemany(
            "UPDATE exemplos_treinamento SET rotulo_humano = $2 WHERE id_comentario = $1",
            list(gabarito.items()),
        )
    finally:
        await conexao.close()
    logger.info("gabarito gravado: %s exemplos", len(gabarito))
    return resultado if isinstance(resultado, int) else len(gabarito)


def executar(diretorio: Path, normalizar: bool) -> tuple[Resultado, dict[str, list[Resposta]]]:
    """Lê, valida e apura. Estoura antes de calcular se qualquer validação falhar."""
    por_avaliador: dict[str, list[Resposta]] = {}
    problemas: list[Problema] = []
    normalizacoes: list[str] = []

    for avaliador in AVALIADORES:
        respostas, encontrados = ler_planilha(
            diretorio / f"{avaliador}.xlsx", avaliador, normalizar
        )
        por_avaliador[avaliador] = respostas
        for problema in encontrados:
            if problema.descricao.startswith("NORMALIZADO"):
                normalizacoes.append(str(problema))
            else:
                problemas.append(problema)

    ids, problemas_conjunto = validar_conjuntos(por_avaliador)
    problemas.extend(problemas_conjunto)

    if problemas:
        logger.error("")
        logger.error("VALIDACAO FALHOU - %s problema(s). Nada foi calculado.", len(problemas))
        for problema in problemas[:50]:
            logger.error("  %s", problema)
        if len(problemas) > 50:
            logger.error("  ... e mais %s", len(problemas) - 50)
        raise SystemExit(1)

    if not ids:
        raise SystemExit("nenhum comentario em comum entre as planilhas")

    if normalizacoes:
        logger.warning("")
        logger.warning("%s rotulo(s) normalizado(s) na leitura:", len(normalizacoes))
        for registro in normalizacoes:
            logger.warning("  %s", registro)

    resultado = apurar(por_avaliador, ids)
    resultado.normalizacoes = normalizacoes
    return resultado, por_avaliador


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--respostas", type=Path, default=DIRETORIO_RESPOSTAS)
    parser.add_argument(
        "--normalizar",
        action="store_true",
        help="aceita 'Positivo ' como 'positivo', registrando cada correcao no relatorio",
    )
    parser.add_argument(
        "--gravar", action="store_true", help="grava rotulo_humano no banco (exige kappa >= meta)"
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="grava mesmo com kappa abaixo da meta — use so com decisao registrada da equipe",
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    resultado, por_avaliador = executar(argumentos.respostas, argumentos.normalizar)
    relatar(resultado)

    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
    gravar_relatorio(resultado, DIRETORIO_SAIDA / "resultado_kappa.json")
    gravar_pauta_desempate(resultado, por_avaliador, argumentos.respostas / "desempate.xlsx")

    if not argumentos.gravar:
        logger.info("")
        logger.info("nada gravado no banco (rode com --gravar quando a equipe decidir)")
        return

    if not resultado.atingiu_meta and not argumentos.forcar:
        logger.error("")
        logger.error(
            "RECUSADO: kappa abaixo de %.2f. O manual (Secao 9) manda revisar o manual e "
            "sortear nova amostra, nao gravar este gabarito. Use --forcar se a equipe "
            "decidiu o contrario e registrou o motivo.",
            META_KAPPA,
        )
        raise SystemExit(1)

    asyncio.run(gravar_gabarito(resultado.gabarito))


if __name__ == "__main__":
    main()
