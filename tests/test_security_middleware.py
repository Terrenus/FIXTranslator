
def test_large_body_rejected(client):
    big = "A" * (2 * 1024 * 1024)  # 2 MB, above 1MB limit in our proposed middleware
    resp = client.post("/parse?mode=lenient", json={"raw": big})
    assert resp.status_code==413

    response_json = resp.json()
    assert "detail" in response_json
    assert "Request body size exceeds the maximum limit" in response_json["detail"]


def test_api_key_required(client):
    client.headers.update({"x-api-key": "testkey"})
    resp = client.post("/parse?mode=lenient", json={"raw": "8=FIX..."})
    assert resp.status_code == 401
