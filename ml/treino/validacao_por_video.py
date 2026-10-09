"""Quanto o BERTimbau cai num vídeo que nunca viu? Um diagnóstico, não um treino de produção.

**A pergunta.** O teste humano saiu dos mesmos 14 vídeos do treino, então ele não mede o
uso real: a campanha da PME não estava no corpus. A queda em vídeo inédito só foi
estimada com o classificador clássico (`ml/baseline/treinar_baseline.py`,
`validar_por_grupo`): 0,713 na validação cruzada aleatória contra 0,612 com os vídeos
separados. O TF-IDF depende do vocabulário de cada vídeo; o BERTimbau, pré-treinado,
deve cair menos. Este módulo mede.

**A conta é a mesma do TF-IDF**, para que as duas quedas sejam comparáveis:

- os mesmos 2.200 exemplos com rótulo fraco (`split IS NULL`), na mesma ordem
  (`dividir_estratificado`, treino + validação);
- cinco dobras **por vídeo**: as MESMAS do TF-IDF, lidas de
  `ml/baseline/saida/busca_baseline.json` (cada vídeo inteiro numa dobra só);
- cinco dobras **aleatórias**, estratificadas pelo rótulo, semente 42. O sorteio é
  próprio (biblioteca padrão), e não o `StratifiedKFold` do scikit-learn, para não
  pôr o scikit-learn no ambiente do treino; as dobras não são as mesmas do TF-IDF, mas
  são do mesmo tipo, e a variação entre dobras aleatórias é pequena (desvio de 0,02
  no TF-IDF);
- a queda é a diferença entre as duas, na média das dobras e nas previsões fora da
  dobra (cada exemplo previsto uma vez, pelo modelo que não o viu).

**A configuração é fixa**: a do `bertimbau-emi 1.0.0` (5e-5, 4 épocas, lote 16, semente
42), e a dobra de fora é avaliada **no fim da última época**. Aqui ela faz papel de
teste; escolher a época por ela inflaria o número medido (`selecionar_epoca=False`).

**Sem gêmeos.** Comentários idênticos ou quase idênticos espalhados entre dobras inflam a
validação aleatória, e a estimativa do TF-IDF misturava esse efeito com o do vídeo. Por
isso sai também o F1 só dos exemplos fora da dobra **sem gêmeo** no treino daquela
dobra (critério de `ml/avaliacao/gemeos.py`), das mesmas previsões, sem treino extra.

**O rótulo é o fraco (Gemini).** Mede imitação da Gemini em vídeo inédito, não acerto
contra humano: o que interessa é a QUEDA. Nada daqui vai para o Capítulo 5 como acerto,
e o teste humano não participa.

**Regra de leitura, gravada antes de rodar:** a queda que decide é a das previsões fora
da dobra **sem gêmeos**. Abaixo de 3 pontos de F1 macro, a queda é pequena e uma rodada
de treino voltada a vídeos novos não se paga; de 3 pontos para cima, ela é relevante.

Uso:
    # Colab (T4), cerca de 25 minutos: dez treinos de 4 épocas
    python -m ml.treino.validacao_por_video --id-execucao 4

    # fumaça local, em CPU: corpus pequeno, uma época (grava com sufixo -reduzido)
    python -m ml.treino.validacao_por_video --id-execucao 4 --limite 150 --epocas 1
"""

import argparse
import asyncio
import json
import logging
import random
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from ml.avaliacao.gemeos import LIMIAR_QUASE, buscar_gemeos
from ml.avaliacao.metricas import avaliar_previsoes, intervalo_bootstrap
from ml.config import CLASSES, DIRETORIO_ML, SEMENTE, dsn_postgres
from ml.treino.dados import Exemplo, carregar_exemplos, dividir_estratificado

logger = logging.getLogger("treino")

ARQUIVO_BASELINE = DIRETORIO_ML / "baseline" / "saida" / "busca_baseline.json"
ARQUIVO_SAIDA = DIRETORIO_ML / "treino" / "historico" / "validacao_por_video_bertimbau.json"

