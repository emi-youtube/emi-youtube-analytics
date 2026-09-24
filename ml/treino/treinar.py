"""Fine-tuning do BERTimbau. Roda igual no Colab (T4) e aqui (CPU).

**Este é o ENSAIO.** Os rótulos são os da Gemini (`rotulo_fraco`), então as métricas
de validação que saem daqui dizem se o *pipeline* funciona — não quanto o modelo
acerta. O número do Capítulo 5 sai de `ml/avaliacao/`, contra o `rotulo_humano`, e só
existe depois que o gabarito voltar. Um F1 de validação alto aqui significa "o modelo
aprendeu a imitar a Gemini", que é o objetivo da rotulagem fraca e não um resultado.

**Laço escrito à mão**, sem `Trainer` do `transformers`. São sessenta linhas, e o que
elas fazem — peso de classe na perda, agenda linear com warmup, seleção do melhor
estado pela validação — é exatamente o que a banca pergunta. Um `Trainer` esconderia
essas três decisões atrás de um dicionário de configuração. De quebra, dispensa
`accelerate` e `datasets` no ambiente.

**Hiperparâmetro é escolhido pela VALIDAÇÃO, e só.** `--busca` treina a grade inteira
e escolhe pelo F1 macro de validação; o conjunto de teste não aparece em lugar nenhum
deste arquivo. Olhar o teste e voltar para mexer na taxa de aprendizado transformaria
o teste num segundo conjunto de validação, e as métricas do capítulo deixariam de
valer.

**O treino oficial roda a configuração escolhida com CINCO sementes**, na mesma
partição, e reporta média e desvio padrão do F1 macro. Uma rodada só não distingue
"esta configuração é melhor" de "esta semente teve sorte": com 1.870 exemplos e uma
cabeça de classificação inicializada ao acaso, dois treinos idênticos a menos da
semente variam alguns pontos. O que a banca lê é a média ± desvio; o que o backend
carrega é a semente **mediana** (`escolher_semente_publicada`).

A busca de hiperparâmetros continua com uma semente só, de propósito: ela compara
nove configurações entre si, e nove vezes cinco rodadas custariam a tarde inteira de
GPU para escolher o mesmo vencedor.

Uso:
    # ensaio curto de fumaca, em CPU (o que roda na maquina da equipe)
    python -m ml.treino.treinar --id-execucao 4 --limite 150 --sementes 42 --epocas 1

    # treino oficial: a configuracao escolhida, cinco sementes (Colab, GPU T4)
    python -m ml.treino.treinar --id-execucao 4

    # busca de hiperparametros pela validacao (uma semente)
    python -m ml.treino.treinar --id-execucao 4 --busca
"""

import argparse
import asyncio
import json
import logging
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from preprocessamento import VERSAO as VERSAO_PREPROCESSAMENTO
from torch import nn
from torch.utils.data import DataLoader
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    get_linear_schedule_with_warmup,
)

from ml.avaliacao.metricas import avaliar_previsoes
from ml.config import CLASSES, DIRETORIO_ML, MAX_LENGTH, MODELO_BASE, SEMENTE
from ml.treino.cartao import montar_cartao, validar_cartao
from ml.treino.dados import (
    Exemplo,
    Particao,
    carregar_exemplos,
    distribuicao,
    dividir_estratificado,
    pesos_de_classe,
    relatar_particao,
)

logger = logging.getLogger("treino")

DIRETORIO_MODELOS = DIRETORIO_ML / "modelos"
DIRETORIO_TREINO = DIRETORIO_ML / "treino"

ARQUIVO_BUSCA = DIRETORIO_TREINO / "busca_hiperparametros.json"
ARQUIVO_SEMENTES = DIRETORIO_TREINO / "relatorio_sementes.json"
NOME_MODELO = "bertimbau-ensaio"

# As sementes do treino oficial. Cinco é o menor número que dá um desvio padrão com
# algum sentido sem multiplicar por cinco o custo da GPU — e são sementes fixas, não
# sorteadas, porque um número do TCC que muda a cada execução não é reproduzível.
#
# A primeira é a semente do projeto (`ml.config.SEMENTE`), que continua sendo a da
# PARTIÇÃO: a divisão treino/validação é a mesma nas cinco rodadas. O que varia entre
# elas é só a inicialização da cabeça de classificação e a ordem dos lotes. Misturar
# as duas coisas daria um desvio padrão do qual não se sabe dizer a origem.
SEMENTES_OFICIAIS = (42, 43, 44, 45, 46)

