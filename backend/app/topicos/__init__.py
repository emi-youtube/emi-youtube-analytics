"""Modelagem de tópicos: TF-IDF + NMF sobre os comentários de uma execução.

Separado de `app/workers/` pelo mesmo motivo que `app/inferencia/`: o worker é
transporte (lê comentário, grava TEMAS e COMENTARIO_TEMA, trata falha) e este
pacote é método (dado um conjunto de textos, quais assuntos existem).

- `texto` — a limpeza própria da tarefa de assunto, que REMOVE emoji em vez de
  convertê-lo (ver o cabeçalho do módulo: é a diferença entre achar assunto e
  achar humor);
- `modelo` — a vetorização, o NMF, a regra de quantos temas e os pesos.
"""
