import calendar
import json
import math
import re
from typing import NoReturn

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.deps import current_account, get_db, require_admin
from app.domain import (
    OFF_SITE_MESSAGE,
    arrival_block_reason,
    minutes_of,
    on_site,
    palmeta_increase_error,
    phone_digits,
    ranges_overlap,
    shift_hours,
    task_block_error,
    work_error,
)
from app.notice_pdf import contract_pdf, money, palmeta_change_pdf, period_label, settlement_pdf
from app.whatsapp import clean_phone, format_assignment_partidas, notify_palmeta_change, notify_work_contract, notify_worker_assignment
from app.geocoding import AddressNotFound, locate_address, shorten_address, suggest_addresses
from app.models import (
    CODE_STATUS,
    ROLE_ADMIN,
    ROLE_HELPER,
    ROLE_SITE_LEAD,
    STATUS_ACCOUNT_ACTIVE,
    STATUS_ACCOUNT_INACTIVE,
    STATUS_ACTIVE,
    STATUS_DELIVERED,
    AccountRow,
    AlertRow,
    ChargeChangeRow,
    BankAccountTypeRow,
    BankRow,
    ChargeItemRow,
    DeductionRow,
    NotificationContactRow,
    MeasureUnitRow,
    PalmetaChangeRow,
    RoleRow,
    SettingRow,
    SettlementRow,
    StatusRow,
    TaskBlockRow,
    TaskRow,
    TimeClockRow,
    UserItemPriceRow,
    UserRow,
    WorkItemRow,
    WorkRow,
    WorkScheduleRow,
    utcnow,
)
from app.presenters import account_out, arrival_out, assignment_out, charge_item_out, clock_coordinates, clock_moment, task_block_out, task_out, work_out
from app.schemas import (
    AccountBody,
    AlertOut,
    ChargeChangeLineOut,
    ChargeChangeOut,
    AccountOut,
    BankOut,
    ArrivalBody,
    ArrivalOut,
    AssignmentOut,
    ChargeItemBody,
    ChargeItemOut,
    ChargeOrderBody,
    CrewBody,
    DeductionBody,
    DeductionOut,
    CrewMemberBody,
    ItemPriceOut,
    LoginBody,
    LoginResult,
    CalendarOut,
    LocateBody,
    LocateOut,
    PalmetaChangeBody,
    PalmetaChangeOut,
    PlaceOut,
    ProfileBody,
    SettingBody,
    SettingOut,
    SettlementBody,
    SettlementItemOut,
    SettlementOut,
    StatusOut,
    TaskBlockBody,
    TaskBlockMoveBody,
    TaskBlockOut,
    TaskBody,
    TaskOut,
    WorkBody,
    WorkChargeOut,
    WorkChargesBody,
    WorkOut,
    WorkStatusBody,
)
from app.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api")


def fail(status: int, detail: str) -> NoReturn:
    raise HTTPException(status_code=status, detail=detail)


def add_alert(db: Session, user_id: int | None, kind: str, message: str, work_id: int | None = None) -> None:
    db.add(AlertRow(user_id=user_id, work_id=work_id, kind=kind, message=message))


def alert_out(row: AlertRow) -> AlertOut:
    return AlertOut(
        id=str(row.id),
        userId=None if row.user_id is None else str(row.user_id),
        workId=None if row.work_id is None else str(row.work_id),
        kind=row.kind,
        message=row.message,
        createdAt=row.created_at.isoformat(),
    )


def field_role(account: AccountRow) -> bool:
    return account.rol_id in {ROLE_SITE_LEAD, ROLE_HELPER}


def pending_counts(db: Session) -> dict[int, int]:
    rows = db.query(PalmetaChangeRow).filter(PalmetaChangeRow.status == "pending").all()
    return {row.work_id: row.next_count for row in rows}


def published_work(row: WorkRow, pending: dict[int, int], charges: list[WorkChargeOut] | None = None) -> WorkOut:
    return work_out(row, pending.get(row.id), charges)


def work_charge_map(db: Session) -> dict[int, list[WorkChargeOut]]:
    grouped: dict[int, list[WorkChargeOut]] = {}
    for row in db.query(WorkItemRow).all():
        grouped.setdefault(row.work_id, []).append(
            WorkChargeOut(itemId=str(row.item_id), quantity=row.quantity, evaluate=bool(row.evaluate))
        )
    return grouped


def work_charges(db: Session, work_id: int) -> list[WorkChargeOut]:
    return work_charge_map(db).get(work_id, [])


def charge_quantities(db: Session, work_id: int) -> dict[int, float]:
    return {
        row.item_id: row.quantity
        for row in db.query(WorkItemRow).filter(WorkItemRow.work_id == work_id)
    }


def charge_flags(db: Session, work_id: int) -> dict[int, bool]:
    return {
        row.item_id: bool(row.evaluate)
        for row in db.query(WorkItemRow).filter(WorkItemRow.work_id == work_id)
    }


def contract_lines(
    db: Session,
    current: dict[int, float],
    previous: dict[int, float] | None,
    evaluated: dict[int, bool] | None = None,
) -> list[tuple[str, float | None, float, str, bool]]:
    keys = set(current)
    if previous is not None:
        keys.update(previous)
    if not keys:
        return []
    items = {row.id: row for row in db.query(ChargeItemRow).filter(ChargeItemRow.id.in_(keys)).all()}
    parent_ids = {item.parent_id for item in items.values() if item.parent_id}
    parents = {
        row.id: row.name
        for row in db.query(ChargeItemRow).filter(ChargeItemRow.id.in_(parent_ids)).all()
    } if parent_ids else {}
    lines: list[tuple[str, float | None, float, str, bool]] = []
    marks = evaluated or {}
    for item_id, item in items.items():
        parent = parents.get(item.parent_id) if item.parent_id else None
        label = f"{parent} - {item.name}" if parent else item.name
        unit = ""
        if item.unit_id is not None:
            measure = db.get(MeasureUnitRow, item.unit_id)
            unit = measure.name if measure is not None and measure.deleted_at is None else ""
        before = previous.get(item_id, 0) if previous is not None else None
        after = current.get(item_id, 0)
        marked = bool(marks.get(item_id))
        if before is None and after == 0 and not marked:
            continue
        if before is not None and before == 0 and after == 0 and not marked:
            continue
        lines.append((label, before, after, unit, marked))
    lines.sort(key=lambda line: line[0].casefold())
    return lines


def client_contract_lines(lines: list[tuple]) -> list[tuple]:
    return [line for line in lines if len(line) <= 4 or line[4]]


def deliver_work_contract(
    db: Session,
    work: WorkRow,
    *,
    updated: bool,
    previous: dict[int, float] | None = None,
    quantities: dict[int, float] | None = None,
    saved: str | None = None,
) -> str:
    label = saved or ("Partidas actualizadas" if updated else "Obra guardada")
    try:
        emails, phones = admin_notice_contacts(db)
        company_phone = phones[0] if phones else ""
        current = quantities if quantities is not None else charge_quantities(db, work.id)
        lines = client_contract_lines(
            contract_lines(db, current, previous if updated else None, charge_flags(db, work.id))
        )
        address = shorten_address(work.address) or work.address
        pdf = contract_pdf(
            updated=updated,
            client_name=work.client_name,
            client_phone=work.client_phone,
            address=address,
            shift_start=work.shift_start,
            shift_end=work.shift_end,
            work_days=work.work_days,
            starts_on=work.starts_on or "",
            lines=lines,
        )
        return notify_work_contract(
            work_id=work.id,
            client_phone=work.client_phone,
            company_phone=company_phone,
            client_name=work.client_name,
            address=address,
            lines=lines,
            pdf=pdf,
            updated=updated,
            saved=label,
            emails=emails,
            phones=phones,
        )
    except Exception as exc:
        return f"{label}. No se pudo enviar el contrato: {exc}"


def save_work_charges(db: Session, work: WorkRow, charges: list[WorkChargeOut]) -> None:
    db.query(WorkItemRow).filter(WorkItemRow.work_id == work.id).delete()
    seen: set[int] = set()
    for charge in charges:
        item_id = num(charge.itemId)
        item = db.get(ChargeItemRow, item_id) if item_id else None
        if item is None or item.deleted_at is not None or item.id in seen:
            continue
        if not math.isfinite(charge.quantity) or charge.quantity < 0:
            fail(400, "La cantidad de la partida no puede ser negativa.")
        charge.quantity = round(float(charge.quantity), 2)
        if charge.quantity == 0 and not charge.evaluate:
            continue
        seen.add(item.id)
        db.add(WorkItemRow(work_id=work.id, item_id=item.id, quantity=charge.quantity, evaluate=1 if charge.evaluate else 0))


