import math
import os
from pathlib import Path

import httpx

from app.domain import phone_digits, quantity_with_unit

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


DAY_NAMES = {
    1: "lunes",
    2: "martes",
    3: "miércoles",
    4: "jueves",
    5: "viernes",
    6: "sábado",
    0: "domingo",
}
DAY_MODES = {
    "weekdays": [1, 2, 3, 4, 5],
    "weekend": [6, 0],
    "all": [1, 2, 3, 4, 5, 6, 0],
    "except-sunday": [1, 2, 3, 4, 5, 6],
}


def format_shift(start: str, end: str) -> str:
    start_clean = start.strip()
    end_clean = end.strip()
    if not start_clean or not end_clean:
        return "-"
    return f"{start_clean} a {end_clean}"


def format_assignment_days(work_days: str, schedule_dates: str = "") -> str:
    listed = []
    for part in schedule_dates.split(","):
        part = part.strip()
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            year, month, day = part.split("-")
            if year.isdigit() and month.isdigit() and day.isdigit():
                listed.append((int(year), int(month), int(day)))
    if listed:
        listed.sort()
        start = listed[0]
        end = listed[-1]
        count = len(listed)
        start_label = f"{start[2]:02d}/{start[1]:02d}/{start[0]}"
        day_label = "1 día" if count == 1 else f"{count} días"
        if start == end:
            return f"{start_label}, {day_label}"
        end_label = f"{end[2]:02d}/{end[1]:02d}/{end[0]}"
        return f"{start_label} al {end_label}, {day_label}"
    chosen = DAY_MODES.get(work_days.strip())
    if chosen is None:
        chosen = [int(part) for part in work_days.split(",") if part.isdigit() and int(part) in DAY_NAMES]
    names = [DAY_NAMES[day] for day in (1, 2, 3, 4, 5, 6, 0) if day in chosen]
    if not names:
        return "-"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} y {names[-1]}"


def format_assignment_partidas(lines: list[tuple]) -> str:
    rows = []
    for line in lines:
        name, quantity = line[0], line[1]
        unit = line[2] if len(line) > 2 else ""
        marked = bool(line[3]) if len(line) > 3 else False
        if quantity <= 0 and not marked:
            continue
        text = f"{name} {quantity_with_unit(quantity, unit)}"
        if marked:
            text = f"{text} (Evaluar: Si)"
        rows.append(text)
    return ", ".join(rows) or "Sin partidas"


def format_partida_changes(lines: list[tuple]) -> str:
    rows = []
    for line in lines:
        name, previous, quantity = line[0], line[1], line[2]
        unit = line[3] if len(line) > 3 else ""
        marked = bool(line[4]) if len(line) > 4 else False
        was_marked = bool(line[5]) if len(line) > 5 else False
        if previous == quantity and marked == was_marked:
            continue
        if previous == 0 and quantity == 0 and not marked and not was_marked:
            continue
        if quantity == 0 and not marked and (previous > 0 or was_marked):
            rows.append(f"Se quita {name}")
            continue
        if previous == 0 and not was_marked:
            text = f"Se agrega {name}, cantidad {quantity_with_unit(quantity, unit)}"
        elif previous != quantity:
            text = f"{name} pasa de {quantity_with_unit(previous, unit)} a {quantity_with_unit(quantity, unit)}"
        else:
            text = f"{name} {quantity_with_unit(quantity, unit)}"
        if marked:
            text = f"{text} (Evaluar: Si)"
        elif was_marked:
            text = f"{text} (Evaluar: No)"
        rows.append(text)
    return ", ".join(rows) or "Sin cambios de partidas"


def map_link(latitude: float, longitude: float) -> str:
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return "-"
    return f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"


