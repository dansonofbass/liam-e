"""Structured, user-safe API refusals."""

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute


def refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def quiet_validation_route(code: str, message: str) -> type[APIRoute]:
    """Route class whose 422 names the problem without echoing the rejected input.

    FastAPI's default 422 body repeats each invalid value, which for chat routes is mail or
    message text.
    """

    class QuietValidationRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def quiet_handler(request):
                try:
                    return await handler(request)
                except RequestValidationError:
                    raise refuse(422, code, message) from None

            return quiet_handler

    return QuietValidationRoute
