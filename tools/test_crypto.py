"""Testes de assinatura e verificacao, sem precisar do RabbitMQ.

Uso:  python -m tools.test_crypto
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.crypto import (  # noqa: E402
    AssinaturaInvalida, Signer, Verifier, load_private, load_public_keys, sha256_hex,
)
from common.envelope import Envelope  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TS = "2026-09-11T12:00:00+00:00"


def assinar(nome_servico, event, payload, timestamp=TS):
    signer = Signer(load_private(ROOT / nome_servico / "keys" / f"{nome_servico}.key.pem"))
    envelope = Envelope(producer=nome_servico, event=event, timestamp=timestamp,
                        payload=payload)
    envelope.signature = signer.sign(envelope.dados_assinados())
    return envelope


def passa(verifier, envelope):
    try:
        verifier.verificar(envelope)
        return True
    except AssinaturaInvalida:
        return False


def main():
    # O ms_estoque verifica usando as chaves publicas da sua propria pasta.
    verifier = Verifier(load_public_keys(ROOT / "ms_estoque" / "keys"))
    payload = {"pedidoId": "PED-0001", "itens": [{"produtoId": "P1", "quantidade": 2}]}

    legitimo = assinar("ms_principal", "pedido.criado", payload)
    print(f"assinados : {legitimo.dados_assinados().decode()}")
    print(f"sha256    : {sha256_hex(legitimo.dados_assinados())}")
    print(f"assinatura: {legitimo.signature[:44]}...\n")

    resultados = []

    def checar(rotulo, condicao):
        resultados.append(condicao)
        print(f"{rotulo:<52} {'OK' if condicao else 'FALHOU'}")

    checar("1. assinatura legitima e aceita", passa(verifier, legitimo))

    adulterado = assinar("ms_principal", "pedido.criado", payload)
    adulterado.payload = {"pedidoId": "PED-9999", "itens": []}
    checar("2. payload adulterado e rejeitado", not passa(verifier, adulterado))

    # O ataque que motivou assinar o envelope inteiro: reusar um payload
    # legitimo como se fosse outro evento.
    trocado = assinar("ms_estoque", "pedido.estoque_ok", payload)
    trocado.event = "pagamento.aprovado"
    checar("3. evento trocado (mesmo payload) e rejeitado", not passa(verifier, trocado))

    remarcado = assinar("ms_principal", "pedido.criado", payload)
    remarcado.timestamp = "2030-01-01T00:00:00+00:00"
    checar("4. timestamp alterado e rejeitado", not passa(verifier, remarcado))

    outro_produtor = assinar("ms_entrega", "pedido.criado", payload)
    outro_produtor.producer = "ms_principal"
    checar("5. assinado por outro servico e rejeitado", not passa(verifier, outro_produtor))

    desconhecido = assinar("ms_principal", "pedido.criado", payload)
    desconhecido.producer = "ms_inexistente"
    checar("6. produtor sem chave conhecida e rejeitado", not passa(verifier, desconhecido))

    sem_assinatura = assinar("ms_principal", "pedido.criado", payload)
    sem_assinatura.signature = ""
    checar("7. envelope sem assinatura e rejeitado", not passa(verifier, sem_assinatura))

    volta = Envelope.from_bytes(legitimo.to_bytes())
    checar("8. envelope sobrevive ao round-trip JSON", volta == legitimo)
    checar("9. e continua valido apos o round-trip", passa(verifier, volta))

    ok = all(resultados)
    print(f"\n{'todos os testes passaram' if ok else 'ALGUM TESTE FALHOU'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
