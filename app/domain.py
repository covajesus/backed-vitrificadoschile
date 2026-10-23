import math
from datetime import date, datetime, timedelta
from urllib.parse import quote

WHATSAPP_PHONE = "56987654321"


def shift_hours(start: str, end: str) -> float:
    start_minutes = minutes_of(start)
    end_minutes = minutes_of(end)
    if start_minutes is None or end_minutes is None:
        return 0
    if end_minutes == 0 and start_minutes > 0:
        end_minutes = 24 * 60
    if end_minutes <= start_minutes:
        return 0
    return (end_minutes - start_minutes) / 60


def minutes_of(value: str) -> int | None:
    if len(value) != 5 or value[2] != ":":
        return None
    hours, minutes = value.split(":")
    if not hours.isdigit() or not minutes.isdigit():
        return None
    hour = int(hours)
    minute = int(minutes)
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


WORK_DAY_MODES = {"weekdays", "weekend", "all", "except-sunday"}
MODE_DAYS = {
    "weekdays": {1, 2, 3, 4, 5},
    "weekend": {6, 0},
    "all": {1, 2, 3, 4, 5, 6, 0},
    "except-sunday": {1, 2, 3, 4, 5, 6},
}


def allowed_weekdays(value: str) -> set[int]:
    preset = MODE_DAYS.get(value)
    if preset is not None:
        return set(preset)
    return {int(part) for part in value.split(",") if part.isdigit() and int(part) in range(7)}


def js_weekday(day: date) -> int:
    return (day.weekday() + 1) % 7


def scheduled_on(work_days: str, start_date: str, day_count: int, excluded: set[str], day: date) -> bool:
    if day.isoformat() in excluded:
        return False
    allowed = allowed_weekdays(work_days)
    if not allowed or js_weekday(day) not in allowed:
        return False
    if not start_date or day_count < 1:
        return True
    if len(start_date) != 10:
        return False
    cursor = date.fromisoformat(start_date)
    found = 0
    for offset in range(day_count * 7 + 7):
        current = cursor + timedelta(days=offset)
        if js_weekday(current) not in allowed:
            continue
        if current == day:
            return True
        found += 1
        if found >= day_count:
            return False
    return False


