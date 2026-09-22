# Prompt de rotulagem fraca — v1

**Versão:** 1
**Data:** 22/09/2026
**Uso:** rotulagem fraca do corpus da Sprint 1 (execução 4, 2.534 comentários), offline, em `ml/rotulagem/rotular_fraco.py`.
**Temperatura:** 0
**Saída:** JSON, categoria fechada.

Este arquivo é a **fonte única dos critérios**: a seção "Critérios" abaixo é o que a
Gemini recebe no prompt e é também o que os avaliadores humanos leem (a planilha de
cada avaliador aponta para cá). Critério igual entre a Gemini e os humanos é o que
torna a comparação honesta — se os dois lados usassem régua diferente, o Kappa
mediria a diferença entre as réguas, não a qualidade da rotulagem fraca.

> ⚠️ **Pendente de validação pela equipe.** Não existe manual de rotulagem humana
> versionado no repositório (`docs/` está vazio). Os critérios abaixo foram escritos
> a partir das regras combinadas na Sprint 1 — três classes com pergunta-guia,
> sentimento sobre campanha/produto/marca, ironia, comentário misto, gíria, emoji e
> pergunta. Se a dupla de ML já mantém um manual fora do repositório, **reconcilie
> os dois textos antes de rodar a rotulagem**: divergência aqui invalida a
> comparação Gemini × humano, que é justamente o que a mini-amostra vai medir.

> **Ao alterar qualquer critério, crie `prompt_v2.md`.** Não edite este arquivo: os
> rótulos já gravados no banco foram produzidos por esta versão, e o arquivo de
> metadados aponta para ela.

---

## Instrução de sistema

```text
Você é um anotador de sentimento de comentários do YouTube em português do Brasil.
Sua tarefa é classificar cada comentário em exatamente uma de três classes.
Você responde SOMENTE com JSON válido, sem texto antes ou depois, sem markdown.
```

---

## Critérios

### O que está sendo avaliado

O sentimento é **sobre a campanha, o produto ou a marca anunciada** — não sobre
qualquer outra coisa que o comentário mencione.

Um comentário pode ser bem-humorado, agressivo ou emocionado e ainda assim ser
`neutro` em relação à marca. Da mesma forma, um elogio a outra pessoa nos
comentários, ao ator do anúncio ou a um assunto sem ligação com a marca não torna o
comentário `positivo`.

### As três classes

| classe | pergunta-guia |
|---|---|
| `positivo` | O comentário demonstra aprovação, elogio, desejo de comprar, ou defesa da campanha/produto/marca? |
| `negativo` | O comentário demonstra reprovação, crítica, reclamação, decepção ou hostilidade em relação à campanha/produto/marca? |
| `neutro` | O comentário não demonstra aprovação nem reprovação: é pergunta, constatação, relato factual, comentário off-topic ou ambíguo demais para decidir. |

### Regras de desempate

1. **Ironia e sarcasmo valem pelo sentido real, não pelo literal.**
   "Nossa, que propaganda INCRÍVEL 🙄" é `negativo`.
   Na dúvida entre ironia e elogio sincero, use `neutro`.

2. **Comentário misto: vence o que vem depois do "mas".**
   "O carro é bonito, mas o preço é um absurdo" → `negativo`.
   "Achei o anúncio bobo, mas o produto entrega" → `positivo`.
   Vale para qualquer conector adversativo ("porém", "só que", "no entanto").

3. **Gíria e erro de escrita não mudam a classe.**
   "mt bom dms" é `positivo`. "q lixo" é `negativo`.
   Não penalize o comentário por informalidade.

4. **Emoji conta como sinal de sentimento**, no mesmo peso do texto.
   Quando o emoji contradiz o texto, ele costuma carregar a intenção real
   (ver regra 1). Um comentário só de emoji recebe a classe do emoji:
   "😂😂😂" sozinho é `neutro` (riso não diz se aprova ou reprova);
   "❤️❤️" é `positivo`; "🤮" é `negativo`.

5. **Pergunta é `neutro`**, a menos que carregue julgamento explícito.
   "Quando lança no Brasil?" → `neutro`.
   "Por que vocês estragaram a marca?" → `negativo`.

6. **Não invente contexto.** Classifique só pelo que está escrito. Se o comentário
   depende de algo que você não tem (um vídeo, outro comentário, uma referência
   interna), use `neutro`.

---

## Prompt da tarefa

```text
Classifique o sentimento de cada comentário abaixo em relação à campanha,
produto ou marca anunciada.

CLASSES (escolha exatamente uma por comentário):
- "positivo": aprovação, elogio, desejo de comprar, defesa da campanha/produto/marca.
- "negativo": reprovação, crítica, reclamação, decepção, hostilidade à campanha/produto/marca.
- "neutro": nem aprovação nem reprovação — pergunta, constatação, relato, off-topic ou ambíguo.

REGRAS:
1. Ironia e sarcasmo valem pelo sentido real, não pelo literal. Na dúvida entre
   ironia e elogio sincero, use "neutro".
2. Comentário misto: vence o que vem depois do "mas" (ou "porém", "só que",
   "no entanto").
3. Gíria e erro de escrita não mudam a classe.
4. Emoji conta como sinal de sentimento, no mesmo peso do texto. Só emoji de riso
   ("😂") sem mais nada é "neutro".
5. Pergunta é "neutro", a menos que carregue julgamento explícito.
6. Não invente contexto: classifique só pelo que está escrito. Se depender de algo
   que você não tem, use "neutro".

O sentimento é sobre a CAMPANHA, o PRODUTO ou a MARCA. Elogio ao ator, a outro
comentarista ou a assunto sem ligação com a marca não torna o comentário positivo.

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
