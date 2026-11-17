"""Start the durable mail worker."""

import asyncio

from env.mail import env as mail_env
from fastapi import FastAPI

from api.calendar.sync import register_worker
from api.mail.jobs import worker_loop


async def startup(app: FastAPI) -> None:
    register_worker()
    if mail_env.mail_worker_enabled:
        stop = asyncio.Event()
        app.state.mail_worker = (stop, asyncio.create_task(worker_loop(stop)))
