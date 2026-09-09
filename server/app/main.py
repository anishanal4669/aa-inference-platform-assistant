import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import meta, stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    app.state.settings = cfg
    logging.getLogger("gateway").info(
        "gateway up: anonymous=%s rpm=%s tpm=%s", cfg.allow_anonymous, cfg.rpm_limit, cfg.tpm_limit
    )
    yield


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title="Inference gateway", version="0.1.0", lifespan=lifespan)
    app.state.settings = cfg  # lifespan doesn't run under bare ASGI transports
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.origins,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
        expose_headers=["x-request-id"],
    )
    app.include_router(stream.router)
    app.include_router(meta.router)
    return app


app = create_app()
