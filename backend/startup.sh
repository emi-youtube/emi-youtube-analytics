#!/usr/bin/env bash
# Comando de arranque do App Service: sobe a API e o runner no MESMO contêiner.
#
# POR QUE OS DOIS JUNTOS (ver docs/DEPLOY.md para a comparacao completa):
# uma B1 tem 1,75 GB e o credito do Azure for Students e finito; dois App
# Services seriam o dobro do custo para rodar dois processos que somados nao
# passam de ~700 MB. WebJob nao serve -- e so Windows, e este e Python/Linux.
#
# A API fica em PRIMEIRO PLANO de proposito: o ciclo de vida do conteiner segue
# o dela, que e o processo que o Azure monitora por HTTP. O runner fica
# supervisionado em segundo plano, porque uma queda dele nao deveria derrubar a
# API junto -- e, enquanto ele volta, o reaper devolve a fila o job que ele
# estava processando (app/workers/fila.devolver_presos).
set -euo pipefail

cd "$(dirname "$0")"

# 1. O lexico precisa estar no disco antes de o runner tentar carrega-lo.
bash scripts/baixar_sentilex.sh

# 2. Migrations. Roda antes de qualquer processo atender: schema velho com
#    codigo novo falha de formas piores que nao subir.
python -m alembic upgrade head

# 3. Runner supervisionado: se morrer, volta. A espera cresce ate 60s para um
#    erro permanente (lexico ausente, banco fora) nao virar laco de reinicio.
supervisionar_runner() {
  local espera=5
  while true; do
    echo "[runner] iniciando"
    if python -m app.workers.runner; then
      echo "[runner] encerrou normalmente"
      espera=5
    else
      echo "[runner] caiu (codigo $?); reiniciando em ${espera}s" >&2
    fi
    sleep "$espera"
    espera=$(( espera < 60 ? espera * 2 : 60 ))
  done
}
supervisionar_runner &

# 4. API em primeiro plano. $PORT e definido pelo App Service.
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
