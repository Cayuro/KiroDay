"""FastAPI application factory and Lambda entrypoint (task 9.3).

Builds the FastAPI app, registers the error handlers (task 9.1) and the routes
(tasks 9.2, 9.3), and exposes a Mangum ASGI handler so the exact same app runs
locally under uvicorn and on AWS Lambda behind API Gateway.

Local development::

    uvicorn app.api.app:app --reload

AWS Lambda handler: ``app.api.app.handler`` (Mangum-wrapped).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import router


def create_app() -> FastAPI:
    """Create and configure the POS FastAPI application."""

    app = FastAPI(
        title="POS MVP API",
        version="0.1.0",
        description="Punto de venta para tienda de barrio (MVP).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Lightweight liveness probe."""

        return {"status": "ok"}

    return app


# The ASGI app used by uvicorn locally and wrapped by Mangum on Lambda.
app = create_app()

# Lambda entrypoint: API Gateway -> Mangum -> FastAPI.
try:  # pragma: no cover - import guard for environments without mangum
    from mangum import Mangum

    handler = Mangum(app)
except ModuleNotFoundError:  # pragma: no cover
    handler = None
