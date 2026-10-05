# Vazamento entre treino, validacao e teste

Criterio: `ml/avaliacao/gemeos.py` (exato = texto normalizado identico; quase = Jaccard de trigramas >= 0.8).

## Contagens

| cruzamento | universo | com gemeo | exato | quase | do mesmo video | curtos (<= 3 palavras) |
|---|---|---|---|---|---|---|
| (a) teste x treino+validacao | 334 | 25 | 18 | 7 | 13 | 16 |
| (b) validacao x treino | 330 | 18 | 15 | 3 | 12 | 12 |
| (c) treino x treino | 1870 | 96 | 62 | 34 | 61 | 57 |

No (a): 23 com gemeo no treino, 7 com gemeo na validacao.

## Metricas no teste, com e sem gemeo (IC 95%, bootstrap)

| metodo | grupo | n | F1 macro | IC 95% | acuracia |
|---|---|---|---|---|---|
| lexico | todos | 334 | 0.553 | [0.500; 0.608] | 0.563 |
| lexico | com_gemeo | 25 | 0.464 | [0.260; 0.699] | 0.520 |
| lexico | sem_gemeo | 309 | 0.558 | [0.500; 0.615] | 0.566 |
| lexico | com_gemeo_exato | 18 | 0.488 | [0.309; 0.748] | 0.556 |
| lexico | com_gemeo_no_treino | 23 | 0.537 | [0.351; 0.776] | 0.565 |
| bertimbau | todos | 334 | 0.731 | [0.682; 0.776] | 0.737 |
| bertimbau | com_gemeo | 25 | 0.913 | [0.782; 1.000] | 0.880 |
| bertimbau | sem_gemeo | 309 | 0.720 | [0.666; 0.769] | 0.725 |
| bertimbau | com_gemeo_exato | 18 | 0.960 | [0.829; 1.000] | 0.944 |
| bertimbau | com_gemeo_no_treino | 23 | 0.909 | [0.739; 1.000] | 0.870 |
| tfidf_logreg | todos | 334 | 0.699 | [0.649; 0.745] | 0.701 |
| tfidf_logreg | com_gemeo | 25 | 0.884 | [0.726; 0.971] | 0.840 |
| tfidf_logreg | sem_gemeo | 309 | 0.688 | [0.636; 0.735] | 0.689 |
| tfidf_logreg | com_gemeo_exato | 18 | 0.919 | [0.723; 1.000] | 0.889 |
| tfidf_logreg | com_gemeo_no_treino | 23 | 0.878 | [0.686; 0.968] | 0.826 |
| gemini (rotulo_fraco) | todos | 334 | 0.829 | [0.790; 0.870] | 0.829 |
| gemini (rotulo_fraco) | com_gemeo | 25 | 0.854 | [0.679; 0.958] | 0.800 |
| gemini (rotulo_fraco) | sem_gemeo | 309 | 0.831 | [0.786; 0.870] | 0.832 |
| gemini (rotulo_fraco) | com_gemeo_exato | 18 | 0.919 | [0.734; 1.000] | 0.889 |
| gemini (rotulo_fraco) | com_gemeo_no_treino | 23 | 0.846 | [0.617; 0.953] | 0.783 |

## Com gemeo no treino (n = 23): quem repete o rotulo fraco do gemeo

| quem | concorda com o rotulo fraco do gemeo |
|---|---|
| gabarito | 18 |
| lexico | 15 |
| bertimbau | 21 |
| tfidf_logreg | 22 |
| gemini (rotulo_fraco) | 19 |
