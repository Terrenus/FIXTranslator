
def test_large_body_rejected(client):
    big = "A" * (2 * 1024 * 1024)  # 2 MB, above 1MB limit in our proposed middleware
    resp = client.post("/parse?mode=lenient", json={"raw": big})
    assert resp.status_code in (413, 400)

def test_api_key_required(client):
    client.headers.update({"x-api-key": "testkey"})
    resp = client.post("/parse?mode=lenient", json={"raw": "8=FIX..."})
    assert resp.status_code == 401
