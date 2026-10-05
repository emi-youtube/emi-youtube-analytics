# ml/avaliacao — as tabelas e as figuras do Capítulo 5

Compara **qualquer conjunto de previsões** contra o `rotulo_humano` e produz o que o
capítulo de resultados precisa: tabelas em Markdown e CSV, figuras em 300 dpi e um
JSON de agregados.

```bash
# o dia em que o gabarito voltar
python -m ml.avaliacao.avaliar --id-execucao <N> \
    --previsoes lexico=ml/dados/previsoes_lexico.csv --gemini

# ensaio antes disso: gabarito sintetico, saida fora do repositorio
python -m ml.avaliacao.avaliar --gabarito ensaio/gabarito.csv \
    --previsoes lexico=ml/dados/previsoes_lexico.csv --saida ensaio/saida
```

Sai em `ml/avaliacao/saida/`: `tabela_metricas.md`, `tabela_metricas.csv`,
`resultado_avaliacao.json` e `figuras/`. Tudo agregado — nenhum texto de terceiros —,
por isso a pasta é versionada.

---

## O gabarito é humano; a Gemini é um método avaliado

O gabarito sai de `exemplos_treinamento.rotulo_humano`, que só existe depois da
validação humana e da apuração do Kappa (`ml/concordancia/`). A Gemini entra pela
outra ponta: o `rotulo_fraco` dos mesmos comentários vira uma coluna de previsão como
qualquer outra, e é medido contra o gabarito humano.

Essa é a diferença entre **medir** a rotulagem fraca e **se validar** com ela. Avaliar
o BERTimbau contra rótulo da Gemini seria circular e inválido (CLAUDE.md regra 6) —
aqui a Gemini é a avaliada, nunca a régua.

**Empate 1-1-1 fica de fora.** `rotulo_humano` é NULO até a reunião de consenso
decidir, e comentário sem gabarito não entra em métrica nenhuma. Quantos ficaram de
fora aparece no relatório: é número de capítulo, não detalhe de execução.

## Um método é um CSV

`id_comentario` mais uma coluna de rótulo (`previsto`, `rotulo` ou `sentimento`).
Qualquer método que produza isso entra na comparação sem tocar no código — hoje o
léxico, amanhã o BERTimbau exportado do Colab.

A validação falha **alto e de uma vez só**, como a da concordância: rótulo fora das
três classes, id repetido, comentário do gabarito sem previsão — tudo é listado com
arquivo, linha e id, e **nada é calculado**. Método a que falta comentário mudaria o
`n` em silêncio, e dois métodos medidos em conjuntos diferentes não são comparáveis.

## O que é reportado, e por quê

| número | para quê |
|---|---|
| **F1 macro** | a métrica do projeto (CLAUDE.md regra 8) — é ela que decide o gate |
| acurácia | porque o capítulo a cita; nunca decide |
| precisão e revocação macro | separam "erra pouco" de "acha pouco" |
| F1 por classe | **onde** o método falha — um macro razoável esconde `negativo` em 0,30 |
| matriz de confusão 3x3 | o mapa do erro: é dela que sai a frase sobre `neutro` × `negativo` |
| **IC 95% do F1** (bootstrap) | se a diferença entre dois métodos existe ou é do tamanho da amostra |
| Kappa de Cohen método × gabarito | concordância descontado o acaso; o da Gemini é o da Tabela 15 do TC2 e vai também no campo de topo `kappa_cohen_gemini_gabarito` do JSON. Usa a mesma `kappa_cohen()` de `ml/concordancia/kappa.py` |

Com 334 comentários, um F1 macro de 0,71 contra 0,68 pode não ser diferença nenhuma.
Publicar o ponto sozinho convida a banca a perguntar "e se fossem outros 334?" — e a
resposta é o intervalo. **Intervalos que se sobrepõem não demonstram diferença**, e o
relatório imprime esse aviso sempre que há mais de um método.

O bootstrap é o percentil não paramétrico: 2.000 reamostragens com reposição, semente
42 (a mesma do resto do pipeline), percentis 2,5 e 97,5.

## A média macro é sempre sobre as três classes

Divergência **deliberada** do padrão do `scikit-learn`, e quem for refazer a conta num
notebook precisa saber: sem `labels=`, a biblioteca faz a média macro só sobre as
classes presentes nos dados, e o denominador muda com a amostra. Aqui o denominador é
sempre 3 — as classes são fechadas no banco (CHECK) e não dependem de quem apareceu no
conjunto. Denominadores diferentes tornariam dois métodos incomparáveis, que é
justamente o que o capítulo faz.

Para chegar ao mesmo número: `f1_score(..., average="macro", labels=["positivo",
"negativo", "neutro"], zero_division=0)`.

## As contas são à mão, e conferidas duas vezes

As fórmulas estão escritas em `metricas.py` sem biblioteca de estatística, como as do
Kappa — dá para mostrar a conta na banca. O que garante que estão certas:

1. um caso 3x3 **calculado à mão**, com a conta na própria docstring do teste;
2. o **scikit-learn**, em cem conjuntos sorteados, célula a célula (`percentil` é
   conferido contra o `numpy`).

O `scikit-learn` é dependência só de desenvolvimento (`ml/requirements-dev.txt`): ele
não participa de nenhuma execução do pipeline. Onde não estiver instalado, esses
testes são pulados e o resto continua valendo.

## As figuras

Três, em 300 dpi, pensadas para **papel** (`graficos.py`):

