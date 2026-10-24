import uuid
from typing import Any

from sqlalchemy import func, or_, select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    def by_email(self, email: str, *, lock: bool = False) -> User | None:
        stmt = select(User).where(User.email == email)
        if lock:
            # Serialises concurrent login attempts for one account so the failed-attempt counter is exact
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(stmt)

    def lock_user(self, user_id: uuid.UUID) -> User | None:
        return self.session.scalar(
            select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
        )

    def count_active_admins(self) -> int:
        return (
            self.session.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))) or 0
        )

    def search(
        self, *, role: str | None, is_active: bool | None, q: str | None, offset: int, limit: int
    ) -> tuple[list[User], int]:
        where: list[Any] = []
        if role:
            where.append(User.role == role)
        if is_active is not None:
            where.append(User.is_active.is_(is_active))
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            where.append(or_(User.email.ilike(like, escape="\\"), User.full_name.ilike(like, escape="\\")))
        total = self.session.scalar(select(func.count(User.id)).where(*where)) or 0
        rows = self.session.scalars(
            select(User).where(*where).order_by(User.full_name, User.id).offset(offset).limit(limit)
        )
        return list(rows), total
