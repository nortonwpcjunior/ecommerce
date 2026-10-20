import random
import string
import threading
from enum import StrEnum


class Status(StrEnum):
    rotulo: str

    def __new__(cls, valor: str, rotulo: str) -> "Status":
        membro = str.__new__(cls, valor)
        membro._value_ = valor
        membro.rotulo = rotulo
        return membro

    AGUARDANDO_ESTOQUE = "AGUARDANDO_ESTOQUE", "aguardando verificacao de estoque"
    ESTOQUE_RESERVADO = "ESTOQUE_RESERVADO", "estoque reservado, abrindo cobranca"
    AGUARDANDO_PAGAMENTO = "AGUARDANDO_PAGAMENTO", "aguardando pagamento"
    PAGAMENTO_APROVADO = "PAGAMENTO_APROVADO", "pagamento aprovado, preparando envio"
    ENVIADO = "ENVIADO", "enviado"
    CANCELADO_SEM_ESTOQUE = "CANCELADO_SEM_ESTOQUE", "CANCELADO - sem estoque"
    CANCELADO_PAGAMENTO = "CANCELADO_PAGAMENTO", "CANCELADO - pagamento recusado"
    CANCELADO_USUARIO = "CANCELADO_USUARIO", "CANCELADO - excluido pelo usuario"


CANCELAVEIS = frozenset({
    Status.AGUARDANDO_ESTOQUE,
    Status.ESTOQUE_RESERVADO,
    Status.AGUARDANDO_PAGAMENTO,
})

TERMINAIS = frozenset({
    Status.ENVIADO,
    Status.CANCELADO_SEM_ESTOQUE,
    Status.CANCELADO_PAGAMENTO,
    Status.CANCELADO_USUARIO,
})

# Sufixo aleatorio para evitar colisao de IDs
SESSAO = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))


class PedidoStore:

    def __init__(self):
        self._lock = threading.Lock()
        self._pedidos = {}
        self._contador = 0

    def novo_id(self) -> str:
        with self._lock:
            self._contador += 1
            return f"PED-{SESSAO}-{self._contador:03d}"

    def registrar(self, pedido_id, cliente, itens, total) -> dict:
        with self._lock:
            self._pedidos[pedido_id] = {
                "cliente": cliente,
                "itens": itens,
                "total": total,
                "status": Status.AGUARDANDO_ESTOQUE,
                "detalhe": "",
                "checkoutUrl": "",
            }
            return self._snapshot_pedido(pedido_id)

    def atualizar(self, pedido_id, status, detalhe="", **extras) -> dict | None:
        with self._lock:
            pedido = self._pedidos.get(pedido_id)
            if pedido is None or pedido["status"] in TERMINAIS:
                return None
            pedido["status"] = status
            pedido["detalhe"] = detalhe
            pedido.update(extras)
            return self._snapshot_pedido(pedido_id)

    def atualizar_se(self, pedido_id, permitidos, status, detalhe="") -> dict | None:
        with self._lock:
            pedido = self._pedidos.get(pedido_id)
            if pedido is None or pedido["status"] not in permitidos:
                return None
            pedido["status"] = status
            pedido["detalhe"] = detalhe
            return self._snapshot_pedido(pedido_id)

    def status_de(self, pedido_id) -> "Status | None":
        with self._lock:
            pedido = self._pedidos.get(pedido_id)
            return pedido["status"] if pedido else None

    def rotulo_de(self, pedido_id) -> str:
        status = self.status_de(pedido_id)
        return status.rotulo if status is not None else "?"

    def obter(self, pedido_id) -> dict | None:
        with self._lock:
            if pedido_id not in self._pedidos:
                return None
            return self._snapshot_pedido(pedido_id)

    def listar(self, cliente: str | None = None) -> list[dict]:
        with self._lock:
            return [
                self._snapshot_pedido(pid)
                for pid in sorted(self._pedidos)
                if cliente is None or self._pedidos[pid]["cliente"] == cliente
            ]

    def _snapshot_pedido(self, pedido_id) -> dict:
        pedido = self._pedidos[pedido_id]
        return {
            "pedidoId": pedido_id,
            "cliente": pedido["cliente"],
            "itens": [dict(item) for item in pedido["itens"]],
            "total": pedido["total"],
            "status": str(pedido["status"]),
            "rotulo": pedido["status"].rotulo,
            "detalhe": pedido["detalhe"],
            "checkoutUrl": pedido["checkoutUrl"],
        }


STORE = PedidoStore()
