"""Persistencia do estoque em SQLite.

O Trab1 guardava o saldo num dict em RAM: reiniciar o processo devolvia tudo
ao valor inicial. O Trab2 pede persistencia, e passa a existir um segundo
leitor -- as threads do servidor HTTP que atendem GET /produtos enquanto a
thread do pika escreve.
"""

import sqlite3
import threading
from enum import StrEnum
from pathlib import Path

from common.catalogo import PRODUTOS

ARQUIVO = Path(__file__).resolve().parent / "estoque.db"

ESTOQUE_INICIAL = {"P1": 10, "P2": 5, "P3": 0, "P4": 3, "P5": 7, "P6": 2}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS produtos (
    id         TEXT PRIMARY KEY,
    nome       TEXT    NOT NULL,
    categoria  TEXT    NOT NULL,
    preco      REAL    NOT NULL,
    quantidade INTEGER NOT NULL CHECK (quantidade >= 0)
);

CREATE TABLE IF NOT EXISTS reservas (
    pedido_id  TEXT    NOT NULL,
    produto_id TEXT    NOT NULL,
    quantidade INTEGER NOT NULL,
    PRIMARY KEY (pedido_id, produto_id)
);
"""


class Resultado(StrEnum):
    OK = "ok"
    DUPLICATA = "duplicata"
    SEM_ESTOQUE = "sem_estoque"


# Uma conexao POR THREAD. Compartilhar uma conexao entre threads
# compartilharia tambem o estado da transacao: uma leitura da thread HTTP
# enxergaria a transacao aberta pela thread do pika.
_local = threading.local()


def conexao() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(ARQUIVO, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL: um escritor (pika) e N leitores (HTTP) sem bloqueio mutuo.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
        # Idempotente, e roda em toda thread: assim um GET /produtos que chegue
        # antes de o consumidor terminar o setup nao encontra tabela faltando.
        conn.executescript(ESQUEMA)
        _local.conn = conn
    return conn


def inicializar() -> bool:
    """Semeia o catalogo no primeiro boot. Devolve True se semeou agora."""
    conn = conexao()
    if conn.execute("SELECT COUNT(*) FROM produtos").fetchone()[0]:
        return False
    conn.executemany(
        "INSERT INTO produtos (id, nome, categoria, preco, quantidade) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (pid, p["nome"], p["categoria"], p["preco"], ESTOQUE_INICIAL.get(pid, 0))
            for pid, p in PRODUTOS.items()
        ],
    )
    return True


def listar() -> list[dict]:
    linhas = conexao().execute(
        "SELECT id, nome, categoria, preco, quantidade FROM produtos ORDER BY id"
    ).fetchall()
    return [dict(linha) for linha in linhas]


def saldos() -> dict[str, int]:
    return {
        linha["id"]: linha["quantidade"]
        for linha in conexao().execute("SELECT id, quantidade FROM produtos")
    }


def reservar(pedido_id: str, itens: list[dict]) -> tuple[Resultado, list[str]]:
    """Reserva todos os itens ou nenhum, numa unica transacao."""
    conn = conexao()
    # IMMEDIATE pega o lock de escrita ja na abertura: o verifica-depois-baixa
    # nao pode ser interrompido no meio.
    conn.execute("BEGIN IMMEDIATE")
    try:
        ja_existe = conn.execute(
            "SELECT 1 FROM reservas WHERE pedido_id = ? LIMIT 1", (pedido_id,)
        ).fetchone()
        if ja_existe:
            conn.execute("ROLLBACK")
            return Resultado.DUPLICATA, []

        disponivel = saldos()
        faltas = [
            f"{i['produtoId']} (pedido {i['quantidade']}, "
            f"disponivel {disponivel.get(i['produtoId'], 0)})"
            for i in itens
            if disponivel.get(i["produtoId"], 0) < i["quantidade"]
        ]
        if faltas:
            conn.execute("ROLLBACK")
            return Resultado.SEM_ESTOQUE, faltas

        for item in itens:
            conn.execute(
                "UPDATE produtos SET quantidade = quantidade - ? "
                "WHERE id = ? AND quantidade >= ?",
                (item["quantidade"], item["produtoId"], item["quantidade"]),
            )
            conn.execute(
                "INSERT INTO reservas (pedido_id, produto_id, quantidade) "
                "VALUES (?, ?, ?)",
                (pedido_id, item["produtoId"], item["quantidade"]),
            )
        conn.execute("COMMIT")
        return Resultado.OK, []
    except Exception:
        conn.execute("ROLLBACK")
        raise


def devolver(pedido_id: str) -> list[dict]:
    """Devolve a reserva ao estoque. Lista vazia se nao havia reserva."""
    conn = conexao()
    conn.execute("BEGIN IMMEDIATE")
    try:
        itens = [
            {"produtoId": linha["produto_id"], "quantidade": linha["quantidade"]}
            for linha in conn.execute(
                "SELECT produto_id, quantidade FROM reservas WHERE pedido_id = ?",
                (pedido_id,),
            )
        ]
        if not itens:
            conn.execute("ROLLBACK")
            return []

        for item in itens:
            conn.execute(
                "UPDATE produtos SET quantidade = quantidade + ? WHERE id = ?",
                (item["quantidade"], item["produtoId"]),
            )
        conn.execute("DELETE FROM reservas WHERE pedido_id = ?", (pedido_id,))
        conn.execute("COMMIT")
        return itens
    except Exception:
        conn.execute("ROLLBACK")
        raise


def reservas_ativas() -> int:
    return conexao().execute(
        "SELECT COUNT(DISTINCT pedido_id) FROM reservas"
    ).fetchone()[0]
