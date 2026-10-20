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

ORIGENS = ["http://localhost:5173", "http://127.0.0.1:5173"]
TIMEOUT = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=2.0)

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
    """Lifespan dos processos que consomem eventos E servem HTTP."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        servico = fabrica()
        app.state.servico = servico

        thread = threading.Thread(target=servico.start, name="consumidor")
        thread.start()

        if ao_subir is not None:
            ao_subir(app)
        try:
            yield
        finally:
            if ao_descer is not None:
                ao_descer(app)
            servico.parar()
            thread.join(timeout=5)
            cliente.close()

    return lifespan


def rodar(app: FastAPI, porta: int, nome: str) -> None:
    configurar_log(nome)
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=porta,
            workers=1,
            log_config=None,
            timeout_graceful_shutdown=5
        )
    except BrokerIndisponivel as exc:
        raise SystemExit(f"\n[ERRO] {exc}\n") from exc
