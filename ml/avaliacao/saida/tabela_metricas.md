# Capitulo 5 - tabelas

Gabarito humano, 334 comentarios.

## Tabela 1 - desempenho geral por metodo

| metodo | acuracia | precisao macro | revocacao macro | F1 macro | IC 95% (F1 macro) | kappa de Cohen |
|---|---|---|---|---|---|---|
| lexico | 0.563 | 0.576 | 0.556 | **0.553** | [0.500; 0.608] | 0.332 |
| bertimbau | 0.737 | 0.731 | 0.737 | **0.731** | [0.682; 0.776] | 0.601 |
| gemini (rotulo_fraco) | 0.829 | 0.829 | 0.843 | **0.829** | [0.790; 0.870] | 0.744 |

## Tabela 2 - desempenho por classe (IC 95% do F1, bootstrap)

| metodo | classe | precisao | revocacao | F1 | IC 95% | suporte |
|---|---|---|---|---|---|---|
| lexico | positivo | 0.648 | 0.461 | 0.539 | [0.458; 0.618] | 128 |
| lexico | negativo | 0.563 | 0.476 | 0.516 | [0.418; 0.611] | 84 |
| lexico | neutro | 0.517 | 0.730 | 0.605 | [0.540; 0.669] | 122 |
| bertimbau | positivo | 0.774 | 0.805 | 0.789 | [0.733; 0.840] | 128 |
| bertimbau | negativo | 0.656 | 0.750 | 0.700 | [0.619; 0.770] | 84 |
| bertimbau | neutro | 0.762 | 0.656 | 0.705 | [0.635; 0.769] | 122 |
| gemini (rotulo_fraco) | positivo | 0.938 | 0.820 | 0.875 | [0.831; 0.917] | 128 |
| gemini (rotulo_fraco) | negativo | 0.730 | 0.964 | 0.831 | [0.773; 0.884] | 84 |
| gemini (rotulo_fraco) | neutro | 0.820 | 0.746 | 0.781 | [0.720; 0.841] | 122 |

## Tabela 3 - matrizes de confusao (linha = gabarito, coluna = previsto)

### lexico

| gabarito \ previsto | positivo | negativo | neutro |
|---|---|---|---|
| **positivo** | 59 | 16 | 53 |
| **negativo** | 14 | 40 | 30 |
| **neutro** | 18 | 15 | 89 |

### bertimbau

| gabarito \ previsto | positivo | negativo | neutro |
|---|---|---|---|
| **positivo** | 103 | 8 | 17 |
| **negativo** | 13 | 63 | 8 |
| **neutro** | 17 | 25 | 80 |

### gemini (rotulo_fraco)

| gabarito \ previsto | positivo | negativo | neutro |
|---|---|---|---|
| **positivo** | 105 | 6 | 17 |
| **negativo** | 0 | 81 | 3 |
| **neutro** | 7 | 24 | 91 |
