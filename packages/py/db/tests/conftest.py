"""Disposable Postgres database for mail accessor contracts."""

import asyncio
import uuid
from pathlib import Path

import db.engine
import env.db
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
def pg_db(monkeypatch):
    name = f"mail_{uuid.uuid4().hex[:12]}"
    admin_url = env.db.env.async_database_url

    async def admin(sql):
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(sql))
        finally:
            await engine.dispose()

    asyncio.run(db.engine.dispose_engine())
    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    monkeypatch.setattr(env.db.env, "database_url", url)
    project = Path(__file__).resolve().parents[1]
    config = Config(str(project / "alembic.ini"))
    config.set_main_option("script_location", str(project / "src/db/migrations"))
    try:
        command.upgrade(config, "heads")
        yield
    finally:
        asyncio.run(db.engine.dispose_engine())
        monkeypatch.undo()
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
