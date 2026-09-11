#!/usr/bin/env bash
# Sobe os 6 processos nao-interativos em background, com log em logs/.
# O ms_principal fica de fora: rode-o em primeiro plano, e ele e a interface.
#
#   ./run_services.sh start    # sobe estoque, pagamento, entrega, promocoes, C1, C2
#   ./run_services.sh stop     # derruba todos
#   ./run_services.sh logs     # acompanha os logs
#
# Para a defesa, prefira 7 terminais separados (ver README).

set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
SERVICOS=(ms_estoque ms_pagamento ms_entrega ms_promocoes consumidor_c1 consumidor_c2)

start() {
  mkdir -p logs
  for s in "${SERVICOS[@]}"; do
    if [ -f "logs/$s.pid" ] && kill -0 "$(cat "logs/$s.pid")" 2>/dev/null; then
      echo "  $s ja esta rodando (pid $(cat "logs/$s.pid"))"
      continue
    fi
    nohup $PY -u -m "$s.main" > "logs/$s.log" 2>&1 &
    echo $! > "logs/$s.pid"
    echo "  $s iniciado (pid $!) -> logs/$s.log"
  done
  echo
  echo "Agora rode a interface:  $PY -m ms_principal.main"
}

stop() {
  for s in "${SERVICOS[@]}"; do
    if [ -f "logs/$s.pid" ]; then
      kill "$(cat "logs/$s.pid")" 2>/dev/null && echo "  $s parado" || echo "  $s nao estava rodando"
      rm -f "logs/$s.pid"
    fi
  done
}

case "${1:-start}" in
  start) start ;;
  stop)  stop ;;
  logs)  tail -f logs/*.log ;;
  *)     echo "uso: $0 {start|stop|logs}"; exit 1 ;;
esac
