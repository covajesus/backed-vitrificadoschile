from collections.abc import Generator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.models import ROLE_ADMIN, UserRow
from app.security import read_token

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def current_account(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> UserRow:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sesión requerida.")
    account_id = read_token(credentials.credentials, request.app.state.secret)
    try:
        key = int(account_id) if account_id else None
    except ValueError:
        key = None
    account = db.get(UserRow, key) if key else None
    if account is None or not account.active:
        raise HTTPException(status_code=401, detail="La sesión no es válida.")
    return account


def require_admin(account: UserRow = Depends(current_account)) -> UserRow:
    if account.rol_id != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tienes permiso para esta acción.")
    return account
