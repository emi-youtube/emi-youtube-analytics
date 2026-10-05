# Regra de decisão da rodada 2 do BERTimbau Base

Gravada em 04/10/2026, **antes de qualquer treino da rodada 2**. O commit que cria este
arquivo é a prova da ordem: a regra existe antes do resultado que ela julga. Mudar a
regra depois de ver o teste invalida a rodada.

## O que é a rodada 2

O mesmo modelo-base da rodada 1 (`neuralmind/bert-base-portuguese-cased`), o mesmo
corpus (execução 4, 2.200 comentários de `split IS NULL` com `rotulo_fraco`), a mesma
partição 85/15 estratificada com semente 42 e o mesmo `preprocessamento`. Mudam duas
coisas, ambas decididas antes do treino:

1. **Filtro de vazamento, em memória.** Saem do treino e da validação os comentários
   que têm gêmeo (texto idêntico depois de normalizar, ou quase idêntico) entre os 334
   do teste; sai do treino o comentário que tem gêmeo na validação. Nada é alterado no
   banco — nem `split`, nem `rotulo_humano`. Quantos saíram, e quais (`id_comentario`),
   vai para os relatórios da rodada. Critério de gêmeo: `ml/avaliacao/gemeos.py`.
2. **Grade nova ao redor da vencedora da rodada 1**, que ficou no canto da grade
   anterior (5e-5, 4 épocas, e 4 das 5 sementes com melhor época na 4ª): taxas
   **3e-5, 4e-5, 5e-5** × épocas **4, 5, 6**. Lote 16, decaimento 0,01, warmup 10%,
   `max_length` 128, AdamW, agenda linear — fixos.

## Regras

1. **Hiperparâmetro sai só da validação.** A busca roda com a semente 42 e escolhe pelo
   F1 macro de validação. O conjunto de teste não participa da busca, da escolha da
   época, da escolha da semente nem do filtro de vazamento além do texto (o filtro lê
   o texto do teste, nunca o rótulo).
2. **Cinco sementes na configuração escolhida** (42, 43, 44, 45, 46), partição fixa;
   publica-se a semente **mediana** em F1 macro de validação, como na rodada 1.
3. **O teste é avaliado uma única vez.** Uma execução de `prever_teste` com o modelo
   da semente mediana e uma execução da avaliação contra o `rotulo_humano`, com o mesmo
   código da rodada 1 (`ml/avaliacao/`). Se um defeito obrigar a repetir, a repetição e
   o motivo entram no `historico_treinos.md`.
4. **O modelo novo só substitui o de produção (`bertimbau-emi 1.0.0`) se as duas
   condições valerem:**
   - o F1 macro no teste for **maior** que o do 1.0.0 (0,7314, medido em 30/09);
   - o IC 95% do **delta pareado** (F1 macro do novo − F1 macro do 1.0.0, nos mesmos
     334 comentários) **não ficar inteiramente abaixo de zero**, isto é, o limite
     superior for ≥ 0.

   O delta pareado é o bootstrap percentil com reamostragem dos **mesmos** índices para
   os dois modelos (2.000 reamostragens, semente 42), calculado por
   `python -m ml.avaliacao.comparar`.
5. **Em qualquer caso, as duas rodadas entram no TCC**: a vencedora e a perdedora, com
   os mesmos números (validação, teste, IC, delta pareado). Uma rodada 2 que não
   supera a 1 é resultado, não fracasso a esconder.

## O que não se faz

- olhar o teste e voltar para mexer na grade, no filtro, no número de épocas ou na
  semente publicada;
- avaliar mais de um candidato da rodada 2 no teste e ficar com o melhor;
- trocar o critério de gêmeo depois de ver o resultado no teste.
