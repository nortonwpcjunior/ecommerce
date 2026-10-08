"""Registro de quem quer receber promocoes, por categoria.

Arquivo JSON simples: so a thread do consumidor escreve, e o volume e de
dezenas de linhas. Fica fora do git (tem e-mail de gente dentro).
"""

import json
import logging
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "interesses.json"

log = logging.getLogger(__name__)

# email -> [categorias]
_registro: dict[str, list[str]] = {}


def carregar() -> None:
    global _registro
    if not ARQUIVO.exists():
        _registro = {}
        return
    try:
        _registro = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning(f"nao foi possivel ler {ARQUIVO.name} ({exc}); comecando vazio")
        _registro = {}


def _gravar() -> None:
    ARQUIVO.write_text(
        json.dumps(_registro, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def registrar(email: str, categorias: list[str]) -> list[str]:
    categorias = sorted({c.strip().upper() for c in categorias if c.strip()})
    _registro[email] = categorias
    _gravar()
    return categorias


def cancelar(email: str) -> bool:
    if _registro.pop(email, None) is None:
        return False
    _gravar()
    return True


def interessados(categoria: str) -> list[str]:
    return sorted(
        email for email, cats in _registro.items() if categoria.upper() in cats
    )


def total() -> int:
    return len(_registro)
