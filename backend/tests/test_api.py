from asyncio import run

from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from pytest import MonkeyPatch

from app.main import app

AUTH_HEADERS = {"X-Session-Token": "test-session-token"}


def request(
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    *,
    json: dict[str, object] | None = None,
    data: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> Response:
    async def send() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(
                method,
                path,
                headers=headers,
                json=json,
                data=data,
                files=files,
            )

    return run(send())


def test_health_requires_session_token() -> None:
    response = request("GET", "/health")
    assert response.status_code == 401


def test_health_returns_readiness_information(monkeypatch: MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "session_token", SecretStr("test-session-token"))
    response = request("GET", "/health", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_cors_preflight_is_limited_to_application_origins() -> None:
    allowed = request(
        "OPTIONS",
        "/api/v1/recordings",
        headers={
            "Origin": "http://127.0.0.1:1420",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-session-token",
        },
    )
    denied = request(
        "OPTIONS",
        "/api/v1/recordings",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:1420"
    assert "access-control-allow-origin" not in denied.headers