# Versão do modelo que sai deste script. Sobe a cada treino que a equipe decidir
# publicar — é o que vai para `VERSOES_MODELO.versao` e para o `model_card.json`.
VERSAO_MODELO = "0.1.0-ensaio"

# Grade da busca. Pequena de propósito: são os três valores que a literatura de
# fine-tuning de BERT recomenda para a taxa de aprendizado (Devlin et al., 2019) e o
# intervalo de épocas em que 1.870 exemplos ou convergem ou começam a decorar.
GRADE_TAXA_APRENDIZADO = (2e-5, 3e-5, 5e-5)
GRADE_EPOCAS = (2, 3, 4)

# Proporção do treino gasta aquecendo a taxa de aprendizado. 10% é o padrão do BERT;
# sem warmup, os primeiros passos com a cabeça de classificação aleatória sacodem os
# pesos pré-treinados que são justamente o que se quer preservar.
FRACAO_WARMUP = 0.1


@dataclass(frozen=True)
class Hiperparametros:
    """Uma configuração de treino. `frozen` para poder ir inteira no cartão."""

    taxa_aprendizado: float
    epocas: int
    lote: int = 16
    decaimento_peso: float = 0.01
    max_length: int = MAX_LENGTH

    def como_dicionario(self) -> dict[str, Any]:
        return {
            "taxa_aprendizado": self.taxa_aprendizado,
            "epocas": self.epocas,
            "lote": self.lote,
            "decaimento_peso": self.decaimento_peso,
            "max_length": self.max_length,
            "fracao_warmup": FRACAO_WARMUP,
            "otimizador": "AdamW",
            "agenda": "linear com warmup",
        }


@dataclass
class Resultado:
    """O que uma rodada de treino produziu.

    `semente` viaja junto porque, no treino oficial, a rodada só é identificável por
    ela: são cinco resultados com os mesmos hiperparâmetros e a mesma partição.
    """

    hiperparametros: Hiperparametros
    semente: int
    f1_macro: float
    acuracia: float
    f1_por_classe: dict[str, float]
    perda_treino: list[float]
    f1_por_epoca: list[float]
    melhor_epoca: int
    estado: dict[str, Any] | None = None
    segundos: float = 0.0


def fixar_semente(semente: int = SEMENTE) -> None:
    """Deixa a rodada reprodutível — até onde o hardware permite.

    Em GPU, a soma de ponto flutuante não é associativa e a ordem das reduções muda
    entre execuções: dois treinos com a mesma semente ficam próximos, não idênticos.
    Por isso o `model_card.json` registra a semente E as métricas obtidas — a semente
    sozinha não é promessa de reprodução exata em CUDA.
    """
    random.seed(semente)
    torch.manual_seed(semente)
    torch.cuda.manual_seed_all(semente)


def escolher_dispositivo(pedido: str | None = None) -> torch.device:
    """GPU quando houver, CPU quando não. O Colab tem T4; a máquina da equipe, não."""
    if pedido:
        return torch.device(pedido)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class ConjuntoDeComentarios(torch.utils.data.Dataset):
    """Dataset mínimo: devolve o texto e o índice do rótulo.

    A tokenização acontece no `collate`, por lote, e não aqui: assim o padding é o do
    lote (e não `max_length` fixo), o que corta o tempo de época quase pela metade num
    corpus em que a mediana tem muito menos que 128 tokens.
    """

    def __init__(self, exemplos: list[Exemplo], classes: tuple[str, ...]) -> None:
        self.exemplos = exemplos
        self.indice = {classe: posicao for posicao, classe in enumerate(classes)}

    def __len__(self) -> int:
        return len(self.exemplos)

    def __getitem__(self, posicao: int) -> tuple[str, int]:
        exemplo = self.exemplos[posicao]
        return exemplo.texto_modelo, self.indice.get(exemplo.rotulo, -1)


