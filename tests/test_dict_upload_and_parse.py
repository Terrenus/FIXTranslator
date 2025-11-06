import io
import pytest

@pytest.fixture
def tmp_upload_dir(tmp_path, monkeypatch):
    # Patch the upload directory to a temporary safe one
    upload_dir = tmp_path / "dicts"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("fixparser.main.DICT_DIR", upload_dir)
    return upload_dir

def test_dict_upload_and_parse(tmp_upload_dir, client):
    # Create a dummy valid XML file content
    xml_content = b"""<?xml version="1.0"?><fix><fields><field number="1" name="Account"/></fields></fix>"""

    # Upload the file through the API
    response = client.post(
        "/upload_dict",
        files={"file": ("FIX44.xml", io.BytesIO(xml_content), "application/xml")},
    )

    assert response.status_code == 200, response.text
    resp_json = response.json()
    assert resp_json.get("status") == 200
    assert resp_json.get("filename", "").lower() == "fix44.xml"

    # Ensure the file was saved correctly in the safe directory
    saved = tmp_upload_dir / "FIX44.xml"
    assert saved.exists()

    # Double-check path stays within allowed directory
    resolved = saved.resolve()
    assert str(tmp_upload_dir.resolve()) in str(resolved)
