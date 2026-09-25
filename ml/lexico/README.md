# ml/lexico — a linha de base do Capítulo 5

Classificador de sentimento por **soma de polaridade** sobre o **SentiLex-PT**, o
léxico que o TC2 cita na Seção 3.8.

Ele não é um concorrente do BERTimbau: é o **piso**. O número que o modelo treinado
precisa superar para que o custo de treinar um modelo se justifique no capítulo de
resultados. Um piso que tivesse sido ajustado deixaria de responder a essa pergunta.

> **A regra não mora mais aqui.** Ela está no pacote compartilhado `lexico/`
> (`lexico/src/lexico/sentilex.py`), instalado nos dois ambientes como o
> `preprocessamento/`, porque o worker de inferência do backend passou a usá-la — ver
> "Promoção para o pacote compartilhado" no fim deste arquivo. Nesta pasta ficou o que
> é **experimento**: `classificar_teste.py`, o `metadados_lexico.json` e esta
> documentação.

```bash
# 1. baixe o recurso (ver "Proveniência" abaixo) para ml/lexico/dados/
# 2. classifique a amostra humana e guarde as previsoes
python -m ml.lexico.classificar_teste --id-execucao <N>
```

Saída: `ml/dados/previsoes_lexico.csv` (previsões, uma por comentário) e
`ml/lexico/metadados_lexico.json` (agregados, hash do recurso — versionado).

---

## As cinco decisões, e o que sustenta cada uma

### 1. A entrada é o `texto_modelo`, não o texto original

O léxico lê exatamente o que o BERTimbau vai ler: o resultado de `preparar_texto`
(`preprocessamento/`, v1.1.0). **É o que isola o método na comparação.** Se o léxico
lesse o texto canônico e o BERTimbau o pré-processado, a diferença entre os dois
misturaria duas causas — o método e o pré-processamento — e o Capítulo 5 não poderia
atribuir o ganho a nenhuma delas.

Efeito colateral, documentado porque aparece no resultado: a conversão de emoji faz o
léxico **enxergar emoji**. Onze palavras do mapa de emoji têm polaridade no SentiLex —
😍 vira "amei" (+1), 😡 vira "raiva" (−1), 😭 vira "choro" (−1), 🤩 vira "maravilhoso"
(+1). Sem o pré-processamento compartilhado, tudo isso seria pontuação para a regra de
soma. O piso está sendo medido com essa ajuda, e o capítulo tem que dizer isso.

Um efeito colateral do efeito colateral: 😎 vira "estiloso", que o SentiLex marca como
**−1**. O piso não tem como saber que ali a intenção era elogio.

### 2. A regra é a soma, e só

```
escore = soma das polaridades das palavras conhecidas
escore > 0 -> positivo   |   escore < 0 -> negativo   |   escore = 0 -> neutro
```

Sem negação, sem intensificador, sem janela de escopo, sem desambiguação por classe
gramatical, sem descontar repetição. Cada uma dessas heurísticas melhoraria o número —
e é exatamente por isso que nenhuma entra.

O `neutro` cobre dois fracassos diferentes, e o relatório os separa: o texto em que o
léxico **não achou nada** e o texto em que os dois lados **se anularam**.

### 3. A polaridade vem do sujeito; quando ele é neutro, do complemento

O SentiLex não declara "a polaridade da palavra". Ele declara a polaridade que a
palavra confere a um **alvo humano**, por posição sintática — o recurso foi construído
para mineração de julgamento social sobre pessoas, e essa é a distância entre ele e a
nossa tarefa, que julga um anúncio.

```
adorar.PoS=V;TG=HUM:N0:N1;POL:N0=0;POL:N1=1     quem adora nao e julgado; quem e adorado sai bem
abandonar.PoS=V;TG=HUM:N0:N1;POL:N0=-1;POL:N1=0 quem abandona sai mal; quem e abandonado, neutro
```

A regra adotada: **vale o `POL:N0`; quando ele é zero e existe `POL:N1` diferente de
zero, vale o `POL:N1`**. Nunca o contrário — polaridade declarada no sujeito não é
sobrescrita.

