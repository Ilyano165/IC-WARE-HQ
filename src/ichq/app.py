"""Anwendungsfabrik. Startet nur, wenn Konfiguration gültig ist und jede Route eine Sicherheitsregel hat."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ichq import __version__
from ichq.api import health as health_routes
from ichq.api.errors import install_error_handlers
from ichq.api.middleware import RequestContextMiddleware
from ichq.api.origin import OriginGuardMiddleware
from ichq.api.security import assert_routes_secured
from ichq.api.state import AppState
from ichq.api.v1.auth import router as auth_router
from ichq.api.v1.comments import router as comments_router
from ichq.api.v1.documents import router as documents_router
from ichq.api.v1.inbox import router as inbox_router
from ichq.api.v1.objects import router as objects_router
from ichq.api.v1.router import router as v1_router
from ichq.api.v1.tasks import router as tasks_router
from ichq.auth.mailer import Mailer, build_mailer
from ichq.core.config import Settings, get_settings
from ichq.core.logging import configure_logging
from ichq.db.engine import Engines, build_engines
from ichq.models import assert_complete
from ichq.storage import Storage, build_storage


def create_app(settings: Settings | None = None, *, engines: Engines | None = None,
               storage: Storage | None = None, mailer: Mailer | None = None,
               extra_routers: tuple[object, ...] = ()) -> FastAPI:
    settings = settings or get_settings()
    assert_complete()
    configure_logging(settings.log_level, settings.log_format)
    engines = engines or build_engines(settings)
    storage = storage or build_storage(settings)
    mailer = mailer or build_mailer(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engines.dispose()

    app = FastAPI(
        title="IC WARE HQ", version=__version__, lifespan=lifespan,
        docs_url="/docs" if settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_docs else None,
    )
    app.state.ichq = AppState(settings=settings, engines=engines, storage=storage, mailer=mailer)
    install_error_handlers(app)
    app.include_router(health_routes.router)
    app.include_router(v1_router)
    app.include_router(auth_router)
    for core in (objects_router, tasks_router, comments_router, documents_router, inbox_router):
        app.include_router(core)
    for r in extra_routers:
        app.include_router(r)  # type: ignore[arg-type]
    app.add_middleware(OriginGuardMiddleware, public_origin=settings.public_origin)
    app.add_middleware(RequestContextMiddleware)   # zuletzt hinzugefügt = äußerste Schicht
    assert_routes_secured(app)
    return app
