# Medição de tempo e de tokens

`medir_tempo_inferencia.py` mede o tempo de **classificação** de 1.000 comentários pelo
caminho do worker de inferência (pré-processamento + modelo, um comentário por vez), num
processo restrito a uma thread e a um núcleo, para simular a instância B1 do Azure. O banco
não entra no tempo. É o número da meta do Capítulo 1 (103,5 s, pior de três rodadas).

O tempo de **ponta a ponta** de uma execução (fila, coleta, classificação e temas) é outra
medida: sai das datas da tabela `jobs` e de `execucoes.concluido_em` em produção.

## Sobre o rótulo `0.1.0-ensaio` em `relatorio_tempo_inferencia.json`

A medição de 30/09/2026 rodou sobre a pasta local `bertimbau-2026-09-30`, treinada naquele dia
com a semente 42, antes de o cartão receber o número da versão publicada. Por isso o campo
`modelo.versao` diz `0.1.0-ensaio`. Os pesos são os da versão 1.0.0: o próprio relatório
confere as 334 previsões do teste contra as publicadas, e as 334 são iguais
(`conferencia_dos_pesos`). O arquivo fica como foi gerado, sem edição à mão.
