"""MS Principal / API Gateway: ponto de entrada do frontend.

Tres threads convivem neste processo:
  - a thread do uvicorn, que atende REST e mantem os streams SSE;
  - a thread do consumidor pika, que ouve o backend e alimenta o SSE;
  - as threads do pool do Starlette, que executam as rotas `def` e publicam.

Cada uma com a sua conexao com o broker: o BlockingConnection do pika nao e
thread-safe.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.http import rodar  # noqa: E402

from ms_principal.api import app  # noqa: E402
from ms_principal.consumidor import NOME  # noqa: E402

PORTA = int(os.getenv("GATEWAY_PORTA", "8000"))

if __name__ == "__main__":
    rodar(app, PORTA, NOME)
