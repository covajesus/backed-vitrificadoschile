from sqlalchemy.orm import Session

from app.models import (
    ROLE_ADMIN,
    ROLE_HELPER,
    ROLE_SITE_LEAD,
    STATUS_ACTIVE,
    STATUS_WORKING,
    ChargeItemRow,
    BankAccountTypeRow,
    MeasureUnitRow,
    BankRow,
    RoleRow,
    ContractTypeRow,
    SettingRow,
    StatusRow,
    TaskRow,
    UserItemPriceRow,
    UserRow,
    WorkItemRow,
    WorkRow,
    WorkScheduleRow,
)

CHARGE_ITEM_NAMES = (
    "Retape",
    "Palmetas de pago",
    "Palmetas de cambio",
    "Instalación",
    "Junquillo",
    "Escalera",
    "Balastro",
)
from app.security import hash_password

PHOTO = "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E"


def seed_if_empty(db: Session) -> None:
    if db.query(RoleRow).first():
        return
    db.add_all([
        ContractTypeRow(id=type_id, name=name, asks_salary=salary, asks_hourly_rate=hourly, asks_item_prices=items, rate_label=label)
        for type_id, name, salary, hourly, items, label in CONTRACT_TYPES
    ])
    db.flush()
    db.add_all([
        RoleRow(id=ROLE_ADMIN, rol="Administrador", protected=1),
        RoleRow(id=ROLE_SITE_LEAD, rol="Maestro de Obra", contract_type_id=2, protected=1),
        RoleRow(id=ROLE_HELPER, rol="Ayudante", contract_type_id=2, protected=1),
        StatusRow(id=STATUS_ACTIVE, name="En espera"),
        StatusRow(id=STATUS_WORKING, name="Trabajando"),
        StatusRow(id=3, name="Entregada"),
    ])
    db.flush()
    db.add_all([
        WorkRow(
            id=1,
            status_id=STATUS_ACTIVE,
            planned_hours=80,
            latitude=-33.4,
            longitude=-70.5,
            names="Faena Los Dominicos",
            address="Av. Apoquindo 4500, Las Condes",
            shift_start="08:00",
            shift_end="17:00",
            work_days="weekdays",
            palmeta_count=200,
            square_meters=85,
            client_name="Inmobiliaria Dominicos",
            client_phone="987654321",
        ),
        WorkRow(
            id=2,
            status_id=STATUS_WORKING,
            planned_hours=120,
            latitude=-33.36,
            longitude=-70.73,
            names="Planta Quilicura",
            address="Av. Américo Vespucio 1200, Quilicura",
            shift_start="07:30",
            shift_end="16:30",
            work_days="except-sunday",
            palmeta_count=40,
            square_meters=120,
            client_name="Planta Quilicura",
            client_phone="912345678",
        ),
    ])
    db.flush()
    db.add_all([
        UserRow(
            id=1,
            rol_id=ROLE_ADMIN,
            names="Administración",
            lastnames="",
            photo="",
            email="admin@vitrificados.local",
            password_hash=hash_password("demo-admin"),
        ),
        UserRow(
            id=2,
            rol_id=ROLE_SITE_LEAD,
            names="Maestro",
            lastnames="de obra",
            hourly_rate=0,
            palmeta_cost=1500,
            phone="912345678",
            photo=PHOTO,
            email="lead.worker@vitrificados.local",
            password_hash=hash_password("demo-site"),
        ),
        UserRow(
            id=3,
            rol_id=ROLE_HELPER,
            names="Ayudante",
            lastnames="de faena",
            hourly_rate=6000,
            photo=PHOTO,
            email="helper.worker@vitrificados.local",
            password_hash=hash_password("demo-site"),
        ),
    ])
    db.flush()
    db.add_all([
        WorkScheduleRow(work_id=1, user_id=2),
        WorkScheduleRow(work_id=1, user_id=3),
        WorkScheduleRow(work_id=2, user_id=2),
    ])
    db.add(SettingRow(id=1, company_phone=""))
    db.commit()


def seed_charge_items(db: Session) -> None:
    if db.query(ChargeItemRow).first():
        return
    db.add_all([
        ChargeItemRow(id=index, name=name, position=index - 1)
        for index, name in enumerate(CHARGE_ITEM_NAMES, start=1)
    ])
    db.flush()
    lead = db.query(UserRow).filter(UserRow.email == "lead.worker@vitrificados.local").one_or_none()
    if lead is not None:
        db.add(UserItemPriceRow(user_id=lead.id, item_id=1, amount=2500))
    if db.get(WorkRow, 1) is not None:
        db.add(WorkItemRow(work_id=1, item_id=1, quantity=12))
    db.commit()


def ensure_charge_items(db: Session) -> None:
    existing = {row.name for row in db.query(ChargeItemRow).all()}
    missing = [name for name in CHARGE_ITEM_NAMES if name not in existing]
    if not missing:
        return
    taken = db.query(ChargeItemRow.position).filter(ChargeItemRow.parent_id.is_(None)).all()
    position = max((int(row[0] or 0) for row in taken), default=-1) + 1
    for name in missing:
        db.add(ChargeItemRow(name=name, position=position))
        position += 1
    db.commit()