def price_map(db: Session) -> dict[int, list[ItemPriceOut]]:
    grouped: dict[int, list[ItemPriceOut]] = {}
    for row in db.query(UserItemPriceRow).all():
        grouped.setdefault(row.user_id, []).append(ItemPriceOut(itemId=str(row.item_id), amount=row.amount))
    return grouped


def item_prices(db: Session, user_id: int) -> list[ItemPriceOut]:
    return price_map(db).get(user_id, [])


def priced_account(db: Session, row: AccountRow) -> AccountOut:
    return account_out(row, item_prices(db, row.id))


def save_item_prices(db: Session, user: AccountRow, prices: list[ItemPriceOut]) -> None:
    db.query(UserItemPriceRow).filter(UserItemPriceRow.user_id == user.id).delete()
    if user.rol_id not in {ROLE_SITE_LEAD, ROLE_HELPER}:
        return
    seen: set[int] = set()
    for price in prices:
        item_id = num(price.itemId)
        item = db.get(ChargeItemRow, item_id) if item_id else None
        if item is None or item.deleted_at is not None or item.id in seen:
            continue
        if price.amount < 0:
            fail(400, "El precio de la partida no puede ser negativo.")
        seen.add(item.id)
        db.add(UserItemPriceRow(user_id=user.id, item_id=item.id, amount=price.amount))


