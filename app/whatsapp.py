import os
from pathlib import Path

import httpx

from app.domain import phone_digits

GRAPH_VERSION = "v22.0"
DEFAULT_PHONE_NUMBER_ID = "790586727468909"


def load_env_file() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def clean_phone(value: str) -> str:
    phone = str(value or "").strip().replace(" ", "")
    if phone.startswith("+"):
        after_plus = phone[1:].replace("-", "")
        if after_plus.isdigit():
            return phone
    digits = phone_digits(phone)
    if digits.startswith("56"):
        return digits
    if len(digits) >= 8:
        return f"56{digits}"
    return digits


def clean_whatsapp_text(value: str, *, keep_lines: bool = False) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if keep_lines:
        text = text.replace("\n", "\u2028")
        parts = []
        for line in text.split("\u2028"):
            collapsed = line
            while "  " in collapsed:
                collapsed = collapsed.replace("  ", " ")
            parts.append(collapsed.strip(" "))
        return "\u2028".join(parts)[:1024] or "-"
    text = text.replace("\n", " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()[:1024] or "-"


def format_contract_partidas(lines: list[tuple[str, int | None, int]]) -> str:
    rows = [f"- {name}: {quantity}." for name, _previous, quantity in lines]
    if not rows:
        return "Sin partidas con cantidad"
    rows[-1] = rows[-1][:-1]
    return "\u2028" + "\u2028".join(rows)


def phone_number_id() -> str:
    return os.environ.get("WHATSAPP_PHONE_NUMBER_ID", DEFAULT_PHONE_NUMBER_ID).strip() or DEFAULT_PHONE_NUMBER_ID


def configured() -> bool:
    return bool(os.environ.get("META_TOKEN", "").strip())


def _post(payload: dict) -> dict:
    token = os.environ.get("META_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "WhatsApp no está configurado."}
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id()}/messages"
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except httpx.HTTPError:
        return {"ok": False, "error": "No se pudo conectar con WhatsApp."}
    body = response.json() if response.content else {}
    if response.status_code != 200:
        error = body.get("error", {})
        detail = (error.get("error_data") or {}).get("details")
        message = error.get("message") or "No se pudo enviar el WhatsApp."
        if detail:
            message = f"{message} {detail}"
        return {"ok": False, "error": message}
    return {"ok": True}


def send_text(phone: str, text: str) -> dict:
    return _post({
        "messaging_product": "whatsapp",
        "to": clean_phone(phone),
        "type": "text",
        "text": {"body": text[:4096]},
    })


CONTRACT_TEMPLATE = "scope_of_work"


def upload_pdf(filename: str, content: bytes) -> dict:
    token = os.environ.get("META_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "WhatsApp no está configurado."}
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id()}/media"
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        data={"messaging_product": "whatsapp", "type": "application/pdf"},
        files={"file": (filename, content, "application/pdf")},
        timeout=30,
    )
    body = response.json() if response.content else {}
    media_id = body.get("id")
    if response.status_code != 200 or not media_id:
        error = body.get("error", {})
        return {"ok": False, "error": error.get("message") or "No se pudo adjuntar el PDF."}
    return {"ok": True, "id": media_id}


def send_template(
    phone: str,
    name: str,
    parameters: list[str],
    button_payloads: list[str] | None = None,
    *,
    document: tuple[str, bytes] | None = None,
    line_parameters: set[int] | None = None,
) -> dict:
    components: list[dict] = []
    if document is not None:
        filename, content = document
        uploaded = upload_pdf(filename, content)
        if not uploaded.get("ok"):
            uploaded["template"] = name
            return uploaded
        components.append({
            "type": "header",
            "parameters": [{
                "type": "document",
                "document": {"id": uploaded["id"], "filename": filename},
            }],
        })
    kept_lines = line_parameters or set()
    components.append({
        "type": "body",
        "parameters": [
            {"type": "text", "text": clean_whatsapp_text(item, keep_lines=index in kept_lines)}
            for index, item in enumerate(parameters)
        ],
    })
    for index, payload in enumerate(button_payloads or []):
        components.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(index),
            "parameters": [{"type": "payload", "payload": payload[:256]}],
        })
    result = _post({
        "messaging_product": "whatsapp",
        "to": clean_phone(phone),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": "es"},
            "components": components,
        },
    })
    result["template"] = name
    return result


def send_document(phone: str, filename: str, content: bytes, caption: str) -> dict:
    uploaded = upload_pdf(filename, content)
    if not uploaded.get("ok"):
        return uploaded
    return _post({
        "messaging_product": "whatsapp",
        "to": clean_phone(phone),
        "type": "document",
        "document": {"id": uploaded["id"], "filename": filename, "caption": caption[:1024]},
    })


def send_buttons(phone: str, text: str, buttons: list[tuple[str, str]]) -> dict:
    payload_buttons = [
        {"type": "reply", "reply": {"id": button_id[:256], "title": title[:20]}}
        for button_id, title in buttons[:3]
    ]
    return _post({
        "messaging_product": "whatsapp",
        "to": clean_phone(phone),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text[:1024]},
            "action": {"buttons": payload_buttons},
        },
    })


def notify_work_contract(
    *,
    work_id: int,
    client_phone: str,
    company_phone: str,
    client_name: str,
    address: str,
    partidas: list[tuple[str, int | None, int]],
    pdf: bytes,
    updated: bool,
    saved: str | None = None,
) -> str:
    saved = saved or ("Partidas actualizadas" if updated else "Obra guardada")
    if len(phone_digits(client_phone)) < 8:
        return f"{saved}. La obra no tiene el teléfono del cliente para enviar el contrato."
    if not configured():
        return f"{saved}. No se envió el contrato porque WhatsApp no está configurado."
    template = send_template(
        client_phone,
        CONTRACT_TEMPLATE,
        [client_name],
        document=(f"contrato-obra-{work_id}.pdf", pdf),
    )
    if not template.get("ok"):
        detail = template.get("error") or "No se pudo enviar el WhatsApp."
        return f"{saved}. No se pudo enviar el contrato: {detail}"
    if len(phone_digits(company_phone)) >= 8:
        try:
            send_template(company_phone, "alerta_nueva_orden", [clean_whatsapp_text(client_name)])
        except Exception:
            pass
    return f"{saved}. Se envió el contrato por WhatsApp al cliente."


def notify_palmeta_change(
    *,
    change_id: int,
    client_phone: str,
    company_phone: str,
    work_name: str,
    client_name: str,
    previous_count: int,
    next_count: int,
    pdf: bytes,
) -> str:
    if not configured():
        return "El cambio quedó pendiente. WhatsApp no está configurado con META_TOKEN."
    filename = f"cambio-palmetas-{change_id}.pdf"
    caption = (
        f"Propuesta de cambio de palmetas en {work_name}. "
        f"De {previous_count} a {next_count}. Revisa el PDF."
    )
    document = send_document(client_phone, filename, pdf, caption)
    buttons = send_buttons(
        client_phone,
        f"¿Aceptas el cambio de palmetas en {work_name}, de {previous_count} a {next_count}?",
        [(f"accept_{change_id}", "Acepto"), (f"reject_{change_id}", "No acepto")],
    )
    company = send_text(
        company_phone,
        (
            f"Cambio de palmetas en {work_name}: de {previous_count} a {next_count}. "
            f"Se envió el PDF a {client_name} para que acepte o rechace."
        ),
    )
    failed = [item for item in (document, buttons, company) if not item.get("ok")]
    if failed:
        return failed[0].get("error") or "No se pudo enviar el WhatsApp."
    return "Se envió el PDF al cliente y el aviso a Vitrificados Chile."