1. `f1_macro.png` — a figura da decisão: F1 macro por método, com o IC como barra de
   erro e o valor escrito ao lado;
2. `f1_por_classe.png` — onde cada método falha, classe a classe;
3. `confusao_<metodo>.png` — a matriz 3x3, linha = gabarito, coluna = previsto,
   intensidade normalizada por linha e contagem absoluta escrita na célula.

A cor é **do método**, fixa por nome: o léxico não muda de tom porque o BERTimbau
entrou na comparação. Cada método leva também uma **hachura**, que é o que mantém as
barras distinguíveis num TCC impresso em preto e branco. A matriz usa **um tom só,
claro para escuro** — magnitude é escala, não identidade. A paleta saiu da linguagem
visual do produto (`frontend/design/DESIGN.md`) e foi conferida em banda de
luminosidade, croma, separação para daltonismo (protan/deutan/tritan) e contraste
contra o papel.

`--sem-graficos` gera só as tabelas, sem exigir `matplotlib` instalado.

## Nada é gravado no banco

A leitura do `rotulo_humano` e do `rotulo_fraco` é a única coisa que o script faz lá.

---

## Comparação pareada (`comparar.py`)

```bash
python -m ml.avaliacao.comparar --id-execucao 4 \
    --a bertimbau=ml/dados/previsoes_bertimbau.csv \
    --b bertimbau_rodada2=ml/dados/previsoes_bertimbau_rodada2.csv \
    --saida ml/treino/historico/comparacao_rodada2.json
```

Dois intervalos que se sobrepõem não demonstram diferença — mas também não a descartam:
os dois métodos classificam **os mesmos** 334 comentários, e um sorteio que caiu nos
difíceis derruba os dois juntos. O IC certo para a diferença é o do **bootstrap
pareado** (`intervalo_bootstrap_pareado` em `metricas.py`): cada reamostragem sorteia um
conjunto de índices e calcula os dois métodos sobre ele. Mesmas 2.000 reamostragens,
mesma semente 42.

É a conta da regra de decisão da rodada 2 (`ml/treino/historico/regra_decisao_rodada2.md`),
que o script imprime no fim: B substitui A se o F1 macro for maior e o IC do delta não
ficar inteiramente abaixo de zero.

## Vazamento entre treino, validação e teste (`vazamento.py`)

```bash
python -m ml.avaliacao.vazamento --id-execucao 4
```

Um comentário do teste que tem **gêmeo** no treino não mede generalização. A régua de
gêmeo (`gemeos.py`) tem dois níveis, sobre o `texto_modelo` (o que o BERTimbau lê):

- **exato** — o mesmo texto depois de normalizar (minúsculas, sem acento, sem pontuação,
  letra repetida reduzida a uma);
- **quase** — Jaccard de trigramas de caractere ≥ **0,8**. A justificativa do limiar,
  com os pares do corpus que o sustentam, está na docstring do módulo, e o histograma da
  maior similaridade de cada comentário do teste vai no JSON.

`gemeos.py` é stdlib pura porque é também o **filtro** da rodada 2 do treino, que roda no
Colab: medição e filtro usam a mesma régua.

### O que a medição deu (04/10/2026)

| cruzamento | universo | com gêmeo | exato | quase | do mesmo vídeo | curtos (≤ 3 palavras) |
|---|---|---|---|---|---|---|
| (a) teste × treino+validação | 334 | **25 (7,5%)** | 18 | 7 | 13 | 16 |
| (b) validação × treino | 330 | 18 | 15 | 3 | 12 | 12 |
| (c) treino × treino | 1.870 | 96 | 62 | 34 | 61 | 57 |

No (a), 23 dos 25 têm o gêmeo no treino. Dois tipos aparecem: o **genérico curto**
("Parabéns", "Que carro lindo", "galinha caipira" — 16 dos 25), que qualquer pessoa
escreveria, e a **cópia real** — o mesmo comentário longo postado duas vezes no mesmo
vídeo.

F1 macro no teste, separando quem tem gêmeo (IC 95%, bootstrap):

| método | todos (334) | com gêmeo (25) | sem gêmeo (309) |
|---|---|---|---|
| léxico | 0,553 | 0,464 [0,260; 0,699] | 0,558 [0,500; 0,615] |
| TF-IDF + logreg | 0,699 | 0,884 [0,726; 0,971] | 0,688 [0,636; 0,735] |
| BERTimbau 1.0.0 | 0,731 | **0,913** [0,782; 1,000] | **0,720** [0,666; 0,769] |
| Gemini (rótulo fraco) | 0,829 | 0,854 [0,679; 0,958] | 0,831 [0,786; 0,870] |

**Léxico e Gemini não treinam com o corpus — são o controle.** Eles não ganham nada no
grupo com gêmeo (o léxico até perde); os dois modelos **supervisionados** ganham ~19
pontos. É a assinatura de memória: entre os 23 com gêmeo no treino, o BERTimbau devolve o
rótulo fraco do gêmeo em 21, mais do que o próprio gabarito concorda com ele (18).

O efeito no número do capítulo é pequeno — **0,731 → 0,720** sem os gêmeos —, porque são
só 25 de 334, mas tem sinal certo e vai para o texto. A rodada 2 do treino remove esses
gêmeos antes de treinar.

O JSON (`saida_vazamento/resultado_vazamento.json`) guarda contagens, os pares por id e
as métricas — nenhum texto. Os exemplos de cada nível saem só no console (`--exemplos`).
