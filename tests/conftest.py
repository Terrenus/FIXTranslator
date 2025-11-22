# tests/conftest.py
import pytest
import os
import sys
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport

TEST_DICT_DIR_PATH = Path(__file__).parent / "test_dicts"

@pytest.fixture(scope="session")
def client():
    os.environ["API_KEYS"] = "testkey123"

    if "fixparser.main" in sys.modules:
        del sys.modules["fixparser.main"]

    from fixparser import main as main_module
    from fastapi.testclient import TestClient

    client = TestClient(main_module.app)
    client.headers.update({"x-api-key": "testkey123"})

    return client

@pytest_asyncio.fixture
async def async_client(client):
    from fixparser.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers.update(client.headers)
        yield ac