import os

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import RoleRow, StatusRow, WorkScheduleRow
from app.notice_pdf import contract_pdf
from app.whatsapp import format_contract_lines

PHOTO = "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E"


def client() -> TestClient:
    os.environ["META_TOKEN"] = ""
    return TestClient(create_app("sqlite://"))


def banking(api: TestClient, headers: dict[str, str], holder: str = "Ana Soto") -> dict[str, str]:
    banks = api.get("/api/banks", headers=headers).json()
    types = api.get("/api/bank-account-types", headers=headers).json()
    return {
        "address": "Av. Apoquindo 100, Las Condes",
        "phone": "912345678",
        "bankId": next(item["id"] for item in banks if item["name"] == "Banco de Chile"),
        "accountTypeId": next(item["id"] for item in types if item["name"] == "Vista"),
        "accountNumber": "12345678",
        "accountHolder": holder,
        "accountHolderDocumentId": "12345678-9",
    }


def admin_headers(api: TestClient) -> dict[str, str]:
    response = api.post("/api/auth/login", json={"email": "admin@vitrificados.local", "password": "demo-admin"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_admin_site_can_call_the_login_preflight() -> None:
    api = client()
    response = api.options(
        "/api/auth/login",
        headers={
            "Origin": "https://admin.vitrificadoschile.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://admin.vitrificadoschile.com"


def test_banks_come_from_the_catalog() -> None:
    api = client()
    headers = admin_headers(api)
    listed = api.get("/api/banks", headers=headers)
    assert listed.status_code == 200
    names = {item["name"] for item in listed.json()}
    assert "Banco de Chile" in names
    assert "Banco del Estado de Chile" in names
    assert "Tenpo Bank" in names
    bank_id = next(item["id"] for item in listed.json() if item["name"] == "Banco de Chile")
    types = api.get("/api/bank-account-types", headers=headers)
    assert types.status_code == 200
    assert {item["name"] for item in types.json()} == {"Ahorro", "Corriente", "Vista"}
    created = api.post("/api/accounts", headers=headers, json={
        "name": "Ana Soto",
        "email": "ana.banco@vitrificados.local",
        "password": "demo-site",
        "roleId": 1,
        **banking(api, headers),
    })
    assert created.status_code == 200
    assert created.json()["bankId"] == bank_id
    assert created.json()["bank"] == "Banco de Chile"
    assert created.json()["accountType"] == "Vista"
    rejected = api.post("/api/accounts", headers=headers, json={
        "name": "Ana Soto",
        "email": "ana.tipo@vitrificados.local",
        "password": "demo-site",
        "roleId": 1,
        **banking(api, headers),
        "accountTypeId": "999",
    })
    assert rejected.status_code == 400


def test_admin_sees_seeded_works() -> None:
    api = client()
    response = api.get("/api/works", headers=admin_headers(api))
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert "Faena Los Dominicos" in names


def test_worker_cannot_list_accounts() -> None:
    api = client()
    login = api.post("/api/auth/login", json={"email": "lead.worker@vitrificados.local", "password": "demo-site"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    accounts = api.get("/api/accounts", headers=headers)
    assert accounts.status_code == 200
    assert [item["id"] for item in accounts.json()] == ["2"]
    assert accounts.json()[0]["roleId"] == 2
    assert accounts.json()[0]["palmetaCost"] == 1500
    assert api.post("/api/works", headers=headers, json={
        "name": "Obra nueva",
        "address": "Calle Falsa 123",
        "shiftStart": "08:00",
        "shiftEnd": "17:00",
        "plannedHours": 8,
    }).status_code == 403
    works = api.get("/api/works", headers=headers)
    assert works.status_code == 200
    assert {item["id"] for item in works.json()} == {"1", "2"}


def test_arrival_requires_photo_and_gps() -> None:
    api = client()
    headers = admin_headers(api)
    response = api.post("/api/arrivals", headers=headers, json={
        "workId": "1",
        "workerId": "2",
        "at": "2026-10-03T12:00:00.000Z",
        "latitude": None,
        "longitude": None,
        "photoDataUrl": PHOTO,
    })
    assert response.status_code == 400
    assert "GPS" in response.json()["detail"]


def test_arrival_rejects_a_mark_away_from_the_site() -> None:
    api = client()
    headers = admin_headers(api)
    away = api.post("/api/arrivals", headers=headers, json={
        "workId": "1",
        "workerId": "2",
        "at": "2026-10-03T12:00:00.000Z",
        "latitude": -33.5,
        "longitude": -70.5,
        "photoDataUrl": PHOTO,
    })
    assert away.status_code == 400
    assert "ubicación del trabajo" in away.json()["detail"]
    on_site = api.post("/api/arrivals", headers=headers, json={
        "workId": "1",
        "workerId": "2",
        "at": "2026-10-03T12:00:00.000Z",
        "latitude": -33.4,
        "longitude": -70.5,
        "photoDataUrl": PHOTO,
    })
    assert on_site.status_code == 200
    assert "wa.me" in on_site.json()["whatsappHref"]


def test_calendar_returns_every_day_of_the_month() -> None:
    api = client()
    headers = admin_headers(api)
    created = api.post("/api/arrivals", headers=headers, json={
        "workId": "1",
        "workerId": "2",
        "at": "2026-10-03T12:00:00.000Z",
        "latitude": -33.4,
        "longitude": -70.5,
        "photoDataUrl": PHOTO,
    })
    assert created.status_code == 200
    response = api.get("/api/works/1/calendar/2026-10", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == "2026-10"
    assert len(body["days"]) == 31
    marked = next(day for day in body["days"] if day["date"] == "2026-10-03")
    assert marked["arrivals"][0]["workerName"] == "Maestro de obra"


def test_assigning_a_site_lead_lists_them_on_the_work() -> None:
    api = client()
    headers = admin_headers(api)
    saved = api.put("/api/works/1/crew", headers=headers, json={
        "members": [{"workerId": "2", "startDate": "2026-10-05", "dayCount": 5}],
    })
    assert saved.status_code == 200
    assert saved.json() == [{"workId": "1", "workerId": "2", "startDate": "2026-10-05", "dayCount": 5}]
    listed = api.get("/api/assignments", headers=headers)
    assert listed.status_code == 200
    match = [item for item in listed.json() if item["workId"] == "1" and item["workerId"] == "2"]
    assert match == [{"workId": "1", "workerId": "2", "startDate": "2026-10-05", "dayCount": 5}]


def test_roles_statuses_and_schedules_are_numeric() -> None:
    api = client()
    with api.app.state.session_factory() as db:
        roles = [(row.id, row.rol) for row in db.query(RoleRow).order_by(RoleRow.id)]
        statuses = [(row.id, row.name) for row in db.query(StatusRow).order_by(StatusRow.id)]
        schedule = db.query(WorkScheduleRow).order_by(WorkScheduleRow.id).first()
    assert roles == [(1, "Administrador"), (2, "Maestro de Obra"), (3, "Ayudante")]
    assert statuses == [
        (1, "En espera"),
        (2, "Trabajando"),
        (3, "Entregada"),
        (4, "Activo"),
        (5, "Desactivado"),
    ]
    assert schedule is not None
    assert schedule.work_id == 1
    assert schedule.user_id == 2


def test_site_lead_uses_charge_item_prices_and_helper_requires_hourly_rate() -> None:
    api = client()
    headers = admin_headers(api)
    created = api.post("/api/accounts", headers=headers, json={
        "name": "Ana Soto",
        "email": "ana@vitrificados.local",
        "password": "demo-site",
        "roleId": 2,
        **banking(api, headers),
    })
    assert created.status_code == 200
    assert created.json()["roleId"] == 2
    assert created.json()["firstName"] == "Ana"
    assert created.json()["lastName"] == "Soto"
    assert created.json()["palmetaCost"] == 0
    helper = api.post("/api/accounts", headers=headers, json={
        "name": "Luis Pérez",
        "email": "luis@vitrificados.local",
        "password": "demo-site",
        "roleId": 3,
        "hourlyRate": 7000,
        **banking(api, headers, "Luis Pérez"),
    })
    assert helper.status_code == 200
    assert helper.json()["roleId"] == 3
    assert helper.json()["hourlyRate"] == 7000


def test_work_keeps_the_chosen_working_days() -> None:
    api = client()
    headers = admin_headers(api)
    created = api.post("/api/works", headers=headers, json={
        "name": "Faena sabatina",
        "address": "Calle Falsa 123",
        "shiftStart": "08:00",
        "shiftEnd": "17:00",
        "plannedHours": 8,
        "workDays": "except-sunday",
        "palmetaCount": 10,
        "squareMeters": 40,
        "clientName": "Cliente Norte",
        "clientPhone": "912345678",
        "latitude": -33.4,
        "longitude": -70.5,
    })
    assert created.status_code == 200
    assert created.json()["workDays"] == "except-sunday"
    custom = api.post("/api/works", headers=headers, json={
        "name": "Faena parcial",
        "address": "Calle Falsa 123",
        "shiftStart": "08:00",
        "shiftEnd": "17:00",
        "plannedHours": 8,
        "workDays": "1,3,5",
        "palmetaCount": 10,
        "squareMeters": 40,
        "clientName": "Cliente Norte",
        "clientPhone": "912345678",
        "latitude": -33.4,
        "longitude": -70.5,
    })
    assert custom.status_code == 200
    assert custom.json()["workDays"] == "1,3,5"
    midnight = api.post("/api/works", headers=headers, json={
        "name": "Faena nocturna",
        "address": "Calle Falsa 123",
        "shiftStart": "10:00",
        "shiftEnd": "00:00",
        "plannedHours": 8,
        "workDays": "weekdays",
        "palmetaCount": 10,
        "squareMeters": 40,
        "clientName": "Cliente Norte",
        "clientPhone": "912345678",
        "latitude": -33.4,
        "longitude": -70.5,
    })
    assert midnight.status_code == 200
    assert midnight.json()["shiftStart"] == "10:00"
    assert midnight.json()["shiftEnd"] == "00:00"
    rejected = api.post("/api/works", headers=headers, json={
        "name": "Faena sabatina",
        "address": "Calle Falsa 123",
        "shiftStart": "08:00",
        "shiftEnd": "17:00",
        "plannedHours": 8,
        "workDays": "lunes",
        "latitude": -33.4,
        "longitude": -70.5,
    })
    assert rejected.status_code == 400


def test_tasks_drop_on_half_hours() -> None:
    api = client()
    headers = admin_headers(api)
    tasks = api.get("/api/tasks", headers=headers)
    assert tasks.status_code == 200
    names = {item["name"] for item in tasks.json()}
    assert names == {"Trabajo de Obra", "Extras"}
    created = api.post("/api/tasks", headers=headers, json={
        "name": "Traslado",
        "kind": "general",
        "amount": 2000,
        "extraAmount": 1500,
    })
    assert created.status_code == 200
    assert created.json()["kind"] == "general"
    assert created.json()["amount"] == 2000
    assert created.json()["extraAmount"] == 0
    site = api.post("/api/tasks", headers=headers, json={
        "name": "Faena base",
        "kind": "site",
        "amount": 9000,
    })
    assert site.status_code == 200
    assert site.json()["amount"] == 0
    task_id = next(item["id"] for item in tasks.json() if item["name"] == "Trabajo de Obra")
    rejected = api.post("/api/task-blocks", headers=headers, json={
        "workId": "1",
        "taskId": task_id,
        "date": "2026-10-04",
        "start": "08:10",
        "end": "08:40",
    })
    assert rejected.status_code == 400
    placed = api.post("/api/task-blocks", headers=headers, json={
        "workId": "1",
        "taskId": task_id,
        "date": "2026-10-04",
        "start": "08:00",
        "end": "08:30",
    })
    assert placed.status_code == 200
    listed = api.get("/api/task-blocks", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == placed.json()["id"] for item in listed.json())
    overlap = api.post("/api/task-blocks", headers=headers, json={
        "workId": "1",
        "taskId": task_id,
        "date": "2026-10-04",
        "start": "08:00",
        "end": "09:00",
    })
    assert overlap.status_code == 400


def test_palmeta_change_only_increases_and_waits_for_the_client() -> None:
    api = client()
    admin = admin_headers(api)
    saved = api.put("/api/settings", headers=admin, json={"companyPhone": "56911112222"})
    assert saved.status_code == 200
    login = api.post("/api/auth/login", json={"email": "lead.worker@vitrificados.local", "password": "demo-site"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    lower = api.post("/api/works/1/palmeta-changes", headers=headers, json={"quantity": 100})
    assert lower.status_code == 400
    proposed = api.post("/api/works/1/palmeta-changes", headers=headers, json={"quantity": 220})
    assert proposed.status_code == 200
    assert proposed.json()["previousCount"] == 200
    assert proposed.json()["nextCount"] == 220
    assert proposed.json()["status"] == "pending"
    works = api.get("/api/works", headers=headers)
    current = next(item for item in works.json() if item["id"] == "1")
    assert current["palmetaCount"] == 200
    assert current["pendingPalmetaCount"] == 220
    assert current["squareMeters"] == 85
    profile = api.put("/api/accounts/me", headers=headers, json={
        "name": "Maestro de obra",
        "email": "lead.worker@vitrificados.local",
        "phone": "912345678",
        "bank": "Banco Estado",
        "accountType": "Cuenta vista",
        "accountNumber": "123456",
        "accountHolder": "Maestro de obra",
        "palmetaCost": 1,
    })
    assert profile.status_code == 403
    own = api.get("/api/accounts", headers=headers)
    assert own.json()[0]["bank"] == ""
    assert own.json()[0]["palmetaCost"] == 1500
    accepted = api.post("/api/whatsapp/webhook", json={
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "56987654321",
                        "interactive": {"button_reply": {"id": f"accept_{proposed.json()['id']}"}},
                    }],
                },
            }],
        }],
    })
    assert accepted.status_code == 200
    works = api.get("/api/works", headers=headers)
    current = next(item for item in works.json() if item["id"] == "1")
    assert current["palmetaCount"] == 220
    assert current["pendingPalmetaCount"] is None


def test_only_the_site_lead_updates_charge_quantities() -> None:
    api = client()
    helper = api.post("/api/auth/login", json={"email": "helper.worker@vitrificados.local", "password": "demo-site"})
    helper_headers = {"Authorization": f"Bearer {helper.json()['token']}"}
    denied = api.put("/api/works/1/charges", headers=helper_headers, json={"charges": [{"itemId": "1", "quantity": 3}]})
    assert denied.status_code == 403
    login = api.post("/api/auth/login", json={"email": "lead.worker@vitrificados.local", "password": "demo-site"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    updated = api.put("/api/works/1/charges", headers=headers, json={"charges": [{"itemId": "1", "quantity": 4}]})
    assert updated.status_code == 200
    assert updated.json()["charges"] == [{"itemId": "1", "quantity": 4}]
    invalid = api.put("/api/works/1/charges", headers=headers, json={"charges": [{"itemId": "1", "quantity": -1}]})
    assert invalid.status_code == 400


def test_charge_items_have_a_price_on_the_lead_and_a_quantity_on_the_work() -> None:
    api = client()
    headers = admin_headers(api)
    created = api.post("/api/charge-items", headers=headers, json={"name": "Cristal"})
    assert created.status_code == 200
    item_id = created.json()["id"]
    lead = api.put("/api/accounts/2", headers=headers, json={
        "name": "Maestro de obra",
        "email": "lead.worker@vitrificados.local",
        "roleId": 2,
        "palmetaCost": 1500,
        "itemPrices": [{"itemId": item_id, "amount": 3200}],
        **banking(api, headers, "Maestro de obra"),
    })
    assert lead.status_code == 200
    assert lead.json()["itemPrices"] == [{"itemId": item_id, "amount": 3200}]
    work = api.post("/api/works", headers=headers, json={
        "name": "Obra con ítems",
        "address": "Calle Nueva 50, Santiago",
        "shiftStart": "08:00",
        "shiftEnd": "17:00",
        "plannedHours": 8,
        "palmetaCount": 10,
        "squareMeters": 20,
        "clientName": "Cliente Ítem",
        "clientPhone": "987654321",
        "charges": [{"itemId": item_id, "quantity": 4}],
    })
    assert work.status_code == 200
    assert work.json()["charges"] == [{"itemId": item_id, "quantity": 4}]
    composed = api.post("/api/charge-items", headers=headers, json={
        "name": "Instalación especial",
        "kind": "composed",
        "lines": [{"name": "Mano de obra"}, {"name": "Material"}],
    })
    assert composed.status_code == 200
    assert composed.json()["kind"] == "composed"
    assert [line["name"] for line in composed.json()["lines"]] == ["Mano de obra", "Material"]


def contract_text(data: bytes) -> str:
    import fitz
    document = fitz.open(stream=data, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    document.close()
    return " ".join(text.split())


def test_contract_pdf_lists_the_agreed_charges() -> None:
    initial = contract_pdf(
        updated=False,
        client_name="Cliente Norte",
        client_phone="912345678",
        address="Calle Falsa 123",
        shift_start="08:00",
        shift_end="17:00",
        work_days="weekdays",
        lines=[("Retape", None, 12)],
    )
    updated = contract_pdf(
        updated=True,
        client_name="Cliente Norte",
        client_phone="912345678",
        address="Calle Falsa 123",
        shift_start="08:00",
        shift_end="17:00",
        work_days="weekdays",
        lines=[("Retape", 12, 4)],
    )
    initial_text = contract_text(initial)
    updated_text = contract_text(updated)
    assert initial.startswith(b"%PDF")
    assert b"/DCTDecode" in initial
    assert "Cliente Norte" in initial_text
    assert "Retape" in initial_text
    assert "12" in initial_text
    assert "El inicio de los trabajos en el inmueble importa aceptación" in initial_text
    assert "Retape" in updated_text
    assert "12 a 4" in updated_text
    assert "ACTUALIZACIÓN DE CONTRATO" in updated_text
    assert "vuelven a iniciarse" in updated_text
    assert "aceptada automáticamente" in updated_text


def test_contract_lines_use_one_line_each() -> None:
    text = format_contract_lines([
        ("Palmetas de cambio", None, 100),
        ("Palmetas de pegado", None, 300),
    ])
    assert text == "\u2028- Palmetas de cambio: 100.\u2028- Palmetas de pegado: 300"
    assert format_contract_lines([]) == "Sin partidas con cantidad"


def test_work_contract_is_sent_to_the_client(monkeypatch) -> None:
    sent: list[dict] = []

    def fake_template(phone, name, parameters, button_payloads=None, *, document=None, line_parameters=None):
        sent.append({
            "phone": phone,
            "name": name,
            "parameters": parameters,
            "buttons": button_payloads,
            "document": document,
        })
        return {"ok": True, "template": name}

    monkeypatch.setattr("app.whatsapp.send_template", fake_template)
    api = client()
    monkeypatch.setenv("META_TOKEN", "test-token")
    headers = admin_headers(api)
    created = api.post("/api/works", headers=headers, json={
        "name": "Faena contrato",
        "address": "Calle Falsa 123",
        "shiftStart": "08:00",
        "shiftEnd": "17:00",
        "plannedHours": 8,
        "workDays": "weekdays",
        "palmetaCount": 10,
        "squareMeters": 40,
        "clientName": "Cliente Norte",
        "clientPhone": "912345678",
        "latitude": -33.4,
        "longitude": -70.5,
        "charges": [{"itemId": "1", "quantity": 3}],
    })
    assert created.status_code == 200
    assert created.json()["notice"] == "Obra guardada. Se envió el contrato por WhatsApp al cliente."
    assert sent[0]["phone"] == "912345678"
    assert sent[0]["name"] == "scope_of_work"
    assert sent[0]["parameters"] == ["Cliente Norte"]
    assert sent[0]["document"][0].startswith("contrato-obra-")
    assert sent[0]["document"][0].endswith(".pdf")
    assert sent[0]["document"][1].startswith(b"%PDF")
    login = api.post("/api/auth/login", json={"email": "lead.worker@vitrificados.local", "password": "demo-site"})
    lead = {"Authorization": f"Bearer {login.json()['token']}"}
    unchanged = api.put("/api/works/1/charges", headers=lead, json={"charges": [{"itemId": "1", "quantity": 12}]})
    assert unchanged.status_code == 200
    assert unchanged.json()["notice"] == ""
    assert len(sent) == 1
    updated = api.put("/api/works/1/charges", headers=lead, json={"charges": [{"itemId": "1", "quantity": 4}]})
    assert updated.status_code == 200
    assert updated.json()["notice"] == "Partidas actualizadas. Se envió el contrato por WhatsApp al cliente."
    assert sent[1]["name"] == "updated_scope_of_work"
    assert sent[1]["parameters"] == ["Inmobiliaria Dominicos"]
    assert sent[1]["document"][1].startswith(b"%PDF")
    edited = api.put(f"/api/works/{created.json()['id']}", headers=headers, json={
        "name": "Faena contrato",
        "address": "Calle Falsa 123",
        "shiftStart": "08:00",
        "shiftEnd": "17:00",
        "plannedHours": 8,
        "workDays": "weekdays",
        "palmetaCount": 10,
        "squareMeters": 40,
        "clientName": "Cliente Norte",
        "clientPhone": "912345678",
        "latitude": -33.4,
        "longitude": -70.5,
        "charges": [{"itemId": "1", "quantity": 3}],
    })
    assert edited.status_code == 200
    assert edited.json()["notice"] == "Obra actualizada. Se envió el contrato por WhatsApp al cliente."
    assert sent[-1]["name"] == "updated_scope_of_work"
    assert sent[-1]["parameters"] == ["Cliente Norte"]


def test_settings_store_many_emails_and_phones() -> None:
    api = client()
    headers = admin_headers(api)
    saved = api.put("/api/settings", headers=headers, json={
        "companyPhone": "",
        "emails": ["obra@vitrificadoschile.com", "aviso@vitrificadoschile.com"],
        "phones": ["56911112222", "56933334444"],
    })
    assert saved.status_code == 200
    assert saved.json()["emails"] == ["obra@vitrificadoschile.com", "aviso@vitrificadoschile.com"]
    assert saved.json()["phones"] == ["56911112222", "56933334444"]
    invalid = api.put("/api/settings", headers=headers, json={"emails": ["sin-arroba"], "phones": []})
    assert invalid.status_code == 400


def test_admin_can_roll_the_work_status() -> None:
    api = client()
    headers = admin_headers(api)
    working = api.put("/api/works/1/status", headers=headers, json={"status": "working"})
    assert working.status_code == 200
    assert working.json()["status"] == "working"
    delivered = api.put("/api/works/1/status", headers=headers, json={"status": "completed"})
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "completed"
    invalid = api.put("/api/works/1/status", headers=headers, json={"status": "paused"})
    assert invalid.status_code == 400
    lead = api.post("/api/auth/login", json={"email": "lead.worker@vitrificados.local", "password": "demo-site"})
    denied = api.put("/api/works/1/status", headers={"Authorization": f"Bearer {lead.json()['token']}"}, json={"status": "active"})
    assert denied.status_code == 403
