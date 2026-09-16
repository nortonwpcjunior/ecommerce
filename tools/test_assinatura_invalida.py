"""Demonstra que eventos forjados sao descartados pelos microsservicos.

Publica quatro eventos na exchange eCommerce e observa os consumidores:
  1. legitimo                          -> PROCESSADO
  2. payload adulterado                -> DESCARTADO
  3. assinado com a chave de OUTRO     -> DESCARTADO
  4. evento trocado (payload legitimo
     de pedido.estoque_ok republicado
     como pagamento.aprovado)          -> DESCARTADO

O caso 4 e o que exige assinar producer+event+timestamp+payload: assinando
apenas o payload, o ms_entrega emitiria nota fiscal de um pedido nunca pago.

Pre-requisito: ms_estoque e ms_entrega rodando.
Uso:  python -m tools.test_assinatura_invalida
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pika  # noqa: E402

from common.crypto import Signer, load_private  # noqa: E402
from common.envelope import Envelope  # noqa: E402
from common.service import EX_ECOMMERCE, connect, declare_topology, keys_dir  # noqa: E402


def signer(nome):
    return Signer(load_private(keys_dir(nome) / f"{nome}.key.pem"))


def assinado(nome, event, payload):
    env = Envelope(
        producer=nome, event=event,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        payload=payload,
    )
    env.signature = signer(nome).sign(env.dados_assinados())
    return env


def main():
    conexao, canal = connect()
    declare_topology(canal)

    def enviar(rotulo, envelope, routing_key=None):
        routing_key = routing_key or envelope.event
        print(f"\n[{rotulo}]")
        print(f"   routing key: {routing_key} | "
              f"pedido: {envelope.payload.get('pedidoId')}")
        canal.basic_publish(EX_ECOMMERCE, routing_key, envelope.to_bytes(),
                            properties=pika.BasicProperties(delivery_mode=2))
        time.sleep(2)

    item = {"produtoId": "P5", "quantidade": 1}

    # 1. legitimo
    enviar("1/4 legitimo -> deve ser PROCESSADO",
           assinado("ms_principal", "pedido.criado",
                    {"pedidoId": "TESTE-VALIDO", "cliente": "teste",
                     "itens": [item], "total": 1250.0}))

    # 2. payload trocado depois de assinar
    env = assinado("ms_principal", "pedido.criado",
                   {"pedidoId": "TESTE-ADULTERADO", "cliente": "teste",
                    "itens": [item], "total": 1250.0})
    env.payload["itens"] = [{"produtoId": "P5", "quantidade": 99}]
    enviar("2/4 payload adulterado -> deve ser DESCARTADO", env)

    # 3. assinado pelo ms_entrega, alegando ser o ms_principal
    env = assinado("ms_entrega", "pedido.criado",
                   {"pedidoId": "TESTE-CHAVE-ERRADA", "cliente": "teste",
                    "itens": [item], "total": 1250.0})
    env.producer = "ms_principal"
    enviar("3/4 chave de outro servico -> deve ser DESCARTADO", env)

    # 4. substituicao de evento: payload assinado para pedido.estoque_ok
    #    republicado como pagamento.aprovado
    env = assinado("ms_estoque", "pedido.estoque_ok",
                   {"pedidoId": "TESTE-SUBSTITUICAO", "itens": [item], "total": 1250.0})
    env.event = "pagamento.aprovado"
    enviar("4/4 evento substituido -> deve ser DESCARTADO", env,
           routing_key="pagamento.aprovado")

    conexao.close()
    print("\nConfira os logs: apenas TESTE-VALIDO deve ter sido reservado,")
    print("e nenhuma nota fiscal deve ter sido emitida.")


if __name__ == "__main__":
    main()
