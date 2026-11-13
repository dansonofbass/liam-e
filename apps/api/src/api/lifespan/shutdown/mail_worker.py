"""Stop the mail worker before disposing of the database."""

import asyncio

from fastapi import FastAPI


async def shutdown(app: FastAPI) -> None:
    worker = getattr(app.state, "mail_worker", None)
    if worker is None:
        return
    stop, task = worker
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=10)
    except TimeoutError:
        pass
