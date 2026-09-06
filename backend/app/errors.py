"""RFC 7807 problem-detail handlers."""

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    invalid_params: list[dict[str, Any]] | None = None


def _response(problem: ProblemDetails) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exc = exc if isinstance(exc, HTTPException) else None
    detail = str(http_exc.detail if http_exc is not None else exc)
    return _response(
        ProblemDetails(
            title="HTTP Error",
            status=http_exc.status_code if http_exc is not None else 500,
            detail=detail,
            instance=str(request.url),
        )
    )


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    validation = exc if isinstance(exc, RequestValidationError) else None
    if validation is None:
        return await unhandled_exception_handler(request, exc)
    invalid = [
        {"name": ".".join(str(part) for part in error["loc"]), "reason": error["msg"]}
        for error in validation.errors()
    ]
    return _response(
        ProblemDetails(
            title="Validation Error",
            status=422,
            detail="Request validation failed.",
            instance=str(request.url),
            invalid_params=invalid,
        )
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del exc
    return _response(
        ProblemDetails(
            title="Internal Server Error",
            status=500,
            detail="An unexpected error occurred.",
            instance=str(request.url),
        )
    )