def montar_collate(tokenizador, max_length: int):
    """Fecha o tokenizador dentro da função que o `DataLoader` chama por lote."""

    def collate(itens: list[tuple[str, int]]) -> dict[str, torch.Tensor]:
        textos = [texto for texto, _ in itens]
        rotulos = [rotulo for _, rotulo in itens]
        lote = tokenizador(
            textos,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        lote["labels"] = torch.tensor(rotulos, dtype=torch.long)
        return lote

    return collate


@torch.no_grad()
def prever(modelo, carregador: DataLoader, dispositivo: torch.device) -> list[int]:
    """Índices previstos, na ordem do carregador (que não embaralha na validação)."""
    modelo.eval()
    previstos: list[int] = []
    for lote in carregador:
        lote = {chave: valor.to(dispositivo) for chave, valor in lote.items()}
        saida = modelo(
            input_ids=lote["input_ids"],
            attention_mask=lote["attention_mask"],
            token_type_ids=lote.get("token_type_ids"),
        )
        previstos.extend(saida.logits.argmax(dim=-1).tolist())
    return previstos


def treinar_uma_vez(
    particao: Particao,
    hiperparametros: Hiperparametros,
    dispositivo: torch.device,
    modelo_base: str = MODELO_BASE,
    semente: int = SEMENTE,
    guardar_estado: bool = True,
) -> Resultado:
    """Treina uma configuração e devolve o melhor estado pela validação.

    "Melhor" é por **F1 macro de validação**, avaliado ao fim de cada época. Selecionar
    pela perda de validação daria o mesmo peso às três classes na conta errada; a
    métrica que decide o projeto é o F1 macro (CLAUDE.md regra 8), e é ela que escolhe
    o checkpoint.
    """
    fixar_semente(semente)
    inicio = time.perf_counter()

    tokenizador = AutoTokenizer.from_pretrained(modelo_base)
    modelo = AutoModelForSequenceClassification.from_pretrained(
        modelo_base,
        num_labels=len(CLASSES),
        id2label={posicao: classe for posicao, classe in enumerate(CLASSES)},
        label2id={classe: posicao for posicao, classe in enumerate(CLASSES)},
    ).to(dispositivo)

    collate = montar_collate(tokenizador, hiperparametros.max_length)
    gerador = torch.Generator()
    gerador.manual_seed(semente)

    carregador_treino = DataLoader(
        ConjuntoDeComentarios(particao.treino, CLASSES),
        batch_size=hiperparametros.lote,
        shuffle=True,
        generator=gerador,
        collate_fn=collate,
    )
    carregador_validacao = DataLoader(
        ConjuntoDeComentarios(particao.validacao, CLASSES),
        batch_size=hiperparametros.lote * 2,
        shuffle=False,
        collate_fn=collate,
    )

    pesos = pesos_de_classe(particao.treino)
    perda = nn.CrossEntropyLoss(weight=torch.tensor(pesos, dtype=torch.float, device=dispositivo))

    otimizador = torch.optim.AdamW(
        modelo.parameters(),
        lr=hiperparametros.taxa_aprendizado,
        weight_decay=hiperparametros.decaimento_peso,
    )
    total_de_passos = len(carregador_treino) * hiperparametros.epocas
    agenda = get_linear_schedule_with_warmup(
        otimizador,
        num_warmup_steps=int(total_de_passos * FRACAO_WARMUP),
        num_training_steps=total_de_passos,
    )

    verdadeiros = [exemplo.rotulo for exemplo in particao.validacao]
    melhor_f1 = -1.0
    melhor_epoca = 0
    melhor_estado: dict[str, Any] | None = None
    melhores_metricas = None
    perda_por_epoca: list[float] = []
    f1_por_epoca: list[float] = []

    for epoca in range(1, hiperparametros.epocas + 1):
        modelo.train()
        acumulada = 0.0
        for lote in carregador_treino:
            lote = {chave: valor.to(dispositivo) for chave, valor in lote.items()}
            rotulos = lote.pop("labels")
            saida = modelo(**lote)
            valor = perda(saida.logits, rotulos)

            valor.backward()
            # Corte de norma: o padrão do BERT. Sem ele, um lote atípico pode dar um
            # passo enorme e desfazer épocas de ajuste.
            torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
            otimizador.step()
            agenda.step()
            otimizador.zero_grad()
            acumulada += valor.item()

        media = acumulada / max(len(carregador_treino), 1)
        indices = prever(modelo, carregador_validacao, dispositivo)
        previstos = [CLASSES[indice] for indice in indices]
        metricas = avaliar_previsoes(verdadeiros, previstos, CLASSES)

        perda_por_epoca.append(media)
        f1_por_epoca.append(metricas.f1_macro)
        logger.info(
            "  epoca %d/%d  perda=%.4f  val F1 macro=%.4f  acuracia=%.4f",
            epoca,
            hiperparametros.epocas,
            media,
            metricas.f1_macro,
            metricas.acuracia,
        )

        if metricas.f1_macro > melhor_f1:
            melhor_f1 = metricas.f1_macro
            melhor_epoca = epoca
            melhores_metricas = metricas
            if guardar_estado:
                melhor_estado = {
                    chave: valor.detach().cpu().clone()
                    for chave, valor in modelo.state_dict().items()
                }

    if melhores_metricas is None:  # pragma: no cover - so acontece com epocas=0
        raise RuntimeError("nenhuma epoca executada")

    return Resultado(
        hiperparametros=hiperparametros,
        semente=semente,
        f1_macro=melhores_metricas.f1_macro,
        acuracia=melhores_metricas.acuracia,
        f1_por_classe={
            classe: metricas_classe.f1
            for classe, metricas_classe in melhores_metricas.por_classe.items()
        },
        perda_treino=perda_por_epoca,
        f1_por_epoca=f1_por_epoca,
        melhor_epoca=melhor_epoca,
        estado=melhor_estado,
        segundos=time.perf_counter() - inicio,
    )


def buscar_hiperparametros(
    particao: Particao,
    dispositivo: torch.device,
    modelo_base: str = MODELO_BASE,
    lote: int = 16,
    semente: int = SEMENTE,
    taxas: tuple[float, ...] = GRADE_TAXA_APRENDIZADO,
    epocas: tuple[int, ...] = GRADE_EPOCAS,
) -> tuple[Hiperparametros, list[Resultado]]:
    """Treina a grade inteira e escolhe pelo F1 macro de VALIDAÇÃO.

    Nove configurações. Não guarda o estado de cada uma (nove BERTs na memória são
    ~4 GB): o vencedor é retreinado depois, com a mesma semente, o que dá o mesmo
    resultado e custa uma rodada a mais.

    O relatório da busca inteira é gravado — inclusive das configurações perdedoras.
    É o que responde "por que essa taxa de aprendizado?" sem depender da memória de
    quem rodou.

    **Uma semente só, de propósito.** O que se compara aqui são nove configurações
    entre si; repetir cada uma cinco vezes custaria a tarde de GPU inteira para
    escolher, quase sempre, a mesma vencedora. A variação entre sementes é medida
    depois, uma vez, na configuração escolhida (`treinar_varias_sementes`).

    `taxas` e `epocas` existem para o ensaio reduzido do notebook rodar a mesma
    função com uma grade de uma célula só — a grade do projeto continua sendo o
    padrão, e ninguém precisa reescrever o laço para encurtá-lo.
    """
    resultados: list[Resultado] = []
    for taxa in taxas:
        for quantas in epocas:
            hiperparametros = Hiperparametros(taxa_aprendizado=taxa, epocas=quantas, lote=lote)
            logger.info("")
            logger.info("--- lr=%.0e  epocas=%d  lote=%d", taxa, quantas, lote)
            resultados.append(
                treinar_uma_vez(
                    particao,
                    hiperparametros,
                    dispositivo,
                    modelo_base=modelo_base,
                    semente=semente,
                    guardar_estado=False,
                )
            )

    melhor = max(resultados, key=lambda resultado: resultado.f1_macro)
    return melhor.hiperparametros, resultados


def treinar_varias_sementes(
    particao: Particao,
    hiperparametros: Hiperparametros,
    dispositivo: torch.device,
    sementes: tuple[int, ...] = SEMENTES_OFICIAIS,
    modelo_base: str = MODELO_BASE,
) -> list[Resultado]:
    """Treina a MESMA configuração, na MESMA partição, uma vez por semente.

    O que varia entre as rodadas é só o sorteio: a inicialização da cabeça de
    classificação e a ordem em que os lotes aparecem. A partição fica fora dessa
    variação de propósito — se ela mudasse junto, o desvio padrão resultante
    misturaria duas fontes e não responderia mais "quanto este treino oscila".

    **Guarda o estado das cinco rodadas**, e isso custa memória: são ~420 MB por
    rodada em CPU, ~2,1 GB no total. Pagar esse preço é o que permite publicar
    exatamente os pesos que produziram a linha mediana da tabela. A alternativa —
    descartar tudo e retreinar a vencedora no fim, como a busca faz — não reproduz
    bit a bit em GPU (ver `fixar_semente`), e aí o artefato publicado carregaria uma
    métrica que não é a dele.
    """
    resultados: list[Resultado] = []
    for posicao, semente in enumerate(sementes, start=1):
        logger.info("")
        logger.info("--- semente %d (%d/%d)", semente, posicao, len(sementes))
        resultados.append(
            treinar_uma_vez(
                particao,
                hiperparametros,
                dispositivo,
                modelo_base=modelo_base,
                semente=semente,
                guardar_estado=True,
            )
        )
    return resultados


def estatisticas(valores: list[float]) -> dict[str, float]:
    """Média, desvio padrão, mínimo, mediana e máximo de uma métrica.

    Desvio padrão **amostral** (divisor n-1): as cinco sementes são uma amostra do
    sorteio de inicialização, não a população de todos os treinos possíveis. Com n=5 o
    amostral sai 12% maior que o populacional, e reportar o menor dos dois faria a
    instabilidade do treino parecer menor do que ela é.
    """
    return {
        "media": statistics.mean(valores),
        "desvio": statistics.stdev(valores) if len(valores) > 1 else 0.0,
        "minimo": min(valores),
        "mediana": statistics.median(valores),
        "maximo": max(valores),
    }


def escolher_semente_publicada(resultados: list[Resultado]) -> Resultado:
    """A rodada **mediana** em F1 macro de validação — nem a melhor, nem a pior.

    Publicar a melhor das cinco seria escolher pelo máximo de uma amostra: o artefato
    sairia com um número sistematicamente acima da média que o relatório reporta, e as
    duas linhas do TCC se contradiriam. A mediana é o representante honesto da
    distribuição que acabou de ser medida, e continua sendo uma escolha feita pela
    VALIDAÇÃO — o conjunto de teste não aparece aqui, como não aparece em nenhum
    ponto deste arquivo.

    Empate é desfeito pela semente, para que a mesma tabela publique sempre o mesmo
    modelo. Com número par de sementes (só acontece no ensaio reduzido) não existe
    mediana exata: sai a superior das duas centrais.

    >>> from dataclasses import replace
    >>> base = Resultado(Hiperparametros(3e-5, 1), 42, 0.5, 0.5, {}, [], [], 1)
    >>> rodadas = [replace(base, semente=s, f1_macro=f)
    ...            for s, f in [(42, 0.70), (43, 0.62), (44, 0.75)]]
    >>> escolher_semente_publicada(rodadas).semente
    42
    """
    ordenadas = sorted(resultados, key=lambda resultado: (resultado.f1_macro, resultado.semente))
    return ordenadas[len(ordenadas) // 2]


def resumir_sementes(resultados: list[Resultado], publicada: Resultado) -> dict[str, Any]:
    """O bloco que vai para o `relatorio_sementes.json` e para dentro do cartão.

    Sai daqui uma vez e é usado nos dois lugares: se o relatório e o cartão montassem
    cada um o seu, eles divergiriam no primeiro campo acrescentado — e o cartão é o
    que o backend lê.
    """
    return {
        "sementes": [resultado.semente for resultado in resultados],
        "semente_publicada": publicada.semente,
        "criterio_publicacao": "semente mediana em F1 macro de validacao",
        "particao": f"fixa para todas as sementes (semente {SEMENTE})",
        "f1_macro": estatisticas([resultado.f1_macro for resultado in resultados]),
        "acuracia": estatisticas([resultado.acuracia for resultado in resultados]),
        "por_semente": [
            {
                "semente": resultado.semente,
                "f1_macro": resultado.f1_macro,
                "acuracia": resultado.acuracia,
                "f1_por_classe": resultado.f1_por_classe,
                "melhor_epoca": resultado.melhor_epoca,
                "segundos": round(resultado.segundos, 1),
            }
            for resultado in sorted(resultados, key=lambda resultado: resultado.semente)
        ],
    }


def relatar_sementes(resumo: dict[str, Any]) -> None:
    """Imprime a tabela das sementes. É o que se lê antes de aceitar o modelo."""
    f1 = resumo["f1_macro"]
    logger.info("")
    logger.info("=" * 66)
    logger.info("TREINO OFICIAL - %d sementes, particao fixa", len(resumo["sementes"]))
    logger.info("=" * 66)
    logger.info("  %-10s %12s %12s %10s", "semente", "F1 macro", "acuracia", "epoca")
    for linha in resumo["por_semente"]:
        marca = "  <- publicada" if linha["semente"] == resumo["semente_publicada"] else ""
        logger.info(
            "  %-10d %12.4f %12.4f %10d%s",
            linha["semente"],
            linha["f1_macro"],
            linha["acuracia"],
            linha["melhor_epoca"],
            marca,
        )
    logger.info("-" * 66)
    logger.info(
        "  F1 macro: media %.4f  desvio %.4f  (min %.4f, max %.4f)",
        f1["media"],
        f1["desvio"],
        f1["minimo"],
        f1["maximo"],
    )
    logger.info(
        "  publicada: semente %d, a mediana — nem a melhor nem a pior",
        resumo["semente_publicada"],
    )
    logger.info("=" * 66)


def gravar_sementes(
    resumo: dict[str, Any], hiperparametros: Hiperparametros, caminho: Path
) -> None:
    """Grava as cinco rodadas — versionado, e só agregados."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "aviso": (
            "metricas de VALIDACAO com rotulo fraco (Gemini). Medem a estabilidade do "
            "treino, NAO a qualidade do modelo. O numero do Capitulo 5 sai de "
            "ml/avaliacao/, contra o rotulo_humano."
        ),
        "hiperparametros": hiperparametros.como_dicionario(),
        **resumo,
    }
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("sementes -> %s", caminho)


def gravar_busca(resultados: list[Resultado], melhor: Hiperparametros, caminho: Path) -> None:
    """Grava a grade inteira — agregados, nenhum texto de terceiros."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "aviso": (
            "metricas de VALIDACAO com rotulo fraco (Gemini). Servem para escolher "
            "hiperparametro e checar o pipeline. NAO vao para o Capitulo 5."
        ),
        "criterio": "F1 macro de validacao",
        "escolhido": melhor.como_dicionario(),
        "grade": [
            {
                **resultado.hiperparametros.como_dicionario(),
                "f1_macro": resultado.f1_macro,
                "acuracia": resultado.acuracia,
                "f1_por_classe": resultado.f1_por_classe,
                "melhor_epoca": resultado.melhor_epoca,
                "segundos": round(resultado.segundos, 1),
            }
            for resultado in sorted(resultados, key=lambda r: -r.f1_macro)
        ],
    }
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("busca -> %s", caminho)