def format_contract_lines(lines: list[tuple]) -> str:
    rows = []
    for line in lines:
        if len(line) > 4 and not line[4]:
            continue
        name, quantity = line[0], line[2]
        unit = line[3] if len(line) > 3 else ""
        suffix = " (Evaluar: Si)" if len(line) > 4 and line[4] else ""
        rows.append(f"- {name}: {quantity_with_unit(quantity, unit)}{suffix}.")
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
UPDATED_CONTRACT_TEMPLATE = "updated_scope_of_work"
ASSIGNMENT_TEMPLATE = "scope_of_worker"
UPDATED_SCOPE_TEMPLATE = "scope_of_work_updated"
SCOPE_REQUEST_TEMPLATE = "worker_work_scope_updated"
LATE_TEMPLATE = "late_alert"


def upload_media(filename: str, content: bytes, mime: str) -> dict:
    token = os.environ.get("META_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "WhatsApp no está configurado."}
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id()}/media"
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        data={"messaging_product": "whatsapp", "type": mime},
        files={"file": (filename, content, mime)},
        timeout=30,
    )
    body = response.json() if response.content else {}
    media_id = body.get("id")
    if response.status_code != 200 or not media_id:
        error = body.get("error", {})
        return {"ok": False, "error": error.get("message") or "No se pudo adjuntar el archivo."}
    return {"ok": True, "id": media_id}


def upload_pdf(filename: str, content: bytes) -> dict:
    return upload_media(filename, content, "application/pdf")


def brand_logo() -> tuple[str, bytes] | None:
    from app.notice_pdf import logo_path
    path = logo_path()
    if path is None:
        return None
    return path.name, path.read_bytes()


def send_template(
    phone: str,
    name: str,
    parameters: list[str],
    button_payloads: list[str] | None = None,
    *,
    document: tuple[str, bytes] | None = None,
    image: tuple[str, bytes] | None = None,
    line_parameters: set[int] | None = None,
    language: str = "es",
) -> dict:
    components: list[dict] = []
    if image is not None:
        filename, content = image
        mime = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
        uploaded = upload_media(filename, content, mime)
        if not uploaded.get("ok"):
            uploaded["template"] = name
            return uploaded
        components.append({
            "type": "header",
            "parameters": [{
                "type": "image",
                "image": {"id": uploaded["id"]},
            }],
        })
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
            "language": {"code": language},
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


def notify_late_arrival(
    *,
    phone: str,
    worker_name: str,
    work_name: str,
    minutes_late: int,
) -> dict:
    if len(phone_digits(phone)) < 8 or not configured():
        return {"ok": False, "error": "WhatsApp no está configurado."}
    parameters = [
        worker_name.strip() or "Trabajador",
        str(minutes_late),
        work_name.strip() or "Obra",
    ]
    try:
        logo = brand_logo()
        sent = send_template(phone, LATE_TEMPLATE, parameters, image=logo, language="es")
        if logo is not None and not sent.get("ok"):
            sent = send_template(phone, LATE_TEMPLATE, parameters, language="es")
        return sent
    except Exception as error:
        return {"ok": False, "error": str(error)}


def notify_worker_assignment(
    *,
    phone: str,
    worker_name: str,
    work_name: str,
    address: str,
    latitude: float,
    longitude: float,
    partidas: str,
    work_notice: str = "",
    crew_note: str = "",
    shift_start: str = "",
    shift_end: str = "",
    work_days: str = "",
    schedule_dates: str = "",
) -> dict:
    if len(phone_digits(phone)) < 8:
        return {"ok": False, "error": "Sin celular."}
    if not configured():
        return {"ok": False, "error": "WhatsApp no está configurado."}
    parameters = [
        worker_name.strip() or "Trabajador",
        work_name.strip() or "Obra",
        format_shift(shift_start, shift_end),
        format_assignment_days(work_days, schedule_dates),
        address.strip() or "-",
        map_link(latitude, longitude),
        partidas.strip() or "Sin partidas",
        work_notice.strip() or "-",
        crew_note.strip() or "-",
    ]
    try:
        logo = brand_logo()
        sent = send_template(phone, ASSIGNMENT_TEMPLATE, parameters, image=logo, language="es")
        if logo is not None and not sent.get("ok"):
            sent = send_template(phone, ASSIGNMENT_TEMPLATE, parameters, language="es")
        return sent
    except Exception as error:
        return {"ok": False, "error": str(error)}


