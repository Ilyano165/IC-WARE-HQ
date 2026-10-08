from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from ichq.api.problems import problem
from ichq.core.errors import AppError

log = logging.getLogger("ichq.api")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> Response:
        return problem(exc.status, exc.code, exc.title, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # Starlette-Texte wie "Not Found" sind generisch; eigene Details nur bei 4xx
        detail = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else None
        return problem(exc.status_code, detail=detail if detail not in ("Not Found", "Method Not Allowed") else None)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        # Bewusst ohne "input": Eingaben könnten Passwörter oder Tokens enthalten
        fehler = [{"loc": [str(x) for x in e.get("loc", ())], "msg": e.get("msg"), "type": e.get("type")}
                  for e in exc.errors()]
        return problem(422, errors=fehler)
