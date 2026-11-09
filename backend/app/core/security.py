import hmac
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class SessionTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied_token = request.headers.get("x-session-token", "")
        if not hmac.compare_digest(supplied_token, settings.session_token.get_secret_value()):
            return Response(status_code=401, content="Unauthorized")
        return await call_next(request)