DOBRAS = 5
# A configuração do bertimbau-emi 1.0.0 (historico_treinos.md, linha 4).
TAXA_APRENDIZADO = 5e-5
EPOCAS = 4
LOTE = 16
# Regra de leitura (docstring): queda sem gêmeos, fora da dobra, a partir da qual vale
# uma rodada de treino voltada a vídeos novos.
LIMIAR_QUEDA_RELEVANTE = 0.03

ALEATORIA = "aleatoria_estratificada"
POR_VIDEO = "por_video"

# Treina numa partição e devolve os rótulos previstos para a dobra de fora.
Treinador = Callable[[list[Exemplo], list[Exemplo]], list[str]]


async def videos_dos_comentarios(id_execucao: int) -> dict[int, int]:
    """id_comentario -> id_video. A mesma consulta do TF-IDF (`treinar_baseline.py`)."""
    conexao = await asyncpg.connect(dsn_postgres())
    try:
        registros = await conexao.fetch(
            """
            SELECT c.id_comentario, c.id_video
            FROM comentarios c JOIN videos v ON v.id_video = c.id_video
            WHERE v.id_execucao = $1
            """,
            id_execucao,
        )
    finally:
        await conexao.close()
    return {registro["id_comentario"]: registro["id_video"] for registro in registros}


def dobras_por_video_do_tfidf(arquivo: Path = ARQUIVO_BASELINE) -> dict[int, int]:
    """id_video -> dobra (1 a 5), exatamente como o TF-IDF dividiu.

    Ler a composição gravada, em vez de refazer o `GroupKFold`, garante que as duas
    quedas foram medidas nas mesmas dobras — e dispensa o scikit-learn aqui.
    """
    if not arquivo.exists():
        raise SystemExit(
            f"{arquivo} nao existe: as dobras por video saem da validacao do TF-IDF "
            "(python -m ml.baseline.treinar_baseline selecionar --id-execucao 4)."
        )
    conteudo = json.loads(arquivo.read_text(encoding="utf-8"))
    dobras = conteudo["validacao_por_grupo"]["por_video_groupkfold"]["dobras"]
    mapa: dict[int, int] = {}
    for dobra in dobras:
        for video in dobra["videos"]:
            if video in mapa:
                raise ValueError(f"video {video} aparece em duas dobras de {arquivo}")
            mapa[video] = dobra["dobra"]
    return mapa


def dobras_estratificadas(
    rotulos: Sequence[str], dobras: int = DOBRAS, semente: int = SEMENTE
) -> list[int]:
    """A dobra (1 a `dobras`) de cada posição, mantendo a proporção das classes.

    Embaralha cada classe com a semente e distribui em rodízio, continuando o rodízio
    de uma classe para a outra, para que as dobras saiam com tamanhos iguais (±1).
    """
    sorteio = random.Random(semente)
    por_classe: dict[str, list[int]] = defaultdict(list)
    for posicao, rotulo in enumerate(rotulos):
        por_classe[rotulo].append(posicao)

    dobra_de = [0] * len(rotulos)
    vez = 0
    for classe in sorted(por_classe):
        posicoes = por_classe[classe]
        sorteio.shuffle(posicoes)
        for posicao in posicoes:
            dobra_de[posicao] = vez % dobras + 1
            vez += 1
    return dobra_de


def f1_macro(verdadeiros: Sequence[str], previstos: Sequence[str]) -> float:
    """O F1 macro do projeto (denominador 3), da mesma função do Capítulo 5."""
    return avaliar_previsoes(verdadeiros, previstos, CLASSES).f1_macro


