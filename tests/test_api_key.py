def test_parse_requires_api_key(monkeypatch, client):
    monkeypatch.setenv("API_KEYS", "mykey")

    # Missing key
    r1 = client.post("/parse", json={"raw": "8=FIX.4.2\x019=12\x0135=0\x0110=000\x01"})
    assert r1.status_code == 401

    # Wrong key
    r2 = client.post("/parse", json={"raw": "8=FIX.4.2\x019=12\x0135=0\x0110=000\x01"},
                     headers={"x-api-key": "wrong"})
    assert r2.status_code == 401

    # Correct key
    r3 = client.post("/parse", json={"raw": "8=FIX.4.2\x019=12\x0135=0\x0110=000\x01"},
                     headers={"x-api-key": "mykey"})
    assert r3.status_code != 401