def num(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def place(address: str) -> tuple[float, float]:
    try:
        return locate_address(address)
    except AddressNotFound as error:
        fail(400, str(error))


def chosen_place(body: WorkBody) -> tuple[float, float]:
    if body.latitude is not None and body.longitude is not None and math.isfinite(body.latitude) and math.isfinite(body.longitude):
        return body.latitude, body.longitude
    return place(body.address)


def login_account(body: LoginBody, db: Session, secret: str) -> LoginResult:
    email = body.email.strip().lower()
    account = db.query(AccountRow).filter(AccountRow.email == email, AccountRow.deleted_at.is_(None)).one_or_none()
    if account is None or account.status_id == STATUS_ACCOUNT_INACTIVE or not verify_password(body.password, account.password_hash):
        fail(401, "Correo o contraseña incorrectos.")
    return LoginResult(token=create_token(str(account.id), secret), account=priced_account(db, account))


@router.get("/auth/me", response_model=AccountOut)
def me(account: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> AccountOut:
    return priced_account(db, account)


@router.get("/works", response_model=list[WorkOut])
def list_works(account: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[WorkOut]:
    rows = db.query(WorkRow).filter(WorkRow.deleted_at.is_(None)).all()
    if field_role(account):
        allowed = {
            item.work_id
            for item in db.query(WorkScheduleRow).filter(
                WorkScheduleRow.user_id == account.id,
                WorkScheduleRow.deleted_at.is_(None),
            )
        }
        rows = [row for row in rows if row.id in allowed]
    pending = pending_counts(db)
    charges = work_charge_map(db)
    waiting = {
        item.work_id
        for item in db.query(ChargeChangeRow).filter(ChargeChangeRow.status == "pending")
    }
    listed = []
    for row in rows:
        result = published_work(row, pending, charges.get(row.id, []))
        result.pendingChange = row.id in waiting
        listed.append(result)
    return listed


@router.get("/works/{work_id}/calendar/{month}", response_model=CalendarOut)
def work_calendar(
    work_id: str,
    month: str,
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> CalendarOut:
    if re.fullmatch(r"\d{4}-\d{2}", month) is None:
        fail(400, "Indica el mes con formato AAAA-MM.")
    year_text, month_text = month.split("-")
    year, month_number = int(year_text), int(month_text)
    if month_number < 1 or month_number > 12:
        fail(400, "Indica el mes con formato AAAA-MM.")
    work_key = num(work_id)
    work = db.get(WorkRow, work_key) if work_key else None
    if work is None or work.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    if field_role(account):
        assigned = db.query(WorkScheduleRow).filter(
            WorkScheduleRow.work_id == work.id,
            WorkScheduleRow.user_id == account.id,
            WorkScheduleRow.deleted_at.is_(None),
        ).one_or_none()
        if assigned is None:
            fail(403, "No tienes acceso a esta obra.")
    users = {row.id: row for row in db.query(UserRow).all()}
    arrivals = [
        row for row in db.query(TimeClockRow).filter(TimeClockRow.work_id == work.id)
        if row.arrive_date[:7] == month
    ]
    _, last_day = calendar.monthrange(year, month_number)
    days = []
    for day in range(1, last_day + 1):
        date = f"{month}-{day:02d}"
        marks = []
        for row in arrivals:
            if row.arrive_date != date:
                continue
            person = users.get(row.user_id)
            name = person.name if person else "Persona"
            latitude, longitude = clock_coordinates(row.location)
            marks.append({
                "workerName": name,
                "at": clock_moment(row),
                "latitude": latitude,
                "longitude": longitude,
                "photoDataUrl": row.photo,
            })
        days.append({"date": date, "arrivals": marks})
    return CalendarOut(workId=str(work.id), month=month, days=days)


@router.post("/works/locate", response_model=LocateOut)
def locate_work(body: LocateBody, _: AccountRow = Depends(require_admin)) -> LocateOut:
    latitude, longitude = place(body.address)
    return LocateOut(latitude=latitude, longitude=longitude)


@router.post("/works/suggest", response_model=list[PlaceOut])
def suggest_work(body: LocateBody, _: AccountRow = Depends(require_admin)) -> list[PlaceOut]:
    return [
        PlaceOut(label=item.label, latitude=item.latitude, longitude=item.longitude)
        for item in suggest_addresses(body.address)
    ]


@router.post("/works", response_model=WorkOut)
def create_work(body: WorkBody, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> WorkOut:
    message = work_fields_error(body)
    if message:
        fail(400, message)
    latitude, longitude = chosen_place(body)
    row = WorkRow(
        status_id=STATUS_ACTIVE,
        latitude=latitude,
        longitude=longitude,
        names=body.name.strip(),
        address=body.address.strip(),
        shift_start=body.shiftStart,
        shift_end=body.shiftEnd,
        arrival_time=body.arrivalTime.strip(),
        planned_hours=shift_hours(body.shiftStart, body.shiftEnd),
        work_days=body.workDays,
        palmeta_count=body.palmetaCount,
        square_meters=body.squareMeters,
        client_name=body.clientName.strip(),
        client_phone=body.clientPhone.strip(),
        apartment=body.apartment.strip(),
        crew_note=body.crewNote.strip(),
        work_notice=body.workNotice.strip(),
        starts_on=body.startsOn.strip(),
        day_count=body.dayCount,
        schedule_dates=body.scheduleDates.strip(),
        finish_sample=body.finishSample.strip(),
        tint_sample=body.tintSample.strip(),
    )
    db.add(row)
    db.flush()
    save_work_charges(db, row, body.charges)
    db.commit()
    db.refresh(row)
    result = published_work(row, pending_counts(db), work_charges(db, row.id))
    result.notice = deliver_work_contract(db, row, updated=False)
    return result


@router.put("/works/{work_id}", response_model=WorkOut)
def update_work(
    work_id: str,
    body: WorkBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WorkOut:
    row = db.get(WorkRow, num(work_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    message = work_fields_error(body)
    if message:
        fail(400, message)
    latitude, longitude = chosen_place(body)
    row.name = body.name.strip()
    row.address = body.address.strip()
    row.latitude = latitude
    row.longitude = longitude
    row.shift_start = body.shiftStart
    row.shift_end = body.shiftEnd
    row.arrival_time = body.arrivalTime.strip()
    row.planned_hours = shift_hours(body.shiftStart, body.shiftEnd)
    row.work_days = body.workDays
    row.palmeta_count = body.palmetaCount
    row.square_meters = body.squareMeters
    row.client_name = body.clientName.strip()
    row.client_phone = body.clientPhone.strip()
    row.apartment = body.apartment.strip()
    row.crew_note = body.crewNote.strip()
    row.work_notice = body.workNotice.strip()
    row.starts_on = body.startsOn.strip()
    row.day_count = body.dayCount
    row.schedule_dates = body.scheduleDates.strip()
    row.finish_sample = body.finishSample.strip()
    row.tint_sample = body.tintSample.strip()
    save_work_charges(db, row, body.charges)
    db.commit()
    db.refresh(row)
    result = published_work(row, pending_counts(db), work_charges(db, row.id))
    result.notice = "Obra actualizada."
    return result


def work_fields_error(body: WorkBody) -> str | None:
    return work_error(
        body.name,
        body.address,
        body.shiftStart,
        body.shiftEnd,
        body.plannedHours,
        body.workDays,
        body.palmetaCount,
        body.squareMeters,
        body.clientName,
        body.clientPhone,
        body.apartment,
        body.crewNote,
        body.workNotice,
        body.startsOn,
        body.dayCount,
        body.scheduleDates,
        body.finishSample,
        body.tintSample,
        body.arrivalTime,
    )


def proposed_quantities(db: Session, charges: list[WorkChargeOut]) -> dict[int, float]:
    seen: set[int] = set()
    result: dict[int, float] = {}
    for charge in charges:
        item_id = num(charge.itemId)
        item = db.get(ChargeItemRow, item_id) if item_id else None
        if item is None or item.deleted_at is not None or item.id in seen:
            continue
        if not math.isfinite(charge.quantity) or charge.quantity < 0:
            fail(400, "La cantidad de la partida no puede ser negativa.")
        quantity = round(float(charge.quantity), 2)
        if quantity == 0:
            continue
        seen.add(item.id)
        result[item.id] = quantity
    return result


def stored_quantities(raw: str) -> dict[int, float]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return {}
    result: dict[int, float] = {}
    if not isinstance(payload, list):
        return result
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            result[int(item["itemId"])] = float(item["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
    return result


def charge_change_lines(db: Session, before: dict[int, float], after: dict[int, float]) -> list[ChargeChangeLineOut]:
    keys = set(before) | set(after)
    items = {row.id: row for row in db.query(ChargeItemRow).filter(ChargeItemRow.id.in_(keys)).all()} if keys else {}
    lines: list[ChargeChangeLineOut] = []
    for item_id in keys:
        previous = before.get(item_id, 0)
        quantity = after.get(item_id, 0)
        if previous == quantity:
            continue
        item = items.get(item_id)
        label = item.name if item is not None else str(item_id)
        lines.append(ChargeChangeLineOut(itemId=str(item_id), label=label, before=previous, after=quantity))
    lines.sort(key=lambda line: line.label.casefold())
    return lines


def charge_change_out(db: Session, row: ChargeChangeRow) -> ChargeChangeOut:
    return ChargeChangeOut(
        id=str(row.id),
        workId=str(row.work_id),
        status=row.status,
        lines=charge_change_lines(db, stored_quantities(row.before_quantities), stored_quantities(row.proposed)),
        createdAt=row.created_at.isoformat(),
        decidedAt=None if row.decided_at is None else row.decided_at.isoformat(),
    )


def pending_charge_change(db: Session, work_id: int) -> ChargeChangeRow | None:
    return (
        db.query(ChargeChangeRow)
        .filter(ChargeChangeRow.work_id == work_id, ChargeChangeRow.status == "pending")
        .first()
    )


@router.put("/works/{work_id}/charges", response_model=WorkOut)
def update_work_charges(
    work_id: str,
    body: WorkChargesBody,
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> WorkOut:
    row = db.get(WorkRow, num(work_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    if account.rol_id != ROLE_SITE_LEAD:
        fail(403, "Solo el maestro de obra puede cambiar las partidas.")
    assigned = db.query(WorkScheduleRow).filter(
        WorkScheduleRow.work_id == row.id,
        WorkScheduleRow.user_id == account.id,
        WorkScheduleRow.deleted_at.is_(None),
    ).first()
    if assigned is None:
        fail(403, "Solo puedes cambiar las partidas de tus obras.")
    previous = charge_quantities(db, row.id)
    proposed = proposed_quantities(db, body.charges)
    result = published_work(row, pending_counts(db), work_charges(db, row.id))
    if previous == proposed:
        return result
    merged = dict(previous)
    for charge in body.charges:
        item_id = num(charge.itemId)
        if item_id:
            merged[item_id] = round(float(charge.quantity), 2) if math.isfinite(charge.quantity) else 0
    current = (
        db.query(ChargeChangeRow)
        .filter(ChargeChangeRow.work_id == row.id, ChargeChangeRow.status == "pending")
        .first()
    )
    payload = json.dumps([{"itemId": str(item_id), "quantity": quantity} for item_id, quantity in sorted(proposed.items())])
    before_payload = json.dumps([{"itemId": str(item_id), "quantity": quantity} for item_id, quantity in sorted(previous.items())])
    if current is None:
        current = ChargeChangeRow(work_id=row.id, user_id=account.id, status="pending")
        db.add(current)
    current.user_id = account.id
    current.before_quantities = before_payload
    current.proposed = payload
    label = (row.client_name or "").strip() or row.names
    add_alert(db, None, "modified", f"El maestro ha solicitado cambios en la obra {label}.", row.id)
    db.commit()
    result.pendingChange = True
    result.notice = deliver_work_contract(
        db,
        row,
        updated=True,
        previous=previous,
        quantities=merged,
        saved="Cambios enviados",
    )
    return result


@router.get("/works/{work_id}/charge-change", response_model=ChargeChangeOut)
def read_charge_change(
    work_id: str,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ChargeChangeOut:
    work = db.get(WorkRow, num(work_id))
    if work is None or work.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    change = pending_charge_change(db, work.id)
    if change is None:
        fail(404, "No hay cambios en espera.")
    return charge_change_out(db, change)


@router.get("/works/{work_id}/charge-log", response_model=list[ChargeChangeOut])
def read_charge_log(
    work_id: str,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ChargeChangeOut]:
    work = db.get(WorkRow, num(work_id))
    if work is None or work.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    rows = (
        db.query(ChargeChangeRow)
        .filter(ChargeChangeRow.work_id == work.id, ChargeChangeRow.status != "pending")
        .order_by(ChargeChangeRow.id.desc())
        .all()
    )
    return [charge_change_out(db, row) for row in rows]


@router.post("/works/{work_id}/charge-change/accept", response_model=WorkOut)
def accept_charge_change(
    work_id: str,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WorkOut:
    work = db.get(WorkRow, num(work_id))
    if work is None or work.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    change = pending_charge_change(db, work.id)
    if change is None:
        fail(404, "No hay cambios en espera.")
    proposed = stored_quantities(change.proposed)
    flags = charge_flags(db, work.id)
    kept = {
        item_id: quantity
        for item_id, quantity in proposed.items()
    }
    for item_id, marked in flags.items():
        if marked and item_id not in kept:
            kept[item_id] = 0
    save_work_charges(
        db,
        work,
        [
            WorkChargeOut(itemId=str(item_id), quantity=quantity, evaluate=flags.get(item_id, False))
            for item_id, quantity in kept.items()
        ],
    )
    change.status = "accepted"
    change.decided_at = utcnow()
    db.commit()
    db.refresh(work)
    result = published_work(work, pending_counts(db), work_charges(db, work.id))
    result.notice = "Cambios aceptados."
    return result


@router.post("/works/{work_id}/charge-change/reject", response_model=WorkOut)
def reject_charge_change(
    work_id: str,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WorkOut:
    work = db.get(WorkRow, num(work_id))
    if work is None or work.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    change = pending_charge_change(db, work.id)
    if change is None:
        fail(404, "No hay cambios en espera.")
    change.status = "rejected"
    change.decided_at = utcnow()
    db.commit()
    db.refresh(work)
    result = published_work(work, pending_counts(db), work_charges(db, work.id))
    result.notice = "Cambios rechazados."
    return result


@router.put("/works/{work_id}/status", response_model=WorkOut)
def update_work_status(
    work_id: str,
    body: WorkStatusBody,
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> WorkOut:
    if account.rol_id == ROLE_SITE_LEAD:
        if body.status != "completed":
            fail(403, "Solo puedes marcar la obra como finalizada.")
    elif account.rol_id != ROLE_ADMIN:
        fail(403, "No puedes cambiar el estado de la obra.")
    row = db.get(WorkRow, num(work_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    status_id = CODE_STATUS.get(body.status)
    if status_id is None:
        fail(400, "El estado de la obra no es válido.")
    row.status_id = status_id
    if account.rol_id == ROLE_SITE_LEAD:
        add_alert(db, None, "completed", f"{account.name} marcó {row.client_name or row.names} como finalizada.")
    db.commit()
    db.refresh(row)
    return published_work(row, pending_counts(db), work_charges(db, row.id))


@router.post("/works/{work_id}/deactivate", response_model=WorkOut)
def deactivate_work(work_id: str, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> WorkOut:
    row = db.get(WorkRow, num(work_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    row.status_id = STATUS_DELIVERED
    db.commit()
    db.refresh(row)
    return published_work(row, pending_counts(db), work_charges(db, row.id))


@router.delete("/works/{work_id}", status_code=204)
def delete_work(work_id: str, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    row = db.get(WorkRow, num(work_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    row.deleted_at = row.updated_at
    from app.models import utcnow
    row.deleted_at = utcnow()
    db.query(WorkScheduleRow).filter(WorkScheduleRow.work_id == row.id).update({WorkScheduleRow.deleted_at: row.deleted_at})
    db.commit()


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> list[AssignmentOut]:
    query = db.query(WorkScheduleRow).filter(WorkScheduleRow.deleted_at.is_(None))
    if field_role(account):
        query = query.filter(WorkScheduleRow.user_id == account.id)
    return [assignment_out(row) for row in query.all()]


def assignment_address(work: WorkRow) -> str:
    address = shorten_address(work.address) or work.address
    apartment = (work.apartment or "").strip()
    if apartment:
        address = f"{address}, depto {apartment}"
    return address


def deliver_assignment_notice(db: Session, work: WorkRow, user_ids: list[int]) -> None:
    if not user_ids:
        return
    try:
        lines = contract_lines(db, charge_quantities(db, work.id), None, charge_flags(db, work.id))
        partidas = format_assignment_partidas([(name, quantity, unit) for name, _previous, quantity, unit, _marked in lines])
        address = assignment_address(work)
        label = (work.client_name or "").strip() or work.name
        for user_id in user_ids:
            person = db.get(UserRow, user_id)
            if person is None:
                continue
            notify_worker_assignment(
                phone=person.phone,
                worker_name=person.name,
                work_name=label,
                address=address,
                latitude=work.latitude,
                longitude=work.longitude,
                partidas=partidas,
                work_notice=work.work_notice or "",
                crew_note=work.crew_note or "",
                shift_start=work.shift_start or "",
                shift_end=work.shift_end or "",
                work_days=work.work_days or "",
                schedule_dates=work.schedule_dates or "",
            )
    except Exception:
        return


@router.put("/works/{work_id}/crew", response_model=list[AssignmentOut])
def replace_crew(
    work_id: str,
    body: CrewBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AssignmentOut]:
    work_key = num(work_id)
    work = db.get(WorkRow, work_key)
    if work is None:
        fail(404, "Obra no encontrada.")
    previous_crew = {
        row.user_id
        for row in db.query(WorkScheduleRow).filter(WorkScheduleRow.work_id == work_key, WorkScheduleRow.deleted_at.is_(None)).all()
    }
    members = body.members or [CrewMemberBody(workerId=item) for item in body.workerIds]
    unique: dict[int, CrewMemberBody] = {}
    for member in members:
        user_key = num(member.workerId)
        person = db.get(UserRow, user_key)
        if person is None or person.deleted_at is not None:
            fail(400, "La dotación incluye un usuario que no existe.")
        start = member.startDate.strip()
        if start and re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) is None:
            fail(400, "La fecha de inicio no es válida.")
        if member.dayCount < 0:
            fail(400, "Los días de la asignación no pueden ser negativos.")
        excluded = []
        for item in member.excludedDates:
            day = item.strip()
            if day and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None:
                fail(400, "La fecha excluida no es válida.")
            if day and day not in excluded:
                excluded.append(day)
        role_id = member.roleId if member.roleId in (ROLE_SITE_LEAD, ROLE_HELPER) else person.rol_id
        if role_id not in (ROLE_SITE_LEAD, ROLE_HELPER):
            fail(400, "Indica si en esta obra es maestro o ayudante.")
        unique[person.id] = CrewMemberBody(
            workerId=str(person.id),
            startDate=start,
            dayCount=member.dayCount,
            excludedDates=excluded,
            roleId=role_id,
        )
    db.query(WorkScheduleRow).filter(WorkScheduleRow.work_id == work_key).delete()
    db.add_all(
        WorkScheduleRow(
            work_id=work_key,
            user_id=user_id,
            start_date=member.startDate,
            day_count=member.dayCount,
            excluded_dates=",".join(member.excludedDates),
            role_id=member.roleId,
        )
        for user_id, member in unique.items()
    )
    work_name = work.client_name or work.names
    added = [user_id for user_id in unique if user_id not in previous_crew]
    for user_id in added:
        add_alert(db, user_id, "assigned", f"Te agregaron a la obra {work_name}.")
    for user_id in previous_crew:
        if user_id not in unique:
            add_alert(db, user_id, "removed", f"Te quitaron de la obra {work_name}.")
    db.commit()
    deliver_assignment_notice(db, work, added)
    rows = db.query(WorkScheduleRow).filter(WorkScheduleRow.work_id == work_key, WorkScheduleRow.deleted_at.is_(None)).all()
    return [assignment_out(row) for row in rows]


@router.get("/arrivals", response_model=list[ArrivalOut])
def list_arrivals(account: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[ArrivalOut]:
    query = db.query(TimeClockRow)
    if field_role(account):
        query = query.filter(TimeClockRow.user_id == account.id)
    users = {row.id: row for row in db.query(UserRow).all()}
    works = {row.id: row for row in db.query(WorkRow).all()}
    rows = query.order_by(TimeClockRow.arrive_date.desc(), TimeClockRow.arrive_time.desc()).all()
    return [
        arrival_out(
            row,
            users[row.user_id].name if row.user_id in users else "Persona",
            works[row.work_id].name if row.work_id in works else "Obra",
        )
        for row in rows
    ]


@router.post("/arrivals", response_model=ArrivalOut)
def register_arrival(
    body: ArrivalBody,
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> ArrivalOut:
    user_key = num(body.workerId)
    work_key = num(body.workId)
    if field_role(account) and user_key != account.id:
        fail(403, "Solo puedes marcar tu propia llegada.")
    work = db.get(WorkRow, work_key)
    person = db.get(UserRow, user_key)
    assigned = person is not None and db.query(WorkScheduleRow).filter(
        WorkScheduleRow.work_id == work_key,
        WorkScheduleRow.user_id == person.id,
        WorkScheduleRow.deleted_at.is_(None),
    ).first() is not None
    manual = account.rol_id == ROLE_ADMIN
    message = arrival_block_reason(
        work_active=work is not None and work.deleted_at is None and work.status in {"active", "working"},
        worker_active=person is not None and person.active,
        assigned=assigned,
        photo_data_url=body.photoDataUrl,
        latitude=body.latitude,
        longitude=body.longitude,
        require_location=not manual,
    )
    if message or work is None or person is None:
        fail(400, message or "No se pudo registrar la llegada.")
    if not manual and (body.latitude is None or body.longitude is None or not on_site(work.latitude, work.longitude, body.latitude, body.longitude)):
        fail(400, OFF_SITE_MESSAGE if body.latitude is not None and body.longitude is not None else "Activa el GPS para registrar la llegada.")
    moment = body.at
    if len(moment) < 16 or moment[4] != "-" or moment[7] != "-" or moment[10] != "T":
        fail(400, "Indica el día y la hora.")
    location = f"{body.latitude},{body.longitude}" if body.latitude is not None and body.longitude is not None else ""
    row = TimeClockRow(
        work_id=work.id,
        user_id=person.id,
        location=location,
        photo=body.photoDataUrl,
        arrive_date=moment[:10],
        arrive_time=moment[11:19] if len(moment) >= 19 else "00:00:00",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return arrival_out(row, person.name, work.name)


def required_account_details(body: AccountBody | ProfileBody) -> str | None:
    if not body.address.strip():
        return "Indica la dirección."
    if len(phone_digits(body.phone)) < 8:
        return "Indica un teléfono válido."
    if not body.accountHolderDocumentId.strip():
        return "Indica el RUT del titular de la cuenta."
    if not body.accountHolder.strip():
        return "Indica el titular."
    if not body.bankId.strip():
        return "Selecciona un banco."
    if not body.accountTypeId.strip():
        return "Selecciona el tipo de cuenta."
    if not body.accountNumber.strip():
        return "Indica el número de cuenta."
    return None


def store_bank_details(db: Session, row: AccountRow, body: AccountBody) -> str | None:
    if body.roleId == ROLE_ADMIN and not body.bankId.strip() and not body.accountTypeId.strip():
        return None
    bank_message = assign_bank(db, row, body.bankId)
    if bank_message:
        return bank_message
    return assign_account_type(db, row, body.accountTypeId)


def assign_bank(db: Session, row: AccountRow, bank_id: str) -> str | None:
    raw = bank_id.strip()
    if not raw.isdigit():
        return "Selecciona un banco."
    bank = db.get(BankRow, int(raw))
    if bank is None or bank.deleted_at is not None:
        return "El banco no es válido."
    row.bank_id = bank.id
    row.bank = bank.name
    return None


def assign_account_type(db: Session, row: AccountRow, type_id: str) -> str | None:
    raw = type_id.strip()
    if not raw.isdigit():
        return "Selecciona el tipo de cuenta."
    account_type = db.get(BankAccountTypeRow, int(raw))
    if account_type is None or account_type.deleted_at is not None:
        return "El tipo de cuenta no es válido."
    row.account_type_id = account_type.id
    row.account_type = account_type.name
    return None


@router.get("/bank-account-types", response_model=list[BankOut])
def list_bank_account_types(_: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[BankOut]:
    rows = db.query(BankAccountTypeRow).filter(BankAccountTypeRow.deleted_at.is_(None)).order_by(BankAccountTypeRow.name).all()
    return [BankOut(id=str(row.id), name=row.name) for row in rows]


@router.get("/banks", response_model=list[BankOut])
def list_banks(_: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[BankOut]:
    rows = db.query(BankRow).filter(BankRow.deleted_at.is_(None)).order_by(BankRow.name).all()
    return [BankOut(id=str(row.id), name=row.name) for row in rows]


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(account: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[AccountOut]:
    prices = price_map(db)
    if field_role(account):
        return [account_out(account, prices.get(account.id, []))]
    return [account_out(row, prices.get(row.id, [])) for row in db.query(AccountRow).filter(AccountRow.deleted_at.is_(None)).all()]


@router.post("/accounts", response_model=AccountOut)
def create_account(body: AccountBody, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> AccountOut:
    message = account_error(body, creating=True)
    if message:
        fail(400, message)
    if db.query(AccountRow).filter(AccountRow.email == body.email.strip().lower()).first():
        fail(400, "Ya existe una cuenta con ese correo.")
    first, last = person_names(body)
    row = AccountRow(
        rol_id=body.roleId,
        names=first,
        lastnames=last,
        phone=body.phone.strip(),
        address=body.address.strip(),
        document_id=body.documentId.strip(),
        photo=body.photoDataUrl,
        account_number=body.accountNumber.strip(),
        account_holder=body.accountHolder.strip(),
        account_holder_document_id=body.accountHolderDocumentId.strip(),
        email=body.email.strip().lower(),
        password_hash=hash_password(body.password),
        hourly_rate=body.hourlyRate if body.roleId == ROLE_HELPER else 0,
        palmeta_cost=body.palmetaCost if body.roleId == ROLE_SITE_LEAD else 0,
        status_id=account_status_id(body.statusId),
    )
    bank_message = store_bank_details(db, row, body)
    if bank_message:
        fail(400, bank_message)
    db.add(row)
    db.flush()
    save_item_prices(db, row, body.itemPrices)
    db.commit()
    db.refresh(row)
    return priced_account(db, row)


@router.put("/accounts/me", response_model=AccountOut)
def update_profile(
    body: ProfileBody,
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> AccountOut:
    if account.rol_id != ROLE_ADMIN:
        fail(403, "Solo el administrador puede cambiar estos datos.")
    message = person_fields_error(body.phone, body.photoDataUrl)
    if message:
        fail(400, message)
    first, last = person_names(body)
    email = body.email.strip().lower()
    if len(first) < 2:
        fail(400, "Indica el nombre.")
    if "@" not in email:
        fail(400, "Indica un correo válido.")
    taken = db.query(AccountRow).filter(AccountRow.email == email, AccountRow.id != account.id).first()
    if taken:
        fail(400, "Ya existe una cuenta con ese correo.")
    account.names = first
    account.lastnames = last
    account.email = email
    account.phone = body.phone.strip()
    account.address = body.address.strip()
    account.document_id = body.documentId.strip()
    account.photo = body.photoDataUrl
    details = required_account_details(body)
    if details:
        fail(400, details)
    bank_message = assign_bank(db, account, body.bankId)
    if bank_message:
        fail(400, bank_message)
    type_message = assign_account_type(db, account, body.accountTypeId)
    if type_message:
        fail(400, type_message)
    account.account_number = body.accountNumber.strip()
    account.account_holder = body.accountHolder.strip()
    account.account_holder_document_id = body.accountHolderDocumentId.strip()
    db.commit()
    db.refresh(account)
    return priced_account(db, account)


def admin_notice_contacts(db: Session) -> tuple[list[str], list[str]]:
    emails: list[str] = []
    phones: list[str] = []
    rows = db.query(AccountRow).filter(AccountRow.rol_id == ROLE_ADMIN, AccountRow.deleted_at.is_(None)).all()
    for row in rows:
        if not row.active:
            continue
        email = row.email.strip()
        if "@" in email and email not in emails:
            emails.append(email)
        phone = row.phone.strip()
        if len(phone_digits(phone)) >= 8 and phone not in phones:
            phones.append(phone)
    return emails, phones


def contact_values(db: Session, kind: str) -> list[str]:
    return [row.value for row in db.query(NotificationContactRow).filter(NotificationContactRow.kind == kind).order_by(NotificationContactRow.id)]


def published_settings(db: Session) -> SettingOut:
    row = db.get(SettingRow, 1)
    phones = contact_values(db, "phone")
    if not phones and row and row.company_phone:
        phones = [row.company_phone]
    return SettingOut(
        companyPhone=row.company_phone if row else "",
        emails=contact_values(db, "email"),
        phones=phones,
        graceMinutes=row.grace_minutes if row else 0,
        leadLatePerMinute=row.lead_late_per_minute if row else 0,
    )


def replace_contacts(db: Session, kind: str, values: list[str]) -> None:
    db.query(NotificationContactRow).filter(NotificationContactRow.kind == kind).delete()
    for value in values:
        db.add(NotificationContactRow(kind=kind, value=value))


@router.get("/statuses", response_model=list[StatusOut])
def list_statuses(_: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> list[StatusOut]:
    rows = db.query(StatusRow).filter(StatusRow.deleted_at.is_(None)).order_by(StatusRow.id).all()
    return [StatusOut(id=str(row.id), name=row.name, scope=row.scope or "work") for row in rows]


@router.get("/settings", response_model=SettingOut)
def get_settings(_: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> SettingOut:
    return published_settings(db)


@router.put("/settings", response_model=SettingOut)
def update_settings(
    body: SettingBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettingOut:
    emails = [item.strip() for item in body.emails or [] if item.strip()] if body.emails is not None else None
    phones = [item.strip() for item in body.phones or [] if item.strip()] if body.phones is not None else None
    if emails is not None and any("@" not in item or "." not in item.split("@")[-1] for item in emails):
        fail(400, "Indica un correo válido.")
    if phones is not None and any(len(phone_digits(item)) < 8 for item in phones):
        fail(400, "Indica un celular válido.")
    if body.companyPhone.strip() and phones is None and len(phone_digits(body.companyPhone)) < 8:
        fail(400, "Indica un teléfono válido.")
    if body.graceMinutes is not None and (body.graceMinutes < 0 or body.graceMinutes > 240):
        fail(400, "El tiempo de gracia debe estar entre 0 y 240 minutos.")
    if body.leadLatePerMinute is not None and (body.leadLatePerMinute < 0 or body.leadLatePerMinute > 1_000_000):
        fail(400, "El monto por minuto debe estar entre 0 y 1.000.000.")
    row = db.get(SettingRow, 1)
    if row is None:
        row = SettingRow(company_phone="")
        db.add(row)
        db.flush()
    if phones is not None:
        replace_contacts(db, "phone", phones)
        row.company_phone = phones[0] if phones else ""
    elif body.companyPhone.strip():
        row.company_phone = body.companyPhone.strip()
    if emails is not None:
        replace_contacts(db, "email", emails)
    if body.graceMinutes is not None:
        row.grace_minutes = body.graceMinutes
    if body.leadLatePerMinute is not None:
        row.lead_late_per_minute = body.leadLatePerMinute
    db.commit()
    return published_settings(db)


@router.post("/jobs/late-arrivals")
def run_late_arrivals(_: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    from app.late_arrivals import chile_now, remind_late_workers

    sent = remind_late_workers(db, chile_now())
    db.commit()
    return {"sent": sent}


@router.post("/works/{work_id}/palmeta-changes", response_model=PalmetaChangeOut)
def request_palmeta_change(
    work_id: str,
    body: PalmetaChangeBody,
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> PalmetaChangeOut:
    if account.rol_id != ROLE_SITE_LEAD:
        fail(403, "Solo el maestro de obra puede cambiar las palmetas.")
    work = db.get(WorkRow, num(work_id))
    if work is None or work.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    assigned = db.query(WorkScheduleRow).filter(
        WorkScheduleRow.work_id == work.id,
        WorkScheduleRow.user_id == account.id,
        WorkScheduleRow.deleted_at.is_(None),
    ).first()
    if assigned is None:
        fail(403, "Solo puedes cambiar las palmetas de tus obras.")
    message = palmeta_increase_error(work.palmeta_count, body.quantity)
    if message:
        fail(400, message)
    if len(phone_digits(work.client_phone)) < 8:
        fail(400, "La obra no tiene el teléfono del cliente.")
    waiting = db.query(PalmetaChangeRow).filter(
        PalmetaChangeRow.work_id == work.id,
        PalmetaChangeRow.status == "pending",
    ).first()
    if waiting is not None:
        fail(400, "Ya hay un cambio de palmetas esperando la respuesta del cliente.")
    _, admin_phones = admin_notice_contacts(db)
    if not admin_phones:
        fail(400, "Ningún administrador tiene celular.")
    change = PalmetaChangeRow(
        work_id=work.id,
        user_id=account.id,
        previous_count=work.palmeta_count,
        next_count=body.quantity,
        status="pending",
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    pdf = palmeta_change_pdf(
        work_name=work.name,
        address=work.address,
        client_name=work.client_name,
        previous_count=change.previous_count,
        next_count=change.next_count,
        square_meters=work.square_meters,
        unit_cost=account.palmeta_cost,
    )
    notice = notify_palmeta_change(
        change_id=change.id,
        client_phone=work.client_phone,
        company_phones=admin_phones,
        work_name=work.name,
        client_name=work.client_name,
        previous_count=change.previous_count,
        next_count=change.next_count,
        pdf=pdf,
    )
    return PalmetaChangeOut(
        id=str(change.id),
        workId=str(work.id),
        previousCount=change.previous_count,
        nextCount=change.next_count,
        status=change.status,
        message=notice,
    )


@router.put("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: str,
    body: AccountBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AccountOut:
    row = db.get(AccountRow, num(account_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Usuario no encontrado.")
    message = account_error(body, creating=False)
    if message:
        fail(400, message)
    first, last = person_names(body)
    row.names = first
    row.lastnames = last
    row.email = body.email.strip().lower()
    row.phone = body.phone.strip()
    row.address = body.address.strip()
    row.document_id = body.documentId.strip()
    row.photo = body.photoDataUrl
    bank_message = store_bank_details(db, row, body)
    if bank_message:
        fail(400, bank_message)
    row.account_number = body.accountNumber.strip()
    row.account_holder = body.accountHolder.strip()
    row.account_holder_document_id = body.accountHolderDocumentId.strip()
    row.rol_id = body.roleId
    row.hourly_rate = body.hourlyRate if body.roleId == ROLE_HELPER else 0
    row.palmeta_cost = body.palmetaCost if body.roleId == ROLE_SITE_LEAD else 0
    if body.password:
        row.password_hash = hash_password(body.password)
    row.status_id = account_status_id(body.statusId)
    save_item_prices(db, row, body.itemPrices)
    db.commit()
    db.refresh(row)
    return priced_account(db, row)


@router.post("/accounts/{account_id}/deactivate", response_model=AccountOut)
def deactivate_account(
    account_id: str,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AccountOut:
    row = db.get(AccountRow, num(account_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Usuario no encontrado.")
    row.active = False
    db.commit()
    db.refresh(row)
    return priced_account(db, row)


def account_status_id(value: str) -> int:
    if value == str(STATUS_ACCOUNT_INACTIVE):
        return STATUS_ACCOUNT_INACTIVE
    return STATUS_ACCOUNT_ACTIVE


def person_names(body: AccountBody | ProfileBody) -> tuple[str, str]:
    first = body.firstName.strip()
    last = body.lastName.strip()
    if first:
        return first, last
    parts = body.name.strip().split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def person_fields_error(phone: str, photo: str) -> str | None:
    if phone.strip() and len(phone_digits(phone)) < 8:
        return "Indica un teléfono válido."
    if photo and not photo.startswith("data:image/"):
        return "La fotografía no es válida."
    return None


def account_error(body: AccountBody, creating: bool) -> str | None:
    message = person_fields_error(body.phone, body.photoDataUrl)
    if message:
        return message
    first, _last = person_names(body)
    if len(first) < 2:
        return "Indica el nombre."
    if body.roleId not in (ROLE_ADMIN, ROLE_SITE_LEAD, ROLE_HELPER):
        return "El rol no es válido."
    if body.roleId == ROLE_HELPER and body.hourlyRate <= 0:
        return "Indica el valor por hora."
    if creating and len(body.password) < 4:
        return "La contraseña debe tener al menos 4 caracteres."
    if "@" not in body.email:
        return "Indica un correo válido."
    if body.roleId == ROLE_ADMIN:
        if len(phone_digits(body.phone)) < 8:
            return "Indica un teléfono válido."
        return None
    return required_account_details(body)


def span_minutes(value: str) -> int | None:
    if value == "24:00":
        return 24 * 60
    return minutes_of(value)


def block_overlap(db: Session, body: TaskBlockBody, ignore_id: int | None, ignore_ids: set[int] | None = None) -> bool:
    start = span_minutes(body.start)
    end = span_minutes(body.end)
    if start is None or end is None:
        return False
    query = db.query(TaskBlockRow).filter(
        TaskBlockRow.work_id == num(body.workId),
        TaskBlockRow.block_date == body.date,
        TaskBlockRow.deleted_at.is_(None),
    )
    for row in query:
        if ignore_id is not None and row.id == ignore_id:
            continue
        if ignore_ids is not None and row.id in ignore_ids:
            continue
        other_start = span_minutes(row.start_time)
        other_end = span_minutes(row.end_time)
        if other_start is None or other_end is None:
            continue
        if ranges_overlap(start, end, other_start, other_end):
            return True
    return False


def charge_lines(db: Session, parent_id: int) -> list[ChargeItemRow]:
    return db.query(ChargeItemRow).filter(
        ChargeItemRow.parent_id == parent_id,
        ChargeItemRow.deleted_at.is_(None),
    ).order_by(ChargeItemRow.name).all()


def measure_name(db: Session, unit_id: int | None) -> str:
    if unit_id is None:
        return ""
    row = db.get(MeasureUnitRow, unit_id)
    if row is None or row.deleted_at is not None:
        return ""
    return row.name


def assign_unit(db: Session, raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None
    if not value.isdigit():
        fail(400, "Selecciona una unidad de medida.")
    row = db.get(MeasureUnitRow, int(value))
    if row is None or row.deleted_at is not None:
        fail(400, "La unidad de medida no es válida.")
    return row.id


def publish_charge_item(db: Session, row: ChargeItemRow) -> ChargeItemOut:
    lines = charge_lines(db, row.id) if row.kind == "composed" else []
    names = {row.unit_id: measure_name(db, row.unit_id)}
    for line in lines:
        names[line.unit_id] = measure_name(db, line.unit_id)
    return charge_item_out(row, lines, names)


def charge_name_taken(db: Session, name: str, ignore_id: int | None = None) -> bool:
    query = db.query(ChargeItemRow).filter(
        ChargeItemRow.name == name,
        ChargeItemRow.deleted_at.is_(None),
        ChargeItemRow.parent_id.is_(None),
    )
    if ignore_id is not None:
        query = query.filter(ChargeItemRow.id != ignore_id)
    return query.first() is not None


def save_charge_lines(db: Session, parent: ChargeItemRow, body: ChargeItemBody) -> None:
    current = db.query(ChargeItemRow).filter(ChargeItemRow.parent_id == parent.id).all()
    now = utcnow()
    if parent.kind != "composed":
        for row in current:
            if row.deleted_at is None:
                row.deleted_at = now
        return
    if not body.lines:
        fail(400, "Agrega al menos una línea.")
    kept: set[int] = set()
    for line in body.lines:
        name = line.name.strip()
        if len(name) < 3:
            fail(400, "Cada línea debe tener al menos 3 caracteres.")
        unit_id = assign_unit(db, line.unitId)
        key = num(line.id) if line.id else None
        match = next((row for row in current if key is not None and row.id == key), None)
        if match is None:
            match = ChargeItemRow(name=name, kind="simple", parent_id=parent.id, unit_id=unit_id)
            db.add(match)
            db.flush()
        else:
            match.name = name
            match.unit_id = unit_id
            match.deleted_at = None
        kept.add(match.id)
    for row in current:
        if row.id not in kept and row.deleted_at is None:
            row.deleted_at = now


@router.get("/measure-units", response_model=list[BankOut])
def list_measure_units(_: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[BankOut]:
    rows = db.query(MeasureUnitRow).filter(MeasureUnitRow.deleted_at.is_(None)).order_by(MeasureUnitRow.name).all()
    return [BankOut(id=str(row.id), name=row.name) for row in rows]


@router.get("/charge-items", response_model=list[ChargeItemOut])
def list_charge_items(_: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[ChargeItemOut]:
    rows = db.query(ChargeItemRow).filter(
        ChargeItemRow.deleted_at.is_(None),
        ChargeItemRow.parent_id.is_(None),
    ).order_by(ChargeItemRow.position, ChargeItemRow.name).all()
    return [publish_charge_item(db, row) for row in rows]


def next_charge_position(db: Session) -> int:
    rows = db.query(ChargeItemRow.position).filter(
        ChargeItemRow.deleted_at.is_(None),
        ChargeItemRow.parent_id.is_(None),
    ).all()
    if not rows:
        return 0
    return max(int(row[0]) for row in rows) + 1


@router.post("/charge-items", response_model=ChargeItemOut)
def create_charge_item(body: ChargeItemBody, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> ChargeItemOut:
    name = body.name.strip()
    if len(name) < 3:
        fail(400, "El nombre debe tener al menos 3 caracteres.")
    if body.kind not in ("simple", "composed"):
        fail(400, "El tipo de partida no es válido.")
    if charge_name_taken(db, name):
        fail(400, "Ya existe una partida con ese nombre.")
    row = ChargeItemRow(name=name, kind=body.kind, unit_id=assign_unit(db, body.unitId), position=next_charge_position(db))
    db.add(row)
    db.flush()
    save_charge_lines(db, row, body)
    db.commit()
    db.refresh(row)
    return publish_charge_item(db, row)


@router.put("/charge-items/order", response_model=list[ChargeItemOut])
def reorder_charge_items(
    body: ChargeOrderBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ChargeItemOut]:
    rows = db.query(ChargeItemRow).filter(
        ChargeItemRow.deleted_at.is_(None),
        ChargeItemRow.parent_id.is_(None),
    ).all()
    by_id = {str(row.id): row for row in rows}
    if set(body.ids) != set(by_id):
        fail(400, "El orden de las partidas no es válido.")
    for index, item_id in enumerate(body.ids):
        by_id[item_id].position = index
    db.commit()
    ordered = sorted(rows, key=lambda row: row.position)
    return [publish_charge_item(db, row) for row in ordered]


@router.put("/charge-items/{item_id}", response_model=ChargeItemOut)
def update_charge_item(
    item_id: str,
    body: ChargeItemBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ChargeItemOut:
    row = db.get(ChargeItemRow, num(item_id))
    if row is None or row.deleted_at is not None or row.parent_id is not None:
        fail(404, "Partida no encontrada.")
    name = body.name.strip()
    if len(name) < 3:
        fail(400, "El nombre debe tener al menos 3 caracteres.")
    if body.kind not in ("simple", "composed"):
        fail(400, "El tipo de partida no es válido.")
    if charge_name_taken(db, name, row.id):
        fail(400, "Ya existe una partida con ese nombre.")
    row.name = name
    row.unit_id = assign_unit(db, body.unitId)
    row.kind = body.kind
    save_charge_lines(db, row, body)
    db.commit()
    db.refresh(row)
    return publish_charge_item(db, row)


@router.delete("/charge-items/{item_id}", status_code=204)
def delete_charge_item(item_id: str, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    row = db.get(ChargeItemRow, num(item_id))
    if row is None or row.deleted_at is not None or row.parent_id is not None:
        fail(404, "Partida no encontrada.")
    now = utcnow()
    row.deleted_at = now
    for line in charge_lines(db, row.id):
        line.deleted_at = now
    db.commit()


def task_fields(body: TaskBody) -> tuple[str, str, int, int]:
    name = body.name.strip()
    if len(name) < 3:
        fail(400, "El nombre debe tener al menos 3 caracteres.")
    if body.kind not in {"site", "general"}:
        fail(400, "El tipo de tarea no es válido.")
    if body.kind == "site":
        return name, "site", 0, 0
    if body.amount < 0:
        fail(400, "El valor no puede ser negativo.")
    return name, "general", body.amount, 0


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(_: AccountRow = Depends(current_account), db: Session = Depends(get_db)) -> list[TaskOut]:
    rows = db.query(TaskRow).filter(TaskRow.deleted_at.is_(None)).order_by(TaskRow.id).all()
    return [task_out(row) for row in rows]


@router.post("/tasks", response_model=TaskOut)
def create_task(body: TaskBody, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> TaskOut:
    name, kind, amount, extra = task_fields(body)
    row = TaskRow(names=name, kind=kind, amount=amount, extra_amount=extra)
    db.add(row)
    db.commit()
    db.refresh(row)
    return task_out(row)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    body: TaskBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TaskOut:
    row = db.get(TaskRow, num(task_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Tarea no encontrada.")
    name, kind, amount, extra = task_fields(body)
    row.names = name
    row.kind = kind
    row.amount = amount
    row.extra_amount = extra
    db.commit()
    db.refresh(row)
    return task_out(row)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    row = db.get(TaskRow, num(task_id))
    if row is None or row.deleted_at is not None:
        fail(404, "Tarea no encontrada.")
    row.deleted_at = utcnow()
    db.query(TaskBlockRow).filter(TaskBlockRow.task_id == row.id, TaskBlockRow.deleted_at.is_(None)).update(
        {TaskBlockRow.deleted_at: row.deleted_at},
    )
    db.commit()


@router.get("/works/{work_id}/task-blocks/{block_date}", response_model=list[TaskBlockOut])
def list_work_task_blocks(
    work_id: str,
    block_date: str,
    _: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> list[TaskBlockOut]:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", block_date) is None:
        fail(400, "Indica el día con formato AAAA-MM-DD.")
    rows = db.query(TaskBlockRow).filter(
        TaskBlockRow.deleted_at.is_(None),
        TaskBlockRow.work_id == num(work_id),
        TaskBlockRow.block_date == block_date,
    ).order_by(TaskBlockRow.start_time).all()
    return [task_block_out(row) for row in rows]


@router.get("/task-blocks", response_model=list[TaskBlockOut])
def list_task_blocks(
    _: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> list[TaskBlockOut]:
    rows = db.query(TaskBlockRow).filter(TaskBlockRow.deleted_at.is_(None)).order_by(
        TaskBlockRow.block_date,
        TaskBlockRow.start_time,
    ).all()
    return [task_block_out(row) for row in rows]


@router.post("/task-blocks", response_model=TaskBlockOut)
def create_task_block(
    body: TaskBlockBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TaskBlockOut:
    return save_task_block(body, None, db)


@router.put("/task-blocks", response_model=list[TaskBlockOut])
def move_task_blocks(
    body: TaskBlockMoveBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TaskBlockOut]:
    if len(body.blocks) == 0:
        fail(400, "No hay tareas para mover.")
    rows = []
    for item in body.blocks:
        row = db.get(TaskBlockRow, num(item.id))
        if row is None or row.deleted_at is not None:
            fail(404, "La tarea de ese horario no existe.")
        rows.append(row)
    moving = {row.id for row in rows}
    spans = []
    for item in body.blocks:
        message = task_block_error(item.start, item.end)
        if message:
            fail(400, message)
        start = span_minutes(item.start)
        end = span_minutes(item.end)
        if start is None or end is None:
            fail(400, "Esa hora ya tiene una tarea.")
        spans.append((start, end))
        if block_overlap(db, item, None, moving):
            fail(400, "Esa hora ya tiene una tarea.")
    for index, span in enumerate(spans):
        for other in spans[index + 1:]:
            if ranges_overlap(span[0], span[1], other[0], other[1]):
                fail(400, "Esa hora ya tiene una tarea.")
    saved = []
    for item, row in zip(body.blocks, rows, strict=True):
        row.work_id = num(item.workId)
        row.task_id = num(item.taskId)
        row.block_date = item.date
        row.start_time = item.start
        row.end_time = item.end
        saved.append(row)
    db.commit()
    for row in saved:
        db.refresh(row)
    return [task_block_out(row) for row in saved]


@router.put("/task-blocks/{block_id}", response_model=TaskBlockOut)
def update_task_block(
    block_id: str,
    body: TaskBlockBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TaskBlockOut:
    return save_task_block(body, num(block_id), db)


@router.delete("/task-blocks/{block_id}", status_code=204)
def delete_task_block(block_id: str, _: AccountRow = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    row = db.get(TaskBlockRow, num(block_id))
    if row is None or row.deleted_at is not None:
        fail(404, "La tarea de ese horario no existe.")
    row.deleted_at = utcnow()
    db.commit()


def save_task_block(body: TaskBlockBody, block_id: int | None, db: Session) -> TaskBlockOut:
    message = task_block_error(body.start, body.end)
    if message:
        fail(400, message)
    work = db.get(WorkRow, num(body.workId))
    task = db.get(TaskRow, num(body.taskId))
    if work is None or work.deleted_at is not None:
        fail(404, "Obra no encontrada.")
    if task is None or task.deleted_at is not None:
        fail(404, "Tarea no encontrada.")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.date) is None:
        fail(400, "Indica el día con formato AAAA-MM-DD.")
    if block_overlap(db, body, block_id):
        fail(400, "Esa media hora ya tiene una tarea.")
    row = db.get(TaskBlockRow, block_id) if block_id is not None else TaskBlockRow()
    if block_id is not None and (row is None or row.deleted_at is not None):
        fail(404, "La tarea de ese horario no existe.")
    assert row is not None
    row.work_id = work.id
    row.task_id = task.id
    row.block_date = body.date
    row.start_time = body.start
    row.end_time = body.end
    db.add(row)
    db.commit()
    db.refresh(row)
    return task_block_out(row)


def settlement_payload(body: SettlementBody, db: Session) -> tuple[UserRow, str, int]:
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", body.period) is None:
        fail(400, "Indica el periodo con formato AAAA-MM.")
    if not body.receiptDataUrl.startswith("data:image/"):
        fail(400, "Adjunta la imagen de la transferencia.")
    try:
        user_id = int(body.workerId)
    except ValueError:
        fail(400, "El trabajador no existe.")
    user = db.get(UserRow, user_id)
    if user is None or user.deleted_at is not None or user.rol_id not in {ROLE_SITE_LEAD, ROLE_HELPER}:
        fail(400, "El trabajador no existe.")
    cleaned: list[dict[str, str | int]] = []
    for item in body.items:
        label = item.label.strip()
        if not label:
            fail(400, "Indica el haber.")
        cleaned.append({"label": label, "amount": int(item.amount)})
    total = sum(int(item["amount"]) for item in cleaned)
    return user, json.dumps(cleaned, ensure_ascii=False), total


def settlement_out(row: SettlementRow) -> SettlementOut:
    raw = json.loads(row.items or "[]")
    items = [
        SettlementItemOut(label=str(item.get("label", "")), amount=int(item.get("amount", 0)))
        for item in raw
    ]
    return SettlementOut(
        id=str(row.id),
        workerId=str(row.user_id),
        period=row.period,
        receiptDataUrl=row.receipt,
        items=items,
        total=row.total,
        createdAt=row.created_at.isoformat(),
    )


def settlement_items(row: SettlementRow) -> list[tuple[str, int]]:
    raw = json.loads(row.items or "[]")
    return [(str(item.get("label", "")), int(item.get("amount", 0))) for item in raw]


def visible_settlement(account: AccountRow, row: SettlementRow) -> bool:
    return account.rol_id == ROLE_ADMIN or row.user_id == account.id


@router.get("/settlements")
def list_settlements(
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> list[SettlementOut]:
    rows = (
        db.query(SettlementRow)
        .filter(SettlementRow.deleted_at.is_(None))
        .order_by(SettlementRow.id.desc())
        .all()
    )
    if field_role(account):
        rows = [row for row in rows if row.user_id == account.id]
    return [settlement_out(row) for row in rows]


@router.post("/settlements")
def create_settlement(
    body: SettlementBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettlementOut:
    user, items, total = settlement_payload(body, db)
    row = SettlementRow(
        user_id=user.id,
        period=body.period,
        items=items,
        total=total,
        receipt=body.receiptDataUrl,
    )
    db.add(row)
    add_alert(db, user.id, "paid", f"Se generó tu pago de {period_label(body.period)} por {money(total)}.")
    db.commit()
    db.refresh(row)
    return settlement_out(row)


@router.put("/settlements/{settlement_id}")
def update_settlement(
    settlement_id: int,
    body: SettlementBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettlementOut:
    row = db.get(SettlementRow, settlement_id)
    if row is None or row.deleted_at is not None:
        fail(404, "La liquidación no existe.")
    user, items, total = settlement_payload(body, db)
    row.user_id = user.id
    row.period = body.period
    row.items = items
    row.total = total
    row.receipt = body.receiptDataUrl
    db.commit()
    db.refresh(row)
    return settlement_out(row)


@router.delete("/settlements/{settlement_id}")
def delete_settlement(
    settlement_id: int,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    row = db.get(SettlementRow, settlement_id)
    if row is None or row.deleted_at is not None:
        fail(404, "La liquidación no existe.")
    row.deleted_at = utcnow()
    (
        db.query(DeductionRow)
        .filter(
            DeductionRow.user_id == row.user_id,
            DeductionRow.period == row.period,
            DeductionRow.deleted_at.is_(None),
        )
        .update({DeductionRow.deleted_at: row.deleted_at}, synchronize_session=False)
    )
    db.commit()
    return {"ok": True}


@router.get("/settlements/{settlement_id}/pdf")
def download_settlement(
    settlement_id: int,
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> Response:
    row = db.get(SettlementRow, settlement_id)
    if row is None or row.deleted_at is not None or not visible_settlement(account, row):
        fail(404, "La liquidación no existe.")
    user = db.get(UserRow, row.user_id)
    role = ""
    if user is not None:
        role_row = db.get(RoleRow, user.rol_id)
        role = role_row.rol if role_row is not None else ""
    data = settlement_pdf(
        person=user.name if user is not None else "",
        period=row.period,
        items=settlement_items(row),
        total=row.total,
        document_id=user.document_id if user is not None else "",
        role=role,
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="liquidacion-{row.period}.pdf"'},
    )


def deduction_payload(body: DeductionBody, db: Session) -> tuple[UserRow, str]:
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", body.period) is None:
        fail(400, "Indica el periodo con formato AAAA-MM.")
    detail = body.detail.strip()
    if not detail:
        fail(400, "Indica el detalle de la deducción.")
    if len(detail) > 160:
        fail(400, "El detalle admite hasta 160 caracteres.")
    if body.amount <= 0:
        fail(400, "Indica un monto mayor a cero.")
    try:
        user_id = int(body.workerId)
    except ValueError:
        fail(400, "El trabajador no existe.")
    user = db.get(UserRow, user_id)
    if user is None or user.deleted_at is not None or user.rol_id not in {ROLE_SITE_LEAD, ROLE_HELPER}:
        fail(400, "El trabajador no existe.")
    return user, detail


def deduction_out(row: DeductionRow) -> DeductionOut:
    return DeductionOut(
        id=str(row.id),
        workerId=str(row.user_id),
        period=row.period,
        detail=row.detail,
        amount=row.amount,
        createdAt=row.created_at.isoformat(),
    )


@router.get("/alerts")
def list_alerts(
    account: AccountRow = Depends(current_account),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    query = db.query(AlertRow).order_by(AlertRow.id.desc())
    if account.rol_id == ROLE_ADMIN:
        query = query.filter(AlertRow.user_id.is_(None))
    else:
        query = query.filter(AlertRow.user_id == account.id)
    return [alert_out(row) for row in query.all()]


@router.get("/deductions")
def list_deductions(
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[DeductionOut]:
    rows = (
        db.query(DeductionRow)
        .filter(DeductionRow.deleted_at.is_(None))
        .order_by(DeductionRow.id.desc())
        .all()
    )
    return [deduction_out(row) for row in rows]


@router.post("/deductions")
def create_deduction(
    body: DeductionBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeductionOut:
    user, detail = deduction_payload(body, db)
    row = DeductionRow(user_id=user.id, period=body.period, detail=detail, amount=body.amount)
    db.add(row)
    db.commit()
    db.refresh(row)
    return deduction_out(row)


@router.put("/deductions/{deduction_id}")
def update_deduction(
    deduction_id: int,
    body: DeductionBody,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeductionOut:
    row = db.get(DeductionRow, deduction_id)
    if row is None or row.deleted_at is not None:
        fail(404, "La deducción no existe.")
    user, detail = deduction_payload(body, db)
    row.user_id = user.id
    row.period = body.period
    row.detail = detail
    row.amount = body.amount
    db.commit()
    db.refresh(row)
    return deduction_out(row)


@router.delete("/deductions/{deduction_id}")
def delete_deduction(
    deduction_id: int,
    _: AccountRow = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    row = db.get(DeductionRow, deduction_id)
    if row is None or row.deleted_at is not None:
        fail(404, "La deducción no existe.")
    row.deleted_at = utcnow()
    db.commit()
    return {"ok": True}


@router.get("/whatsapp/webhook")
def verify_whatsapp(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> PlainTextResponse:
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "vitrificados_chile_whatsapp")
    if mode == "subscribe" and token == expected:
        return PlainTextResponse(challenge)
    fail(403, "Verificación rechazada.")


@router.post("/whatsapp/webhook")
async def receive_whatsapp(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                apply_palmeta_reply(db, message.get("from", ""), message)
    return {"status": "ok"}


def apply_palmeta_reply(db: Session, sender: str, message: dict) -> None:
    button = (message.get("interactive") or {}).get("button_reply") or {}
    button_id = str(button.get("id", ""))
    if button_id.startswith("accept_"):
        decision = "accepted"
        change_key = button_id.removeprefix("accept_")
    elif button_id.startswith("reject_"):
        decision = "rejected"
        change_key = button_id.removeprefix("reject_")
    else:
        return
    if not change_key.isdigit():
        return
    row = db.get(PalmetaChangeRow, int(change_key))
    if row is None or row.status != "pending":
        return
    work = db.get(WorkRow, row.work_id)
    if work is None or clean_phone(sender) != clean_phone(work.client_phone):
        return
    if decision == "accepted" and row.next_count > work.palmeta_count:
        work.palmeta_count = row.next_count
        row.status = "accepted"
    else:
        row.status = "rejected"
    db.commit()
