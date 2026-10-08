"""MS Estoque: consome pedidos, reserva produtos e expoe o saldo por REST.

Duas threads: a do consumidor pika (unica que escreve no SQLite) e a do
uvicorn, que atende o GET /produtos consultado pelo API Gateway.
"""

import logging
import sys
from pathlib import Path
from typing import override

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.eventos import Evento  # noqa: E402
from common.http import com_consumidor, criar_app, registrar_health, rodar  # noqa: E402
from common.service import EX_ECOMMERCE, Microservice  # noqa: E402

from ms_estoque import estoque  # noqa: E402

NOME = "ms_estoque"
PORTA = 8002

log = logging.getLogger(NOME)


class MsEstoque(Microservice):
    name = NOME
    queue = "fila.estoque"
    bindings = [
        (EX_ECOMMERCE, Evento.PEDIDO_CRIADO),
        (EX_ECOMMERCE, Evento.PEDIDO_EXCLUIDO),
    ]

    def setup(self):
        super().setup()
        if estoque.inicializar():
            log.info(f"banco criado em {estoque.ARQUIVO.name} (catalogo semeado)")
        self._mostrar_estoque("estoque atual")

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

        resultado, faltas = estoque.reservar(pedido_id, itens)

        # Idempotencia: a entrega do RabbitMQ e at-least-once.
        if resultado is estoque.Resultado.DUPLICATA:
            log.info(f"pedido {pedido_id} ja reservado -- ignorando duplicata")
            return

        if resultado is estoque.Resultado.SEM_ESTOQUE:
            motivo = f"produtos indisponiveis: {', '.join(faltas)}"
            log.info(f"SEM ESTOQUE para {pedido_id}: {', '.join(faltas)}")
            self.publish(EX_ECOMMERCE, Evento.ESTOQUE_INDISPONIVEL, {
                "pedidoId": pedido_id,
                "motivo": motivo,
            })
            return

        log.info(f"reservado para {pedido_id}: {self._resumo(itens)}")
        self._mostrar_estoque("apos reserva")
        self.publish(EX_ECOMMERCE, Evento.PEDIDO_ESTOQUE_OK, {
            "pedidoId": pedido_id,
            "itens": itens,
            "total": pedido.get("total", 0.0),
        })

    def _pedido_excluido(self, evento):
        pedido_id = evento["pedidoId"]
        itens = estoque.devolver(pedido_id)

        if not itens:
            log.info(f"pedido {pedido_id} nao possuia reserva -- nada a devolver")
            return

        log.info(f"devolvido ao estoque de {pedido_id}: {self._resumo(itens)}")
        self._mostrar_estoque("apos devolucao")

    @staticmethod
    def _resumo(itens):
        return ", ".join(f"{i['quantidade']}x {i['produtoId']}" for i in itens)

    def _mostrar_estoque(self, titulo):
        saldos = " ".join(f"{p}={q}" for p, q in sorted(estoque.saldos().items()))
        log.info(f"{titulo}: {saldos} | reservas ativas: {estoque.reservas_ativas()}")


app = criar_app("MS Estoque", lifespan=com_consumidor(MsEstoque))
registrar_health(app)


@app.get("/produtos")
def listar_produtos():
    """Unico endpoint do estoque: o API Gateway le daqui o saldo real.

    E a excecao que o Trab2 abre a regra do Trab1 de nao haver chamada direta
    entre processos -- e so leitura, e so o gateway chama.
    """
    return estoque.listar()


if __name__ == "__main__":
    rodar(app, PORTA, NOME)
