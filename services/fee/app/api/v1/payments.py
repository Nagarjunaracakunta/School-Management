import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import get_payment_service, require_roles
from app.schemas.common import ErrorResponse, Page
from app.schemas.fee import PaymentCreate, PaymentOut, ReceiptOut
from app.services.payment_service import PaymentService, payment_out
from app.utils.security import CurrentUser, Role

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

Service = Annotated[PaymentService, Depends(get_payment_service)]
AdminOrParent = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.PARENT))]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=64, pattern=r"^[A-Za-z0-9\-_.]+$")
]

ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    502: {"model": ErrorResponse, "description": "Student service unavailable"},
}


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_payment(body: PaymentCreate, key: IdempotencyKey, service: Service, user: AdminOrParent, response: Response):
    """Pay (part of) a fee. Send a fresh `Idempotency-Key` per payment attempt and reuse it on retries:
    the same key returns the original payment (200) instead of charging twice."""
    payment, created = service.pay(body, key, user)
    location = f"/api/v1/payments/{payment.id}"
    if not created:
        return JSONResponse(
            status_code=200,
            content=payment_out(payment).model_dump(mode="json"),
            headers={"Location": location, "Idempotent-Replayed": "true"},
        )
    response.headers["Location"] = location
    return payment_out(payment)


@router.get("", response_model=Page[PaymentOut], responses=ERRORS)
def list_payments(
    service: Service,
    user: AdminOrParent,
    fee_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(COMPLETED|FAILED|PENDING)$"),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = service.list(user, fee_id=fee_id, status=status, offset=(page - 1) * page_size, limit=page_size)
    return Page(items=[payment_out(p) for p in items], total=total, page=page, page_size=page_size)


@router.get("/{payment_id}", response_model=PaymentOut, responses=ERRORS)
def get_payment(payment_id: uuid.UUID, service: Service, user: AdminOrParent):
    return payment_out(service.get(payment_id, user))


@router.get("/{payment_id}/receipt", response_model=ReceiptOut, responses=ERRORS)
def get_receipt(payment_id: uuid.UUID, service: Service, user: AdminOrParent):
    return service.receipt(payment_id, user)
