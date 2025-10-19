import os
import tempfile
import shutil
from fastapi.testclient import TestClient
from fixparser.main import app, DICT_DIR

client = TestClient(app)

# minimal QuickFIX XML dictionary content with a custom tag 9999
SAMPLE_DICT_XML = '''<?xml version="1.0"?>
<fix>
  <fields>
    <field number="9999" name="CustomTag" type="STRING"/>
  </fields>
</fix>
'''

def test_upload_dict_and_parse(tmp_path, monkeypatch):
    # create a tmp dict dir and point DICT_DIR env var to it before calling app
    tmpdir = tmp_path / "dicts"
    tmpdir.mkdir()
    # monkeypatch the DICT_DIR in the module so upload goes there
    monkeypatch.setenv("FIXPARSER_DICT_DIR", str(tmpdir))
    # we need to reload parts of app to pick env change; but upload endpoint uses DICT_DIR var defined at import
    # so instead write directly to the expected DICT_DIR used by the running app:
    # Use the DICT_DIR from the imported module (already set). Ensure it exists.
    ddir = DICT_DIR
    os.makedirs(ddir, exist_ok=True)

    # upload file via API
    files = {"file": ("custom.xml", SAMPLE_DICT_XML, "application/xml")}
    resp = client.post("/upload_dict", files=files)
    assert resp.status_code == 200, resp.text
    j = resp.json()
    assert j["ok"] is True
    filename = j["filename"]
    assert filename == "custom.xml"
    # Now parse a message that contains tag 9999
    msg = "8=FIX.4.4|9=176|35=D|49=CLIENT|56=BROKER|11=1|9999=HELLO|10=000|"
    r = client.post(f"/parse?dict_name={filename}", json={"raw": msg})
    assert r.status_code == 200, r.text
    body = r.json()
    # parsed_by_tag should include '9999'
    parsed = body.get("parsed")
    assert parsed is not None
    assert "9999" in parsed
    assert parsed["9999"]["name"] == "CustomTag"
    assert parsed["9999"]["value"] == "HELLO"
