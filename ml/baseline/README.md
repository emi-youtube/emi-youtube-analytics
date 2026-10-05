# ml/baseline — TF-IDF + regressão logística

O degrau que faltava no Capítulo 5, entre o piso léxico e o BERTimbau: um classificador
supervisionado clássico, treinado com **os mesmos dados** do BERTimbau. É ele que separa
"o BERTimbau é bom" de "qualquer modelo supervisionado com 1.870 rótulos fracos chegaria
lá".

```bash
pip install -r ml/requirements-baseline.txt   # scikit-learn

# 1. grade pela validacao + validacao por grupo de videos. NAO le o teste.
python -m ml.baseline.treinar_baseline selecionar --id-execucao 4

# 2. a escolhida, treinada no treino, avaliada no teste UMA vez
python -m ml.baseline.treinar_baseline avaliar-teste --id-execucao 4
```

A segunda etapa lê a configuração de `saida/busca_baseline.json` — não escolhe de novo —
e se recusa a rodar se `ml/dados/previsoes_baseline.csv` já existir (`--refazer` só para
erro de operação). É a mesma separação de `treinar.py` e `prever_teste.py`: o teste é
olhado uma vez, e o código garante isso, não a memória de quem roda.

`ml/` não usava `scikit-learn` fora dos testes. Ele entra só aqui, num requirements
próprio: o Colab não precisa dele, e o pino que o notebook confere não muda.

## Mesmas condições do BERTimbau

| | BERTimbau (rodada 1) | baseline |
|---|---|---|
| exemplos | 2.200 de `split IS NULL`, `rotulo_fraco` | os mesmos (`carregar_exemplos`) |
| partição | 1.870 / 330, semente 42 | a mesma função (`dividir_estratificado`) |
| texto | `preparar_texto` | o mesmo `texto_modelo` |
| desbalanceamento | peso `N / (k * n_j)` | `class_weight='balanced'` — a mesma fórmula |
| escolha | F1 macro de validação | F1 macro de validação |
| teste | 334, `rotulo_humano`, uma vez | o mesmo, uma vez, com `ml/avaliacao/` |

## A grade (12 configurações, validação de 330)

C ∈ {0,1; 1; 10} × n-gramas de palavra {(1,1), (1,2)} × n-gramas de caractere
(`char_wb` 2–5) {não, sim}. TF-IDF sublinear; o token aceita palavra de uma letra (o
padrão do scikit-learn descarta "n", que é "não").

| C | palavra | caractere | F1 macro val |
|---|---|---|---|
| **10** | **(1,2)** | **sim** | **0,7419** ← escolhida |
| 1 | (1,1) | sim | 0,7390 |
| 10 | (1,1) | sim | 0,7359 |
| 1 | (1,2) | sim | 0,7282 |
| 10 | (1,1) | não | 0,7114 |
| … | | | (as 12 em `saida/busca_baseline.json`) |

N-grama de caractere é o que mais pesa (+3 pontos): é a robustez à grafia ("musica" ×
"música", "vamooo") que o modelo linear não tem de outro jeito. A escolhida ficou em
C = 10, o canto da grade, mas a distância para C = 1 é de 0,3 ponto — abaixo da variação
que a própria validação de 330 tem. A grade não foi estendida.

## No teste (334, gabarito humano, uma vez — 04/10/2026)

| método | F1 macro | IC 95% | acurácia | κ |
|---|---|---|---|---|
| léxico | 0,553 | [0,500; 0,608] | 0,563 | 0,332 |
| **TF-IDF + logreg** | **0,699** | **[0,649; 0,745]** | 0,701 | 0,552 |
| BERTimbau 1.0.0 | 0,731 | [0,682; 0,776] | 0,737 | 0,601 |
| Gemini (rótulo fraco) | 0,829 | [0,790; 0,870] | 0,829 | 0,744 |

**Diferença pareada, BERTimbau − baseline: +0,032, IC 95% [−0,020; +0,086]**
(`saida/comparacao_bertimbau_baseline.json`, bootstrap pareado, 2.000 reamostragens).

O intervalo cruza o zero: **com 334 comentários, a vantagem do BERTimbau sobre um TF-IDF
bem ajustado não está demonstrada.** O ponto favorece o BERTimbau, e o que aparece por
classe é onde: o baseline perde 8 pontos no `neutro` (0,623 contra 0,705) e empata no
`positivo` e no `negativo`. Isso é resultado de capítulo, não detalhe — e é o argumento
para a rodada 2 e, depois, para o Large.

Tabelas, matrizes e figuras dos quatro métodos lado a lado, geradas pelo mesmo código
do Capítulo 5: `saida/avaliacao/`.

## Validação por grupo de vídeos: quanto cai num vídeo inédito

Os 2.200 com rótulo fraco, a configuração escolhida, 5 dobras nos dois esquemas:

| esquema | F1 macro (média ± desvio das dobras) | F1 fora da dobra | IC 95% |
|---|---|---|---|
| aleatória estratificada | 0,713 ± 0,020 | 0,713 | [0,694; 0,732] |
| **por vídeo** (`GroupKFold`) | **0,612 ± 0,028** | **0,632** | [0,612; 0,653] |
| **queda** | **−10,0 pontos** | **−8,1 pontos** | |

Na partição aleatória, comentários do mesmo vídeo caem dos dois lados, e o modelo acerta
em parte por reconhecer o assunto do vídeo. Num vídeo que ele nunca viu — **a situação
real da PME**, cuja campanha não estava no corpus — o F1 cai 8 a 10 pontos. Os IC dos dois
esquemas não se tocam.

Duas ressalvas para o texto do TCC:

- o rótulo aqui é o **fraco** (Gemini): o número absoluto mede imitação da Gemini; o que
  interessa é a **queda** entre os esquemas;
- o teste humano de 334 foi sorteado do **mesmo** conjunto de 14 vídeos do treino, ou
  seja, ele é da partição "aleatória". O F1 de 0,731 do BERTimbau provavelmente é
  otimista para um vídeo novo; quanto, só um teste humano com vídeos fora do corpus
  mede — a queda do baseline aqui é um indício, não a medida do BERTimbau.

## O que é versionado

| arquivo | conteúdo |
|---|---|
| `saida/busca_baseline.json` | a grade inteira, a escolhida e a validação por grupo (dobras, vídeos de cada dobra, F1) |
| `saida/avaliacao/` | tabelas, `resultado_avaliacao.json` e figuras dos quatro métodos no teste |
| `saida/comparacao_bertimbau_baseline.json` | o delta pareado e o IC |
| `ml/dados/previsoes_baseline.csv` | **não** (`.gitignore`), como as outras previsões |

Só agregados e ids — nenhum texto de comentário.
