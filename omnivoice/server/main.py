"""FastAPI application entry point for the geny-omnivoice service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from server import engine
from server.api import router
from server.diagnostics import router as diag_router
from server.settings import get_settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    settings = get_settings()
    _configure_logging(settings.log_level)
    log = logging.getLogger("server.lifespan")
    log.info("Starting geny-omnivoice; model=%s device=%s", settings.model, settings.device)

    # Configure CUDA allocator + cudnn flags BEFORE any tensor lands on
    # the device — the allocator settings only take effect for
    # subsequent allocations.
    try:
        engine.configure_runtime(settings)
    except Exception:
        log.exception("configure_runtime failed; continuing with defaults.")

    try:
        engine.load(settings)
    except Exception:
        log.exception("Failed to load OmniVoice model; service will return 503 on /tts.")
        engine.set_phase("error")
    else:
        if settings.warmup_enabled:
            try:
                await engine.warmup()
            except Exception:
                log.exception("Warmup failed; serving anyway with cold caches.")
                engine.set_phase("ok")
        else:
            engine.set_phase("ok")

    try:
        yield
    finally:
        log.info("Shutting down geny-omnivoice")
        engine.unload()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Geny OmniVoice",
        description="Geny's in-cluster wrapper around k2-fsa/OmniVoice TTS.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(diag_router)
    return app


app = create_app()


def run() -> None:
    """Console-script entry point used by ``geny-omnivoice-server``."""
    settings = get_settings()
    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