def sem_gemeo_no_treino(
    fora: list[Exemplo], treino: list[Exemplo], limiar: float = LIMIAR_QUASE
) -> set[int]:
    """Ids da dobra de fora que NÃO têm gêmeo no treino daquela dobra."""
    gemeos = buscar_gemeos(
        [(exemplo.id_comentario, exemplo.texto_modelo) for exemplo in fora],
        [(exemplo.id_comentario, exemplo.texto_modelo) for exemplo in treino],
        limiar,
    )
    return {exemplo.id_comentario for exemplo in fora} - set(gemeos)


def _agregado(exemplos: list[Exemplo], previsto: dict[int, str], ids: set[int]) -> dict[str, Any]:
    """F1 macro e IC 95% das previsões fora da dobra, só dos `ids` pedidos."""
    escolhidos = [exemplo for exemplo in exemplos if exemplo.id_comentario in ids]
    if not escolhidos:
        # Só acontece em corpus de fumaça: todo exemplo tem gêmeo do outro lado.
        return {"n": 0, "f1_macro": None, "ic95_f1_macro": None}
    verdadeiros = [exemplo.rotulo for exemplo in escolhidos]
    previstos = [previsto[exemplo.id_comentario] for exemplo in escolhidos]
    return {
        "n": len(escolhidos),
        "f1_macro": f1_macro(verdadeiros, previstos),
        "ic95_f1_macro": intervalo_bootstrap(verdadeiros, previstos, CLASSES).get("macro"),
    }


def validar_esquema(
    exemplos: list[Exemplo],
    dobra_de: list[int],
    treinar: Treinador,
    rotulo_de_grupo: Callable[[Exemplo], int] | None = None,
) -> dict[str, Any]:
    """Treina uma vez por dobra e junta as previsões de fora. `treinar` é injetado para
    que a conta possa ser testada sem GPU e sem baixar o BERTimbau."""
    previsto: dict[int, str] = {}
    sem_gemeo: set[int] = set()
    por_dobra: list[dict[str, Any]] = []

    for numero in sorted(set(dobra_de)):
        fora = [e for e, d in zip(exemplos, dobra_de, strict=True) if d == numero]
        treino = [e for e, d in zip(exemplos, dobra_de, strict=True) if d != numero]
        if not fora or not treino:
            continue
        logger.info("  dobra %d: treino %d | fora %d", numero, len(treino), len(fora))
        previstos = treinar(treino, fora)
        if len(previstos) != len(fora):
            raise RuntimeError(
                f"dobra {numero}: {len(previstos)} previsoes para {len(fora)} exemplos"
            )
        for exemplo, rotulo in zip(fora, previstos, strict=True):
            previsto[exemplo.id_comentario] = rotulo
        livres = sem_gemeo_no_treino(fora, treino)
        sem_gemeo |= livres
        por_dobra.append(
            {
                "dobra": numero,
                "n": len(fora),
                "n_sem_gemeo": len(livres),
                "videos": sorted({rotulo_de_grupo(e) for e in fora}) if rotulo_de_grupo else None,
                "f1_macro": f1_macro([e.rotulo for e in fora], previstos),
            }
        )
        logger.info("  dobra %d: F1 macro fora %.4f", numero, por_dobra[-1]["f1_macro"])

    valores = [dobra["f1_macro"] for dobra in por_dobra]
    todos = set(previsto)
    return {
        "f1_macro_media_das_dobras": statistics.mean(valores),
        "f1_macro_desvio_das_dobras": statistics.stdev(valores) if len(valores) > 1 else 0.0,
        "fora_da_dobra": _agregado(exemplos, previsto, todos),
        "fora_da_dobra_sem_gemeos": _agregado(exemplos, previsto, sem_gemeo),
        "dobras": por_dobra,
    }


