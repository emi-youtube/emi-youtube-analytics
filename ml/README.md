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
```

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

`ml/dados/*.csv` está no `.gitignore`: o corpus não é versionado, é regenerável a
partir da execução.

## O que ainda não existe

`rotulagem/` (rotulagem fraca via Gemini, offline), `treino/` e `avaliacao/`.
Duas regras do `CLAUDE.md` que valem para quando entrarem:

- a Gemini **não** roda em produção, só aqui, offline;
- o conjunto de **teste é só humano** — avaliar contra rótulo da Gemini seria circular.
