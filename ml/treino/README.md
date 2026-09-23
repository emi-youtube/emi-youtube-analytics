# ml/treino — o ensaio do fine-tuning

Fine-tuning do BERTimbau com o **rótulo fraco** da Gemini, enquanto o gabarito humano
não volta. O mesmo código roda no Colab (T4) e na máquina da equipe (CPU).

```bash
# teste de fumaca local, em CPU (~2 min)
python -m ml.treino.treinar --id-execucao 4 --limite 150 --epocas 1 --lote 8

# treino completo + busca de hiperparametros (Colab, T4)
python -m ml.treino.treinar --id-execucao 4 --busca

# conversao para ONNX int8 e medicao de RAM/latencia
python -m ml.treino.exportar_onnx --id-execucao 4 --modelo ml/modelos/bertimbau-ensaio

# o teste, uma unica vez, no fim: previsoes (nenhuma metrica)
python -m ml.treino.prever_teste --id-execucao 4 --modelo ml/modelos/bertimbau-ensaio
```

O notebook `colab_bertimbau.ipynb` faz esses mesmos passos na T4. Ele **não
reimplementa nada**: clona o repositório e chama estes módulos. Notebook com código
próprio diverge do repositório na primeira correção, e aí o modelo publicado deixa de
ser o que o repositório descreve.

---

## Estas métricas não vão para o Capítulo 5

Os rótulos são os da Gemini. Um F1 de validação alto aqui significa **"o modelo
aprendeu a imitar a Gemini"** — que é exatamente o objetivo da rotulagem fraca, e não
um resultado sobre sentimento. O número do capítulo sai de `ml/avaliacao/`, contra o
`rotulo_humano`, e só existe depois que o gabarito voltar.

Por isso o aviso está escrito dentro do `model_card.json`, do
`busca_hiperparametros.json` e do `relatorio_onnx.json`: daqui a seis meses, ninguém
vai lembrar de qual JSON era qual.

## Quem entra no treino

| | |
|---|---|
| fonte | `exemplos_treinamento`, `split IS NULL` e `rotulo_fraco IS NOT NULL` |
| total | 2.200 (positivo 968, neutro 653, negativo 579) |
| treino / validação | 1.870 / 330, estratificado 85/15, semente 42 |
| entrada do modelo | `preparar_texto` (pacote `preprocessamento`, v1.1.0) |
| fora | os 334 de `split = 'teste'` — em nenhuma etapa |

**A partição não vai para o banco, e isso é deliberado.** Se o Kappa ficar abaixo de
0,60, a Seção 9 do manual manda sortear uma amostra humana **nova**, e o sorteio
(`ml/amostra/sortear_amostra_humana.py`) só enxerga quem está sem partição. Gravar
`split` aqui marcaria os 2.200 como treino/validação e esvaziaria justamente o pool de
onde essa segunda rodada teria que sair. Enquanto o gabarito não volta, a partição é
um detalhe do ensaio, não um fato do corpus.

**O peso de classe sai do treino, não do corpus** — `N / (k * n_j)`, o
`class_weight='balanced'` do CLAUDE.md regra 8, escrito à mão. Calcular sobre o corpus
inteiro deixaria a composição da validação vazar para dentro da função de perda:
vazamento pequeno, e gratuito de evitar. Com a distribuição real, positivo pesa 0,757 e
negativo 1,267 — sem isso, a saída ótima para a perda média é chutar `positivo` (44% do
corpus), a acurácia sobe e o F1 macro desaba.

## Hiperparâmetro é escolhido pela validação, e só

`--busca` treina as nove configurações (3 taxas × 3 números de época) e escolhe pelo
**F1 macro de validação**. A grade inteira — inclusive as perdedoras — vai para
`busca_hiperparametros.json`, que é o que responde "por que essa taxa de aprendizado?"
sem depender da memória de quem rodou.

O conjunto de teste não aparece em `treinar.py` em lugar nenhum. Olhar o teste e voltar
para mexer num hiperparâmetro transformaria o teste num segundo conjunto de validação,
e as métricas do Capítulo 5 perderiam o sentido que o TC2 atribui a elas. É também por
isso que `prever_teste.py` **carrega os 334 sem os rótulos** e não calcula métrica
nenhuma: a comparação é outro processo, rodado depois.

## Por que o laço é escrito à mão

Sem `Trainer` do `transformers`. São sessenta linhas, e o que elas fazem é exatamente o
que a banca pergunta:

