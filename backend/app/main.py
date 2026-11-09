from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.recordings import router as recordings_router
from app.core.security import SessionTokenMiddleware
from app.schemas.health import HealthResponse
from app.services.recordings import RecordingSession


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        application.state.recording_session.close()


app = FastAPI(title="Aureon API", version="1.0.0", lifespan=lifespan)
app.state.recording_session = RecordingSession()
app.add_middleware(SessionTokenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(tauri://localhost|https?://tauri\.localhost|http://(127\.0\.0\.1|localhost):1420)$",
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["X-Session-Token", "Content-Type"],
)
app.include_router(recordings_router, prefix="/api/v1")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=app.version)
