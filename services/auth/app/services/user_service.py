import datetime as dt
import logging
import uuid

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import PasswordChange, UserCreate, UserUpdate
from app.services.passwords import PasswordHasher, validate_password
from app.utils.errors import ConflictError, NotFoundError, UnprocessableError
from app.utils.security import CurrentUser, Role

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, repo: UserRepository, hasher: PasswordHasher) -> None:
        self.repo = repo
        self.hasher = hasher

    def create(self, data: UserCreate, admin: CurrentUser) -> User:
        email = str(data.email).strip().lower()
        if self.repo.by_email(email):
            raise ConflictError("A user with this email already exists")
        user = User(
            email=email,
            full_name=data.full_name,
            role=data.role.value,
            password_hash=self.hasher.hash(data.password),
        )
        self.repo.add(user)  # a racing duplicate is caught by the UNIQUE key and becomes a 409
        self.repo.commit()
        logger.info(
            "user created", extra={"event": "user_created", "user_id": str(user.id), "role": user.role, "by": admin.id}
        )
        return user

    def get(self, user_id: uuid.UUID, caller: CurrentUser) -> User:
        user = self.repo.get(User, user_id)
        # A non-admin may read only their own record; anything else looks like "does not exist"
        if user is None or (caller.role is not Role.ADMIN and str(user.id) != caller.id):
            raise NotFoundError("User not found")
        return user

    def me(self, caller: CurrentUser) -> User:
        user = self.repo.get(User, uuid.UUID(caller.id))
        if user is None or not user.is_active:
            raise NotFoundError("User not found")  # a deactivated user's old token stops being useful here
        return user

    def list(self, *, role, is_active, q, offset, limit) -> tuple[list[User], int]:
        return self.repo.search(role=role, is_active=is_active, q=q, offset=offset, limit=limit)

    def update(self, user_id: uuid.UUID, data: UserUpdate, admin: CurrentUser) -> User:
        user = self.repo.lock_user(user_id)
        if user is None:
            raise NotFoundError("User not found")

        new_role = data.role.value if data.role else user.role
        new_active = user.is_active if data.is_active is None else data.is_active
        losing_admin = user.role == "admin" and user.is_active and (new_role != "admin" or not new_active)
        if losing_admin:
            if str(user.id) == admin.id:
                raise ConflictError("You cannot demote or deactivate your own account")
            if self.repo.count_active_admins() <= 1:
                raise ConflictError("There must always be at least one active administrator")

        if data.full_name is not None:
            user.full_name = data.full_name
        user.role, user.is_active = new_role, new_active
        self.repo.commit()
        logger.info(
            "user updated",
            extra={
                "event": "user_updated",
                "user_id": str(user.id),
                "role": user.role,
                "active": user.is_active,
                "by": admin.id,
            },
        )
        return user

    def reset_password(self, user_id: uuid.UUID, new_password: str, admin: CurrentUser) -> None:
        user = self.repo.lock_user(user_id)
        if user is None:
            raise NotFoundError("User not found")
        self._set_password(user, new_password)
        user.failed_attempts, user.locked_until = 0, None  # an admin reset also unlocks the account
        self.repo.commit()
        logger.info(
            "password reset by admin", extra={"event": "password_reset", "user_id": str(user.id), "by": admin.id}
        )

    def change_own_password(self, data: PasswordChange, caller: CurrentUser) -> None:
        user = self.repo.lock_user(uuid.UUID(caller.id))
        if user is None or not user.is_active:
            raise NotFoundError("User not found")
        if not self.hasher.verify(user.password_hash, data.current_password):
            # 422, not 401: a 401 makes the browser log the user out as if their session had expired
            raise UnprocessableError("Current password is incorrect")
        self._set_password(user, data.new_password)
        self.repo.commit()
        logger.info("password changed", extra={"event": "password_changed", "user_id": str(user.id)})

    def _set_password(self, user: User, new_password: str) -> None:
        try:
            validate_password(new_password, user.email)
        except ValueError as exc:
            raise UnprocessableError(str(exc)) from exc
        user.password_hash = self.hasher.hash(new_password)
        user.password_changed_at = dt.datetime.now(dt.UTC)
