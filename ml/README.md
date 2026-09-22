# ml/ — pipeline de IA

Produz o modelo que o `backend/` consome. As duas metades não se importam: a
comunicação é por artefato (pesos + `model_card.json`) e pelo banco.

## Ambiente

```bash
py -3.11 -m venv ml/.venv
ml/.venv/Scripts/python.exe -m pip install -r ml/requirements.txt
```

O `requirements.txt` instala `preprocessamento/` (raiz do repo) em modo editável.
Esse pacote é **compartilhado com o `backend/`**: é dele que sai a função única de
pré-processamento aplicada tanto ao corpus de treino quanto ao comentário que chega
ao worker de inferência. Não duplique essa lógica dentro do `ml/`.

`torch` não está aqui de propósito — medir o corpus não exige carregar pesos. Ele
entra só no treino, que roda no Colab.

## Ordem de execução (Sprint 1)

Rodar sempre da **raiz do repositório**:

```bash
# 1. corpus: le os COMENTARIOS da execucao, popula EXEMPLOS_TREINAMENTO,
#    escreve ml/dados/corpus.csv
python -m ml.exportacao.exportar_corpus --id-execucao <N>

# 2. medicao: distribuicao de comprimento em tokens e perda de emoji
python -m ml.medicao.medir_tokens

# 3. rotulagem fraca com a Gemini (OFFLINE, exige ml/.env)
python -m ml.rotulagem.listar_modelos                                # antes de tudo
python -m ml.rotulagem.rotular_fraco --id-execucao <N> --limite 50   # ensaio
python -m ml.rotulagem.rotular_fraco --id-execucao <N>               # corpus todo

# 4. amostra humana (gabarito): Cochran + estratificacao pelo rotulo fraco
python -m ml.amostra.sortear_amostra_humana --id-execucao <N>

# 5. planilhas dos avaliadores (as cegas, uma ordem por avaliador)
python -m ml.amostra.gerar_planilhas_avaliadores --id-execucao <N>
```

O passo 3 exige `ml/.env` com a `GEMINI_API_KEY` — **nunca** no `.env` da raiz
(CLAUDE.md regra 3: o backend de produção não pode ter chave de LLM nem por
acidente). Copie de `ml/env.example`.

### Escolher o modelo antes de rodar

`GEMINI_MODELO` **não tem valor padrão** e a rotulagem recusa rodar sem ele. O
catálogo da Gemini muda: o padrão anterior deste repositório, `gemini-2.0-flash`,
já não existe para a chave do projeto. Rode `python -m ml.rotulagem.listar_modelos`,
copie um nome marcado com `*` e escreva em `ml/.env`.

O `*` exclui preview, experimental e os apelidos `-latest`. Apelido é o pior dos
três para o TCC: ele continua funcionando depois que o Google troca o alvo, então o
`metadados_rotulagem.json` registraria um nome que não descreve mais o modelo que
rotulou o corpus.

Estar na listagem não basta. O `ListModels` mostra também modelos **fechados para
chaves novas** — a família `gemini-2.5-*` aparece na listagem desta chave e devolve
HTTP 404 (*"no longer available to new users"*) na hora de gerar — e não diz nada
sobre demanda: nesta chave, toda a linha `-flash` acima da `-flash-lite` responde
HTTP 503.

Por isso `escolher_modelo()` tem três portões, do mais barato ao mais caro:

1. `GEMINI_MODELO` preenchido em `ml/.env` (sem valor padrão);
2. o `ListModels` conhece o nome, ele faz `generateContent` e é estável;
3. **uma chamada real** com os 12 casos do exercício de calibração (Seção 8 do
   manual), antes do primeiro lote.

O terceiro portão é o que fecha o buraco: numa chamada só ele confirma que o modelo
responde para esta chave, que o modo JSON funciona, que a categoria fechada é
obedecida e que o modelo acerta a mesma régua dos avaliadores. O corte é o do
manual — errar mais de 3 dos 12 reprova, para a Gemini como para o humano. O
resultado vai para o `metadados_rotulagem.json` da rodada, medido na própria sessão.

### Por que o modelo atual, e não os outros