def late_slot(shift_start: str, grace_minutes: int, now_minutes: int) -> int | None:
    start = minutes_of(shift_start)
    if start is None:
        return None
    grace = grace_minutes if isinstance(grace_minutes, int) and grace_minutes > 0 else 0
    late = now_minutes - (start + grace)
    if late < 30:
        return None
    return (late // 30) * 30


def work_error(
    name: str,
    address: str,
    shift_start: str,
    shift_end: str,
    planned_hours: float,
    work_days: str = "weekdays",
    palmeta_count: int = 0,
    square_meters: float = 0,
    client_name: str = "",
    client_phone: str = "",
    apartment: str = "",
    crew_note: str = "",
    work_notice: str = "",
) -> str | None:
    if len(name.strip()) < 3:
        return "El nombre debe tener al menos 3 caracteres."
    if len(address.strip()) < 5:
        return "Indica la dirección de la obra."
    if minutes_of(shift_start) is None:
        return "Indica el inicio de la jornada."
    if minutes_of(shift_end) is None:
        return "Indica el término de la jornada."
    if shift_hours(shift_start, shift_end) <= 0:
        return "El término debe ser posterior al inicio."
    if not math.isfinite(planned_hours) or planned_hours <= 0:
        return "Indica las horas previstas de la obra."
    if not valid_work_days(work_days):
        return "Marca al menos un día."
    if not isinstance(palmeta_count, int) or isinstance(palmeta_count, bool) or palmeta_count < 0:
        return "Indica la cantidad de palmetas."
    if len(client_name.strip()) < 3:
        return "Indica el nombre del cliente."
    if len(phone_digits(client_phone)) < 8:
        return "Indica el teléfono del cliente."
    if len(apartment.strip()) > 40:
        return "El número de departamento es demasiado largo."
    if len(crew_note.strip()) > 500:
        return "El aviso para la cuadrilla es demasiado largo."
    if len(work_notice.strip()) > 500:
        return "El aviso de obra es demasiado largo."
    return None


def format_quantity(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def valid_work_days(value: str) -> bool:
    if value in WORK_DAY_MODES:
        return True
    seen: set[int] = set()
    for part in value.split(","):
        if not part.isdigit():
            return False
        day = int(part)
        if day not in {0, 1, 2, 3, 4, 5, 6} or day in seen:
            return False
        seen.add(day)
    return len(seen) > 0


def compact_national_id(value: str) -> str:
    return "".join(char for char in value if char.isdigit() or char in "kK").upper()


def is_valid_national_id(value: str) -> bool:
    compact = compact_national_id(value)
    if len(compact) < 2:
        return False
    body, digit = compact[:-1], compact[-1]
    if not body.isdigit():
        return False
    total = 0
    multiplier = 2
    for char in reversed(body):
        total += int(char) * multiplier
        multiplier = 2 if multiplier == 7 else multiplier + 1
    rest = 11 - (total % 11)
    expected = "0" if rest == 11 else "K" if rest == 10 else str(rest)
    return digit == expected


SITE_RADIUS_METERS = 20
OFF_SITE_MESSAGE = "Usted no puede marcar puesto que no se encuentra en la ubicación del trabajo."


def distance_meters(latitude: float, longitude: float, other_latitude: float, other_longitude: float) -> float:
    earth = 6_371_000
    first_lat = math.radians(latitude)
    second_lat = math.radians(other_latitude)
    delta_lat = math.radians(other_latitude - latitude)
    delta_lon = math.radians(other_longitude - longitude)
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(first_lat) * math.cos(second_lat) * math.sin(delta_lon / 2) ** 2
    return 2 * earth * math.asin(math.sqrt(haversine))


def on_site(site_latitude: float, site_longitude: float, latitude: float, longitude: float) -> bool:
    return distance_meters(site_latitude, site_longitude, latitude, longitude) <= SITE_RADIUS_METERS


def arrival_block_reason(
    *,
    work_active: bool,
    worker_active: bool,
    assigned: bool,
    photo_data_url: str,
    latitude: float | None,
    longitude: float | None,
) -> str | None:
    if not work_active:
        return "La obra no está activa."
    if not worker_active:
        return "El trabajador no está activo."
    if not assigned:
        return "Solo la dotación asignada puede marcar llegada en esta obra."
    if not photo_data_url.startswith("data:image/"):
        return "La fotografía es obligatoria."
    if latitude is None or longitude is None or not math.isfinite(latitude) or not math.isfinite(longitude):
        return "Activa el GPS para registrar la llegada."
    return None


def task_block_error(start: str, end: str) -> str | None:
    start_minutes = minutes_of(start)
    end_minutes = 24 * 60 if end == "24:00" else minutes_of(end)
    if (
        start_minutes is None
        or end_minutes is None
        or start_minutes % 30 != 0
        or end_minutes % 30 != 0
        or end_minutes > 24 * 60
    ):
        return "Las tareas se colocan cada media hora."
    if end_minutes <= start_minutes:
        return "El término debe ser posterior al inicio."
    return None


def ranges_overlap(start: int, end: int, other_start: int, other_end: int) -> bool:
    return start < other_end and other_start < end


def phone_digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def palmeta_amount(count: int, unit_cost: float) -> int:
    if count < 0 or unit_cost < 0 or not math.isfinite(unit_cost):
        return 0
    return round(count * unit_cost)


def palmeta_increase_error(current: int, proposed: int) -> str | None:
    if not isinstance(proposed, int) or isinstance(proposed, bool):
        return "Indica una cantidad entera de palmetas."
    if proposed <= current:
        return "La cantidad de palmetas solo puede aumentar."
    return None


def amount_for_arrivals(hourly_rate: float, shift_lengths: list[float]) -> int:
    if hourly_rate <= 0:
        return 0
    return round(sum(hourly_rate * hours for hours in shift_lengths))


def whatsapp_href(text: str) -> str:
    digits = "".join(char for char in WHATSAPP_PHONE if char.isdigit())
    e164 = digits if digits.startswith("56") else f"56{digits}"
    return f"https://wa.me/{e164}?text={quote(text)}"


def arrival_notice(worker_name: str, work_name: str, at: str, latitude: float, longitude: float) -> str:
    when = datetime.fromisoformat(at.replace("Z", "+00:00")).strftime("%d-%m-%Y %H:%M")
    maps = f"https://maps.google.com/?q={latitude},{longitude}"
    return f"Llegada a faena: {worker_name} en {work_name}. {when}. Ubicación: {maps}"