def notify_updated_scope(
    *,
    phone: str,
    worker_name: str,
    work_name: str,
    changes: str,
) -> dict:
    if len(phone_digits(phone)) < 8:
        return {"ok": False, "error": "Sin celular."}
    if not configured():
        return {"ok": False, "error": "WhatsApp no está configurado."}
    parameters = [
        worker_name.strip() or "Trabajador",
        work_name.strip() or "Obra",
        changes.strip() or "Sin cambios de partidas",
    ]
    try:
        logo = brand_logo()
        sent = send_template(phone, UPDATED_SCOPE_TEMPLATE, parameters, image=logo, language="es")
        if logo is not None and not sent.get("ok"):
            sent = send_template(phone, UPDATED_SCOPE_TEMPLATE, parameters, language="es")
        return sent
    except Exception as error:
        return {"ok": False, "error": str(error)}


def notify_scope_request(*, phone: str, maestro_name: str, work_name: str) -> dict:
    if len(phone_digits(phone)) < 8:
        return {"ok": False, "error": "Sin celular."}
    if not configured():
        return {"ok": False, "error": "WhatsApp no está configurado."}
    parameters = [
        maestro_name.strip() or "Maestro",
        work_name.strip() or "Obra",
    ]
    try:
        return send_template(phone, SCOPE_REQUEST_TEMPLATE, parameters, language="es")
    except Exception as error:
        return {"ok": False, "error": str(error)}


def notify_work_contract(
    *,
    work_id: int,
    client_phone: str,
    company_phone: str,
    client_name: str,
    address: str,
    lines: list[tuple[str, int | None, int]],
    pdf: bytes,
    updated: bool,
    saved: str | None = None,
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    notify_admins: bool = True,
) -> str:
    saved = saved or ("Partidas actualizadas" if updated else "Obra guardada")
    if len(phone_digits(client_phone)) < 8:
        return f"{saved}. La obra no tiene el teléfono del cliente para enviar el contrato."
    if not configured():
        return f"{saved}. No se envió el contrato porque WhatsApp no está configurado."
    template = send_template(
        client_phone,
        UPDATED_CONTRACT_TEMPLATE if updated else CONTRACT_TEMPLATE,
        [client_name],
        document=(f"contrato-obra-{work_id}.pdf", pdf),
    )
    if not template.get("ok"):
        detail = template.get("error") or "No se pudo enviar el WhatsApp."
        return f"{saved}. No se pudo enviar el contrato: {detail}"
    notified: list[str] = []
    if company_phone:
        notified.append(company_phone)
    for phone in phones or []:
        if phone not in notified and len(phone_digits(phone)) >= 8:
            notified.append(phone)
    for phone in notified:
        if not notify_admins or len(phone_digits(phone)) < 8:
            continue
        try:
            send_template(phone, "alerta_nueva_orden", [clean_whatsapp_text(client_name)])
        except Exception:
            pass
    from app.mail import send_contract_email
    subject = "Actualización de contrato" if updated else "Contrato de obra"
    mail = send_contract_email(
        emails or [],
        f"{subject} — {client_name}",
        f"{saved}. Cliente: {client_name}. Dirección: {address}.",
        f"contrato-obra-{work_id}.pdf",
        pdf,
    )
    sent = f"{saved}. Se envió el contrato por WhatsApp al cliente."
    return f"{sent} {mail}".strip() if mail else sent


def notify_palmeta_change(
    *,
    change_id: int,
    client_phone: str,
    company_phones: list[str],
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
    notice = (
        f"Cambio de palmetas en {work_name}: de {previous_count} a {next_count}. "
        f"Se envió el PDF a {client_name} para que acepte o rechace."
    )
    company_messages = [send_text(phone, notice) for phone in company_phones]
    failed = [item for item in (document, buttons, *company_messages) if not item.get("ok")]
    if failed:
        return failed[0].get("error") or "No se pudo enviar el WhatsApp."
    return "Se envió el PDF al cliente y el aviso a Vitrificados Chile."
