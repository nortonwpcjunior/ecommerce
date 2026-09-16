#!/usr/bin/env python3
"""Microsservico Principal.

    Consome:  pedido.estoque_ok, estoque.indisponivel, pagamento.aprovado,
              pagamento.recusado, pedido.enviado
    Publica:  pedido.criado, pedido.excluido

Unico microsservico com DUAS threads:
  - thread de fundo: consumidor, atualiza o status dos pedidos;
  - thread principal: menu de terminal, cria e exclui pedidos.

Duas regras que nao podem ser violadas aqui:
  1. cada thread tem a SUA conexao com o broker (pika nao e thread-safe);
  2. todo acesso ao STORE passa pelo lock, porque as duas threads o tocam --
     e publicar SEMPRE fora do lock, para nao prender a thread do menu
     durante a ida ao broker.
"""

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
    """Status interno do pedido, com o rotulo exibido ao usuario.

    O valor do membro e o nome interno -- e o que vai para o STORE e o que o
    `startswith("CANCELADO")` do menu testa. O rotulo fica no mesmo lugar, em
    vez de num dicionario paralelo que pode sair de sincronia.
    """

    # Anotacao sem valor: o enum nao a trata como membro, e o type checker
    # passa a conhecer o atributo que o __new__ preenche.
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


# Sufixo aleatorio por execucao do processo. Sem ele, reiniciar o ms_principal
# reinicia o contador em 1 e os novos pedidos colidem com os IDs que o
# ms_estoque e o ms_pagamento ainda mantem em memoria.
SESSAO = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))


class PedidoStore:
    """Estado dos pedidos, compartilhado entre a thread do menu e a do consumidor."""

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
        """Atualiza um pedido conhecido. Devolve False se o ID for desconhecido.

        Nao cria pedido a partir de evento recebido: o ms_principal e a unica
        origem de pedidos. Um evento para ID desconhecido significa broker com
        mensagem antiga, outro Principal no ar ou evento injetado -- deve ser
        registrado e ignorado, nunca virar um pedido na lista do usuario.
        """
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
        """Rotulo do status, ou '?' se o pedido nao existir."""
        status = self.status_de(pedido_id)
        return status.rotulo if status is not None else "?"

    def listar(self):
        with self._lock:
            return [(pid, dict(dados)) for pid, dados in sorted(self._pedidos.items())]


STORE = PedidoStore()


# --------------------------------------------------------------------------
# Thread de fundo: consumidor de eventos
# --------------------------------------------------------------------------

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

        # `case Evento.X` e padrao de VALOR porque o nome e pontilhado. Um
        # `case X` simples seria padrao de CAPTURA e casaria com tudo.
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

        # Produto indisponivel ou pagamento recusado: o Principal publica
        # pedido.excluido para que o Estoque devolva a reserva.
        # Fora de qualquer lock.
        if cancelar_com is not None:
            self.publish(EX_ECOMMERCE, Evento.PEDIDO_EXCLUIDO, {
                "pedidoId": pedido_id,
                "motivo": cancelar_com,
                "origem": event,
            })


# --------------------------------------------------------------------------
# Thread principal: menu de terminal (print, nao log -- e interface)
# --------------------------------------------------------------------------

def ler(prompt: str):
    """input() que devolve None em Ctrl+D / Ctrl+C, em vez de estourar.

    Sem isso, um Ctrl+D dentro de um submenu derruba o processo com traceback.
    """
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
    """Le pares produto/quantidade ate uma linha vazia."""
    itens = {}
    print("\nInforme os itens (ENTER vazio para terminar).")
    while True:
        entrada = ler("  produto [qtd]: ")
        if not entrada:      # linha vazia, Ctrl+D ou Ctrl+C: encerra a lista
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
    # Registra ANTES de publicar: a resposta pode voltar antes do print.
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
    # Thread do consumidor: conexao propria, criada dentro de MsPrincipal.
    servico = MsPrincipal()
    threading.Thread(target=servico.start, name="consumidor", daemon=True).start()

    # Thread do menu: Publisher com conexao propria e heartbeat desligado,
    # porque fica ociosa enquanto o usuario le o menu.
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
