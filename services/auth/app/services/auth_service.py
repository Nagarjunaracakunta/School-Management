import datetime as dt
import logging
from collections.abc import Callable

from app.config.settings import Settings
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse
from app.services.passwords import PasswordHasher
from app.services.tokens import TokenIssuer
from app.utils.errors import UnauthorizedError

logger = logging.getLogger(__name__)

# One message for EVERY failure (no such user, wrong password, locked, disabled), so the response never
# tells an attacker which of those it was.
INVALID_LOGIN = "Invalid email or password"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


class AuthService:
    def __init__(
        self,
        repo: UserRepository,
        hasher: PasswordHasher,
        issuer: TokenIssuer,
        settings: Settings,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self.repo = repo
        self.hasher = hasher
        self.issuer = issuer
        self.max_failed = settings.max_failed_logins
        self.lockout = dt.timedelta(minutes=settings.lockout_minutes)
        self.now = clock

    def login(self, email: str, password: str) -> TokenResponse:
        email = email.strip().lower()
        user = self.repo.by_email(email, lock=True)
        now = self.now()

        if user is None:
            self.hasher.verify_dummy(password)  # same cost as a real check: no timing hint
            self._fail("unknown_email", email)

        locked = user.locked_until is not None and self._aware(user.locked_until) > now
        if locked:
            self.hasher.verify_dummy(password)  # do not even try the real hash while locked
            self._fail("account_locked", email, user_id=str(user.id))

        if not self.hasher.verify(user.password_hash, password):
            user.failed_attempts += 1
            if user.failed_attempts >= self.max_failed:
                user.locked_until = now + self.lockout
                user.failed_attempts = 0
                logger.warning("account locked after repeated failures", extra={"user_id": str(user.id)})
            self.repo.commit()
            self._fail("wrong_password", email, user_id=str(user.id))

        if not user.is_active:
            self.repo.commit()
            self._fail("account_disabled", email, user_id=str(user.id))

        user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
        if self.hasher.needs_rehash(user.password_hash):
            user.password_hash = self.hasher.hash(password)  # silently upgrade old hashes to current settings
        self.repo.commit()
        logger.info("login succeeded", extra={"event": "login_success", "user_id": str(user.id), "role": user.role})
        return TokenResponse(access_token=self.issuer.issue(user, now), expires_in=self.issuer.ttl_seconds)

    @staticmethod
    def _aware(value: dt.datetime) -> dt.datetime:
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)  # SQLite drops the timezone

    def _fail(self, reason: str, email: str, user_id: str | None = None):
        # The REASON goes to the log (for security monitoring), never to the caller.
        logger.warning(
            "login failed",
            extra={"event": "login_failed", "reason": reason, "email": mask_email(email), "user_id": user_id},
        )
        raise UnauthorizedError(INVALID_LOGIN)
