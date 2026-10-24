import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.utils.errors import ConflictError


class BaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, obj: Any) -> None:
        self.session.add(obj)
        try:
            self.session.flush()  # the INSERT happens here, so constraint errors surface here too
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("A record with these values already exists") from exc

    def get(self, model: type, object_id: uuid.UUID) -> Any | None:
        return self.session.get(model, object_id)

    def page(self, model: type, *where: Any, order_by: Any, offset: int, limit: int) -> tuple[list[Any], int]:
        total = self.session.scalar(select(func.count()).select_from(model).where(*where)) or 0
        rows = self.session.scalars(select(model).where(*where).order_by(order_by).offset(offset).limit(limit))
        return list(rows.unique()), total

    def commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            # A unique constraint caught a race that the friendly pre-checks missed.
            self.session.rollback()
            raise ConflictError("A record with these values already exists") from exc