É a cláusula que faz o piso enxergar os verbos de julgamento, que são o modo mais
comum de elogiar um comercial. Medido: **3.927 formas flexionadas** mudam de
polaridade e **22 dos 334 comentários** mudam de rótulo, puxados por "amei" (7),
"gostei" (3), "amo" (3), "adorei" e "odiei". Sem a cláusula, `amei o comercial` é
invisível para o léxico — e um piso que não vê "amei" não mede o método, mede a
leitura errada do recurso.

### 4. Acento conta. Foi medido, não decidido no gosto

Ignorar acento nos dois lados parecia a escolha generosa: comentário de YouTube
escreve "otimo" e "horrivel". **A medição no conjunto de teste derrubou a ideia:**

| | palavras casadas |
|---|---|
| exigindo o acento | 413 |
| ignorando o acento | 446 |

Dos 33 ganhos, **17 são a conjunção "mas" casando com "más"** (feminino plural de
"mau", polaridade −1) — isto é, a palavra que o manual de rotulagem usa como marca de
contraste passaria a injetar −1 em quase toda frase adversativa do corpus. O mesmo
acontece com "seria"/"séria", "vila"/"vilã", "manhã"/"manha", "peço"/"peco" e
"dúvida"/"duvida", todos presentes nos 334. Os ganhos legítimos foram quatro:
"otima", "fantastico", "pessima", "horrivel".

Trocar quatro acertos por dezessete erros sistemáticos não é generosidade com o piso.
O acento que o comentarista não digitou **continua sendo uma limitação do método
léxico** — e é isso que o capítulo diz, em vez de escondê-la atrás de uma normalização
que cria um problema maior. `ml/tests/test_lexico.py` tem o caso do "mas" como teste
de regressão.

### 5. O que do recurso não dá para usar, e quanto é

Com o arquivo `flex` (82.347 formas flexionadas):

| | entradas | por quê |
|---|---|---|
| utilizáveis | 43.061 | |
| descartadas: multipalavra | 34.918 | as 666 expressões idiomáticas e suas flexões ("abrir o coração") não casam com busca palavra a palavra |
| descartadas: grafia ambígua | 1.510 | mesma grafia com polaridades opostas em classes diferentes ("abatido" é −1 como adjetivo e +1 como particípio). A chave sai inteira: escolher embutiria no piso uma desambiguação que a regra não faz |
| descartadas: polaridade inválida | 3 | erros de digitação do recurso publicado (`POL:N0=7`, `=8`, `=-2`, `=-3`) |

**O arquivo `flex` e não o `lem`** (7.014 lemas): o pipeline não tem lematizador e não
vai ganhar um só para a linha de base. Com o `lem`, "adorei" não casaria com "adorar"
e o piso mediria a ausência do lematizador, não o léxico.

---

## O que a medição de hoje já mostra

Rodado sobre os 334 comentários da amostra humana (previsões, ainda sem gabarito):

| | |
|---|---|
| previu `neutro` | 172 (51,5%) |
| previu `positivo` | 91 (27,2%) |
| previu `negativo` | 71 (21,3%) |
| **sem nenhuma palavra do léxico** | **147 (44,0%)** |
| neutro por empate de polaridade | 25 |

Quase metade dos comentários não tem **uma única palavra** do SentiLex. Não é falha da
implementação: é o que acontece quando um léxico de julgamento social de 2012 encontra
comentário de YouTube de 2026 — gíria, emoji, nome de marca e frase curta. O
`neutro` do piso é, em grande parte, `neutro` por ignorância, e a matriz de confusão do
Capítulo 5 vai mostrar isso como revocação alta em `neutro` e baixa nas outras duas.

---

## Proveniência do recurso

**SentiLex-PT02** — Paula Carvalho e Mário J. Silva. Licença **CC-BY 4.0**.

> Silva, M. J.; Carvalho, P.; Sarmento, L. *Building a Sentiment Lexicon for Social
> Judgement Mining*. PROPOR 2012, LNCS/LNAI.

7.014 lemas e 82.347 formas flexionadas: 4.779 adjetivos, 1.081 nomes, 489 verbos e
666 expressões idiomáticas.

**Os arquivos não são versionados** (`.gitignore`), pelo mesmo motivo do corpus: são
dado de terceiros, e 6,9 MB. Baixe para `ml/lexico/dados/`:

```bash
curl -L -o ml/lexico/dados/SentiLex-flex-PT02.txt \
  https://raw.githubusercontent.com/sillasgonzaga/lexiconPT/master/data-raw/SentiLex-flex-PT02.txt
```

