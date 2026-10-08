"""Camada HTTP compartilhada: app FastAPI, ciclo de vida e cliente httpx.

O Trab2 poe um servidor HTTP em quatro processos. O que muda em relacao ao
Trab1 e que agora cada processo tem DUAS threads: a do consumidor pika e a do
uvicorn. Este modulo concentra o que as duas precisam combinar.
"""

import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.service import BrokerIndisponivel, Microservice, configurar_log

log = logging.getLogger(__name__)

# A origem do frontend em desenvolvimento (vite).
ORIGENS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Timeout curto de proposito: estas chamadas acontecem dentro do handle() do
# pika, e um httpx sem prazo seguraria a thread do consumidor por minutos.
TIMEOUT = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=2.0)

# httpx.Client e thread-safe para requisicoes concorrentes: um por processo,
# compartilhado entre a thread do pika e as threads HTTP.
cliente = httpx.Client(timeout=TIMEOUT)


def criar_app(titulo: str, lifespan=None) -> FastAPI:
    app = FastAPI(title=titulo, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ORIGENS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def com_consumidor(fabrica: Callable[[], Microservice], ao_subir=None, ao_descer=None):
    """Monta o lifespan dos processos que consomem eventos E servem HTTP.

    A ordem importa: a fabrica roda AQUI, na thread do lifespan, porque o
    __init__ do Microservice ja conecta no broker -- assim o broker fora
    aborta o startup do uvicorn com mensagem clara, em vez de matar uma
    thread em silencio.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        servico = fabrica()
        app.state.servico = servico

        # non-daemon: o teardown faz join, nao queremos matar no meio de um ack.
        thread = threading.Thread(target=servico.start, name="consumidor")
        thread.start()
        app.state.consumidor = thread

        if ao_subir is not None:
            ao_subir(app, servico)
        try:
            yield
        finally:
            if ao_descer is not None:
                ao_descer(app, servico)
            servico.parar()
            thread.join(timeout=5)
            cliente.close()

    return lifespan


def registrar_health(app: FastAPI) -> None:
    """/health expoe se a thread do consumidor continua viva.

    Sem isso, o consumidor pode morrer e o processo seguir respondendo 200 em
    todas as rotas enquanto nenhum evento e processado -- uma falha que nao
    aparece em lugar nenhum.
    """

    @app.get("/health")
    def health():
        thread = getattr(app.state, "consumidor", None)
        return {
            "ok": thread is not None and thread.is_alive(),
            "consumidor_vivo": thread is not None and thread.is_alive(),
        }


def rodar(app: FastAPI, porta: int, nome: str) -> None:
    """Sobe o uvicorn em UM processo, sem reload.

    Com --workers ou --reload cada processo abriria o seu proprio consumidor
    na MESMA fila: o RabbitMQ distribuiria os eventos em round-robin entre
    eles, e o cliente conectado ao worker 2 perderia o evento consumido pelo
    worker 1. O SSE quebraria de forma intermitente.
    """
    configurar_log(nome)
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=porta,
            workers=1,
            log_config=None,  # o configurar_log acima ja cuidou do logging
            timeout_graceful_shutdown=5,
        )
    except BrokerIndisponivel as exc:
        raise SystemExit(f"\n[ERRO] {exc}\n") from exc
