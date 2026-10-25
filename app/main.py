import os
import re

import pymysql
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.routes import login_account, router
from app.seed import ensure_bank_account_types, ensure_banks, ensure_charge_items, ensure_contract_types, ensure_measure_units, ensure_roles, ensure_setting, ensure_statuses, ensure_tasks, seed_charge_items, seed_if_empty, seed_tasks
from app.whatsapp import load_env_file

SECRET = "vitrificados-chile-dev-secret"
FALLBACK_DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/vitrificados_chile?charset=utf8mb4"


def ensure_mysql_database(database_url: str) -> None:
    url = make_url(database_url)
    name = url.database
    if not name or not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("El nombre de la base debe usar letras, números o guion bajo.")
    connection = pymysql.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        user=url.username or "root",
        password=url.password or "",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        connection.commit()
    finally:
        connection.close()


def ensure_work_days(engine) -> None:
    inspector = inspect(engine)
    if "works" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("works")}
    if "work_days" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE works ADD COLUMN work_days VARCHAR(20) NOT NULL DEFAULT 'weekdays'"))


def ensure_column(engine, table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column in columns:
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_measure_columns(engine) -> None:
    ensure_column(engine, "works", "palmeta_count", "palmeta_count INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "works", "square_meters", "square_meters FLOAT NOT NULL DEFAULT 0")
    ensure_column(engine, "works", "client_name", "client_name VARCHAR(160) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "client_phone", "client_phone VARCHAR(30) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "apartment", "apartment VARCHAR(40) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "crew_note", "crew_note VARCHAR(500) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "work_notice", "work_notice VARCHAR(500) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "starts_on", "starts_on VARCHAR(10) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "day_count", "day_count INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "works", "schedule_dates", "schedule_dates VARCHAR(8000) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "finish_sample", "finish_sample VARCHAR(160) NOT NULL DEFAULT ''")
    ensure_column(engine, "works", "tint_sample", "tint_sample VARCHAR(160) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "phone", "phone VARCHAR(30) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "address", "address VARCHAR(300) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "document_id", "document_id VARCHAR(40) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "palmeta_cost", "palmeta_cost FLOAT NOT NULL DEFAULT 0")
    ensure_column(engine, "users", "bank", "bank VARCHAR(80) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "account_type", "account_type VARCHAR(40) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "account_number", "account_number VARCHAR(40) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "account_holder", "account_holder VARCHAR(120) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "account_holder_document_id", "account_holder_document_id VARCHAR(40) NOT NULL DEFAULT ''")
    ensure_column(engine, "users", "bank_id", "bank_id INTEGER NULL")
    ensure_column(engine, "users", "account_type_id", "account_type_id INTEGER NULL")
    ensure_column(engine, "charge_items", "kind", "kind VARCHAR(20) NOT NULL DEFAULT 'simple'")
    ensure_column(engine, "charge_items", "unit_id", "unit_id INTEGER NULL")
    ensure_column(engine, "charge_items", "parent_id", "parent_id INTEGER NULL")
    ensure_column(engine, "charge_items", "position", "position INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "statuses", "scope", "scope VARCHAR(20) NOT NULL DEFAULT 'work'")
    ensure_column(engine, "users", "status_id", "status_id INTEGER NULL")
    ensure_column(engine, "work_schedules", "start_date", "start_date VARCHAR(10) NOT NULL DEFAULT ''")
    ensure_column(engine, "work_schedules", "day_count", "day_count INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "work_schedules", "excluded_dates", "excluded_dates VARCHAR(1000) NOT NULL DEFAULT ''")
    ensure_column(engine, "work_schedules", "role_id", "role_id INTEGER NULL")
    ensure_column(engine, "tasks", "kind", "kind VARCHAR(20) NOT NULL DEFAULT 'site'")
    ensure_column(engine, "tasks", "amount", "amount INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "tasks", "extra_amount", "extra_amount INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "deductions", "detail", "detail VARCHAR(160) NOT NULL DEFAULT ''")
    ensure_column(engine, "alerts", "work_id", "work_id INTEGER NULL")
    ensure_column(engine, "settings", "grace_minutes", "grace_minutes INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "settings", "lead_late_per_minute", "lead_late_per_minute INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "work_items", "evaluate", "evaluate INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "works", "arrival_time", "arrival_time VARCHAR(8) NOT NULL DEFAULT ''")
    ensure_role_pay(engine)


def ensure_role_pay(engine) -> None:
    inspector = inspect(engine)
    if "roles" not in inspector.get_table_names() or "users" not in inspector.get_table_names():
        return
    role_columns = {item["name"] for item in inspector.get_columns("roles")}
    amount = "DOUBLE" if engine.dialect.name == "mysql" else "FLOAT"
    ensure_column(engine, "roles", "contract_type_id", "contract_type_id INTEGER NULL")
    ensure_column(engine, "roles", "protected", "protected INTEGER NOT NULL DEFAULT 0")
    ensure_column(engine, "users", "salary", f"salary {amount} NOT NULL DEFAULT 0")
    ensure_column(engine, "users", "contract_type_id", "contract_type_id INTEGER NULL")
    with engine.begin() as connection:
        if "by_contract" in role_columns:
            connection.execute(text(
                "UPDATE roles SET contract_type_id = 1 "
                "WHERE contract_type_id IS NULL AND by_contract = 1 AND id <> 1"
            ))
        if "site_worker" in role_columns:
            connection.execute(text(
                "UPDATE roles SET contract_type_id = 2 "
                "WHERE contract_type_id IS NULL AND site_worker = 1 AND id <> 1"
            ))
            connection.execute(text(
                "UPDATE roles SET contract_type_id = 3 "
                "WHERE contract_type_id IS NULL AND COALESCE(by_contract, 0) = 0 "
                "AND COALESCE(site_worker, 0) = 0 AND id <> 1"
            ))
        connection.execute(text(
            "UPDATE roles SET contract_type_id = 2 WHERE contract_type_id IS NULL AND id IN (2, 3)"
        ))
        connection.execute(text("UPDATE roles SET protected = 1 WHERE id IN (1, 2, 3)"))
        connection.execute(text(
            "UPDATE users SET contract_type_id = ("
            "SELECT roles.contract_type_id FROM roles WHERE roles.id = users.rol_id"
            ") WHERE contract_type_id IS NULL AND rol_id <> 1"
        ))


def ensure_hourly_rate(engine) -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "hourly_rate" in columns:
        return
    column = "DOUBLE" if engine.dialect.name == "mysql" else "FLOAT"
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE users ADD COLUMN hourly_rate {column} NOT NULL DEFAULT 0"))


def drop_legacy_tables(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    retired = {"workers", "payments", "arrivals", "assignments", "accounts"}
    if "time_clocks" in tables and "statuses" in tables and "users" in tables and "works" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        work_columns = {column["name"] for column in inspector.get_columns("works")}
        clock_columns = {column["name"] for column in inspector.get_columns("time_clocks")}
        expected = {"id", "work_id", "user_id", "location", "photo", "arrive_date", "arrive_time"}
        if (
            "worker_id" not in user_columns
            and {"status_id", "names", "latitude", "longitude"}.issubset(work_columns)
            and expected.issubset(clock_columns)
            and not retired.intersection(tables)
        ):
            return
    names = [
        "task_blocks",
        "tasks",
        "time_clocks",
        "work_schedules",
        "payments",
        "arrivals",
        "assignments",
        "accounts",
        "users",
        "bank_account_types",
        "banks",
        "workers",
        "works",
        "roles",
        "statuses",
    ]
    with engine.begin() as connection:
        if engine.dialect.name == "mysql":
            connection.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for name in names:
            connection.execute(text(f"DROP TABLE IF EXISTS {name}"))
        if engine.dialect.name == "mysql":
            connection.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def ensure_decimal_quantity(engine) -> None:
    inspector = inspect(engine)
    if "work_items" not in inspector.get_table_names():
        return
    columns = {column["name"]: column for column in inspector.get_columns("work_items")}
    quantity = columns.get("quantity")
    if quantity is None or "int" not in str(quantity["type"]).lower():
        return
    if engine.dialect.name != "mysql":
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE work_items MODIFY quantity DOUBLE NOT NULL DEFAULT 0"))


def link_saved_units(engine) -> None:
    inspector = inspect(engine)
    if "charge_items" not in inspector.get_table_names() or "measure_units" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("charge_items")}
    if "unit" not in columns or "unit_id" not in columns:
        return
    statement = (
        "UPDATE charge_items "
        "INNER JOIN measure_units ON measure_units.name = charge_items.unit "
        "SET charge_items.unit_id = measure_units.id "
        "WHERE charge_items.unit_id IS NULL AND charge_items.unit <> ''"
        if engine.dialect.name == "mysql"
        else
        "UPDATE charge_items SET unit_id = ("
        "SELECT measure_units.id FROM measure_units WHERE measure_units.name = charge_items.unit"
        ") WHERE unit_id IS NULL AND unit <> ''"
    )
    with engine.begin() as connection:
        connection.execute(text(statement))


def create_app(database_url: str | None = None, secret: str = SECRET) -> FastAPI:
    load_env_file()
    if database_url is None:
        database_url = os.environ.get("DATABASE_URL", FALLBACK_DATABASE_URL)
    if database_url.startswith("mysql"):
        ensure_mysql_database(database_url)
        engine = create_engine(database_url)
    else:
        engine_kwargs: dict = {}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        if database_url == "sqlite://":
            engine_kwargs["poolclass"] = StaticPool
        engine = create_engine(database_url, **engine_kwargs)
    drop_legacy_tables(engine)
    Base.metadata.create_all(engine)
    ensure_hourly_rate(engine)
    ensure_work_days(engine)
    ensure_measure_columns(engine)
    ensure_decimal_quantity(engine)
    if database_url.startswith("sqlite"):
        with engine.begin() as connection:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_time_clocks_work_date ON time_clocks (work_id, arrive_date)"))
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        seed_if_empty(db)
        seed_tasks(db)
        ensure_tasks(db)
        seed_charge_items(db)
        ensure_charge_items(db)
        ensure_statuses(db)
        ensure_contract_types(db)
        ensure_roles(db)
        ensure_banks(db)
        ensure_measure_units(db)
        ensure_bank_account_types(db)
        ensure_setting(db)
    link_saved_units(engine)

    app = FastAPI(title="Vitrificados Chile")
    app.state.session_factory = session_factory
    app.state.secret = secret
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "https://vitrificadoschile.com",
            "https://www.vitrificadoschile.com",
            "https://admin.vitrificadoschile.com",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    if os.environ.get("LATE_WATCH", "1") != "0" and not database_url.startswith("sqlite"):
        from app.late_arrivals import start_late_watch

        start_late_watch(session_factory)

    from fastapi import Depends
    from sqlalchemy.orm import Session

    from app.deps import get_db
    from app.schemas import LoginBody, LoginResult

    @app.post("/api/auth/login", response_model=LoginResult)
    def login(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> LoginResult:
        return login_account(body, db, request.app.state.secret)

    return app


app = create_app()
