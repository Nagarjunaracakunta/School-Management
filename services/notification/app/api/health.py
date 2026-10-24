import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["ops"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    """Liveness: 'the process is running'. Must NOT check the database; otherwise a DB
    outage makes Kubernetes restart healthy pods, which only makes things worse."""
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request):
    """Readiness: 'I can serve traffic'. Failing removes the pod from the load balancer."""
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    return {"status": "ready", "database": "up"}
