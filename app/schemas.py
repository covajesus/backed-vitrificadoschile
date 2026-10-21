from pydantic import BaseModel, ConfigDict, Field


class ItemPriceOut(BaseModel):
    itemId: str
    amount: float


class WorkChargeOut(BaseModel):
    itemId: str
    quantity: int


class WorkChargesBody(BaseModel):
    charges: list[WorkChargeOut] = []


class ChargeLineBody(BaseModel):
    id: str | None = None
    name: str


class ChargeLineOut(BaseModel):
    id: str
    name: str


class ChargeItemBody(BaseModel):
    name: str
    kind: str = "simple"
    lines: list[ChargeLineBody] = []


class ChargeItemOut(BaseModel):
    id: str
    name: str
    kind: str = "simple"
    lines: list[ChargeLineOut] = []


class BankOut(BaseModel):
    id: str
    name: str


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    firstName: str = ""
    lastName: str = ""
    email: str
    roleId: int
    workerId: str | None
    hourlyRate: float = 0
    palmetaCost: float = 0
    phone: str = ""
    address: str = ""
    documentId: str = ""
    photoDataUrl: str = ""
    bankId: str = ""
    bank: str = ""
    accountTypeId: str = ""
    accountType: str = ""
    accountNumber: str = ""
    accountHolder: str = ""
    accountHolderDocumentId: str = ""
    itemPrices: list[ItemPriceOut] = []
    active: bool
    statusId: str = "4"
    statusName: str = "Activo"


class LoginBody(BaseModel):
    email: str
    password: str


class LoginResult(BaseModel):
    token: str
    account: AccountOut


class WorkBody(BaseModel):
    name: str
    address: str
    shiftStart: str
    shiftEnd: str
    plannedHours: float
    workDays: str = "weekdays"
    palmetaCount: int = 0
    squareMeters: float = 0
    clientName: str = ""
    clientPhone: str = ""
    latitude: float | None = None
    longitude: float | None = None
    charges: list[WorkChargeOut] = []


class WorkStatusBody(BaseModel):
    status: str


class WorkOut(WorkBody):
    id: str
    status: str
    latitude: float
    longitude: float
    pendingPalmetaCount: int | None = None
    notice: str = ""


class LocateBody(BaseModel):
    address: str


class LocateOut(BaseModel):
    latitude: float
    longitude: float


class PlaceOut(BaseModel):
    label: str
    latitude: float
    longitude: float


class WorkerBody(BaseModel):
    firstName: str
    lastName: str
    nationalId: str
    phone: str
    address: str
    email: str
    photoDataUrl: str
    hourlyRate: float = 0


class WorkerOut(WorkerBody):
    id: str
    active: bool


class RateBody(BaseModel):
    hourlyRate: float


class CrewBody(BaseModel):
    workerIds: list[str]


class AssignmentOut(BaseModel):
    workId: str
    workerId: str


class ArrivalBody(BaseModel):
    workId: str
    workerId: str
    at: str
    latitude: float | None = None
    longitude: float | None = None
    photoDataUrl: str


class ArrivalOut(BaseModel):
    id: str
    workId: str
    workerId: str
    at: str
    latitude: float
    longitude: float
    photoDataUrl: str
    whatsappHref: str


class AccountBody(BaseModel):
    name: str
    firstName: str = ""
    lastName: str = ""
    email: str
    password: str = ""
    roleId: int
    workerId: str | None = None
    hourlyRate: float = 0
    palmetaCost: float = 0
    phone: str = ""
    address: str = ""
    documentId: str = ""
    photoDataUrl: str = ""
    bankId: str = ""
    bank: str = ""
    accountTypeId: str = ""
    accountType: str = ""
    accountNumber: str = ""
    accountHolder: str = ""
    accountHolderDocumentId: str = ""
    itemPrices: list[ItemPriceOut] = []
    statusId: str = "4"


class PaymentBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workerId: str
    period_from: str = Field(alias="from")
    period_to: str = Field(alias="to")
    receiptDataUrl: str


class CalendarArrivalOut(BaseModel):
    workerName: str
    at: str
    latitude: float
    longitude: float
    photoDataUrl: str


class CalendarDayOut(BaseModel):
    date: str
    arrivals: list[CalendarArrivalOut]


class CalendarOut(BaseModel):
    workId: str
    month: str
    days: list[CalendarDayOut]


class TaskBody(BaseModel):
    name: str


class TaskOut(BaseModel):
    id: str
    name: str


class TaskBlockBody(BaseModel):
    workId: str
    taskId: str
    date: str
    start: str
    end: str


class TaskBlockOut(TaskBlockBody):
    id: str


class ProfileBody(BaseModel):
    name: str
    firstName: str = ""
    lastName: str = ""
    email: str
    phone: str = ""
    address: str = ""
    documentId: str = ""
    photoDataUrl: str = ""
    bankId: str = ""
    bank: str = ""
    accountTypeId: str = ""
    accountType: str = ""
    accountNumber: str = ""
    accountHolder: str = ""
    accountHolderDocumentId: str = ""


class StatusOut(BaseModel):
    id: str
    name: str
    scope: str


class SettingBody(BaseModel):
    companyPhone: str = ""
    emails: list[str] | None = None
    phones: list[str] | None = None


class SettingOut(BaseModel):
    companyPhone: str
    emails: list[str] = []
    phones: list[str] = []


class PalmetaChangeBody(BaseModel):
    quantity: int


class PalmetaChangeOut(BaseModel):
    id: str
    workId: str
    previousCount: int
    nextCount: int
    status: str
    message: str


class PaymentOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    workerId: str
    period_from: str = Field(alias="from")
    period_to: str = Field(alias="to")
    amount: int
    receiptDataUrl: str
    createdAt: str
