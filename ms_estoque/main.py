import logging
import sys
from pathlib import Path
from typing import override

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.eventos import Evento  # noqa: E402
from common.service import EX_ECOMMERCE, Microservice  # noqa: E402

log = logging.getLogger(__name__)

ESTOQUE_INICIAL = {"P1": 10, "P2": 5, "P3": 0, "P4": 3, "P5": 7, "P6": 2}


class MsEstoque(Microservice):
    name = "ms_estoque"
    queue = "fila.estoque"
    bindings = [
        (EX_ECOMMERCE, Evento.PEDIDO_CRIADO),
        (EX_ECOMMERCE, Evento.PEDIDO_EXCLUIDO),
    ]

    def __init__(self):
        super().__init__()
        self.estoque = dict(ESTOQUE_INICIAL)
        self.reservas = {}

    def setup(self):
        super().setup()
        self._mostrar_estoque("estoque inicial")

    @override
    def handle(self, event, payload):
        match event:
            case Evento.PEDIDO_CRIADO:
                self._pedido_criado(payload)
            case Evento.PEDIDO_EXCLUIDO:
                self._pedido_excluido(payload)

    def _pedido_criado(self, pedido):
        pedido_id = pedido["pedidoId"]
        itens = pedido["itens"]

        # Idempotencia
        if pedido_id in self.reservas:
            log.info(f"pedido {pedido_id} ja reservado -- ignorando duplicata")
            return

        # Verifica todos os itens antes de remover do estoque.
        indisponiveis = [
            item for item in itens
            if self.estoque.get(item["produtoId"], 0) < item["quantidade"]
        ]

        if indisponiveis:
            faltas = ", ".join(
                f"{i['produtoId']} (pedido {i['quantidade']}, "
                f"disponivel {self.estoque.get(i['produtoId'], 0)})"
                for i in indisponiveis
            )
            log.info(f"SEM ESTOQUE para {pedido_id}: {faltas}")
            self.publish(EX_ECOMMERCE, Evento.ESTOQUE_INDISPONIVEL, {
                "pedidoId": pedido_id,
                "motivo": f"produtos indisponiveis: {faltas}",
            })
            return

        for item in itens:
            self.estoque[item["produtoId"]] -= item["quantidade"]
        self.reservas[pedido_id] = itens

        log.info(f"reservado para {pedido_id}: {self._resumo(itens)}")
        self._mostrar_estoque("apos reserva")
        self.publish(EX_ECOMMERCE, Evento.PEDIDO_ESTOQUE_OK, {
            "pedidoId": pedido_id,
            "itens": itens,
            "total": pedido.get("total", 0.0),
        })

    def _pedido_excluido(self, evento):
        pedido_id = evento["pedidoId"]
        itens = self.reservas.pop(pedido_id, None)

        if itens is None:
            log.info(f"pedido {pedido_id} nao possuia reserva -- nada a devolver")
            return

        for item in itens:
            self.estoque[item["produtoId"]] = (
                self.estoque.get(item["produtoId"], 0) + item["quantidade"]
            )
        log.info(f"devolvido ao estoque de {pedido_id}: {self._resumo(itens)}")
        self._mostrar_estoque("apos devolucao")

    @staticmethod
    def _resumo(itens):
        return ", ".join(f"{i['quantidade']}x {i['produtoId']}" for i in itens)

    def _mostrar_estoque(self, titulo):
        saldos = " ".join(f"{p}={q}" for p, q in sorted(self.estoque.items()))
        log.info(f"{titulo}: {saldos} | reservas ativas: {len(self.reservas)}")


if __name__ == "__main__":
    MsEstoque().start()
