from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["ops"])


@router.get("/.well-known/jwks.json")
def jwks(request: Request, response: Response) -> dict:
    """Public signing keys (JWKS). Safe to publish. Services can fetch this instead of being handed a PEM
    file, which is what makes zero-downtime key rotation possible."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return request.app.state.issuer.jwks()
