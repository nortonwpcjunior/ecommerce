import logging
import random
import string
import sys
import threading
from enum import StrEnum
from pathlib import Path
from typing import override

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.catalogo import PRODUTOS  # noqa: E402
from common.eventos import Evento  # noqa: E402
from common.service import EX_ECOMMERCE, Microservice, Publisher  # noqa: E402

NOME = "ms_principal"
log = logging.getLogger(NOME)


class Status(StrEnum):
    rotulo: str

    def __new__(cls, valor: str, rotulo: str) -> "Status":
        membro = str.__new__(cls, valor)
        membro._value_ = valor
        membro.rotulo = rotulo
        return membro

    AGUARDANDO_ESTOQUE = "AGUARDANDO_ESTOQUE", "aguardando verificacao de estoque"
    ESTOQUE_RESERVADO = "ESTOQUE_RESERVADO", "estoque reservado, aguardando pagamento"
    PAGAMENTO_APROVADO = "PAGAMENTO_APROVADO", "pagamento aprovado, preparando envio"
    ENVIADO = "ENVIADO", "enviado"
    CANCELADO_SEM_ESTOQUE = "CANCELADO_SEM_ESTOQUE", "CANCELADO - sem estoque"
    CANCELADO_PAGAMENTO = "CANCELADO_PAGAMENTO", "CANCELADO - pagamento recusado"
    CANCELADO_USUARIO = "CANCELADO_USUARIO", "CANCELADO - excluido pelo usuario"


# Sufixo aleatorio para evitar colisao de IDsß.
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

    def registrar(self, pedido_id, cliente, itens, total):
        with self._lock:
            self._pedidos[pedido_id] = {
                "cliente": cliente,
                "itens": itens,
                "total": total,
                "status": Status.AGUARDANDO_ESTOQUE,
                "detalhe": "",
            }

    def atualizar(self, pedido_id, status, detalhe="") -> bool:
        with self._lock:
            pedido = self._pedidos.get(pedido_id)
            if pedido is None:
                return False
            pedido["status"] = status
            pedido["detalhe"] = detalhe
            return True

    def status_de(self, pedido_id) -> "Status | None":
        with self._lock:
            pedido = self._pedidos.get(pedido_id)
            return pedido["status"] if pedido else None

    def rotulo_de(self, pedido_id) -> str:
        status = self.status_de(pedido_id)
        return status.rotulo if status is not None else "?"

    def listar(self):
        with self._lock:
            return [(pid, dict(dados)) for pid, dados in sorted(self._pedidos.items())]


STORE = PedidoStore()


# Thread consumidora de eventos
class MsPrincipal(Microservice):
    name = NOME
    queue = "fila.principal"
    bindings = [
        (EX_ECOMMERCE, Evento.PEDIDO_ESTOQUE_OK),
        (EX_ECOMMERCE, Evento.ESTOQUE_INDISPONIVEL),
        (EX_ECOMMERCE, Evento.PAGAMENTO_APROVADO),
        (EX_ECOMMERCE, Evento.PAGAMENTO_RECUSADO),
        (EX_ECOMMERCE, Evento.PEDIDO_ENVIADO),
    ]

    @override
    def handle(self, event, payload):
        pedido_id = payload["pedidoId"]

        if STORE.status_de(pedido_id) is None:
            log.warning(f"evento {event} para pedido desconhecido {pedido_id} "
                        "-- ignorado")
            return

        cancelar_com = None

        match event:
            case Evento.PEDIDO_ESTOQUE_OK:
                STORE.atualizar(pedido_id, Status.ESTOQUE_RESERVADO)

            case Evento.ESTOQUE_INDISPONIVEL:
                motivo = payload.get("motivo", "sem estoque")
                STORE.atualizar(pedido_id, Status.CANCELADO_SEM_ESTOQUE, motivo)
                cancelar_com = motivo

            case Evento.PAGAMENTO_APROVADO:
                STORE.atualizar(pedido_id, Status.PAGAMENTO_APROVADO,
                                f"autorizacao {payload.get('autorizacao', '?')}")

            case Evento.PAGAMENTO_RECUSADO:
                motivo = payload.get("motivo", "pagamento recusado")
                STORE.atualizar(pedido_id, Status.CANCELADO_PAGAMENTO, motivo)
                cancelar_com = motivo

            case Evento.PEDIDO_ENVIADO:
                STORE.atualizar(pedido_id, Status.ENVIADO,
                                f"nota {payload.get('notaFiscal', '?')}, "
                                f"rastreio {payload.get('rastreio', '?')}")

        log.info(f"pedido {pedido_id} -> {STORE.rotulo_de(pedido_id)}")

        if cancelar_com is not None:
            self.publish(EX_ECOMMERCE, Evento.PEDIDO_EXCLUIDO, {
                "pedidoId": pedido_id,
                "motivo": cancelar_com,
                "origem": event,
            })


