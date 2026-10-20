import httpx
import logging
import os

log = logging.getLogger(__name__)

API_URL = "https://api.resend.com/emails"

REMETENTE = os.getenv("RESEND_FROM", "Promocoes <onboarding@resend.dev>")


def chave() -> str:
    return os.getenv("RESEND_API_KEY", "").strip()


def modo() -> str:
    return "Resend" if chave() else "DRY-RUN (defina RESEND_API_KEY para enviar)"


def enviar(cliente: httpx.Client, destinos: list[str], assunto: str, html: str) -> bool:
    if not destinos:
        return False

    api_key = chave()
    if not api_key:
        log.info(f"[DRY-RUN] e-mail para {', '.join(destinos)}: {assunto}")
        return False

    try:
        resposta = cliente.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": REMETENTE,
                "to": destinos,
                "subject": assunto,
                "html": html,
            },
        )
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        log.error(f"falha ao enviar e-mail via Resend: {exc}")
        return False

    log.info(f"e-mail enviado para {', '.join(destinos)}: {assunto}")
    return True


def montar_html(promocao: dict) -> str:
    return f"""\
<div style="font-family:system-ui,sans-serif;max-width:480px">
  <h2 style="margin-bottom:.2rem">{promocao['nome']}</h2>
  <p style="color:#64748b;margin-top:0">Categoria {promocao['categoria']}</p>
  <p style="font-size:1.6rem;margin:.6rem 0">
    <strong>{promocao['descontoPct']}% OFF</strong>
  </p>
  <p>
    <s style="color:#94a3b8">R$ {promocao['precoOriginal']:.2f}</s>
    &nbsp;&rarr;&nbsp;
    <strong style="color:#16a34a">R$ {promocao['precoPromocional']:.2f}</strong>
  </p>
  <p style="color:#94a3b8;font-size:.85rem">
    Voce recebeu este e-mail porque pediu ofertas da categoria
    {promocao['categoria']}.
  </p>
</div>"""
