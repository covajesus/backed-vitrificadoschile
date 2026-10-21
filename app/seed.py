from sqlalchemy.orm import Session

from app.models import (
    ROLE_ADMIN,
    ROLE_HELPER,
    ROLE_SITE_LEAD,
    STATUS_ACTIVE,
    STATUS_WORKING,
    ChargeItemRow,
    BankAccountTypeRow,
    BankRow,
    RoleRow,
    SettingRow,
    StatusRow,
    TaskRow,
    UserItemPriceRow,
    UserRow,
    WorkItemRow,
    WorkRow,
    WorkScheduleRow,
    utcnow,
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
        RoleRow(id=ROLE_ADMIN, rol="Administrador"),
        RoleRow(id=ROLE_SITE_LEAD, rol="Maestro de Obra"),
        RoleRow(id=ROLE_HELPER, rol="Ayudante"),
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
    db.add_all([ChargeItemRow(id=index, name=name) for index, name in enumerate(CHARGE_ITEM_NAMES, start=1)])
    db.flush()
    lead = db.query(UserRow).filter(UserRow.email == "lead.worker@vitrificados.local").one_or_none()
    if lead is not None:
        db.add(UserItemPriceRow(user_id=lead.id, item_id=1, amount=2500))
    if db.get(WorkRow, 1) is not None:
        db.add(WorkItemRow(work_id=1, item_id=1, quantity=12))
    db.commit()


def ensure_charge_items(db: Session) -> None:
    now = utcnow()
    for row in db.query(ChargeItemRow).filter(ChargeItemRow.name.in_(("Sellado", "Pulido")), ChargeItemRow.deleted_at.is_(None)):
        row.deleted_at = now
    existing = {
        row.name
        for row in db.query(ChargeItemRow).filter(ChargeItemRow.deleted_at.is_(None))
    }
    for name in CHARGE_ITEM_NAMES:
        if name not in existing:
            db.add(ChargeItemRow(name=name))
    db.commit()


def seed_tasks(db: Session) -> None:
    if db.query(TaskRow).first():
        return
    db.add_all([
        TaskRow(names="Trabajo de Obra"),
        TaskRow(names="Extras"),
    ])
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
        db.add(RoleRow(id=ROLE_HELPER, rol="Ayudante"))
    if lead.rol == "Empleado":
        lead.rol = "Maestro de Obra"
        helper = db.query(UserRow).filter(UserRow.email == "helper.worker@vitrificados.local").one_or_none()
        if helper is not None and helper.rol_id == ROLE_SITE_LEAD:
            helper.rol_id = ROLE_HELPER
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
