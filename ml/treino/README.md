# ml/treino — o ensaio do fine-tuning

Fine-tuning do BERTimbau com o **rótulo fraco** da Gemini, enquanto o gabarito humano
não volta. O mesmo código roda no Colab (T4) e na máquina da equipe (CPU).

```bash
# teste de fumaca local, em CPU (~2 min): corpus pequeno e uma semente so.
# Com --limite TUDO sai com sufixo -reduzido -- os dois relatorios e a pasta do
# modelo. Os pesos do treino de verdade estao fora do git e uma sessao de T4 nao
# volta: ja aconteceu de um ensaio de 150 exemplos gravar por cima deles.
python -m ml.treino.treinar --id-execucao 4 --limite 150 --sementes 42 --epocas 1 --lote 8

# treino oficial: busca de hiperparametros + a configuracao escolhida em 5 sementes
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

### O ambiente do Colab tem quatro armadilhas

As quatro já custaram uma sessão:

- **instalação editável não vale no kernel que já está rodando.** `pip install -e`
  registra um `.pth` que o interpretador lê ao iniciar; num kernel vivo, o pacote só
  aparece depois de *Reiniciar ambiente de execução*. Por isso o notebook reinstala o
  `preprocessamento` **sem `-e`** depois dos requirements. O `ml/requirements.txt`
  continua editável de propósito — é o que faz uma mudança no mapa de emoji valer nos
  dois ambientes locais sem reinstalar;
- **`!pip` que falha não interrompe o notebook.** O erro rola para fora da tela e a
  célula seguinte quebra com um `ModuleNotFoundError` que não tem nada a ver com a
  causa: foi assim que uma instalação incompleta apareceu como "No module named
  'asyncpg'" três células adiante. O `asyncpg` está nos requisitos desde sempre — e o
  `pip install --dry-run` a partir da raiz do repositório resolve ele e o
  `preprocessamento` sem erro; o que faltou foi a instalação inteira ter dado certo no
  Colab. Hoje a instalação é `subprocess.run(..., check=True)`, que para na linha que
  falha, e a célula de verificação importa tudo logo depois — o erro aparece onde
  nasce;
- **clone não idempotente cria uma cópia dentro da outra.** `git clone` rodado de
  dentro do próprio repositório produz `emi-youtube-analytics/emi-youtube-analytics`, e
  a partir daí cada célula grava numa cópia diferente conforme o diretório em que o
  kernel estiver. Foi o que matou a exportação ONNX: o treino salvou o modelo numa
  cópia, a exportação foi procurá-lo na outra — onde `ml/modelos/` nem existe, porque a
  pasta inteira está no `.gitignore` (o `.gitkeep` não é reincluído: `git` não readmite
  arquivo sob diretório excluído). Daí as duas regras do notebook: o clone **atualiza**
  em vez de clonar de novo, e **todo caminho sai da constante `RAIZ`**, absoluta;
- **`asyncio.run` não roda dentro de um kernel.** O Colab já tem um laço de eventos
  vivo, e `asyncio.run` dentro de um laço vivo levanta `RuntimeError: asyncio.run()
  cannot be called from a running event loop`. Em notebook a forma certa é o `await` de
  nível superior. Nos scripts (`treinar.py`, `exportar_onnx.py`) o `asyncio.run`
  continua certo: ali o laço é só deles.

A célula de verificação também compara **versão instalada com pino do requirements**. O
Colab já vem com `torch`, e uma instalação que falhou em silêncio deixa o notebook
rodando com a versão da casa: o treino até roda, e quem quebra é a exportação quatro
células depois, com uma mensagem que não fala em versão nenhuma. A mesma conferência
pegou um caso local — o `ipykernel` puxa `ipython`, que exige `psutil>=7`, e instalar o
`requirements-dev.txt` subiu o `psutil` que mede o RSS do relatório ONNX.

`ml/tests/test_ambiente_colab.py` protege as quatro coisas. Ele lê os comandos **do
próprio notebook** — copiar a lista de pacotes para o teste criaria uma segunda fonte
de verdade, que é o tipo de divergência que ele deveria detectar.

---

## Estas métricas não vão para o Capítulo 5

Os rótulos são os da Gemini. Um F1 de validação alto aqui significa **"o modelo
aprendeu a imitar a Gemini"** — que é exatamente o objetivo da rotulagem fraca, e não
um resultado sobre sentimento. O número do capítulo sai de `ml/avaliacao/`, contra o
`rotulo_humano`, e só existe depois que o gabarito voltar.

Por isso o aviso está escrito dentro do `model_card.json`, do
`busca_hiperparametros.json`, do `relatorio_sementes.json` e do `relatorio_onnx.json`:
daqui a seis meses, ninguém vai lembrar de qual JSON era qual.

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

A busca roda com **uma semente**. O que ela compara são nove configurações entre si, e
repetir cada uma cinco vezes custaria a tarde de GPU inteira para escolher, quase
sempre, a mesma vencedora. A variação entre sementes é medida uma vez, depois, na
configuração escolhida.

## O treino oficial roda cinco sementes

Uma rodada só não distingue "esta configuração é melhor" de "esta semente teve sorte".
Com 1.870 exemplos e uma cabeça de classificação inicializada ao acaso, dois treinos
idênticos a menos da semente variam alguns pontos de F1 macro — e um TCC que reporta o
número de uma rodada única está reportando também a sorte dela.

`python -m ml.treino.treinar --id-execucao 4` roda a configuração escolhida com as
sementes **42, 43, 44, 45 e 46** e grava `relatorio_sementes.json` com a tabela das
cinco, média, desvio padrão, mínimo, mediana e máximo.

| decisão | por quê |
|---|---|
| **partição fixa** nas cinco rodadas | o que varia é só o sorteio da inicialização e a ordem dos lotes. Se a partição mudasse junto, o desvio misturaria "o treino oscila" com "a validação mudou", e não responderia nem uma coisa nem outra |
| **desvio padrão amostral** (divisor n-1) | as cinco sementes são uma amostra do sorteio, não a população de todos os treinos possíveis. Com n=5 o amostral sai 12% maior que o populacional — usar o menor dos dois faria a instabilidade do treino parecer menor do que é |
| **publica a semente mediana** | publicar a melhor das cinco seria escolher pelo máximo de uma amostra: o artefato sairia com um número sistematicamente acima da média reportada duas linhas antes. A mediana é o representante honesto da distribuição — e continua sendo escolha pela **validação**, não pelo teste |
| **as cinco rodadas ficam na memória** (~420 MB cada) | os pesos publicados são exatamente os que produziram a linha mediana da tabela. Descartar e retreinar a mediana no fim seria mais econômico e não reproduz bit a bit em GPU |

As sementes são **fixas, não sorteadas**: um número do TCC que muda a cada execução não
é reproduzível. A primeira é a semente do projeto (`ml.config.SEMENTE`), que continua
sendo a da partição.

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

### O que a medição do ensaio deu: **int8 reprovado**

Medido nos 330 comentários da validação, com os pesos do ensaio
(`relatorio_onnx.json`, uma thread, um processo por formato):

| | F1 macro | mediana | p95 | RSS de pico | tamanho | previsões ≠ base |
|---|---|---|---|---|---|---|
| pytorch fp32 | 0,8051 | 89,1 ms | 181,8 ms | 666 MB | 416,2 MB | — |
| onnx fp32 | 0,8051 | 59,0 ms | 154,3 ms | 1.059 MB | 415,8 MB | **0** / 330 |
| onnx int8 | 0,7648 | 28,0 ms | 80,5 ms | 579 MB | 104,7 MB | **53** / 330 |

O int8 é ~3× mais rápido que o PyTorch e ocupa 25% do tamanho, mas perde **4,0 pontos
de F1 macro** — quatro vezes o portão de 1 ponto. **Reprovado**, e não por pouco: 53 dos
330 comentários (16,1%) mudam de rótulo, muito acima do limite de 2% que já seria aviso.

As colunas de qualidade são determinísticas — duas execuções dão os mesmos F1 até o
último dígito. As de tempo **não**: duas medições nesta mesma máquina deram 3,2× e 4,1×
para o int8, porque a latência depende do que mais estava rodando. Leia os tempos como
ordem de grandeza, e meça de novo no hardware que vai hospedar.

A perda **não** cai onde se esperaria: o neutro, que é a classe mais fraca no fp32, é a
que menos perde (−1,3 ponto). Quem desaba é o **negativo** (−6,5), seguido do positivo
(−4,3) — ou seja, o int8 estraga justamente as duas classes que o fp32 acertava bem. Não
é "classe difícil fica mais difícil", é outra coisa; qual, esta medição não diz.

Duas ressalvas antes de concluir qualquer coisa sobre a arquitetura:

- **o modelo medido é o do ensaio**, treinado com rótulo fraco e já decorando: a perda
  de treino cai de 0,178 para 0,074 na quarta época enquanto o F1 de validação para de
  subir na terceira (0,8051 → 0,8030). Modelo que decora sai com logit extremo, e é
  justamente a faixa que a quantização dinâmica representa pior — este número **não**
  transfere direto para o modelo final;
- **quem decide é o F1 contra o `rotulo_humano`**, não este. A medição aqui responde
  "o int8 responde como o fp32?", e a resposta foi não.

O caminho que sobra para a B1, enquanto isso: o **onnx fp32** é ~1,5× mais rápido
sem trocar **nenhuma** previsão — 0 de 330, e é por isso que o relatório grava a
divergência de todo formato, não só a do int8: zero ali é o que separa "o int8 degradou"
de "a exportação degradou".

O que o fp32 não resolve é a memória: **1.059 MB de pico contra 666 MB do PyTorch**.
Cada formato é medido no seu próprio processo, então não é contaminação de um pelo
outro — o `onnxruntime` gasta mesmo mais RSS que o PyTorch para o mesmo grafo, e a causa
não foi investigada. Cabe nos 1,75 GB da B1, com folga menor que a do PyTorch. É esta a
medição a repetir depois do treino oficial, junto com a decisão de se o int8 volta para
a mesa.

## Testes

`ml/tests/test_treino.py` cobre partição, pesos de classe e `model_card.json` — sem
`torch` e sem banco, para rodar na máquina de quem só mexe na API (que é justamente
quem quebra o contrato do cartão sem perceber). O laço de treino em si é exercitado
pelo teste de fumaça acima, que roda de verdade contra o modelo de verdade.

`ml/tests/test_ambiente_colab.py` tem dois níveis. O estático roda sempre e confere
que a célula de instalação do notebook cobre cada import de terceiros de `ml/treino`.
O real cria um ambiente virtual limpo, roda os comandos de instalação do notebook e
importa todos os módulos lá dentro — é o único que reproduz o Colab, e por isso só
roda sob demanda:

```bash
TESTE_AMBIENTE=1 ml/.venv/Scripts/python.exe -m pytest ml/tests/test_ambiente_colab.py
```

Rode-o antes de mexer no notebook ou nos requirements. O teste de fumaça **não** pega
esse tipo de erro: ele roda no `ml/.venv`, que já tem tudo instalado desde a
exportação do corpus.

`ml/tests/test_sementes.py` cobre a estatística das cinco rodadas e a escolha de quem é
publicado — média, desvio amostral, mediana e desempate. Fica separado do
`test_treino.py` porque importa `treinar.py`, que carrega `torch`; sem `torch`
instalado ele se pula sozinho.

`ml/tests/test_notebook.py` **executa o notebook inteiro** num kernel (`nbclient`), com
`ENSAIO_REDUZIDO=1`: corpus de 150, grade de uma configuração, duas sementes, medição
ONNX em 40 comentários. Ele não mede qualidade nenhuma — prova que **nenhuma célula
levanta exceção** e que **todo caminho que o notebook promete gravar existe no fim, com
data desta execução**. É o teste que faltava: as correções anteriores do notebook
passaram no `ruff` e nos testes estáticos, e a sessão seguinte no Colab quebrou mesmo
assim, porque erro de notebook (laço de eventos já rodando, caminho montado na hora,
célula que promete arquivo e não grava) só aparece executando.

```bash
TESTE_NOTEBOOK=1 ml/.venv/Scripts/python.exe -m pytest ml/tests/test_notebook.py
```

Precisa de banco e de uns 20 minutos. Rode-o depois de mexer no notebook e **antes** de
gastar uma sessão de GPU com ele. As células que só existem no Colab (clone, `pip`,
cofre, download) ficam atrás do `NO_COLAB` e não executam aqui — quem cobre a instalação
é o `test_ambiente_colab.py`.

## Custo de tempo

| | |
|---|---|
| teste de fumaça, CPU (150 exemplos, 1 época) | ~2 min |
| treino completo, CPU (1.870 exemplos, 3 épocas) | ~40 min — dá para rodar, mas é para o Colab |
| treino completo, T4 | ~2 min |
| treino oficial (5 sementes), T4 | ~10 min |
| busca das 9 configurações, T4 | ~25 min |
| conversão + medição ONNX, CPU | ~8 min (330 comentários) |
| notebook inteiro reduzido, CPU (`TESTE_NOTEBOOK=1`) | ~20 min |

## O que é versionado

| arquivo | conteúdo | versionado? |
|---|---|---|
| `busca_hiperparametros.json` | a grade inteira, com as métricas de validação de cada configuração | **sim** |
| `relatorio_sementes.json` | as cinco rodadas, média e desvio, e qual semente foi publicada | **sim** |
| `relatorio_onnx.json` | F1, divergência, latência, RAM e tamanho dos três formatos | **sim** |
| `colab_bertimbau.ipynb` | o notebook (sem saídas) | **sim** |
| `ml/modelos/` | pesos, tokenizer, `model_card.json`, grafos ONNX | não (`.gitignore`) |
| `ml/dados/previsoes_bertimbau.csv` | previsões do teste | não (`.gitignore`) |

Os três JSON só têm agregados — nenhum texto de terceiros. O modelo é regenerável a
partir deles mais o corpus.
