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
from app.seed import ensure_bank_account_types, ensure_banks, ensure_charge_items, ensure_roles, ensure_setting, seed_charge_items, seed_if_empty, seed_tasks
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
    ensure_column(engine, "charge_items", "parent_id", "parent_id INTEGER NULL")


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
    if database_url.startswith("sqlite"):
        with engine.begin() as connection:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_time_clocks_work_date ON time_clocks (work_id, arrive_date)"))
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        seed_if_empty(db)
        seed_tasks(db)
        seed_charge_items(db)
        ensure_charge_items(db)
        ensure_roles(db)
        ensure_banks(db)
        ensure_bank_account_types(db)
        ensure_setting(db)

    app = FastAPI(title="Vitrificados Chile")
    app.state.session_factory = session_factory
    app.state.secret = secret
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    from fastapi import Depends
    from sqlalchemy.orm import Session

    from app.deps import get_db
    from app.schemas import LoginBody, LoginResult

    @app.post("/api/auth/login", response_model=LoginResult)
    def login(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> LoginResult:
        return login_account(body, db, request.app.state.secret)

    return app


app = create_app()