def quedas(aleatoria: dict[str, Any], por_video: dict[str, Any]) -> dict[str, float | None]:
    """Aleatória menos por vídeo: quanto se perde quando o vídeo não foi visto."""

    def menos(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else a - b

    return {
        "media_das_dobras": aleatoria["f1_macro_media_das_dobras"]
        - por_video["f1_macro_media_das_dobras"],
        "fora_da_dobra": menos(
            aleatoria["fora_da_dobra"]["f1_macro"], por_video["fora_da_dobra"]["f1_macro"]
        ),
        "fora_da_dobra_sem_gemeos": menos(
            aleatoria["fora_da_dobra_sem_gemeos"]["f1_macro"],
            por_video["fora_da_dobra_sem_gemeos"]["f1_macro"],
        ),
    }


def ler_queda(queda_sem_gemeos: float | None, limiar: float = LIMIAR_QUEDA_RELEVANTE) -> str:
    """A regra de leitura da docstring, como texto para o relatório."""
    if queda_sem_gemeos is None:
        return "sem leitura: nenhum exemplo sem gemeo (corpus de fumaca)"
    if queda_sem_gemeos < limiar:
        return (
            f"pequena: {queda_sem_gemeos * 100:.1f} pontos, abaixo de {limiar * 100:.0f}; "
            "uma rodada de treino voltada a videos novos nao se paga"
        )
    return (
        f"relevante: {queda_sem_gemeos * 100:.1f} pontos, a partir de {limiar * 100:.0f}; "
        "vale a rodada 3 (mais videos, validacao por video, teste humano de videos ineditos)"
    )


def queda_do_tfidf(arquivo: Path = ARQUIVO_BASELINE) -> dict[str, float] | None:
    """A queda já medida com o TF-IDF, para ficar ao lado da do BERTimbau."""
    if not arquivo.exists():
        return None
    grupo = json.loads(arquivo.read_text(encoding="utf-8"))["validacao_por_grupo"]
    return grupo.get("queda_estimada_em_video_inedito")


def montar_treinador(epocas: int, dispositivo_pedido: str | None, semente: int) -> Treinador:
    """O treino de verdade: o mesmo laço do `treinar.py`, sem escolher época pela dobra."""
    from ml.treino.dados import Particao
    from ml.treino.treinar import Hiperparametros, escolher_dispositivo, treinar_uma_vez

    dispositivo = escolher_dispositivo(dispositivo_pedido)
    hiperparametros = Hiperparametros(taxa_aprendizado=TAXA_APRENDIZADO, epocas=epocas, lote=LOTE)
    logger.info("dispositivo: %s | %s", dispositivo, hiperparametros.como_dicionario())

    def treinar(treino: list[Exemplo], fora: list[Exemplo]) -> list[str]:
        resultado = treinar_uma_vez(
            Particao(treino=treino, validacao=fora),
            hiperparametros,
            dispositivo,
            semente=semente,
            guardar_estado=False,
            selecionar_epoca=False,
        )
        return list(resultado.previstos or [])

    return treinar


def executar(argumentos: argparse.Namespace) -> dict[str, Any]:
    exemplos_banco = asyncio.run(carregar_exemplos(argumentos.id_execucao))
    if argumentos.limite:
        exemplos_banco = exemplos_banco[: argumentos.limite]
    particao = dividir_estratificado(exemplos_banco)
    # A ordem do TF-IDF: treino + validação da partição do treino oficial.
    exemplos = particao.treino + particao.validacao

    videos = asyncio.run(videos_dos_comentarios(argumentos.id_execucao))
    dobra_do_video = dobras_por_video_do_tfidf()
    sem_dobra = sorted({videos[e.id_comentario] for e in exemplos} - set(dobra_do_video))
    if sem_dobra:
        raise SystemExit(
            f"videos sem dobra no TF-IDF: {sem_dobra}. O corpus mudou desde a validacao do "
            "TF-IDF; refaca-a antes, para as duas quedas serem comparaveis."
        )

    treinar = montar_treinador(argumentos.epocas, argumentos.dispositivo, SEMENTE)
    grupo = {e.id_comentario: videos[e.id_comentario] for e in exemplos}

    logger.info("VALIDACAO ALEATORIA ESTRATIFICADA - %d dobras", DOBRAS)
    aleatoria = validar_esquema(
        exemplos, dobras_estratificadas([e.rotulo for e in exemplos]), treinar
    )
    logger.info("VALIDACAO POR VIDEO - as dobras do TF-IDF")
    por_video = validar_esquema(
        exemplos,
        [dobra_do_video[grupo[e.id_comentario]] for e in exemplos],
        treinar,
        rotulo_de_grupo=lambda e: grupo[e.id_comentario],
    )

    queda = quedas(aleatoria, por_video)
    return {
        "aviso": (
            "rotulo FRACO (Gemini): mede a QUEDA em video inedito, nao o acerto contra "
            "humano. Nada daqui vai para o Capitulo 5 como acerto; o teste humano nao "
            "participa."
        ),
        "data_utc": datetime.now(UTC).isoformat(),
        "id_execucao": argumentos.id_execucao,
        "reduzido": bool(argumentos.limite),
        "dados": {
            "exemplos": len(exemplos),
            "videos": len(set(grupo.values())),
            "ordem": "dividir_estratificado (semente 42): treino + validacao, como no TF-IDF",
            "texto": "texto_modelo (preparar_texto)",
        },
        "configuracao": {
            "modelo_base": "neuralmind/bert-base-portuguese-cased",
            "taxa_aprendizado": TAXA_APRENDIZADO,
            "epocas": argumentos.epocas,
            "lote": LOTE,
            "semente": SEMENTE,
            "epoca_avaliada": "a ultima (sem escolher epoca pela dobra de fora)",
        },
        "dobras": {
            ALEATORIA: "estratificadas pelo rotulo, semente 42, sorteio proprio (stdlib)",
            POR_VIDEO: f"as mesmas do TF-IDF ({ARQUIVO_BASELINE.relative_to(DIRETORIO_ML.parent)})",
            "gemeos": f"ml/avaliacao/gemeos.py, limiar {LIMIAR_QUASE}",
        },
        ALEATORIA: aleatoria,
        POR_VIDEO: por_video,
        "queda_em_video_inedito": queda,
        "queda_do_tfidf": queda_do_tfidf(),
        "regra_de_leitura": {
            "medida": "queda fora da dobra, sem gemeos",
            "limiar": LIMIAR_QUEDA_RELEVANTE,
            "leitura": ler_queda(queda["fora_da_dobra_sem_gemeos"]),
        },
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument("--epocas", type=int, default=EPOCAS)
    parser.add_argument("--limite", type=int, default=None, help="so os N primeiros (fumaca)")
    parser.add_argument("--dispositivo", default=None, help="cuda ou cpu (padrao: o que houver)")
    parser.add_argument("--saida", type=Path, default=None)
    argumentos = parser.parse_args()

    saida = argumentos.saida or (
        ARQUIVO_SAIDA.with_name(ARQUIVO_SAIDA.stem + "-reduzido.json")
        if argumentos.limite
        else ARQUIVO_SAIDA
    )
    relatorio = executar(argumentos)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")

    queda = relatorio["queda_em_video_inedito"]
    logger.info("")
    logger.info("QUEDA EM VIDEO INEDITO (BERTimbau, rotulo fraco)")

    def pontos(valor: float | None) -> str:
        return "sem dado" if valor is None else f"{valor * 100:+.1f} pontos"

    logger.info("  media das dobras ............ %s", pontos(queda["media_das_dobras"]))
    logger.info("  fora da dobra ............... %s", pontos(queda["fora_da_dobra"]))
    logger.info("  fora da dobra, sem gemeos ... %s", pontos(queda["fora_da_dobra_sem_gemeos"]))
    if relatorio["queda_do_tfidf"]:
        logger.info(
            "  TF-IDF, mesmas dobras por video: %s fora da dobra",
            pontos(relatorio["queda_do_tfidf"]["fora_da_dobra"]),
        )
    logger.info("leitura: %s", relatorio["regra_de_leitura"]["leitura"])
    logger.info("relatorio -> %s", saida)


if __name__ == "__main__":
    main()
