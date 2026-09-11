#!/usr/bin/env python3
"""Microsservico Pagamento.

    Consome:  pedido.estoque_ok
    Publica:  pagamento.aprovado, pagamento.recusado

A aprovacao e simulada por variavel aleatoria (TAXA_APROVACAO, padrao 0.7).
"""

import logging
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
        (EX_ECOMMERCE, "pedido.estoque_ok"),
    ]

    def handle(self, event, payload):
        if event != "pedido.estoque_ok":
            return

        pedido_id = payload["pedidoId"]
        valor = payload.get("total", 0.0)

        log.info("processando pagamento de %s (R$ %.2f)...", pedido_id, valor)
        time.sleep(1)  # simula latencia da operadora

        if random.random() < TAXA_APROVACAO:
            autorizacao = "AUT-%06d" % random.randint(0, 999999)
            log.info("APROVADO (%s)", autorizacao)
            self.publish(EX_ECOMMERCE, "pagamento.aprovado", {
                "pedidoId": pedido_id,
                "valor": valor,
                "autorizacao": autorizacao,
                "itens": payload.get("itens", []),
            })
        else:
            motivo = random.choice(MOTIVOS_RECUSA)
            log.info("RECUSADO (%s)", motivo)
            self.publish(EX_ECOMMERCE, "pagamento.recusado", {
                "pedidoId": pedido_id,
                "valor": valor,
                "motivo": motivo,
            })


if __name__ == "__main__":
    MsPagamento().start()
