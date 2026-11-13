"""Structured, user-safe API refusals."""

from fastapi import HTTPException


def refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})
