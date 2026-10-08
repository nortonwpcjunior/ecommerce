"""Mock de Pagamento: o provedor de pagamentos externo.

Nao importa nada de common/, nao tem chave privada e nao fala com o RabbitMQ.
Isso e proposital: ele representa um sistema de TERCEIROS, que so conhece o
MS Pagamento por HTTP. O fluxo tem tres passos:

    1. MS Pagamento  --POST /cobrancas-->  aqui          (cria a cobranca)
    2. usuario       --GET  /checkout/X->  aqui          (abre a aba e decide)
    3. aqui          --POST webhookUrl-->  MS Pagamento  (devolve a decisao)
"""

import logging
import os
import secrets
import sys
import threading
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

NOME = "mock_pagamento"
PORTA = int(os.getenv("MOCK_PORTA", "8004"))

# Segredo compartilhado com o MS Pagamento. Sem ele, qualquer um que alcance a
# porta do webhook aprova qualquer pedido -- e o evento resultante sairia
# ASSINADO pelo ms_pagamento, fazendo a cadeia de assinatura do trabalho
# atestar um dado forjado.
SEGREDO = os.getenv("MOCK_WEBHOOK_SECRET", "segredo-de-demonstracao")

log = logging.getLogger(NOME)

app = FastAPI(title="Mock de Pagamento")

_lock = threading.Lock()
_cobrancas: dict[str, dict] = {}


class Cobranca(BaseModel):
    pedidoId: str
    valor: float = 0.0
    webhookUrl: str


@app.post("/cobrancas")
def criar_cobranca(cobranca: Cobranca):
    """Passo 1: o MS Pagamento pede a cobranca e recebe a URL de checkout."""
    cobranca_id = secrets.token_hex(8)
    with _lock:
        _cobrancas[cobranca_id] = {
            "pedidoId": cobranca.pedidoId,
            "valor": cobranca.valor,
            "webhookUrl": cobranca.webhookUrl,
            "decisao": None,
        }
    log.info(f"cobranca {cobranca_id} criada para {cobranca.pedidoId} "
             f"(R$ {cobranca.valor:.2f})")
    return {
        "cobrancaId": cobranca_id,
        "checkoutUrl": f"http://localhost:{PORTA}/checkout/{cobranca_id}",
    }


PAGINA = """<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pagamento {pedido}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0;
         min-height: 100vh; display: grid; place-items: center;
         background: #f1f5f9; color: #0f172a; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0f172a; color: #e2e8f0; }}
    .cartao {{ background: #1e293b !important; }}
  }}
  .cartao {{ background: #fff; padding: 2.5rem; border-radius: 16px;
            box-shadow: 0 10px 30px rgb(0 0 0 / .12); max-width: 420px;
            width: calc(100% - 2rem); text-align: center; }}
  h1 {{ font-size: 1.1rem; letter-spacing: .08em; text-transform: uppercase;
       opacity: .6; margin: 0 0 .5rem; }}
  .valor {{ font-size: 2.4rem; font-weight: 700; margin: .25rem 0 .25rem; }}
  .pedido {{ opacity: .65; font-size: .9rem; margin-bottom: 2rem; }}
  button {{ width: 100%; padding: .9rem; font-size: 1rem; font-weight: 600;
           border: 0; border-radius: 10px; cursor: pointer; margin-top: .6rem;
           color: #fff; }}
  .ok {{ background: #16a34a; }}
  .nao {{ background: #dc2626; }}
  button:hover {{ filter: brightness(1.08); }}
  #aviso {{ margin-top: 1.4rem; font-size: .92rem; min-height: 1.4em; }}
</style></head>
<body><div class="cartao">
  <h1>Mock de Pagamento</h1>
  <div class="valor">R$ {valor}</div>
  <div class="pedido">Pedido {pedido}</div>
  <button class="ok"  onclick="decidir('APROVADO')">Pagamento Aprovado</button>
  <button class="nao" onclick="decidir('RECUSADO')">Pagamento Recusado</button>
  <p id="aviso"></p>
</div>
<script>
async function decidir(status) {{
  for (const b of document.querySelectorAll('button')) b.disabled = true;
  const aviso = document.getElementById('aviso');
  aviso.textContent = 'Enviando...';
  try {{
    const r = await fetch('/checkout/{id}/decidir?status=' + status, {{method: 'POST'}});
    const d = await r.json();
    aviso.textContent = d.mensagem;
  }} catch (e) {{
    aviso.textContent = 'Falha ao avisar a loja: ' + e;
  }}
}}
</script></body></html>
"""


@app.get("/checkout/{cobranca_id}", response_class=HTMLResponse)
def checkout(cobranca_id: str):
    """Passo 2: a pagina que o usuario abre em nova aba."""
    with _lock:
        cobranca = _cobrancas.get(cobranca_id)
    if cobranca is None:
        raise HTTPException(404, "cobranca nao encontrada")
    return PAGINA.format(
        id=cobranca_id,
        pedido=cobranca["pedidoId"],
        valor=f"{cobranca['valor']:.2f}",
    )


@app.post("/checkout/{cobranca_id}/decidir")
def decidir(cobranca_id: str, status: str):
    """Passo 3: dispara o webhook de volta para o MS Pagamento."""
    status = status.upper()
    if status not in ("APROVADO", "RECUSADO"):
        raise HTTPException(400, "status deve ser APROVADO ou RECUSADO")

    with _lock:
        cobranca = _cobrancas.get(cobranca_id)
        if cobranca is None:
            raise HTTPException(404, "cobranca nao encontrada")
        if cobranca["decisao"] is not None:
            return {"mensagem": f"Esta cobranca ja foi {cobranca['decisao']}."}
        cobranca["decisao"] = status

    corpo = {
        "cobrancaId": cobranca_id,
        "pedidoId": cobranca["pedidoId"],
        "status": status,
        "valor": cobranca["valor"],
    }
    log.info(f"usuario escolheu {status} para {cobranca['pedidoId']}; "
             f"chamando webhook {cobranca['webhookUrl']}")
    try:
        resposta = httpx.post(
            cobranca["webhookUrl"],
            json=corpo,
            headers={"X-Webhook-Secret": SEGREDO},
            timeout=5.0,
        )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        with _lock:
            cobranca["decisao"] = None  # deixa tentar de novo
        log.error(f"webhook falhou: {exc}")
        raise HTTPException(502, f"nao foi possivel avisar a loja: {exc}") from exc

    return {"mensagem": f"Pagamento {status.lower()}. Pode fechar esta aba."}


@app.get("/health")
def health():
    return {"ok": True, "cobrancas": len(_cobrancas)}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common.service import configurar_log  # noqa: E402

    configurar_log(NOME)
    uvicorn.run(app, host="0.0.0.0", port=PORTA, log_config=None)