def salvar_modelo(
    resultado: Resultado,
    particao: Particao,
    destino: Path,
    modelo_base: str = MODELO_BASE,
    versao: str = VERSAO_MODELO,
    sementes: dict[str, Any] | None = None,
) -> Path:
    """Grava pesos, tokenizer e `model_card.json` na pasta do modelo.

    Os três saem juntos e sempre: peso sem tokenizer não classifica, e peso sem cartão
    classifica errado em silêncio (regra 5).

    A semente do cartão é a do `resultado` — a rodada cujos pesos estão sendo gravados,
    e não uma constante. `sementes` é o resumo das cinco rodadas (`resumir_sementes`):
    ele entra no cartão para que quem abrir o artefato veja a média e o desvio ao lado
    do número da rodada publicada, sem precisar do relatório separado.
    """
    destino.mkdir(parents=True, exist_ok=True)

    tokenizador = AutoTokenizer.from_pretrained(modelo_base)
    modelo = AutoModelForSequenceClassification.from_pretrained(
        modelo_base,
        num_labels=len(CLASSES),
        id2label={posicao: classe for posicao, classe in enumerate(CLASSES)},
        label2id={classe: posicao for posicao, classe in enumerate(CLASSES)},
    )
    if resultado.estado is not None:
        modelo.load_state_dict(resultado.estado)

    modelo.save_pretrained(destino)
    tokenizador.save_pretrained(destino)

    cartao = montar_cartao(
        classes=CLASSES,
        max_length=resultado.hiperparametros.max_length,
        versao=versao,
        versao_preprocessamento=VERSAO_PREPROCESSAMENTO,
        modelo_base=modelo_base,
        hiperparametros=resultado.hiperparametros.como_dicionario(),
        semente=resultado.semente,
        metricas_validacao={
            "aviso": (
                "rotulo fraco (Gemini) — checagem de pipeline, NAO e metrica do "
                "Capitulo 5. O numero do capitulo sai de ml/avaliacao/ contra o "
                "rotulo_humano."
            ),
            "f1_macro": resultado.f1_macro,
            "acuracia": resultado.acuracia,
            "f1_por_classe": resultado.f1_por_classe,
            "melhor_epoca": resultado.melhor_epoca,
            "f1_por_epoca": resultado.f1_por_epoca,
            "perda_treino_por_epoca": resultado.perda_treino,
            **({"sementes": sementes} if sementes else {}),
        },
        dados={
            "fonte": "exemplos_treinamento.rotulo_fraco, split IS NULL",
            "treino": len(particao.treino),
            "validacao": len(particao.validacao),
            "distribuicao_treino": distribuicao(particao.treino),
            "distribuicao_validacao": distribuicao(particao.validacao),
            "particao": "85/15 estratificada, em memoria (nao gravada no banco)",
            "pesos_de_classe": dict(
                zip(CLASSES, pesos_de_classe(particao.treino), strict=True)
            ),
        },
        observacoes=(
            "Ensaio da Sprint 1: treinado com rotulo fraco. O conjunto de teste "
            "(split='teste', 334 comentarios) nao participou de nenhuma etapa."
        ),
    )
    validar_cartao(cartao)
    (destino / "model_card.json").write_text(
        json.dumps(cartao, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info("")
    logger.info("modelo -> %s", destino)
    logger.info("  pesos, tokenizer e model_card.json")
    return destino


def caminhos_de_saida(limite: int | None, saida: Path | None) -> tuple[Path, Path, Path]:
    """Onde esta rodada grava: relatório da busca, relatório das sementes e modelo.

    Com `--limite` os três ganham o sufixo `-reduzido`. Os dois JSON já ganhavam; a
    pasta do MODELO não, e foi por aí que um ensaio de fumaça de 150 exemplos gravou
    por cima dos pesos de uma sessão de T4 — `ml/modelos/` está fora do git, e o que
    se perde ali não volta de lugar nenhum. Um cartão dizendo `treino: 128` no lugar
    do de 1.870 nem parece errado até alguém conferir.

    É a mesma regra do notebook (`ENSAIO_REDUZIDO`), e agora pelo mesmo motivo nos dois
    lados: os três caminhos saem de uma função só, e nenhuma parte do script monta
    caminho por conta própria.

    `--saida` explicito vence o sufixo: quem escreve o caminho na mão está dizendo
    exatamente onde quer.

    >>> busca, sementes, modelo = caminhos_de_saida(150, None)
    >>> modelo.name
    'bertimbau-ensaio-reduzido'
    >>> caminhos_de_saida(None, None)[2].name
    'bertimbau-ensaio'
    """
    sufixo = "-reduzido" if limite else ""
    return (
        ARQUIVO_BUSCA.with_name(f"{ARQUIVO_BUSCA.stem}{sufixo}.json"),
        ARQUIVO_SEMENTES.with_name(f"{ARQUIVO_SEMENTES.stem}{sufixo}.json"),
        saida or DIRETORIO_MODELOS / f"{NOME_MODELO}{sufixo}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument("--epocas", type=int, default=3)
    parser.add_argument("--lote", type=int, default=16)
    parser.add_argument("--taxa-aprendizado", type=float, default=3e-5)
    parser.add_argument(
        "--sementes",
        type=int,
        nargs="+",
        default=list(SEMENTES_OFICIAIS),
        metavar="N",
        help=(
            "sementes do treino oficial: a configuracao roda uma vez por semente e o "
            "relatorio sai com media e desvio. A PARTICAO nao muda com elas."
        ),
    )
    parser.add_argument("--modelo-base", default=MODELO_BASE)
    parser.add_argument(
        "--saida",
        type=Path,
        default=None,
        help=(
            "pasta do modelo (padrao: ml/modelos/bertimbau-ensaio, e "
            "bertimbau-ensaio-reduzido quando houver --limite)"
        ),
    )
    parser.add_argument("--dispositivo", default=None, help="cuda, cpu (padrao: detecta)")
    parser.add_argument(
        "--busca",
        action="store_true",
        help="treina a grade e escolhe pela validacao (ignora --epocas/--taxa-aprendizado)",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="usa so os N primeiros exemplos — teste de fumaca, nao treino",
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(message)s", stream=sys.stdout)

    exemplos = asyncio.run(carregar_exemplos(argumentos.id_execucao))
    if argumentos.limite:
        exemplos = exemplos[: argumentos.limite]
        logger.warning(
            "LIMITE=%s: isto e teste de fumaca, nao treino. As metricas nao valem nada.",
            argumentos.limite,
        )
    if not exemplos:
        raise SystemExit(
            f"nenhum exemplo com split NULL e rotulo_fraco na execucao {argumentos.id_execucao}. "
            "Rode antes: python -m ml.rotulagem.rotular_fraco --id-execucao "
            f"{argumentos.id_execucao}"
        )

    # Ensaio de fumaca nao escreve por cima de artefato oficial: com --limite, os dois
    # JSON *e a pasta do modelo* saem com sufixo. Mesma regra do notebook
    # (ENSAIO_REDUZIDO), e pelo mesmo motivo -- um JSON de 150 exemplos parado no lugar
    # do oficial e indistinguivel do verdadeiro seis meses depois, e os pesos por cima
    # dos quais ele gravaria estao fora do git.
    arquivo_busca, arquivo_sementes, destino = caminhos_de_saida(
        argumentos.limite, argumentos.saida
    )

    # A particao sai da semente do PROJETO, sempre, e nao das sementes de treino: as
    # cinco rodadas precisam ser comparaveis entre si, e duas validacoes diferentes
    # dariam um desvio padrao que mistura "o treino oscila" com "a validacao mudou".
    particao = dividir_estratificado(exemplos)
    relatar_particao(particao, pesos_de_classe(particao.treino))

    dispositivo = escolher_dispositivo(argumentos.dispositivo)
    logger.info("dispositivo: %s", dispositivo)

    if argumentos.busca:
        escolhido, resultados_busca = buscar_hiperparametros(
            particao,
            dispositivo,
            modelo_base=argumentos.modelo_base,
            lote=argumentos.lote,
        )
        gravar_busca(resultados_busca, escolhido, arquivo_busca)
        logger.info("")
        logger.info(
            "escolhido pela validacao: lr=%.0e epocas=%d",
            escolhido.taxa_aprendizado,
            escolhido.epocas,
        )
    else:
        escolhido = Hiperparametros(
            taxa_aprendizado=argumentos.taxa_aprendizado,
            epocas=argumentos.epocas,
            lote=argumentos.lote,
        )

    logger.info("")
    logger.info("treino oficial: %d semente(s), a mesma particao", len(argumentos.sementes))
    resultados = treinar_varias_sementes(
        particao,
        escolhido,
        dispositivo,
        sementes=tuple(argumentos.sementes),
        modelo_base=argumentos.modelo_base,
    )

    publicada = escolher_semente_publicada(resultados)
    resumo = resumir_sementes(resultados, publicada)
    relatar_sementes(resumo)
    gravar_sementes(resumo, escolhido, arquivo_sementes)

    salvar_modelo(
        publicada,
        particao,
        destino,
        modelo_base=argumentos.modelo_base,
        sementes=resumo,
    )

    logger.info("")
    logger.info("Metricas acima sao de VALIDACAO com rotulo fraco: servem para checar o")
    logger.info("pipeline, nao para o Capitulo 5. O numero do capitulo sai de")
    logger.info("ml/avaliacao/, contra o rotulo_humano, depois que o gabarito voltar.")


if __name__ == "__main__":
    main()
