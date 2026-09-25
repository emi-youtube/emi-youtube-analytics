#!/usr/bin/env bash
# Monta o pacote que vai para o Azure App Service.
#
# POR QUE ISTO EXISTE. O `backend/requirements.txt` instala dois pacotes que
# moram FORA de backend/ -- `preprocessamento/` e `lexico/`, na raiz do
# repositorio (CLAUDE.md Secao 3: o que treino e inferencia precisam executar
# igual mora num terceiro pacote). Com `backend/` como raiz da aplicacao no
# Azure, esses caminhos simplesmente nao existem, e o deploy sobe sem eles.
#
# Pior que nao existir: eles estao declarados com `-e` (editavel). Editavel
# grava no site-packages um ponteiro para a PASTA DE ORIGEM. No servidor essa
# pasta e o diretorio temporario onde o Oryx monta o app, que depois e copiado
# para outro lugar -- o ponteiro fica apontando para o vazio e o import quebra em
# producao, nao no build.
#
# A solucao e o pacote ser AUTOCONTIDO: os dois pacotes compartilhados viajam
# dentro dele, e o requirements do pacote os instala por caminho relativo e SEM
# `-e`, o que copia o codigo para dentro do site-packages.
#
# O `backend/requirements.txt` do repositorio NAO muda: `-e` continua sendo o
# certo para desenvolvimento, onde editar `preprocessamento/` tem de valer na
# hora nos dois ambientes. A troca acontece so na copia que vai para o servidor.
#
# Este script e usado pelo workflow de deploy E pela prova local, de proposito:
# se a prova montasse o pacote de outro jeito, ela nao provaria nada sobre o que
# e publicado.
#
#   uso: backend/scripts/montar_pacote.sh <diretorio-de-saida>
set -euo pipefail

DESTINO="${1:?uso: montar_pacote.sh <diretorio-de-saida>}"
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"

rm -rf "$DESTINO"
mkdir -p "$DESTINO"

EXCLUIR=(
  --exclude=.venv
  --exclude=__pycache__
  --exclude=.pytest_cache
  --exclude=.ruff_cache
  --exclude=build
  --exclude='*.egg-info'
  --exclude='*.pyc'
)

# 1. O conteudo de backend/ vai para a RAIZ do pacote: e o que o App Service
#    serve, e o que faz `app.main:app` resolver sem prefixo.
#    `tests/` fica de fora -- nao roda em producao e so aumentaria o pacote.
tar -c "${EXCLUIR[@]}" --exclude=tests -C "$RAIZ/backend" . | tar -x -C "$DESTINO"

# 2. Os dois pacotes compartilhados entram COMO PASTAS dentro do pacote, para o
#    caminho relativo do requirements resolver no servidor.
for compartilhado in preprocessamento lexico; do
  mkdir -p "$DESTINO/$compartilhado"
  tar -c "${EXCLUIR[@]}" --exclude=tests -C "$RAIZ/$compartilhado" . \
    | tar -x -C "$DESTINO/$compartilhado"
done

# 3. Tira o `-e` das duas linhas. A instalacao passa a COPIAR o codigo para o
#    site-packages, em vez de deixar um ponteiro para uma pasta que nao vai
#    sobreviver a copia do Oryx.
python - "$DESTINO/requirements.txt" <<'PY'
import io, re, sys

caminho = sys.argv[1]
texto = io.open(caminho, encoding="utf-8").read()
novo, trocas = re.subn(r"(?m)^-e\s+(\./(?:preprocessamento|lexico))\s*$", r"\1", texto)
if trocas != 2:
    raise SystemExit(
        f"esperava trocar 2 linhas editaveis em {caminho}, troquei {trocas}. "
        "Se o requirements mudou, ajuste montar_pacote.sh junto."
    )
io.open(caminho, "w", encoding="utf-8", newline="\n").write(novo)
print(f"[pacote] requirements.txt: {trocas} pacote(s) compartilhado(s) sem -e")
PY

# 4. Conferencia: o pacote tem de ser autocontido. Falhar aqui e muito melhor
#    que descobrir o import quebrado no Log stream depois do deploy.
for exigido in app/main.py alembic.ini startup.sh scripts/baixar_sentilex.sh \
               preprocessamento/pyproject.toml lexico/pyproject.toml; do
  [ -e "$DESTINO/$exigido" ] || { echo "[pacote] FALTA $exigido" >&2; exit 1; }
done
if grep -qE '^\s*-e\s' "$DESTINO/requirements.txt"; then
  echo "[pacote] ERRO: sobrou instalacao editavel no requirements do pacote" >&2
  exit 1
fi

echo "[pacote] pronto em $DESTINO"
