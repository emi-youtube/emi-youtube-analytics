#!/usr/bin/env bash
# Comando de arranque do App Service: sobe a API e o runner no MESMO contêiner.
#
# As dependencias sao instaladas pelo Oryx, no servidor, antes de este script
# rodar -- o pacote publicado traz so codigo-fonte. Ver o cabecalho do workflow.
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

# O diretorio do app NAO e /home/site/wwwroot.
#
# Com build automatico, o Oryx comprime a saida em `output.tar.zst`, deixa esse
# tarball no wwwroot e o extrai em /tmp/<uid> no arranque. O wwwroot fica so com
# o tarball e o manifesto; o app roda de /tmp/<uid>. A propria documentacao do
# App Service diz isso e manda usar caminho relativo:
#
#   "content is deployed to and served from /tmp/<uid>, not under
#    /home/site/wwwroot. You can access this content directory by using the
#    APP_PATH environment variable."
#   "All commands must use paths that are relative to the project root folder."
#   -- learn.microsoft.com/azure/app-service/configure-language-python
#
# Dai o `APP_PATH` primeiro: e o caminho que a plataforma define. O `dirname`
# cobre execucao local e o caso de o script ser chamado por caminho.
cd "${APP_PATH:-$(dirname "$0")}"
echo "[startup] diretorio do app: $PWD"

# 0. O virtualenv que o Oryx montou.
#
# Quem instala as dependencias e o SERVIDOR (ver docs/DEPLOY.md secao 1 e o
# cabecalho do workflow): o Oryx roda o pip install e cria o `antenv`. A imagem
# do App Service normalmente ja o ativa antes de chamar este script, mas quando
# o Startup Command e customizado isso nem sempre acontece -- e um `python` sem
# o venv nao acha fastapi nenhum e o site sobe 503.
#
# Ativar aqui e barato e torna o script correto nos dois casos.
for candidato in "$PWD/antenv" /tmp/*/antenv; do
  if [ -f "$candidato/bin/activate" ]; then
    # shellcheck disable=SC1091
    . "$candidato/bin/activate"
    echo "[startup] virtualenv ativado: $candidato"
    break
  fi
done

# Diagnostico que vale ouro no Log stream: diz QUAL python esta rodando e se as
# dependencias estao la, antes de qualquer coisa falhar por outro motivo.
echo "[startup] python: $(command -v python || echo 'NAO ENCONTRADO')"
if ! python -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "[startup] ERRO: dependencias ausentes. O Oryx nao construiu o app." >&2
  echo "[startup] Confira nas App settings: SCM_DO_BUILD_DURING_DEPLOYMENT=1," >&2
  echo "[startup] ENABLE_ORYX_BUILD=true e NENHUM WEBSITE_RUN_FROM_PACKAGE." >&2
  exit 1
fi

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
