from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def long_text():
    return Text().with_variant(MEDIUMTEXT(), "mysql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)


ROLE_ADMIN = 1
ROLE_SITE_LEAD = 2
ROLE_HELPER = 3
ROLE_EMPLOYEE = ROLE_SITE_LEAD
STATUS_ACTIVE = 1
STATUS_WORKING = 2
STATUS_DELIVERED = 3
STATUS_ACCOUNT_ACTIVE = 4
STATUS_ACCOUNT_INACTIVE = 5

STATUS_CODE = {
    STATUS_ACTIVE: "active",
    STATUS_WORKING: "working",
    STATUS_DELIVERED: "completed",
}
CODE_STATUS = {code: status_id for status_id, code in STATUS_CODE.items()}


class RoleRow(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rol: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StatusRow(Base):
    __tablename__ = "statuses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80))
    scope: Mapped[str] = mapped_column(String(20), default="work")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkRow(Base):
    __tablename__ = "works"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    status_id: Mapped[int] = mapped_column(ForeignKey("statuses.id"))
    planned_hours: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    names: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(300))
    shift_start: Mapped[str] = mapped_column(String(5))
    shift_end: Mapped[str] = mapped_column(String(5))
    work_days: Mapped[str] = mapped_column(String(20), default="weekdays")
    palmeta_count: Mapped[int] = mapped_column(Integer, default=0)
    square_meters: Mapped[float] = mapped_column(Float, default=0)
    client_name: Mapped[str] = mapped_column(String(160), default="")
    client_phone: Mapped[str] = mapped_column(String(30), default="")
    apartment: Mapped[str] = mapped_column(String(40), default="")
    crew_note: Mapped[str] = mapped_column(String(500), default="")
    work_notice: Mapped[str] = mapped_column(String(500), default="")
    starts_on: Mapped[str] = mapped_column(String(10), default="")
    day_count: Mapped[int] = mapped_column(Integer, default=0)
    schedule_dates: Mapped[str] = mapped_column(String(8000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def name(self) -> str:
        return self.names

    @name.setter
    def name(self, value: str) -> None:
        self.names = value

    @property
    def status(self) -> str:
        return STATUS_CODE[self.status_id]


class BankRow(Base):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BankAccountTypeRow(Base):
    __tablename__ = "bank_account_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rol_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    status_id: Mapped[int | None] = mapped_column(ForeignKey("statuses.id"), nullable=True)
    bank_id: Mapped[int | None] = mapped_column(ForeignKey("banks.id"), nullable=True)
    account_type_id: Mapped[int | None] = mapped_column(ForeignKey("bank_account_types.id"), nullable=True)
    hourly_rate: Mapped[float] = mapped_column(Float, default=0)
    palmeta_cost: Mapped[float] = mapped_column(Float, default=0)
    phone: Mapped[str] = mapped_column(String(30), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    document_id: Mapped[str] = mapped_column(String(40), default="")
    bank: Mapped[str] = mapped_column(String(80), default="")
    account_type: Mapped[str] = mapped_column(String(40), default="")
    account_number: Mapped[str] = mapped_column(String(40), default="")
    account_holder: Mapped[str] = mapped_column(String(120), default="")
    account_holder_document_id: Mapped[str] = mapped_column(String(40), default="")
    names: Mapped[str] = mapped_column(String(120))
    lastnames: Mapped[str] = mapped_column(String(120), default="")
    photo: Mapped[str] = mapped_column(long_text(), default="")
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def name(self) -> str:
        return f"{self.names} {self.lastnames}".strip()

    @name.setter
    def name(self, value: str) -> None:
        parts = value.strip().split(" ", 1)
        self.names = parts[0]
        self.lastnames = parts[1] if len(parts) > 1 else ""

    @property
    def active(self) -> bool:
        if self.status_id == STATUS_ACCOUNT_INACTIVE:
            return False
        return self.deleted_at is None

    @active.setter
    def active(self, value: bool) -> None:
        self.deleted_at = None if value else utcnow()


class WorkScheduleRow(Base):
    __tablename__ = "work_schedules"
    __table_args__ = (UniqueConstraint("work_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[str] = mapped_column(String(10), default="")
    day_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_dates: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    names: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="site")
    amount: Mapped[int] = mapped_column(Integer, default=0)
    extra_amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskBlockRow(Base):
    __tablename__ = "task_blocks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    block_date: Mapped[str] = mapped_column(String(10))
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TimeClockRow(Base):
    __tablename__ = "time_clocks"
    __table_args__ = (Index("ix_time_clocks_work_date", "work_id", "arrive_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    location: Mapped[str] = mapped_column(String(80))
    photo: Mapped[str] = mapped_column(long_text())
    arrive_date: Mapped[str] = mapped_column(String(10))
    arrive_time: Mapped[str] = mapped_column(String(8))


class SettingRow(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_phone: Mapped[str] = mapped_column(String(30), default="")
    grace_minutes: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LateNoticeRow(Base):
    __tablename__ = "late_notices"
    __table_args__ = (UniqueConstraint("user_id", "work_id", "work_date", "slot"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"))
    work_date: Mapped[str] = mapped_column(String(10))
    slot: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NotificationContactRow(Base):
    __tablename__ = "notification_contacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MeasureUnitRow(Base):
    __tablename__ = "measure_units"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChargeItemRow(Base):
    __tablename__ = "charge_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("charge_items.id"), nullable=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("measure_units.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="simple")
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserItemPriceRow(Base):
    __tablename__ = "user_item_prices"
    __table_args__ = (UniqueConstraint("user_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("charge_items.id"))
    amount: Mapped[float] = mapped_column(Float, default=0)


class WorkItemRow(Base):
    __tablename__ = "work_items"
    __table_args__ = (UniqueConstraint("work_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("charge_items.id"))
    quantity: Mapped[float] = mapped_column(Float, default=0)


class SettlementRow(Base):
    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    period: Mapped[str] = mapped_column(String(7))
    items: Mapped[str] = mapped_column(Text, default="[]")
    total: Mapped[int] = mapped_column(Integer, default=0)
    receipt: Mapped[str] = mapped_column(long_text(), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeductionRow(Base):
    __tablename__ = "deductions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    period: Mapped[str] = mapped_column(String(7))
    detail: Mapped[str] = mapped_column(String(160), default="")
    amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AlertRow(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    work_id: Mapped[int | None] = mapped_column(ForeignKey("works.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChargeChangeRow(Base):
    __tablename__ = "charge_changes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    before_quantities: Mapped[str] = mapped_column(Text, default="[]")
    proposed: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PalmetaChangeRow(Base):
    __tablename__ = "palmeta_changes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    previous_count: Mapped[int] = mapped_column(Integer)
    next_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


AccountRow = UserRow
ArrivalRow = TimeClockRow