A distribuição oficial é o registro do B2SHARE/EUDAT (busque "SentiLex-PT 02"); o
espelho acima é o do pacote R `lexiconPT` e bate com as contagens publicadas. O
`metadados_lexico.json` de cada rodada grava o **sha256** do arquivo que foi usado — é
o que prova, na banca, que o número do capítulo saiu deste recurso e não de outro.

Arquivo usado na medição registrada acima:
`sha256 88ab7389bfe6f4a2b489a4a53c42306691796bc2fef9d4c2a26790dd927ba85c`.

---

## Este experimento não grava no banco

`classificar_teste.py` **só lê** do Postgres. As previsões saem em CSV, e não em
`ANALISES_SENTIMENTO`, por dois motivos:

1. aquela tabela tem `UNIQUE(id_comentario)` — e o lugar é da **inferência de
   produção**, que hoje é o worker (`backend/app/workers/inferencia.py`). Duas
   escritas disputando a mesma linha por comentário quebrariam uma das duas;
2. ela é a superfície que o dashboard lê. O painel da PME mostra o que o worker
   gravou, com a linha de `VERSOES_MODELO` correspondente; previsão de experimento ali
   seria indistinguível de resultado de execução.

A comparação do Capítulo 5 é **artefato de experimento**, não análise de produção — e é
por isso que ela sai em arquivo, ainda que a regra seja a mesma que roda em produção.

**O que mudou com o worker:** a mesma soma de polaridade agora também grava em
`ANALISES_SENTIMENTO`, pelo caminho de produção, com uma linha própria em
`VERSOES_MODELO` (`lexico-sentilex`, versão do pacote `lexico`) e o `sha256` do recurso
na proveniência. São dois consumidores da mesma função pura, não duas cópias da regra.

---

## Promoção para o pacote compartilhado (feita)

`sentilex.py` era **puro** de propósito: stdlib, sem banco, sem CLI, sem `ml.config` —
inclusive os três rótulos repetidos lá dentro em vez de importados, com um teste
travando a cópia contra o CHECK do banco. Era o que tornava o módulo utilizável pelo
worker de inferência sem arrastar o `ml/` para dentro do `backend/`.

**Aconteceu.** O worker de inferência precisou de um classificador antes de o BERTimbau
existir, e o import direto não podia acontecer (`backend/` não importa de `ml/`, e
vice-versa — CLAUDE.md Seção 3). O caminho foi o mesmo do pré-processamento, e custou o
`git mv` e o `pip install -e` previstos:

| antes | agora |
|---|---|
| `ml/lexico/sentilex.py` | `lexico/src/lexico/sentilex.py` (pacote `lexico`) |
| importado como `ml.lexico.sentilex` | importado como `lexico`, dos dois lados |
| só experimento | experimento **e** produção, a mesma função |

```bash
backend/.venv/Scripts/python.exe -m pip install -e ./lexico
ml/.venv/Scripts/python.exe      -m pip install -e ./lexico
```

Não é mais *fallback* do BERTimbau, como este README imaginava: é a **primeira
implementação** da interface `Classificador` (`backend/app/inferencia/base.py`). O
BERTimbau entra como uma segunda implementação, e o léxico continua sendo o piso.

**As duas coisas que viajaram junto**, como previsto:

1. **o arquivo do léxico virou dependência de runtime do backend.** Não é mais só dado
   de experimento. O caminho é configuração (`SENTILEX_PATH`, com padrão apontando para
   `ml/lexico/dados/` para quem já rodou o experimento), e ele continua fora do git;
2. **o `sha256` ganhou o tratamento da `versao_preprocessamento`.** O hash esperado é
   constante no classificador de produção (`backend/app/inferencia/lexico.py`),
   conferido na **inicialização do worker**: arquivo ausente, ilegível ou diferente do
   medido aqui e o worker se recusa a subir, dizendo o caminho que tentou. Sem isso, um
   espelho diferente ou um download truncado mudaria a classificação de produção em
   silêncio — e os números deste README passariam a descrever um recurso que não é mais
   o que está rodando.

O portão da `versao_preprocessamento` também vale para o léxico, e pelo mesmo motivo: o
piso publicado foi medido sobre uma versão específica de `preparar_texto`, conversão de
emoji incluída. Com outra versão, o piso do capítulo deixa de ser o piso que está em
produção.
