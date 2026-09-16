"""Teste ponta a ponta sem interface: publica um pedido e acompanha o status.

Pre-requisitos: RabbitMQ no ar e os microsservicos Estoque, Pagamento e
Entrega rodando (./run_services.sh start).

Uso:  python -m tools.smoke_test [PRODUTO] [QTD]
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.catalogo import PRODUTOS  # noqa: E402
from common.eventos import Evento  # noqa: E402
from common.service import EX_ECOMMERCE, Publisher  # noqa: E402
from ms_principal.main import STORE, MsPrincipal, Status  # noqa: E402

TERMINAIS = frozenset({
    Status.ENVIADO, Status.CANCELADO_SEM_ESTOQUE, Status.CANCELADO_PAGAMENTO,
})


def main():
    produto = (sys.argv[1] if len(sys.argv) > 1 else "P1").upper()
    qtd = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    if produto not in PRODUTOS:
        sys.exit(f"produto inexistente: {produto}")

    servico = MsPrincipal()
    threading.Thread(target=servico.start, daemon=True).start()
    time.sleep(1.5)  # deixa o consumidor assinar a fila antes de publicar

    publisher = Publisher("ms_principal")
    itens = [{"produtoId": produto, "quantidade": qtd}]
    total = round(PRODUTOS[produto]["preco"] * qtd, 2)
    pedido_id = STORE.novo_id()
    STORE.registrar(pedido_id, "smoke-test", itens, total)

    print(f"\n>>> publicando pedido.criado: {pedido_id} "
          f"({qtd}x {produto}, R$ {total:.2f})\n")
    publisher.publish(EX_ECOMMERCE, Evento.PEDIDO_CRIADO, {
        "pedidoId": pedido_id, "cliente": "smoke-test",
        "itens": itens, "total": total,
    })

    limite = time.time() + 30
    while time.time() < limite:
        status = STORE.status_de(pedido_id)
        if status is not None and status in TERMINAIS:
            print(f"\n>>> status final de {pedido_id}: {status} "
                  f"({status.rotulo})")
            publisher.close()
            return 0
        time.sleep(0.3)

    print(f"\n>>> TIMEOUT: status parou em {STORE.status_de(pedido_id)}")
    print("    verifique se ms_estoque/ms_pagamento/ms_entrega estao rodando.")
    publisher.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
