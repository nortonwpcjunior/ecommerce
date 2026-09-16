"""Criptografia de chave assimetrica: hash, assinatura e verificacao.

RSA-2048 + SHA-256, padding PKCS#1 v1.5.

O hash e calculado explicitamente e a assinatura usa utils.Prehashed, para que
os tres passos exigidos pelo enunciado aparecam separados no codigo:
  1. gerar o hash do conteudo do evento;
  2. assinar com a chave privada do produtor;
  3. incluir a assinatura no campo Signature do envelope.
"""

import base64
import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils

TAMANHO_CHAVE = 2048


class AssinaturaInvalida(Exception):
    """Envelope reprovado na verificacao. O evento deve ser descartado."""


# --------------------------------------------------------------------------
# Hash
# --------------------------------------------------------------------------

def sha256_digest(dados: bytes) -> bytes:
    return hashlib.sha256(dados).digest()


def sha256_hex(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


# --------------------------------------------------------------------------
# Assinatura (lado do produtor)
# --------------------------------------------------------------------------

class Signer:
    """Assina com a chave PRIVADA do microsservico produtor."""

    def __init__(self, private_key):
        self._key = private_key

    def sign(self, dados: bytes) -> str:
        digest = sha256_digest(dados)                      # passo 1
        assinatura = self._key.sign(                       # passo 2
            digest, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256())
        )
        return base64.b64encode(assinatura).decode("ascii")


# --------------------------------------------------------------------------
# Validacao (lado do consumidor)
# --------------------------------------------------------------------------

class Verifier:
    """Verifica com a chave PUBLICA do produtor declarado no envelope."""

    def __init__(self, public_keys: dict):
        self._keys = public_keys

    def produtores_conhecidos(self):
        return sorted(self._keys)

    def verificar(self, envelope) -> None:
        """Valida o envelope. Levanta AssinaturaInvalida se reprovar.

        Cobre producer, event, timestamp e payload: trocar qualquer um deles
        invalida a assinatura.
        """
        # 1. obter a chave publica do microsservico produtor
        chave = self._keys.get(envelope.producer)
        if chave is None:
            raise AssinaturaInvalida(
                "chave publica de '%s' nao encontrada nesta pasta keys/"
                % envelope.producer
            )

        if not envelope.signature:
            raise AssinaturaInvalida("envelope sem assinatura")

        digest = sha256_digest(envelope.dados_assinados())

        # 2. e 3. verificar a assinatura -> autenticidade e integridade
        try:
            chave.verify(
                base64.b64decode(envelope.signature),
                digest,
                padding.PKCS1v15(),
                utils.Prehashed(hashes.SHA256()),
            )
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise AssinaturaInvalida(
                "assinatura de '%s' nao confere" % envelope.producer
            ) from exc
        # 4. so apos este ponto o evento pode ser processado


# --------------------------------------------------------------------------
# Chaves: geracao, gravacao e carregamento
# --------------------------------------------------------------------------

def generate_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=TAMANHO_CHAVE)


def private_to_pem(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def public_to_pem(key) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def load_private(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            "%s nao existe. Rode primeiro: python -m tools.gen_keys" % path
        )
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def load_public(path: Path):
    return serialization.load_pem_public_key(path.read_bytes())


def load_public_keys(keys_dir: Path) -> dict:
    """Carrega as chaves publicas de uma pasta keys/.

    O nome do arquivo define o produtor: ms_estoque.pub.pem -> "ms_estoque".
    """
    if not keys_dir.is_dir():
        raise FileNotFoundError(
            "%s nao existe. Rode primeiro: python -m tools.gen_keys" % keys_dir
        )
    chaves = {
        path.name[: -len(".pub.pem")]: load_public(path)
        for path in sorted(keys_dir.glob("*.pub.pem"))
    }
    if not chaves:
        raise FileNotFoundError("nenhuma chave publica encontrada em %s" % keys_dir)
    return chaves
