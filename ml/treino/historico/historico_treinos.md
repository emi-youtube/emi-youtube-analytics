# Histórico de treinos do BERTimbau

Evidência para o TCC: todo treino que a equipe rodou, com o que foi usado, o que saiu e
de onde cada número vem. Uma linha por treino, na ordem em que aconteceram.

**Regra de datas.** Cada data diz a sua fonte: `treinado_em_utc` do `model_card.json`,
data de commit ou data de modificação do arquivo baixado. Onde nenhum artefato registra
a data exata, está escrito **não registrada** — nada aqui foi estimado.

**O que é métrica de quê.** "F1 val" é F1 macro na **validação de rótulo fraco**
(Gemini, 330 comentários): mede imitação da Gemini e escolhe hiperparâmetro, não vai
para o Capítulo 5. "Teste humano" é F1 macro contra o `rotulo_humano` dos 334
(`split = 'teste'`), avaliado uma única vez por rodada.

## Rodada 1

| # | treino | data (fonte) | objetivo | modelo-base | hiperparâmetros | sementes | corpus e partição | F1 val | teste humano | commit | sha256 dos pesos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **ensaio** `0.1.0-ensaio` | 23/09/2026 21:31:50 UTC (`treinado_em_utc` do cartão do ensaio); busca baixada 23/09 18:38 -03 (data do arquivo) | provar o pipeline de ponta a ponta com o rótulo fraco, antes de o gabarito voltar | `neuralmind/bert-base-portuguese-cased` | busca 3 taxas {2e-5, 3e-5, 5e-5} × 3 épocas {2, 3, 4}; escolhida **5e-5, 4 épocas** (melhor época 3); lote 16, decaimento 0,01, warmup 10%, `max_length` 128, AdamW, agenda linear | **42** (uma só; as cinco sementes entraram em `11a035f`, 24/09) | execução 4: 2.200 de `split IS NULL` com `rotulo_fraco`; 1.870 / 330 estratificado, semente 42; `preprocessamento` 1.1.0 | **0,8051** | **não** — nenhum artefato registra avaliação deste modelo contra o `rotulo_humano` | código do treino: `22d7c64` (na `main` desde o PR #7, 23/09 13:18). O commit que o Colab clonou não foi registrado | `9db349f8ece01217a125b0485630bb12c86f505388fd4a2c8dc7699e5e650d49` |
| 2 | **teste de fumaça reduzido** (`ENSAIO_REDUZIDO=1`, `ml/tests/test_notebook.py`) | 28/09/2026 16:52 -03 (data dos arquivos `*-reduzido.json`, não versionados) | provar que todas as células do notebook rodam e gravam o que prometem — não mede qualidade | `neuralmind/bert-base-portuguese-cased` | grade de uma configuração: 3e-5, 1 época; lote 16, demais iguais | 42 e 43 | os **150 primeiros** exemplos: 128 / 22, semente 42; CPU | 0,2741 (42) e 0,2722 (43) — sem significado com 128 exemplos e 1 época | **não** — o notebook gerou previsões (`previsoes_bertimbau-reduzido.csv`), nenhuma foi avaliada | não registrado. O commit seguinte no histórico é `9cd42d5` (28/09 17:47, correções do notebook) | não registrado (pasta `-reduzido` não foi guardada) |
| 3 | **busca de hiperparâmetros oficial** | não registrada no arquivo; baixado 30/09 10:49 -03 (data do arquivo), junto com o relatório das sementes, da mesma sessão do Colab | escolher taxa e épocas pela validação | `neuralmind/bert-base-portuguese-cased` | a mesma grade 3 × 3; escolhida **5e-5, 4 épocas** (melhor época 4) — **no canto da grade**: maior taxa e maior número de épocas | 42 | a mesma da linha 1 (2.200; 1.870 / 330, semente 42) | **0,8167** | não (a busca não olha o teste) | não registrado; último merge na `main` antes do treino: `e0df271` (PR #22, 28/09) | — (a busca não guarda pesos) |
| 4 | **treino oficial, 5 sementes** → `bertimbau-emi 1.0.0` (produção) | 30/09/2026 13:44:17 UTC (`treinado_em_utc` do cartão) | medir a variação entre sementes e publicar a mediana | `neuralmind/bert-base-portuguese-cased` | 5e-5, 4 épocas, lote 16, demais iguais | 42, 43, 44, 45, 46; **publicada a 42** (mediana) | a mesma da linha 1 | 0,8167 (42), 0,8060 (43), 0,8302 (44), 0,8187 (45), 0,8027 (46); **média 0,8149 ± 0,0110** (desvio amostral) | **sim, uma vez**, em 30/09: F1 macro **0,7314**, IC 95% [0,6816; 0,7764], acurácia 0,7365, κ de Cohen 0,601 (`ml/avaliacao/saida/resultado_avaliacao.json`) | não registrado; último merge na `main` antes do treino: `e0df271`. Avaliação: `4660bcb`, `e85dc53` | `acdea8d393472fc996469f88f94c9936ecbeaed12c5735757959c7fb593b1617` (confere com `backend/app/inferencia/bertimbau_manifesto.json`) |

### Arquivos desta pasta

| arquivo | o que é | sha256 |
|---|---|---|
| `relatorio_sementes.json` | as cinco sementes de 30/09 (linha 4), cópia byte a byte do download | `a7163cb6…54b3c8` |
| `busca_hiperparametros.json` | a busca oficial de 30/09 (linha 3), cópia byte a byte do arquivo `busca_hiperparametros (1).json` de Downloads | `aba61fe7…62f7ae` |
| `busca_hiperparametros_anterior_2026-09-23.json` | a busca do ensaio (linha 1), **não é da rodada oficial**. Igual ao download mais o campo `aviso_historico` no topo; o original tinha sha256 `7a0c1562…d8ac50` | — |
| `model_card_bertimbau-emi-1.0.0.json` | o cartão do modelo de produção, **sem os pesos**. Byte a byte igual ao que o manifesto do backend confere | `c98548fb…bf25c2a` |
| `regra_decisao_rodada2.md` | a regra que decide a rodada 2, gravada **antes** do treino | — |

O `ml/treino/relatorio_onnx.json` (já versionado, 24/09) é a medição ONNX dos pesos do
**ensaio** (linha 1), não do modelo de produção.

### A variação entre execuções (linhas 1 e 3)

As duas buscas usam a mesma grade, a mesma semente, a mesma partição e o mesmo corpus.
Entre `22d7c64` e `e0df271`, o laço de treino (`treinar_uma_vez`) e os pinos de `torch`
e `transformers` não mudaram — a diferença de código é só o parâmetro `semente`. Mesmo
assim:

| taxa | épocas | F1 val 23/09 | F1 val 30/09 | diferença |
|---|---|---|---|---|
| 2e-5 | 2 | 0,7824 | 0,7757 | −0,0067 |
| 2e-5 | 3 | 0,7818 | 0,7824 | +0,0006 |
| 2e-5 | 4 | 0,7907 | 0,7973 | +0,0066 |
| 3e-5 | 2 | 0,7833 | 0,7856 | +0,0023 |
| 3e-5 | 3 | 0,8021 | 0,7983 | −0,0038 |
| 3e-5 | 4 | 0,8011 | 0,8033 | +0,0022 |
| 5e-5 | 2 | 0,7796 | 0,7809 | +0,0013 |
| 5e-5 | 3 | 0,7877 | 0,7881 | +0,0005 |
| **5e-5** | **4** | **0,8051** | **0,8167** | **+0,0116** |

A mesma configuração com a mesma semente variou até 1,2 ponto de F1 macro de uma sessão
para outra — da ordem do desvio entre sementes (1,1 ponto). A explicação documentada é a
de `fixar_semente`: em GPU a soma de ponto flutuante não é associativa e a ordem das
reduções muda entre execuções. O ambiente CUDA de cada sessão não foi registrado, então
a causa não pode ser isolada além disso. A consequência para o TCC: diferenças de
validação abaixo de ~1 ponto entre configurações da grade não separam uma da outra.

## Rodada 2

Ainda não treinada. A regra que vai decidir se o modelo novo substitui o de produção
está em `regra_decisao_rodada2.md`, gravada antes de qualquer treino. As saídas da
rodada 2 entram nesta pasta com o sufixo `_rodada2`, sem sobrescrever nada da rodada 1.
