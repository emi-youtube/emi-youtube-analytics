"""Classificação de sentimento: a interface e suas implementações.

Separado de `app/workers/` de propósito. O worker é **transporte** — reivindica job,
lê comentário, grava análise, trata falha. O classificador é **método** — dado um
texto, qual rótulo. Quando o BERTimbau entrar, só esta pasta ganha arquivo; o worker
não muda uma linha, e é isso que torna a troca verificável.

- `base` — a interface (`Classificador`), o que ela devolve (`Classificacao`) e o
  portão da versão do pré-processamento (CLAUDE.md regra 5);
- `lexico` — a implementação de hoje: SentiLex-PT02, o piso do Capítulo 5;
- `versao` — a linha de VERSOES_MODELO para a qual as análises apontam.
"""
