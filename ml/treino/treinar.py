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

Uso:
    # ensaio curto de fumaca, em CPU (o que roda na maquina da equipe)
    python -m ml.treino.treinar --id-execucao 4 --limite 60 --epocas 1 --lote 8

    # treino completo (Colab, GPU T4)
    python -m ml.treino.treinar --id-execucao 4

    # busca de hiperparametros pela validacao
    python -m ml.treino.treinar --id-execucao 4 --busca
"""

import argparse
import asyncio
import json
import logging
import random
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
    """O que uma rodada de treino produziu."""

    hiperparametros: Hiperparametros
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
) -> tuple[Hiperparametros, list[Resultado]]:
    """Treina a grade inteira e escolhe pelo F1 macro de VALIDAÇÃO.

    Nove configurações. Não guarda o estado de cada uma (nove BERTs na memória são
    ~4 GB): o vencedor é retreinado depois, com a mesma semente, o que dá o mesmo
    resultado e custa uma rodada a mais.

    O relatório da busca inteira é gravado — inclusive das configurações perdedoras.
    É o que responde "por que essa taxa de aprendizado?" sem depender da memória de
    quem rodou.
    """
    resultados: list[Resultado] = []
    for taxa in GRADE_TAXA_APRENDIZADO:
        for epocas in GRADE_EPOCAS:
            hiperparametros = Hiperparametros(taxa_aprendizado=taxa, epocas=epocas, lote=lote)
            logger.info("")
            logger.info("--- lr=%.0e  epocas=%d  lote=%d", taxa, epocas, lote)
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
    semente: int = SEMENTE,
) -> Path:
    """Grava pesos, tokenizer e `model_card.json` na pasta do modelo.

    Os três saem juntos e sempre: peso sem tokenizer não classifica, e peso sem cartão
    classifica errado em silêncio (regra 5).
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
        semente=semente,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument("--epocas", type=int, default=3)
    parser.add_argument("--lote", type=int, default=16)
    parser.add_argument("--taxa-aprendizado", type=float, default=3e-5)
    parser.add_argument("--semente", type=int, default=SEMENTE)
    parser.add_argument("--modelo-base", default=MODELO_BASE)
    parser.add_argument("--saida", type=Path, default=DIRETORIO_MODELOS / "bertimbau-ensaio")
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

    particao = dividir_estratificado(exemplos, semente=argumentos.semente)
    relatar_particao(particao, pesos_de_classe(particao.treino))

    dispositivo = escolher_dispositivo(argumentos.dispositivo)
    logger.info("dispositivo: %s", dispositivo)

    if argumentos.busca:
        escolhido, resultados = buscar_hiperparametros(
            particao,
            dispositivo,
            modelo_base=argumentos.modelo_base,
            lote=argumentos.lote,
            semente=argumentos.semente,
        )
        gravar_busca(resultados, escolhido, ARQUIVO_BUSCA)
        logger.info("")
        logger.info(
            "escolhido pela validacao: lr=%.0e epocas=%d",
            escolhido.taxa_aprendizado,
            escolhido.epocas,
        )
        logger.info("retreinando a configuracao vencedora para guardar os pesos...")
    else:
        escolhido = Hiperparametros(
            taxa_aprendizado=argumentos.taxa_aprendizado,
            epocas=argumentos.epocas,
            lote=argumentos.lote,
        )

    logger.info("")
    resultado = treinar_uma_vez(
        particao,
        escolhido,
        dispositivo,
        modelo_base=argumentos.modelo_base,
        semente=argumentos.semente,
    )
    logger.info("")
    logger.info(
        "melhor epoca: %d  |  val F1 macro: %.4f  |  %.0fs",
        resultado.melhor_epoca,
        resultado.f1_macro,
        resultado.segundos,
    )

    salvar_modelo(
        resultado,
        particao,
        argumentos.saida,
        modelo_base=argumentos.modelo_base,
        semente=argumentos.semente,
    )

    logger.info("")
    logger.info("Metricas acima sao de VALIDACAO com rotulo fraco: servem para checar o")
    logger.info("pipeline, nao para o Capitulo 5. O numero do capitulo sai de")
    logger.info("ml/avaliacao/, contra o rotulo_humano, depois que o gabarito voltar.")


if __name__ == "__main__":
    main()
