"""A API REST + SSE consumida pelo frontend.

Regra que atravessa o arquivo: rotas que PUBLICAM no broker sao `def`
(sincronas), porque o pika bloqueia e o Starlette as manda para o threadpool.
Uma rota `async def` publicando travaria o event loop e congelaria todos os
streams SSE de uma vez. A unica `async def` aqui e a do SSE.
"""

import asyncio
import logging
import os

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field

from common.catalogo import PRODUTOS
from common.eventos import Evento
from common.http import (
    cliente as http_cliente,
    com_consumidor,
    criar_app,
    registrar_health,
)
from common.service import EX_ECOMMERCE, BrokerOcupado, PublisherHTTP

from ms_principal.consumidor import NOME, MsPrincipal
from ms_principal.sse import BARRAMENTO, stream
from ms_principal.store import EXCLUIVEIS, STORE, Status

log = logging.getLogger(NOME)

ESTOQUE_URL = os.getenv("ESTOQUE_URL", "http://localhost:8002")

CABECALHOS_SSE = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # impede buffering se houver proxy na frente
}


class Item(BaseModel):
    produtoId: str
    quantidade: int = Field(ge=1)


class NovoPedido(BaseModel):
    clienteId: str = Field(min_length=1)
    itens: list[Item] = Field(min_length=1)


class Interesse(BaseModel):
    email: EmailStr
    categorias: list[str] = Field(default_factory=list)


def _ao_subir(app, servico):
    # O loop so existe aqui dentro; a thread do pika vai usa-lo para o fan-out.
    BARRAMENTO.ligar(asyncio.get_running_loop())
    app.state.publisher = PublisherHTTP(NOME)


def _ao_descer(app, servico):
    BARRAMENTO.encerrar_todos()
    app.state.publisher.close()


app = criar_app(
    "API Gateway (ms_principal)",
    lifespan=com_consumidor(MsPrincipal, _ao_subir, _ao_descer),
)
registrar_health(app)


def _publicar(routing_key: str, payload: dict) -> None:
    try:
        app.state.publisher.publish(EX_ECOMMERCE, routing_key, payload)
    except BrokerOcupado as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/produtos")
def listar_produtos():
    """Consulta o saldo real direto no MS Estoque, via REST."""
    try:
        resposta = http_cliente.get(f"{ESTOQUE_URL}/produtos")
        resposta.raise_for_status()
        return resposta.json()
    except httpx.HTTPError as exc:
        log.error(f"MS Estoque indisponivel: {exc}")
        raise HTTPException(503, "MS Estoque indisponivel") from exc


@app.post("/api/pedidos", status_code=202)
def criar_pedido(novo: NovoPedido):
    itens = [item.model_dump() for item in novo.itens]

    desconhecidos = [i["produtoId"] for i in itens if i["produtoId"] not in PRODUTOS]
    if desconhecidos:
        raise HTTPException(400, f"produto inexistente: {', '.join(desconhecidos)}")

    total = round(
        sum(PRODUTOS[i["produtoId"]]["preco"] * i["quantidade"] for i in itens), 2
    )
    pedido_id = STORE.novo_id()

    # REGISTRAR ANTES DE PUBLICAR. O pedido.estoque_ok volta em milissegundos e
    # o handle() descarta evento de pedidoId desconhecido -- publicar primeiro
    # perderia o primeiro evento da cadeia.
    retrato = STORE.registrar(pedido_id, novo.clienteId, itens, total)

    _publicar(Evento.PEDIDO_CRIADO, {
        "pedidoId": pedido_id,
        "cliente": novo.clienteId,
        "itens": itens,
        "total": total,
    })
    BARRAMENTO.publicar(novo.clienteId, Evento.PEDIDO_CRIADO, retrato)
    return retrato


@app.get("/api/pedidos")
def listar_pedidos(clienteId: str | None = None):
    return STORE.listar(clienteId)


@app.delete("/api/pedidos/{pedido_id}")
def excluir_pedido(pedido_id: str):
    pedido_id = pedido_id.upper()

    if STORE.obter(pedido_id) is None:
        raise HTTPException(404, f"pedido nao encontrado: {pedido_id}")

    # Transicao atomica: dois DELETE concorrentes nao podem publicar dois
    # pedido.excluido para o mesmo pedido.
    retrato = STORE.atualizar_se(
        pedido_id, EXCLUIVEIS, Status.CANCELADO_USUARIO, "excluido pelo usuario"
    )
    if retrato is None:
        atual = STORE.status_de(pedido_id)
        motivo = ("ja foi enviado" if atual == Status.ENVIADO else "ja esta cancelado")
        raise HTTPException(409, f"pedido {pedido_id} {motivo}")

    _publicar(Evento.PEDIDO_EXCLUIDO, {
        "pedidoId": pedido_id,
        "motivo": "excluido pelo usuario",
        "origem": "usuario",
    })
    BARRAMENTO.publicar(retrato["cliente"], Evento.PEDIDO_EXCLUIDO, retrato)
    return retrato


@app.post("/api/interesses", status_code=202)
def registrar_interesse(interesse: Interesse):
    categorias = _validar_categorias(interesse.categorias)
    if not categorias:
        raise HTTPException(400, "informe ao menos uma categoria")
    _publicar(Evento.INTERESSE_PROMOCAO, {
        "email": str(interesse.email),
        "categorias": categorias,
        "acao": "registrar",
    })
    return {"email": interesse.email, "categorias": categorias, "acao": "registrar"}


@app.delete("/api/interesses", status_code=202)
def cancelar_interesse(email: EmailStr):
    _publicar(Evento.INTERESSE_PROMOCAO, {
        "email": str(email),
        "categorias": [],
        "acao": "cancelar",
    })
    return {"email": email, "acao": "cancelar"}


@app.get("/api/categorias")
def listar_categorias():
    return sorted({p["categoria"] for p in PRODUTOS.values()})


@app.get("/api/eventos/{cliente_id}")
async def eventos(cliente_id: str):
    """Canal SSE: toda mudanca de estado dos pedidos deste cliente."""
    return StreamingResponse(
        stream(cliente_id),
        media_type="text/event-stream",
        headers=CABECALHOS_SSE,
    )


def _validar_categorias(categorias) -> list[str]:
    validas = {p["categoria"] for p in PRODUTOS.values()}
    return sorted({c.strip().upper() for c in categorias} & validas)
