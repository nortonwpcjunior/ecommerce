import logging
import os
import random
import sys
from pathlib import Path
from typing import override

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.eventos import Evento  # noqa: E402
from common.service import EX_ECOMMERCE, Microservice  # noqa: E402

log = logging.getLogger(__name__)

TAXA_APROVACAO = float(os.getenv("TAXA_APROVACAO", "0.7"))
MOTIVOS_RECUSA = [
    "saldo insuficiente",
    "cartao expirado",
    "suspeita de fraude",
    "limite excedido",
]


class MsPagamento(Microservice):
    name = "ms_pagamento"
    queue = "fila.pagamento"
    bindings = [
        (EX_ECOMMERCE, Evento.PEDIDO_ESTOQUE_OK),
    ]

    @override
    def handle(self, event, payload):
        if event != Evento.PEDIDO_ESTOQUE_OK:
            return

        pedido_id = payload["pedidoId"]
        valor = payload.get("total", 0.0)

        if random.random() < TAXA_APROVACAO:
            autorizacao = f"AUT-{random.randint(0, 999999):06d}"
            log.info(f"APROVADO ({autorizacao})")
            self.publish(EX_ECOMMERCE, Evento.PAGAMENTO_APROVADO, {
                "pedidoId": pedido_id,
                "valor": valor,
                "autorizacao": autorizacao,
                "itens": payload.get("itens", []),
            })
        else:
            motivo = random.choice(MOTIVOS_RECUSA)
            log.info(f"RECUSADO ({motivo})")
            self.publish(EX_ECOMMERCE, Evento.PAGAMENTO_RECUSADO, {
                "pedidoId": pedido_id,
                "valor": valor,
                "motivo": motivo,
            })


if __name__ == "__main__":
    MsPagamento().start()
