from fastapi.testclient import TestClient
from fixparser.main import app

SAMPLE = "8=FIX.4.4|9=176|35=D|49=CLIENT12|56=BROKER03|34=215|52=20250927-12:30:05.123|11=12345|55=EUR/USD|54=1|38=1000000|40=2|44=1.1850|60=20250927-12:30:05|10=062|"

client = TestClient(app)

def test_parse_endpoint_json_single():
    r = client.post("/parse", json={"raw": SAMPLE})
    assert r.status_code == 200
    body = r.json()
    # API returns a 'flat' mapping and 'raw'
    assert "flat" in body
    assert "raw" in body
    # Expect MsgType (tag 35) present inside parsed_by_tag
    parsed = body.get("parsed", {})
    assert "35" in parsed and parsed["35"]["value"] == "D"

def test_ui_get():
    r = client.get("/ui")
    assert r.status_code == 200
    # page should include the form textarea marker
    assert "<textarea" in r.text
