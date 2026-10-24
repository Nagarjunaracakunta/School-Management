from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError

from app.config.settings import Settings

MIN_LENGTH, MAX_LENGTH = 12, 128
# A very small deny-list of the passwords attackers try first. Real systems also check breached-password lists.
COMMON = {
    "password1234",
    "123456789012",
    "qwertyuiop12",
    "iloveyou1234",
    "letmein12345",
    "welcome12345",
    "administrator",
    "changeme1234",
    "schoolschool",
    "password12345",
}


def password_problem(password: str, email: str = "") -> str | None:
    """Returns why a password is unacceptable, or None when it is fine.

    Length matters far more than symbol rules, so we require length and reject the obvious, but we do not
    force "one capital, one digit, one symbol" (which pushes people to Password1!).
    """
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters"
    if len(password) > MAX_LENGTH:
        return f"Password must be at most {MAX_LENGTH} characters"
    lowered = password.lower()
    if lowered in COMMON or len(set(lowered)) < 4:
        return "That password is too easy to guess"
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in lowered:
        return "Password must not contain your email name"
    return None


def validate_password(password: str, email: str = "") -> str:
    problem = password_problem(password, email)
    if problem:
        raise ValueError(problem)
    return password


class PasswordHasher:
    """Argon2id: memory-hard, so stolen hashes are expensive to crack on GPUs. Each hash carries its own
    random salt and parameters, so raising the cost later still lets old hashes verify (and upgrade)."""

    def __init__(self, settings: Settings) -> None:
        self._argon = Argon2(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
        # Verified against when the account does not exist, so "no such user" costs the same time as
        # "wrong password" and response timing cannot be used to discover which emails are registered.
        self._dummy_hash = self._argon.hash("not-a-real-user-password")

    def hash(self, password: str) -> str:
        return self._argon.hash(password)

    def _check(self, stored_hash: str, password: str) -> bool:
        try:
            return self._argon.verify(stored_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def verify(self, stored_hash: str, password: str) -> bool:
        return self._check(stored_hash, password)

    def verify_dummy(self, password: str) -> None:
        """Burns the same time as a real check, against a hash that can never match."""
        self._check(self._dummy_hash, password)

    def needs_rehash(self, stored_hash: str) -> bool:
        return self._argon.check_needs_rehash(stored_hash)
