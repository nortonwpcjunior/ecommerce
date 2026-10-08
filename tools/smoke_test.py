"""Teste ponta a ponta sem navegador: cria um pedido e paga pelo Mock.

Diferente do Trab1, o pagamento nao e mais sorteado: alguem tem de clicar no
checkout. Aqui o clique e simulado por HTTP, no mesmo endpoint que a pagina do
Mock usa -- entao o caminho exercitado e exatamente o da demonstracao.

Pre-requisitos: broker no ar e ./run_services.sh start.

Uso:  python -m tools.smoke_test [PRODUTO] [QTD] [aprovado|recusado]
"""

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.catalogo import PRODUTOS  # noqa: E402

GATEWAY = "http://localhost:8000"
MOCK = "http://localhost:8004"
CLIENTE = "smoke-test"

TERMINAIS = {"ENVIADO", "CANCELADO_SEM_ESTOQUE", "CANCELADO_PAGAMENTO"}


def esperar(cliente: httpx.Client, pedido_id: str, condicao, limite=30.0):
    fim = time.time() + limite
    while time.time() < fim:
        pedidos = cliente.get(f"{GATEWAY}/api/pedidos",
                              params={"clienteId": CLIENTE}).json()
        for pedido in pedidos:
            if pedido["pedidoId"] == pedido_id and condicao(pedido):
                return pedido
        time.sleep(0.3)
    return None


def main() -> int:
    produto = (sys.argv[1] if len(sys.argv) > 1 else "P1").upper()
    qtd = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    decisao = (sys.argv[3] if len(sys.argv) > 3 else "aprovado").upper()

    if produto not in PRODUTOS:
        sys.exit(f"produto inexistente: {produto}")

    with httpx.Client(timeout=10.0) as cliente:
        try:
            cliente.get(f"{GATEWAY}/health")
        except httpx.HTTPError:
            sys.exit("API Gateway fora do ar. Rode ./run_services.sh start")

        print(f">>> POST /api/pedidos ({qtd}x {produto})")
        pedido = cliente.post(f"{GATEWAY}/api/pedidos", json={
            "clienteId": CLIENTE,
            "itens": [{"produtoId": produto, "quantidade": qtd}],
        }).json()
        pedido_id = pedido["pedidoId"]
        print(f"    {pedido_id} -- R$ {pedido['total']:.2f}")

        # Ou chega a cobranca, ou o pedido ja morreu por falta de estoque.
        atual = esperar(cliente, pedido_id,
                        lambda p: p["checkoutUrl"] or p["status"] in TERMINAIS)
        if atual is None:
            print(">>> TIMEOUT esperando o estoque responder")
            return 1

        if atual["status"] in TERMINAIS:
            print(f">>> status final: {atual['status']} ({atual['rotulo']})")
            return 0

        cobranca_id = atual["checkoutUrl"].rsplit("/", 1)[-1]
        print(f">>> checkout aberto: {atual['checkoutUrl']}")
        print(f">>> simulando clique '{decisao}' no Mock")
        cliente.post(f"{MOCK}/checkout/{cobranca_id}/decidir",
                     params={"status": decisao})

        final = esperar(cliente, pedido_id, lambda p: p["status"] in TERMINAIS)
        if final is None:
            print(">>> TIMEOUT esperando o status final")
            return 1

        print(f">>> status final de {pedido_id}: {final['status']} "
              f"({final['rotulo']})")
        if final["detalhe"]:
            print(f"    {final['detalhe']}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