O comparativo que fechou a escolha está em `ESCOLHA_DO_MODELO`
(`ml/rotulagem/rotular_fraco.py`) e é copiado para o metadado de cada rodada. Para
refazê-lo: `listar_modelos` dá os candidatos estáveis, e um `escolher_modelo()` com
cada nome no `ml/.env` dá disponibilidade e nota de calibração de cada um — a sonda
é exatamente o experimento.

### Se o Kappa ficar abaixo de 0,60

A Seção 9 do manual manda reescrever a régua e refazer a medição com uma amostra
**nova**. "Nova" precisa significar comentários que nenhum avaliador viu: reapresentar
os mesmos faria o segundo Kappa medir a memória dos avaliadores, não o manual
reescrito.

Por isso o sorteio só enxerga quem está **sem partição** (`split IS NULL`), e existe
uma segunda passada explícita:

```bash
# 1a rodada
python -m ml.amostra.sortear_amostra_humana --id-execucao <N>

# Kappa < 0,60 → manual_rotulagem_v2.md → 2a rodada, preservando a amostra anterior
python -m ml.amostra.sortear_amostra_humana --id-execucao <N> --nova-rodada
```

`--nova-rodada` mantém a amostra anterior marcada (ninguém rotula o mesmo comentário
duas vezes) e sorteia entre os que sobraram. `--refazer` é outra coisa: descarta a
amostra anterior, e só serve para erro de operação, antes de qualquer avaliador abrir
planilha. Os dois juntos são recusados.

O `n` de Cochran continua sendo calculado sobre o corpus rotulado inteiro — a precisão
declarada é sobre o corpus, que não encolheu porque uma rodada gastou parte dele.

### Checkpoint da rotulagem fraca

O passo 3 termina imprimindo a distribuição das três classes e **sai com erro** se
alguma passar de 85% ou ficar abaixo de 5%. Distribuição assim quase sempre é
prompt ruim, não corpus desbalanceado — o prompt precisa de revisão (crie
`prompt_v2.md`) antes de qualquer treino.

## Decisões que valem registro

| Decisão | Valor | Onde |
|---|---|---|
| Semente de toda amostragem | `42` | `ml/config.py` |
| Teto de comentários por vídeo | `400` | `exportar_corpus.py` |
| Partição (`split`) | **NULL na exportação** | `exportar_corpus.py` |
| Pré-processamento | `preprocessamento` v1.1.0 | `preprocessamento/` (raiz) |
| Fração mínima de letras latinas | `0.5` | `exportar_corpus.py` |
| Tokenizer / modelo base | `neuralmind/bert-base-portuguese-cased` | `ml/config.py` |
| `max_length` avaliado | `128` | `ml/config.py` |

**A chave estável do corpus é `id_comentario`, não `id_exemplo`.** `id_exemplo` é
`serial`: reexecutar a exportação apaga e reinsere as linhas, e a sequência avança.
Planilha de rotulagem e validação humana devem casar por `id_comentario`.

O teto por vídeo é amostragem aleatória com semente fixa, aplicada **depois** do
pré-processamento e do descarte de texto vazio — amostrar antes deixaria o vídeo com
menos de 400 exemplos úteis.

