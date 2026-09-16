"""Gera os pares de chaves RSA-2048 e distribui as chaves publicas.

Cada microsservico recebe, na sua pasta keys/:
  - <nome>.key.pem       sua chave PRIVADA (nunca versionada, ver .gitignore)
  - <outro>.pub.pem      a chave PUBLICA de todos os microsservicos

Os consumidores de promocoes (C1 e C2) nao publicam nada, portanto recebem
apenas a chave publica do ms_promocoes.

Uso:  python -m tools.gen_keys [--force]
"""

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
CONSUMIDORES = ["consumidor_c1", "consumidor_c2"]


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

    for consumidor in CONSUMIDORES:
        pasta = ROOT / consumidor / "keys"
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "ms_promocoes.pub.pem").write_bytes(public_to_pem(pares["ms_promocoes"]))
        print(f"  {consumidor:<14} -> ms_promocoes.pub.pem")

    print("\nPronto. Chaves privadas com permissao 0600 e fora do git.")


if __name__ == "__main__":
    main()
