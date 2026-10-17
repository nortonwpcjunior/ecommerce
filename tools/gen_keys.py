import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.crypto import generate_keypair, private_to_pem, public_to_pem  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

MICROSSERVICOS = [
    "ms_principal",
    "ms_estoque",
    "ms_pagamento",
    "ms_entrega",
    "ms_promocoes",
]


def main() -> None:
    force = "--force" in sys.argv

    existentes = [
        s for s in MICROSSERVICOS
        if (ROOT / s / "keys" / f"{s}.key.pem").exists()
    ]
    if existentes and not force:
        print(f"Chaves privadas ja existem para: {', '.join(existentes)}")
        print("Use --force para gerar novamente (invalida as chaves atuais).")
        return

    print(f"Gerando {len(MICROSSERVICOS)} pares RSA-2048...\n")
    pares = {nome: generate_keypair() for nome in MICROSSERVICOS}

    for dono in MICROSSERVICOS:
        pasta = ROOT / dono / "keys"
        pasta.mkdir(parents=True, exist_ok=True)

        priv = pasta / f"{dono}.key.pem"
        priv.write_bytes(private_to_pem(pares[dono]))
        priv.chmod(0o600)

        for servico, chave in pares.items():
            (pasta / f"{servico}.pub.pem").write_bytes(public_to_pem(chave))

        print(f"  {dono:<14} -> 1 privada + {len(pares)} publicas")

    print("\nPronto. Chaves privadas com permissao 0600 e fora do git.")
    print("O mock_pagamento nao entra aqui: ele e um sistema EXTERNO, fala por")
    print("HTTP e nunca publica no broker, entao nao tem (nem precisa de) chave.")


if __name__ == "__main__":
    main()
