# Prompt de rotulagem fraca — v1

**Versão:** 1
**Data:** 22/09/2026
**Uso:** rotulagem fraca do corpus da Sprint 1 (execução 4, 2.534 comentários), offline, em `ml/rotulagem/rotular_fraco.py`.
**Temperatura:** 0
**Saída:** JSON, categoria fechada.

A **fonte única dos critérios é `manual_rotulagem_v1.md`.** Este arquivo não decide
nada: ele reproduz, de forma condensada e em linguagem de instrução, as Seções 3, 4,
5 e 6 do manual — as mesmas classes, as mesmas regras e os mesmos exemplos. Os
avaliadores humanos leem o manual; a Gemini recebe o texto da seção "Prompt da
tarefa" abaixo.

Critério igual entre a Gemini e os humanos é o que torna a comparação honesta — se
os dois lados usassem régua diferente, o Kappa mediria a diferença entre as réguas,
não a qualidade da rotulagem fraca. Por isso a sincronia é verificada por teste
(`ml/tests/test_rotulagem.py`): o bloco de tarefa abaixo precisa bater com a
constante `PROMPT_TAREFA` do código, e as regras-chave do manual precisam aparecer
aqui.

> **Ao alterar qualquer critério, crie `manual_rotulagem_v2.md` e `prompt_v2.md`
> juntos.** Não edite esta versão: os rótulos gravados no banco foram produzidos por
> ela, e o arquivo de metadados aponta para ela.

---

## Instrução de sistema

```text
Você é um anotador de sentimento de comentários do YouTube em português do Brasil.
Sua tarefa é classificar cada comentário em exatamente uma de três classes.
Você responde SOMENTE com JSON válido, sem texto antes ou depois, sem markdown.
```

---

## Critérios

Espelho condensado do manual. Onde este resumo e o manual divergirem, **vale o
manual** — e a divergência é um defeito a corrigir, não uma escolha.

### O que está sendo avaliado (manual, Seção 4)

O sentimento é **sobre a campanha, o produto ou a marca anunciada** — nunca sobre
qualquer outra coisa que o comentário mencione.

- Elogio a um **elemento da campanha** (a atriz, a música, o roteiro) conta como
  elogio à campanha: "a atriz é linda demais" é `positivo`.
- **Entrega, atendimento e preço contam como marca**: são parte da experiência de
  comprar o produto anunciado. "os Correios são uma vergonha, meu pedido tá parado"
  é `negativo`.
- O que não fala da campanha, do produto nem da marca é `neutro`.

### As três classes (manual, Seção 3)

| classe | pergunta-guia |
|---|---|
| `positivo` | O autor aprova, elogia ou demonstra vontade de comprar? |
| `negativo` | O autor reprova, reclama, critica ou desiste da compra? |
| `neutro` | O autor não expressa aprovação nem reprovação? |

**`neutro` não é o "lugar da dúvida".** É uma classe com critério próprio: ausência
de avaliação. Um comentário em que não dá para decidir entre positivo e negativo
**não é neutro** — é um caso difícil, e as regras da Seção 5 do manual decidem por
ele. Uma pergunta também não é automaticamente neutra.

### Casos difíceis (manual, Seção 5)

| # | caso | regra |
|---|---|---|
| 5.1 | ironia e sarcasmo | vale o que o autor **quis dizer**, não o literal; sem certeza de que é ironia, vale o **sentido literal** |
| 5.2 | elogio e reclamação juntos | vence a parte que **encerra** o comentário ou a que vem depois de "mas", "porém", "só que" |
| 5.3 | gíria | **traduza** antes de rotular; gíria é vocabulário, não sentimento |
| 5.4 | só emoji | vale o sentido dominante do emoji; 😂 e 🤔 sozinhos são `neutro` |
| 5.5 | pergunta | só é neutra se não carregar avaliação |
| 5.6 | fora do tema | `neutro` |
| 5.7 | spam | `neutro` |
| 5.8 | comentário sobre outro comentário | rotule o que ele diz **sobre a campanha** |

