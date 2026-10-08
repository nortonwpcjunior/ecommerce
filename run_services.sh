#!/usr/bin/env bash
# Sobe os 6 processos do backend em background, com log em logs/.
# O frontend (npm run dev) fica de fora: rode-o num terminal proprio.
#
#   ./run_services.sh start    # sobe estoque, pagamento, entrega, promocoes,
#                              # mock e o API gateway
#   ./run_services.sh stop     # derruba todos
#   ./run_services.sh logs     # acompanha os logs
#
# Para a defesa, prefira um terminal por processo (ver README).

set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python

# A ordem importa na subida: o gateway consulta o estoque, e o pagamento
# precisa do mock de pe para abrir a cobranca.
SERVICOS=(ms_estoque mock_pagamento ms_pagamento ms_entrega ms_promocoes ms_principal)

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
  echo "API Gateway:  http://localhost:8000/docs"
  echo "Agora rode o frontend:  cd frontend && npm run dev"
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
