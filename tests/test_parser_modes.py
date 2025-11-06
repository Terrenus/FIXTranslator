import pytest

VALID_MESSAGE = b"8=FIX.4.2\x019=12\x0135=D\x0110=000\x01"
MALFORMED_MESSAGE = b"8=FIX.4.2|9=12|35=D|10=000|"  # wrong delimiter and structure

def test_parse_lenient_accepts_various_delimiters(client):
    resp = client.post("/parse?mode=lenient", json={"raw": MALFORMED_MESSAGE.decode("latin1")})
    assert resp.status_code == 200
    data = resp.json()
    assert "message_type" in data or "parsed" in data  # expect parser to produce something

def test_parse_strict_rejects_malformed(client):
    resp = client.post("/parse?mode=strict", json={"raw": MALFORMED_MESSAGE.decode("latin1")})
    assert resp.status_code == 400

def test_parse_valid_message_strict(client):
    resp = client.post("/parse?mode=strict", json={"raw": VALID_MESSAGE.decode("latin1")})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("flat", {}).get("Tag8") == "FIX.4.2"

@pytest.mark.parametrize("mode", ["lenient", "strict"])
def test_parse_requires_raw_key(mode, client):
    resp = client.post(f"/parse?mode={mode}", json={"not_raw": "x"})
    assert resp.status_code == 422  # schema validation