**O `split` sai NULO e isso é deliberado.** Sortear a partição na exportação, antes
de existir qualquer rótulo, faz o conjunto de teste nascer dentro do corpus de rótulo
fraco — a circularidade da Seção 4.1.2, e o oposto do `CLAUDE.md` regra 6 ("o teste é
só humano"). A atribuição acontece **depois** da rotulagem fraca e da validação
humana, quando dá para estratificar por rótulo e reservar para teste só o que tem
rótulo humano. `NULL` = partição ainda não atribuída (migration `0007`).

### Quem vê qual texto

Isto é o ponto mais fácil de errar do pipeline (`CLAUDE.md` Seção 3):

| | conteúdo | quem consome |
|---|---|---|
| `exemplos_treinamento.texto` e coluna `texto` | **original**, só espaço normalizado | avaliador humano, Gemini |
| coluna `texto_modelo` | `preparar_texto`: tipografia + emoji convertidos | BERTimbau (treino e inferência) |

O banco guarda o **original**. O texto do modelo é derivado e descartável — quem
treina pode recalculá-lo do canônico a qualquer momento chamando `preparar_texto`.
Rótulo tem que ser dado sobre o que a pessoa escreveu: se o avaliador lesse "risos"
onde o usuário digitou 😂, estaria rotulando o nosso pré-processamento.

A coluna `versao_preprocessamento` viaja no CSV para que uma amostra rotulada nunca
fique órfã da versão que a gerou. Ao mexer no mapa de emoji ou nas substituições
tipográficas, **suba a versão do pacote** — ela vai no `model_card.json`, e o worker
de inferência deve recusar o modelo se divergir da instalada.

**Emoji e tipografia viram texto** só na entrada do BERTimbau. Sem isso, 100% das
2.385 ocorrências de emoji viravam `[UNK]`. Com a v1.1.0 o corpus sai com 64 `[UNK]`
(0,10% dos tokens) contra 830 no texto canônico — **92,3% eliminados**. O que sobra é
quase todo gíria (`q` 50×, `qnd`, `qd`), que **não** é expandida: normalização
semântica é trabalho do leitor, não do pipeline.

**Comentário majoritariamente fora do alfabeto latino é descartado** na exportação.
O modelo é português; um comentário em coreano não tem como ser rotulado pela equipe
e vira `[UNK]` puro. O corte é por script Unicode e só derruba o texto em que menos
da metade das letras é latina — "não", "coração" e "über" passam.

## Dados: o que versiona e o que não

| pasta | conteúdo | versionado? |
|---|---|---|
| `ml/curadoria/` | planilha de curadoria dos vídeos — **entrada** | **sim** |
| `ml/dados/` | corpus e derivados — **saída gerada** | não (`.gitignore`) |
| `ml/rotulagem/manual_rotulagem_v*.md` | **fonte única dos critérios** — vai para o TCC | **sim** |
| `ml/rotulagem/prompt_v*.md` | espelho condensado do manual, dirigido à Gemini | **sim** |
| `ml/rotulagem/metadados_rotulagem.json` | modelo, data, temperatura, nº de chamadas, nota da calibração, comparativo dos candidatos | **sim** |
| `ml/amostra/planilhas/` | planilhas dos avaliadores (texto de terceiros) | não (`.gitignore`) |

`ml/curadoria/curadoria_videos_sprint1.xlsx` é a **proveniência do corpus**: registra
quais vídeos entraram, por quê, e permite a qualquer pessoa recoletar exatamente o
mesmo conjunto. É evidência metodológica do TCC, não dado pesado — por isso versiona.
O status na planilha tem que bater com o corpus que foi de fato usado (hoje: 14
aprovados + 1 reprovado).

`ml/dados/*.csv` está no `.gitignore` e **não pode sair disso**: o repositório é
público e o corpus são textos de terceiros. O corpus é regenerável a partir da
execução mais a planilha de curadoria.

### Uma régua só, dos dois lados

`manual_rotulagem_v1.md` é a **fonte única dos critérios**. O avaliador humano lê o
manual inteiro; a Gemini recebe o espelho condensado das Seções 3, 4, 5 e 6 que está
em `prompt_v1.md`. A aba de instruções das planilhas aponta para o **manual**.

Se as duas réguas divergirem, o Kappa entre a Gemini e os humanos mede a diferença
entre as réguas, não a qualidade da rotulagem fraca — e o número perde o sentido que
o TCC atribui a ele. `ml/tests/test_rotulagem.py` trava isso: o prompt do código tem
que bater com o do arquivo, e as regras-chave do manual (a do "mas", "neutro não é o
lugar da dúvida", ironia, spam, pergunta com pressuposição) têm que aparecer no
texto que a Gemini de fato recebe.

Ao mudar um critério, **suba as duas versões juntas** (`manual_rotulagem_v2.md` e
`prompt_v2.md`). Editar a v1 depois de rotular o corpus deixaria os rótulos gravados
órfãos da régua que os produziu.

## O que ainda não existe

`treino/` e `avaliacao/`. Duas regras do `CLAUDE.md` que valem para quando entrarem:

- a Gemini **não** roda em produção, só aqui, offline;
- o conjunto de **teste é só humano** — avaliar contra rótulo da Gemini seria circular.