- **peso de classe na perda** (`CrossEntropyLoss(weight=...)`);
- **agenda linear com 10% de warmup** — sem ela, os primeiros passos com a cabeça de
  classificação aleatória sacodem os pesos pré-treinados que são o motivo de usar o
  BERTimbau;
- **corte de norma do gradiente em 1,0**, o padrão do BERT;
- **seleção do melhor estado pelo F1 macro de validação**, não pela última época nem
  pela perda — a métrica que decide o projeto é a que escolhe o checkpoint.

Um `Trainer` esconderia as quatro atrás de um dicionário de configuração. De quebra,
dispensa `accelerate` e `datasets` no ambiente.

A tokenização acontece por lote, no `collate`, com padding do lote em vez de
`max_length` fixo: num corpus cuja mediana é muito menor que 128 tokens, isso corta o
tempo de época quase pela metade.

## O `model_card.json`

O contrato entre o `ml/` e o `backend/` — as duas metades não se importam, conversam
por artefato (CLAUDE.md Seção 3). Três campos existem por causa de bugs que evitam:

| campo | o que evita |
|---|---|
| `id2label` | a ordem dos rótulos sai daqui, nunca do código (regra 5). Hardcodar causa bug silencioso: prevê "negativo", grava "neutro" |
| `versao_preprocessamento` | o worker **recusa o modelo** se divergir da versão instalada — texto de produção diferente do texto de treino tem que ser erro, não queda silenciosa de acurácia |
| `max_length` | truncar em 128 no treino e em 512 na inferência daria ao modelo uma entrada com cauda que ele nunca viu |

O resto (hiperparâmetros, semente, distribuição dos conjuntos, métricas, data) é
reprodutibilidade. `validar_cartao` confere tudo **antes** de o cartão sair junto dos
pesos: um cartão quebrado é barato aqui e caro no worker, em produção, no meio de uma
execução.

## ONNX int8 — o modelo cabe na instância B1?

A pergunta não é de qualidade, é de infraestrutura: o crédito do Azure for Students
paga uma B1 (1 vCPU, 1,75 GB), e um BERT em float32 não cabe com folga. O portão é
perder no máximo **1 ponto de F1 macro** na validação.

Duas decisões de método que mudaram o resultado quando foram corrigidas:

- **uma thread nos dois lados.** O `torch` usa todos os núcleos por padrão e o
  `onnxruntime` está preso a um aqui de propósito. Sem igualar, a primeira medição
  dizia que o ONNX era *mais lento* que o PyTorch — estava medindo o número de núcleos
  da máquina de desenvolvimento, não o formato;
- **um processo por formato.** Com os três no mesmo processo, o RSS do ONNX sai somado
  ao do BERT do PyTorch ainda carregado: a primeira medição acusou 1.158 MB para um
  grafo de 416 MB. Cada formato agora é medido num subprocesso, e o número que sai é o
  que o Azure vai cobrar.

Além do F1, o relatório traz a **divergência de previsão** — quantos comentários mudam
de rótulo. O F1 pode empatar com os erros trocando de lugar, e aí o int8 acerta *outros*
comentários, não os mesmos. Acima de 2% isso vira aviso (não é portão: o portão é o F1).

## Custo de tempo

| | |
|---|---|
| teste de fumaça, CPU (150 exemplos, 1 época) | ~2 min |
| treino completo, CPU (1.870 exemplos, 3 épocas) | ~40 min — dá para rodar, mas é para o Colab |
| treino completo, T4 | ~2 min |
| busca das 9 configurações, T4 | ~25 min |
| conversão + medição ONNX, CPU | ~5 min |

## O que é versionado

| arquivo | conteúdo | versionado? |
|---|---|---|
| `busca_hiperparametros.json` | a grade inteira, com as métricas de validação de cada configuração | **sim** |
| `relatorio_onnx.json` | F1, latência, RAM e tamanho dos três formatos | **sim** |
| `colab_bertimbau.ipynb` | o notebook (sem saídas) | **sim** |
| `ml/modelos/` | pesos, tokenizer, `model_card.json`, grafos ONNX | não (`.gitignore`) |
| `ml/dados/previsoes_bertimbau.csv` | previsões do teste | não (`.gitignore`) |

Os dois JSON só têm agregados — nenhum texto de terceiros. O modelo é regenerável a
partir deles mais o corpus.
