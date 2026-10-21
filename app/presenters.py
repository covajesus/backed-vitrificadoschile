from app.domain import arrival_notice, whatsapp_href
from app.models import STATUS_ACCOUNT_INACTIVE, ChargeItemRow, TaskBlockRow, TaskRow, TimeClockRow, UserRow, WorkRow, WorkScheduleRow
from app.schemas import AccountOut, ArrivalOut, AssignmentOut, ChargeItemOut, ChargeLineOut, ItemPriceOut, TaskBlockOut, TaskOut, WorkChargeOut, WorkOut


def work_out(row: WorkRow, pending_palmeta_count: int | None = None, charges: list[WorkChargeOut] | None = None) -> WorkOut:
    return WorkOut(
        id=str(row.id),
        name=row.names,
        address=row.address,
        shiftStart=row.shift_start,
        shiftEnd=row.shift_end,
        plannedHours=row.planned_hours,
        workDays=row.work_days,
        palmetaCount=row.palmeta_count,
        squareMeters=row.square_meters,
        clientName=row.client_name,
        clientPhone=row.client_phone,
        status=row.status,
        latitude=row.latitude,
        longitude=row.longitude,
        pendingPalmetaCount=pending_palmeta_count,
        charges=charges or [],
    )


def account_out(row: UserRow, item_prices: list[ItemPriceOut] | None = None) -> AccountOut:
    return AccountOut(
        id=str(row.id),
        name=row.name,
        firstName=row.names,
        lastName=row.lastnames,
        email=row.email,
        roleId=row.rol_id,
        workerId=None,
        hourlyRate=row.hourly_rate,
        palmetaCost=row.palmeta_cost,
        phone=row.phone,
        address=row.address,
        documentId=row.document_id,
        photoDataUrl=row.photo,
        bankId=str(row.bank_id) if row.bank_id else "",
        bank=row.bank,
        accountTypeId=str(row.account_type_id) if row.account_type_id else "",
        accountType=row.account_type,
        accountNumber=row.account_number,
        accountHolder=row.account_holder,
        accountHolderDocumentId=row.account_holder_document_id,
        itemPrices=item_prices or [],
        active=row.active,
        statusId=str(row.status_id or 4),
        statusName="Desactivado" if row.status_id == STATUS_ACCOUNT_INACTIVE else "Activo",
    )


def charge_item_out(row: ChargeItemRow, lines: list[ChargeItemRow] | None = None) -> ChargeItemOut:
    return ChargeItemOut(
        id=str(row.id),
        name=row.name,
        kind=row.kind or "simple",
        lines=[ChargeLineOut(id=str(line.id), name=line.name) for line in (lines or [])],
    )


def task_out(row: TaskRow) -> TaskOut:
    return TaskOut(id=str(row.id), name=row.names)


def task_block_out(row: TaskBlockRow) -> TaskBlockOut:
    return TaskBlockOut(
        id=str(row.id),
        workId=str(row.work_id),
        taskId=str(row.task_id),
        date=row.block_date,
        start=row.start_time,
        end=row.end_time,
    )


def assignment_out(row: WorkScheduleRow) -> AssignmentOut:
    return AssignmentOut(
        workId=str(row.work_id),
        workerId=str(row.user_id),
        startDate=row.start_date or "",
        dayCount=row.day_count or 0,
    )


def clock_moment(row: TimeClockRow) -> str:
    return f"{row.arrive_date}T{row.arrive_time}"


def clock_coordinates(location: str) -> tuple[float, float]:
    latitude, longitude = location.split(",", 1)
    return float(latitude), float(longitude)


def arrival_out(row: TimeClockRow, person_name: str, work_name: str) -> ArrivalOut:
    latitude, longitude = clock_coordinates(row.location)
    moment = clock_moment(row)
    notice = arrival_notice(person_name, work_name, moment, latitude, longitude)
    return ArrivalOut(
        id=str(row.id),
        workId=str(row.work_id),
        workerId=str(row.user_id),
        at=moment,
        latitude=latitude,
        longitude=longitude,
        photoDataUrl=row.photo,
        whatsappHref=whatsapp_href(notice),
    )