### Fluxo de decisão (manual, Seção 6)

A primeira resposta "sim" decide o rótulo:

1. Fala da campanha, do produto ou da marca? Se não → `neutro`.
2. Há ironia? → rotule pelo sentido pretendido.
3. Tem elogio e reclamação juntos? → vence a parte depois do "mas".
4. Aprova, elogia ou quer comprar? → `positivo`.
5. Reprova, reclama ou desiste? → `negativo`.
6. Nenhum dos dois → `neutro`.

### Onde a Gemini não acompanha o humano

O manual tem duas instruções que **não** têm equivalente no prompt, e isso é
deliberado:

- **Coluna "dúvida"** (manual, Seções 2 e 6): o avaliador registra hesitação sem
  mudar o rótulo. A Gemini devolve categoria fechada, sem canal para isso — as
  regras do manual que terminam em "e marque dúvida" viram, no prompt, só a parte
  que escolhe a classe.
- **Seções 1, 2, 7, 8 e 9** (Kappa, desempate, calibração, higiene do avaliador):
  são procedimento humano. Não são critério de rotulagem e não entram aqui.

---

## Prompt da tarefa

```text
Classifique o sentimento de cada comentário abaixo em relação à campanha,
produto ou marca anunciada.

CLASSES (escolha exatamente uma por comentário):
- "positivo": o autor aprova, elogia ou demonstra vontade de comprar.
- "negativo": o autor reprova, reclama, critica ou desiste da compra.
- "neutro": o autor não expressa aprovação nem reprovação.

"neutro" NÃO é o lugar da dúvida. Neutro é ausência de avaliação, não incerteza:
comentário difícil de decidir entre positivo e negativo NÃO é neutro — aplique as
regras abaixo e escolha uma das duas.

SOBRE O QUE É O SENTIMENTO: sempre sobre a campanha, o produto ou a marca
anunciada, nunca sobre qualquer outra coisa que o comentário mencione.
- Elogio a um elemento da campanha conta como elogio à campanha: "a atriz é
  linda demais" é "positivo".
- Entrega, atendimento e preço contam como marca: "os Correios são uma vergonha,
  meu pedido tá parado" é "negativo".
- "odeio segunda-feira, mas esse comercial salvou meu dia" é "positivo": o ódio é
  pela segunda-feira; sobre o anúncio, é elogio.
- Comentário que não fala da campanha, do produto nem da marca é "neutro".

ORDEM DE DECISÃO (a primeira resposta "sim" decide o rótulo):
1. Fala da campanha, do produto ou da marca? Se não, "neutro".
2. Há ironia? Rotule pelo sentido pretendido (regra 1).
3. Tem elogio e reclamação juntos? Vence a parte depois do "mas" (regra 2).
4. Aprova, elogia ou quer comprar? "positivo".
5. Reprova, reclama ou desiste? "negativo".
6. Nenhum dos dois: "neutro".

REGRAS:
1. IRONIA E SARCASMO: rotule pelo que o autor quis dizer, não pelas palavras que
   usou. Sinais: elogio exagerado para algo ruim, palavras em MAIÚSCULAS, "né",
   "hein", "parabéns", aplausos (👏) depois de uma reclamação.
   "nossa que entrega RÁPIDA hein, só 3 semanas pra chegar 👏👏" → "negativo".
   "amei que o produto quebrou no segundo dia, qualidade top" → "negativo".
   Sem certeza de que é ironia, rotule pelo sentido literal.
2. ELOGIO E RECLAMAÇÃO NO MESMO COMENTÁRIO: vence a parte que encerra o
   comentário ou a que vem depois de "mas", "porém", "só que", "no entanto".
   "demorou pra chegar, mas o produto é maravilhoso" → "positivo".
   "bonito sim, mas 2 mil reais num anel banhado? tá de brincadeira" → "negativo".
   "gostei do anúncio. o preço é que não dá" → "negativo".
   Se as duas partes têm o mesmo peso e não há conectivo, vale a que fala do
   PRODUTO, não a que fala do anúncio.
3. GÍRIA: traduza a gíria antes de rotular. Gíria não é sentimento, é vocabulário.
   "brabo", "insano", "surreal", "top", "pica" → positivo.
   "mó paia", "flopou", "fraco", "deu ruim" → negativo.
   "kkkk", "rsrs", "mds" sozinhos → "neutro": risada sem objeto não avalia nada.
   "mds que anúncio brabo" é "positivo"; "mds que caro" é "negativo" — o "mds"
   não decide, o resto da frase decide.
   Erro de escrita e abreviação não mudam a classe.
4. SÓ EMOJI: emoji isolado vale o sentido dominante dele.
   😍 🔥 ❤️ 👏 (sem reclamação antes) → "positivo".
   😡 🤮 👎 → "negativo".
   😂 sozinho → "neutro": rir não diz se aprova ou não. 🤔 → "neutro".
5. PERGUNTA: pergunta só é neutra se não carregar avaliação.
   "tem pra entrega no Nordeste?" → "neutro".
   "alguém mais recebeu com defeito?" → "negativo": pressupõe o problema.
   "alguém mais achou caro demais?" → "negativo": carrega reclamação.
   "onde compro? quero muito" → "positivo": intenção de compra.
6. FORA DO TEMA → "neutro". Inclui marcar amigos ("@joao olha isso"), falar de
   outro assunto, "primeiro!" e pedido de inscrição no canal.
7. SPAM e propaganda de terceiros → "neutro". Exemplo: "ganhe 500 reais por dia
   trabalhando de casa, link na bio".
8. COMENTÁRIO SOBRE OUTRO COMENTÁRIO: rotule o que ele diz sobre a campanha.
   "concordo total, também achei caro" → "negativo": endossa a reclamação.
   "você tá louco, o anúncio é ótimo" → "positivo".
   "quem ta aqui em 2026?" → "neutro".
   Se ele só reage a outra pessoa, sem dizer nada da campanha, é "neutro".
9. NÃO INVENTE CONTEXTO: classifique só pelo que está escrito. Se o sentido
   depender de algo que você não tem (o vídeo, outro comentário), rotule pelo que
   o texto sozinho mostra; se o texto sozinho não aprova nem reprova, "neutro".

COMENTÁRIOS:
{comentarios_json}

RESPONDA SOMENTE com um array JSON, um objeto por comentário, na mesma ordem,
sem markdown e sem texto fora do JSON:
[{"id_comentario": <int>, "rotulo": "positivo"|"negativo"|"neutro"}]

O array deve ter exatamente {quantidade} objetos.
```

---

## Formato dos dados

**Entrada** (`{comentarios_json}`) — o texto é o **ORIGINAL** (coluna `texto`),
com emoji preservados. Nunca o `texto_modelo`: a conversão de emoji para palavra
existe por limitação do tokenizer do BERTimbau, e a Gemini lê emoji nativamente.
Mandar o texto convertido daria à Gemini uma entrada diferente da que o avaliador
humano vê, e a comparação perderia o sentido.

```json
[
  {"id_comentario": 1, "texto": "Que nostalgia que me deu pqp"},
  {"id_comentario": 2, "texto": "Estou surpresa, parece bom 😂"}
]
```

**Saída esperada:**

```json
[
  {"id_comentario": 1, "rotulo": "neutro"},
  {"id_comentario": 2, "rotulo": "positivo"}
]
```

## Validação da resposta

O script recusa e refaz o lote quando:

- a resposta não é JSON válido;
- algum `rotulo` está fora de `{positivo, negativo, neutro}`;
- algum `id_comentario` não pertence ao lote enviado;
- falta ou sobra item em relação ao lote.

O casamento é por `id_comentario` (a chave estável do corpus), não pela posição no
array — mesmo com a instrução de manter a ordem, depender dela é frágil.
