import re
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Accept a caller-supplied ID only if it looks sane; otherwise a malicious header
# could inject junk (or log-forging newlines) into our logs.
_SAFE_ID = re.compile(r"^[A-Za-z0-9\-_.]{8,64}$")


def resolve_request_id(incoming: str | None) -> str:
    return incoming if incoming and _SAFE_ID.match(incoming) else str(uuid.uuid4())
