from fastapi.testclient import TestClient
from fixparser.main import app

client = TestClient(app)

def test_parse_batch_simple():
    m1 = {"raw": "8=FIX.4.4|9=176|35=D|49=A|56=B|11=1|55=EUR/USD|10=000|"}
    m2 = {"raw": "8=FIX.4.4|9=176|35=D|49=B|56=A|11=2|55=GBP/USD|10=000|"}
    payload = [m1, m2]
    r = client.post("/parse/batch", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["flat"] is not None
    assert body[1]["flat"] is not None
