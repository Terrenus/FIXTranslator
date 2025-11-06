# tests/conftest.py
import pytest
import os
import sys

@pytest.fixture(scope="session")
def client():
    os.environ["API_KEYS"] = "testkey123"

    from fixparser import main as main_module
    from fastapi.testclient import TestClient

    client = TestClient(main_module.app)
    client.headers.update({"x-api-key": "testkey123"})
    del sys.modules["fixparser.main"]
    return client
