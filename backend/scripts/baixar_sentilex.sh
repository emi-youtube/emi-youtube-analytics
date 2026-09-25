#!/usr/bin/env bash
# Coloca o SentiLex-PT02 no servidor e CONFERE o sha256 antes de dar por bom.
#
# O arquivo nao esta no git (dado de terceiro, 6,9 MB -- ver ml/lexico/README.md),
# entao ele precisa chegar ao servidor de alguma forma. Baixar no arranque, num
# caminho persistente, e a forma que nao exige registry nem storage a parte.
#
# A conferencia do sha256 NAO e zelo extra: o classificador lexico recusa subir
# com hash diferente (app/inferencia/lexico.py), entao um download truncado ou um
# espelho trocado derrubaria o worker com uma mensagem clara. Conferir aqui
# adianta esse erro para o arranque e evita baixar de novo o que ja esta certo.
set -euo pipefail

# /home e o unico caminho que sobrevive a restart no Azure App Service.
DESTINO="${SENTILEX_PATH:-/home/data/SentiLex-flex-PT02.txt}"
ESPERADO="88ab7389bfe6f4a2b489a4a53c42306691796bc2fef9d4c2a26790dd927ba85c"
URL="https://raw.githubusercontent.com/sillasgonzaga/lexiconPT/master/data-raw/SentiLex-flex-PT02.txt"

conferir() {
  [ -f "$1" ] || return 1
  echo "${ESPERADO}  $1" | sha256sum --check --status
}

if conferir "$DESTINO"; then
  echo "[sentilex] ja presente e com o sha256 esperado: $DESTINO"
  exit 0
fi

echo "[sentilex] baixando para $DESTINO"
mkdir -p "$(dirname "$DESTINO")"
curl -fsSL --retry 3 --retry-delay 2 -o "${DESTINO}.parcial" "$URL"

# So promove depois de conferir: um arquivo errado no caminho definitivo faria o
# worker recusar subir a cada restart, sem conseguir se recuperar sozinho.
if ! echo "${ESPERADO}  ${DESTINO}.parcial" | sha256sum --check --status; then
  echo "[sentilex] ERRO: sha256 do arquivo baixado nao confere com o medido no Capitulo 5." >&2
  echo "[sentilex] esperado: ${ESPERADO}" >&2
  echo "[sentilex] obtido:   $(sha256sum "${DESTINO}.parcial" | cut -d' ' -f1)" >&2
  rm -f "${DESTINO}.parcial"
  exit 1
fi

mv "${DESTINO}.parcial" "$DESTINO"
echo "[sentilex] ok: $DESTINO"
