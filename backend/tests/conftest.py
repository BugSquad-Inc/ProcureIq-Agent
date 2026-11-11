"""conftest.py — Shared pytest setup and clean async engine teardown."""
import pytest_asyncio

from app.infrastructure.database.session import engine


@pytest_asyncio.fixture(scope="session", autouse=True)
async def dispose_engine_after_session():
    yield
    await engine.dispose()

