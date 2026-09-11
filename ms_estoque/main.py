#!/usr/bin/env python3
"""Microsservico Estoque.

    Consome:  pedido.criado, pedido.excluido      (exchange eCommerce, direct)
    Publica:  pedido.estoque_ok, estoque.indisponivel

Nao ha Lock protegendo o estado: o pika entrega as mensagens uma a uma na
mesma thread, entao os handlers nunca rodam em paralelo aqui.
"""

import logging
import sys
from pathlib import Path

# Permite rodar como `python ms_estoque/main.py` ou `python -m ms_estoque.main`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.service import EX_ECOMMERCE, Microservice  # noqa: E402

log = logging.getLogger(__name__)

# As quantidades existem APENAS aqui. O catalogo compartilhado tem so os dados
# cadastrais do produto -- por isso o menu do Principal nao mostra saldo: nao
# ha como consultar sem chamada direta, que o enunciado proibe.
ESTOQUE_INICIAL = {"P1": 10, "P2": 5, "P3": 0, "P4": 3, "P5": 7, "P6": 2}


class MsEstoque(Microservice):
    name = "ms_estoque"
    queue = "fila.estoque"
    bindings = [
        (EX_ECOMMERCE, "pedido.criado"),
        (EX_ECOMMERCE, "pedido.excluido"),
    ]

    def __init__(self):
        super().__init__()
        self.estoque = dict(ESTOQUE_INICIAL)
        self.reservas = {}  # pedido_id -> lista de itens reservados

    def setup(self):
        super().setup()
        self._mostrar_estoque("estoque inicial")

    def handle(self, event, payload):
        if event == "pedido.criado":
            self._pedido_criado(payload)
        elif event == "pedido.excluido":
            self._pedido_excluido(payload)

    # ---- pedido.criado -------------------------------------------------

    def _pedido_criado(self, pedido):
        pedido_id = pedido["pedidoId"]
        itens = pedido["itens"]

        # Idempotencia: a entrega do RabbitMQ e at-least-once, um evento
        # reentregue nao pode reservar duas vezes.
        if pedido_id in self.reservas:
            log.info("pedido %s ja reservado -- ignorando duplicata", pedido_id)
            return

        # Verifica TODOS os itens antes de dar qualquer baixa.
        indisponiveis = [
            item for item in itens
            if self.estoque.get(item["produtoId"], 0) < item["quantidade"]
        ]

        if indisponiveis:
            faltas = ", ".join(
                "%s (pedido %d, disponivel %d)"
                % (i["produtoId"], i["quantidade"], self.estoque.get(i["produtoId"], 0))
                for i in indisponiveis
            )
            log.info("SEM ESTOQUE para %s: %s", pedido_id, faltas)
            self.publish(EX_ECOMMERCE, "estoque.indisponivel", {
                "pedidoId": pedido_id,
                "motivo": "produtos indisponiveis: %s" % faltas,
            })
            return

        for item in itens:
            self.estoque[item["produtoId"]] -= item["quantidade"]
        self.reservas[pedido_id] = itens

        log.info("reservado para %s: %s", pedido_id, self._resumo(itens))
        self._mostrar_estoque("apos reserva")
        self.publish(EX_ECOMMERCE, "pedido.estoque_ok", {
            "pedidoId": pedido_id,
            "itens": itens,
            "total": pedido.get("total", 0.0),
        })

    # ---- pedido.excluido -----------------------------------------------

    def _pedido_excluido(self, evento):
        pedido_id = evento["pedidoId"]
        itens = self.reservas.pop(pedido_id, None)

        if itens is None:
            log.info("pedido %s nao possuia reserva -- nada a devolver", pedido_id)
            return

        for item in itens:
            self.estoque[item["produtoId"]] = (
                self.estoque.get(item["produtoId"], 0) + item["quantidade"]
            )
        log.info("devolvido ao estoque de %s: %s", pedido_id, self._resumo(itens))
        self._mostrar_estoque("apos devolucao")

    # ---- apoio ---------------------------------------------------------

    @staticmethod
    def _resumo(itens):
        return ", ".join("%dx %s" % (i["quantidade"], i["produtoId"]) for i in itens)

    def _mostrar_estoque(self, titulo):
        log.info("%s: %s | reservas ativas: %d", titulo,
                 " ".join("%s=%d" % (p, q) for p, q in sorted(self.estoque.items())),
                 len(self.reservas))


if __name__ == "__main__":
    MsEstoque().start()