# Thread principal: menu
def ler(prompt: str):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def mostrar_produtos():
    print("\n--- Produtos ---")
    print(f"{'ID':<5} {'PRODUTO':<22} {'CATEGORIA':<10} {'PRECO':>12}")
    for pid, p in PRODUTOS.items():
        preco = f"R$ {p['preco']:.2f}"
        print(f"{pid:<5} {p['nome']:<22} {p['categoria']:<10} {preco:>12}")
    print("(o saldo em estoque vive apenas no ms_estoque e nao pode ser"
          "\n consultado daqui: nao ha chamadas diretas entre processos)")


def ler_itens():
    itens = {}
    print("\nInforme os itens (ENTER vazio para terminar).")
    while True:
        entrada = ler("  produto [qtd]: ")
        if not entrada:
            break
        partes = entrada.split()
        produto_id = partes[0].upper()
        if produto_id not in PRODUTOS:
            print(f"  produto inexistente: {produto_id}")
            continue
        try:
            qtd = int(partes[1]) if len(partes) > 1 else 1
        except ValueError:
            print("  quantidade invalida")
            continue
        if qtd < 1:
            print("  quantidade deve ser >= 1")
            continue
        itens[produto_id] = itens.get(produto_id, 0) + qtd
        print(f"  + {qtd}x {PRODUTOS[produto_id]['nome']}")
    return [{"produtoId": pid, "quantidade": qtd} for pid, qtd in itens.items()]


def realizar_pedido(publisher, cliente):
    mostrar_produtos()
    itens = ler_itens()
    if not itens:
        print("Pedido cancelado (nenhum item).")
        return

    total = round(sum(
        PRODUTOS[i["produtoId"]]["preco"] * i["quantidade"] for i in itens
    ), 2)
    pedido_id = STORE.novo_id()
    STORE.registrar(pedido_id, cliente, itens, total)

    print(f"\nPedido {pedido_id} criado -- total R$ {total:.2f}")
    publisher.publish(EX_ECOMMERCE, Evento.PEDIDO_CRIADO, {
        "pedidoId": pedido_id,
        "cliente": cliente,
        "itens": itens,
        "total": total,
    })


def consultar_pedidos():
    pedidos = STORE.listar()
    if not pedidos:
        print("\nNenhum pedido realizado ainda.")
        return
    print("\n--- Meus pedidos ---")
    for pedido_id, dados in pedidos:
        resumo = ", ".join(
            f"{i['quantidade']}x {i['produtoId']}" for i in dados["itens"]
        ) or "-"
        rotulo = dados["status"].rotulo
        print(f"{pedido_id}  R$ {dados['total']:8.2f}  {resumo:<14} {rotulo}")
        if dados["detalhe"]:
            print(f"                {dados['detalhe']}")


def excluir_pedido(publisher):
    consultar_pedidos()
    entrada = ler("\nID do pedido a excluir: ")
    if not entrada:
        print("Exclusao cancelada.")
        return
    pedido_id = entrada.upper()
    status = STORE.status_de(pedido_id)

    if status is None:
        print(f"Pedido nao encontrado: {pedido_id}")
        return
    if status.startswith("CANCELADO"):
        print(f"Pedido {pedido_id} ja esta cancelado.")
        return
    if status == Status.ENVIADO:
        print(f"Pedido {pedido_id} ja foi enviado e nao pode ser excluido.")
        return

    STORE.atualizar(pedido_id, Status.CANCELADO_USUARIO, "excluido pelo usuario")
    publisher.publish(EX_ECOMMERCE, Evento.PEDIDO_EXCLUIDO, {
        "pedidoId": pedido_id,
        "motivo": "excluido pelo usuario",
        "origem": "usuario",
    })
    print(f"Pedido {pedido_id} excluido.")


MENU = """
============ E-COMMERCE (ms_principal) ============
 1) Visualizar produtos
 2) Realizar pedido
 3) Consultar meus pedidos e status
 4) Excluir pedido
 0) Sair
 (ENTER redesenha o menu)
==================================================="""


def main():
    # Inicializa a thread do consumidor.
    servico = MsPrincipal()
    threading.Thread(target=servico.start, name="consumidor", daemon=True).start()

    # Inicializa a thread do Publisher
    publisher = Publisher(NOME)

    cliente = ler("\nSeu nome (ENTER para 'cliente1'): ") or "cliente1"

    acoes = {
        "1": mostrar_produtos,
        "2": lambda: realizar_pedido(publisher, cliente),
        "3": consultar_pedidos,
        "4": lambda: excluir_pedido(publisher),
    }

    while True:
        print(MENU)
        opcao = ler("opcao> ")
        if opcao is None or opcao == "0":
            break
        if opcao in acoes:
            acoes[opcao]()
        elif opcao:
            print("Opcao invalida.")

    publisher.close()
    print(f"\n[{NOME}] encerrado.")


if __name__ == "__main__":
    main()
