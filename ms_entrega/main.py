#!/usr/bin/env python3
"""Microsservico Entrega.

    Consome:  pagamento.aprovado
    Publica:  pedido.enviado

Emite a nota fiscal (simulada) e prepara a entrega antes de publicar.
"""

import logging
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.service import EX_ECOMMERCE, Microservice  # noqa: E402

log = logging.getLogger(__name__)

TRANSPORTADORAS = ["Correios", "Jadlog", "Loggi", "Azul Cargo"]


class MsEntrega(Microservice):
    name = "ms_entrega"
    queue = "fila.entrega"
    bindings = [
        (EX_ECOMMERCE, "pagamento.aprovado"),
    ]

    def __init__(self):
        super().__init__()
        self._proxima_nota = 1000
        self._emitidas = set()

    def handle(self, event, payload):
        if event != "pagamento.aprovado":
            return

        pedido_id = payload["pedidoId"]

        # Idempotencia: nao emitir duas notas para o mesmo pedido.
        if pedido_id in self._emitidas:
            log.info(f"nota de {pedido_id} ja emitida -- ignorando duplicata")
            return

        self._proxima_nota += 1
        nota = f"NF-{self._proxima_nota}"
        log.info(f"emitindo nota fiscal {nota} para {pedido_id}...")
        time.sleep(1)  # simula emissao da nota e preparacao do pacote

        rastreio = f"BR{random.randint(0, 999999999):09d}"
        transportadora = random.choice(TRANSPORTADORAS)
        self._emitidas.add(pedido_id)
        log.info(f"despachado via {transportadora} (rastreio {rastreio})")

        self.publish(EX_ECOMMERCE, "pedido.enviado", {
            "pedidoId": pedido_id,
            "notaFiscal": nota,
            "rastreio": rastreio,
            "transportadora": transportadora,
        })


if __name__ == "__main__":
    MsEntrega().start()
