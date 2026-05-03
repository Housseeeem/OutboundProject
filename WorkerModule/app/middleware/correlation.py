import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Injects a unique correlation_id into every request and response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_correlation_id = request.headers.get("X-Correlation-ID", "").strip()
        request.state.correlation_id = incoming_correlation_id or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response