def seed_tasks(db: Session) -> None:
    if db.query(TaskRow).first():
        return
    db.add_all([
        TaskRow(names="Trabajo de Obra", kind="site"),
        TaskRow(names="Almuerzo", kind="site"),
        TaskRow(names="Extras", kind="general"),
    ])
    db.commit()


def ensure_tasks(db: Session) -> None:
    existing = {
        row.names
        for row in db.query(TaskRow).filter(TaskRow.deleted_at.is_(None))
    }
    if "Almuerzo" not in existing:
        db.add(TaskRow(names="Almuerzo", kind="site", amount=0, extra_amount=0))
        db.commit()


STATUS_NAMES = {
    1: ("En espera", "work"),
    2: ("Trabajando", "work"),
    3: ("Entregada", "work"),
    4: ("Activo", "account"),
    5: ("Desactivado", "account"),
}


def ensure_statuses(db: Session) -> None:
    for status_id, (name, scope) in STATUS_NAMES.items():
        row = db.get(StatusRow, status_id)
        if row is None:
            db.add(StatusRow(id=status_id, name=name, scope=scope))
        else:
            row.name = name
            row.scope = scope
    db.flush()
    db.query(UserRow).filter(UserRow.status_id.is_(None), UserRow.deleted_at.is_(None)).update({UserRow.status_id: 4})
    db.query(UserRow).filter(UserRow.deleted_at.isnot(None), UserRow.status_id.is_(None)).update({UserRow.status_id: 5})
    db.commit()


def ensure_roles(db: Session) -> None:
    lead = db.get(RoleRow, ROLE_SITE_LEAD)
    if lead is None:
        return
    if db.get(RoleRow, ROLE_HELPER) is None:
        db.add(RoleRow(id=ROLE_HELPER, rol="Ayudante", contract_type_id=2, protected=1))
    if lead.rol == "Empleado":
        lead.rol = "Maestro de Obra"
        helper = db.query(UserRow).filter(UserRow.email == "helper.worker@vitrificados.local").one_or_none()
        if helper is not None and helper.rol_id == ROLE_SITE_LEAD:
            helper.rol_id = ROLE_HELPER
    for role_id in (ROLE_ADMIN, ROLE_SITE_LEAD, ROLE_HELPER):
        row = db.get(RoleRow, role_id)
        if row is not None:
            row.protected = 1
    if lead.contract_type_id is None:
        lead.contract_type_id = 2
    helper = db.get(RoleRow, ROLE_HELPER)
    if helper is not None and helper.contract_type_id is None:
        helper.contract_type_id = 2
    db.commit()


CONTRACT_TYPES = (
    (1, "Por contrato", 1, 0, 0, ""),
    (2, "Trabajador de obra", 0, 1, 1, "Valor por hora"),
    (3, "Por hora", 0, 1, 0, "Costo por hora"),
)


def ensure_contract_types(db: Session) -> None:
    for type_id, name, salary, hourly, items, label in CONTRACT_TYPES:
        row = db.get(ContractTypeRow, type_id)
        if row is None:
            db.add(ContractTypeRow(
                id=type_id,
                name=name,
                asks_salary=salary,
                asks_hourly_rate=hourly,
                asks_item_prices=items,
                rate_label=label,
            ))
        elif type_id == 3 and row.name == "Trabajador por día":
            row.name = name
    db.commit()


BANK_NAMES = (
    "Banco de Chile",
    "Banco Internacional",
    "Banco del Estado de Chile",
    "Scotiabank Chile",
    "Banco de Crédito e Inversiones",
    "Banco BICE",
    "HSBC Bank (Chile)",
    "Banco Santander",
    "Banco Itaú Chile",
    "Banco Security",
    "Banco Falabella",
    "Banco Ripley",
    "Banco Consorcio",
    "Banco BTG Pactual Chile",
    "Tanner Banco Digital",
    "Tenpo Bank",
    "JP Morgan Chase Bank",
    "China Construction Bank",
    "Bank of China",
)


ACCOUNT_TYPE_NAMES = ("Ahorro", "Corriente", "Vista")


def ensure_bank_account_types(db: Session) -> None:
    existing = {row.name for row in db.query(BankAccountTypeRow).all()}
    for name in ACCOUNT_TYPE_NAMES:
        if name not in existing:
            db.add(BankAccountTypeRow(name=name))
    db.commit()


MEASURE_UNIT_NAMES = ("m²", "ml", "un", "kg", "L", "gl")


def ensure_measure_units(db: Session) -> None:
    existing = {row.name for row in db.query(MeasureUnitRow).all()}
    for name in MEASURE_UNIT_NAMES:
        if name not in existing:
            db.add(MeasureUnitRow(name=name))
    db.commit()


def ensure_banks(db: Session) -> None:
    existing = {row.name for row in db.query(BankRow).all()}
    for name in BANK_NAMES:
        if name not in existing:
            db.add(BankRow(name=name))
    db.commit()


def ensure_setting(db: Session) -> None:
    if db.get(SettingRow, 1) is None:
        db.add(SettingRow(id=1, company_phone=""))
        db.commit()
