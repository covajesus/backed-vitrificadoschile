import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import client_ride_for, late_notice_due, scheduled_on
from app.models import (
    ROLE_HELPER,
    ROLE_SITE_LEAD,
    STATUS_ACTIVE,
    STATUS_WORKING,
    LateNoticeRow,
    SettingRow,
    TimeClockRow,
    UserRow,
    WorkRow,
    WorkScheduleRow,
    ClientRideRow,
)
from app.whatsapp import notify_late_arrival


def chile_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Santiago")).replace(tzinfo=None)
    except Exception:
        return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)


def remind_late_workers(db: Session, now: datetime) -> int:
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        locked = db.execute(text("SELECT GET_LOCK('vitrificados_late_arrivals', 0)")).scalar()
        if locked != 1:
            return 0
    try:
        return _remind(db, now)
    finally:
        if dialect == "mysql":
            db.execute(text("SELECT RELEASE_LOCK('vitrificados_late_arrivals')"))


def _remind(db: Session, now: datetime) -> int:
    setting = db.get(SettingRow, 1)
    grace = setting.grace_minutes if setting else 0
    today = now.date()
    today_iso = today.isoformat()
    now_minutes = now.hour * 60 + now.minute
    works = {
        row.id: row
        for row in db.query(WorkRow).filter(
            WorkRow.deleted_at.is_(None),
            WorkRow.status_id.in_([STATUS_ACTIVE, STATUS_WORKING]),
        )
    }
    users = {row.id: row for row in db.query(UserRow).filter(UserRow.deleted_at.is_(None))}
    arrived = {
        (row.work_id, row.user_id)
        for row in db.query(TimeClockRow).filter(TimeClockRow.arrive_date == today_iso)
    }
    ride_rows = [
        (row.work_id, row.worker_ids or "", row.ride_dates or "", row.arrival_time or "", row.latitude, row.longitude)
        for row in db.query(ClientRideRow).filter(ClientRideRow.deleted_at.is_(None)).all()
    ]
    sent = 0
    schedules = db.query(WorkScheduleRow).filter(WorkScheduleRow.deleted_at.is_(None)).all()
    for schedule in schedules:
        work = works.get(schedule.work_id)
        person = users.get(schedule.user_id)
        if work is None or person is None or person.rol_id not in {ROLE_SITE_LEAD, ROLE_HELPER}:
            continue
        if not person.active:
            continue
        excluded = {item for item in (schedule.excluded_dates or "").split(",") if item}
        if not scheduled_on(work.work_days, schedule.start_date or "", schedule.day_count or 0, excluded, today):
            continue
        if (work.id, person.id) in arrived:
            continue
        ride = client_ride_for(ride_rows, work.id, person.id, today_iso)
        start = ride[0] if ride is not None else work.shift_start
        slot = late_notice_due(start, grace, now_minutes)
        if slot is None or len((person.phone or "").strip()) < 8:
            continue
        already = db.query(LateNoticeRow).filter(
            LateNoticeRow.user_id == person.id,
            LateNoticeRow.work_id == work.id,
            LateNoticeRow.work_date == today_iso,
            LateNoticeRow.slot == slot,
        ).first()
        if already is not None:
            continue
        label = work.client_name.strip() or work.name
        result = notify_late_arrival(
            phone=person.phone,
            worker_name=person.name,
            work_name=label,
            minutes_late=slot,
        )
        if not result.get("ok"):
            continue
        try:
            with db.begin_nested():
                db.add(LateNoticeRow(
                    user_id=person.id,
                    work_id=work.id,
                    work_date=today_iso,
                    slot=slot,
                ))
        except IntegrityError:
            continue
        sent += 1
    return sent


def start_late_watch(session_factory) -> None:
    def loop() -> None:
        while True:
            try:
                with session_factory() as db:
                    remind_late_workers(db, chile_now())
                    db.commit()
            except Exception:
                pass
            time.sleep(60)

    threading.Thread(target=loop, name="late-arrivals", daemon=True).start()
