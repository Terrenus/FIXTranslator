import io
import pytest
from pathlib import Path
from starlette import status
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def disable_apikey_check_for_all_tests(monkeypatch):
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")

@pytest.fixture
def fix_dict_content():
    dict_file_path = Path("fixparser/dicts/FIX44.xml") 
    
    if not dict_file_path.exists():
        pytest.fail(f"Required FIX dictionary fixture not found at: {dict_file_path}. Please place the file there.")
        
    return dict_file_path.read_bytes()    

@pytest.fixture
def valid_json_content():
    """Provides a minimal, valid JSON dictionary as bytes."""
    return b"""
{
    "tags": {
        "8": "BeginString",
        "9": "BodyLength",
        "35": "MsgType"
    },
    "messages": {
        "0": {
            "name": "Heartbeat",
            "fields": [
                {"number": 112, "name": "TestReqID", "required": false}
            ]
        }
    }
}
"""

@pytest.fixture
def invalid_json_content():
    """Provides broken/invalid JSON content as bytes."""
    return b"""
{
    "tags": {
        "8": "BeginString"
    , 
"""

@pytest.fixture
def tmp_upload_dir(tmp_path, monkeypatch):
    upload_dir = tmp_path / "dicts"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("fixparser.main.DICT_DIR", upload_dir)
    return upload_dir

def test_dict_upload_and_parse(tmp_upload_dir, client, fix_dict_content):
    
    response = client.post(
        "/upload_dict",
        files={"file": ("FIX44.xml", io.BytesIO(fix_dict_content), "application/xml")},
    )

    assert response.status_code == 201, response.text  
    resp_json = response.json()
    assert resp_json.get("status") == "created"       
    assert resp_json.get("upload_filename", "").lower() == "fix44.xml"

    saved = tmp_upload_dir / "FIX44.xml"
    assert saved.exists()
    assert saved.read_bytes() == fix_dict_content 

    resolved = saved.resolve()
    assert str(tmp_upload_dir.resolve()) in str(resolved)

def test_upload_dict_file_valid_but_empty(client, monkeypatch, tmp_upload_dir):
    mock_dict = MagicMock()
    mock_dict.tags = {} 
    from fixparser import main
    
    monkeypatch.setattr(main, 'DICT_DIR', tmp_upload_dir)
    
    monkeypatch.setattr(main.parser, 'FixDictionary', lambda: mock_dict)
    file_content = b"<fix><header/></fix>" 
    
    response = client.post(
        "/upload_dict",
        files={"file": ("empty_dict.xml", file_content, "application/xml")}
    )
    
    assert response.status_code == 400
    assert "Dictionary loaded but contains no valid FIX messages or fields" in response.json()["detail"]
    
    saved_path = tmp_upload_dir / "empty_dict.xml"
    assert not saved_path.exists()

def test_upload_dict_file_exists(client, tmp_upload_dir, caplog):

    existing_file_name = "existing.xml"
    existing_file_path = tmp_upload_dir / existing_file_name
    
    existing_file_path.write_text("<fix><fields><field number='8' name='BeginString' type='STRING'/></fields></fix>") 
    
    assert existing_file_path.exists()

    response = client.post(
        "/upload_dict",
        data={"update": "false"},
        files={"file": ("existing.xml", b"<fix>new content</fix>", "application/xml")}
    )
    
    assert response.status_code == status.HTTP_409_CONFLICT 
    assert f"Dictionary file '{existing_file_path.name}' already exists. Use 'update=true" in response.json()["detail"]
    assert any("Upload blocked: Dictionary file already exists" in record.message for record in caplog.records)

def test_dict_upload_path_traversal_attack(tmp_upload_dir, client):
    xml_content = b"""<?xml version="1.0"?>
<fix major="4" minor="4">
    <header>
        <field name="BeginString" required="Y"/>
    </header>
    <messages>
        <message name="Heartbeat" msgtype="0" msgcat="admin">
            <field name="TestReqID" required="N"/>
        </message>
    </messages>
    <trailer>
        <field name="CheckSum" required="Y"/>
    </trailer>
    
    <fields>
        <field number="8" name="BeginString" type="STRING" />
        <field number="112" name="TestReqID" type="STRING" />
        <field number="10" name="CheckSum" type="STRING" />
    </fields>
    </fix>"""
    malicious_filename = "../../etc/passwd"
    
    response = client.post(
        "/upload_dict",
        files={"file": (malicious_filename, io.BytesIO(xml_content), "application/xml")},
    )

    assert response.status_code == 400
    assert "unsupported file type" in response.text 

    malicious_filename_2 = "../test_dict.xml"
    response_2 = client.post(
        "/upload_dict",
        files={"file": (malicious_filename_2, io.BytesIO(xml_content), "application/xml")},
    )
    
    assert response_2.status_code == 201
    assert response_2.json()["upload_filename"] == "test_dict.xml" 
    assert not (tmp_upload_dir / "../test_dict.xml").exists()
    assert (tmp_upload_dir / "test_dict.xml").exists()

def test_dict_upload_invalid_file_type(client):
    
    response = client.post(
        "/upload_dict",
        files={"file": ("test.txt", io.BytesIO(b"i am a text file"), "text/plain")},
    )
    
    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"]

def test_dict_upload_invalid_xml_content(tmp_upload_dir, client):
    
    invalid_xml = b"<xml><not_a_fix_dict></not_a_fix_dict></xml>"
    filename = "broken.xml"
    
    response = client.post(
        "/upload_dict",
        files={"file": (filename, io.BytesIO(invalid_xml), "application/xml")},
    )
    
    assert response.status_code == 400
    assert "dictionary validation failed" in response.json()["detail"]

    saved_path = tmp_upload_dir / filename
    assert not saved_path.exists()

def test_dict_upload_billion_laughs_attack(tmp_upload_dir, client):
    malicious_xml = b"""<?xml version="1.0"?>
<!DOCTYPE fix [
<!ENTITY a "b">
<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">
<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">
<!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;">
<!ENTITY g "&f;&f;&f;&f;&f;&f;&f;&f;&f;&f;">
<!ENTITY h "&g;&g;&g;&g;&g;&g;&g;&g;&g;&g;">
<!ENTITY i "&h;&h;&h;&h;&h;&h;&h;&h;&h;&h;">
<!ENTITY j "&i;&i;&i;&i;&i;&i;&i;&i;&i;&i;">
]>
<fix major="4" minor="4">
    <fields>
        <field number="999" name="Attack" type="STRING">
            <value enum="&j;" description="Attack"/>
        </field>
    </fields>
</fix>"""
    
    filename = "evil.xml"
    
    response = client.post(
        "/upload_dict",
        files={"file": (filename, io.BytesIO(malicious_xml), "application/xml")},
    )
    
    assert response.status_code == 400
    
    assert "validation failed" in response.text or "not well-formed" in response.text

def test_upload_dict_file_exists_succeeds_with_update(client, tmp_upload_dir, fix_dict_content, caplog):
    """
    Tests the happy path for the 'update=true' flag.
    Verifies that an existing file is correctly overwritten.
    """
    existing_file_name = "existing_for_update.xml"
    existing_file_path = tmp_upload_dir / existing_file_name
    
    # 1. Create the initial file
    initial_content = b"<fix>initial</fix>"
    existing_file_path.write_bytes(initial_content)
    assert existing_file_path.read_bytes() == initial_content

    response = client.post(
        "/upload_dict",
        data={"update": "true"}, 
        files={"file": (existing_file_name, io.BytesIO(fix_dict_content), "application/xml")}
    )
    
    # 3. Assert success and overwrite
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["upload_filename"] == existing_file_name
    
    # Verify the content was
    assert existing_file_path.read_bytes() == fix_dict_content
    assert any("Overwriting permitted" in record.message for record in caplog.records)


def test_dict_upload_valid_json(client, tmp_upload_dir, valid_json_content):
    """
    Tests the happy path for a valid JSON dictionary upload.
    """
    filename = "valid_dict.json"
    
    response = client.post(
        "/upload_dict",
        files={"file": (filename, io.BytesIO(valid_json_content), "application/json")},
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["upload_filename"] == filename
    
    saved_path = tmp_upload_dir / filename
    assert saved_path.exists()
    assert saved_path.read_bytes() == valid_json_content


def test_dict_upload_invalid_json(client, tmp_upload_dir, invalid_json_content):
    """
    Tests the failure path for an invalid (broken) JSON dictionary.
    Ensures the temp file is cleaned up.
    """
    filename = "broken.json"
    
    response = client.post(
        "/upload_dict",
        files={"file": (filename, io.BytesIO(invalid_json_content), "application/json")},
    )
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "dictionary validation failed" in response.json()["detail"]
    
    # Verify the broken file (and its .tmp variant) were cleaned up
    assert not (tmp_upload_dir / filename).exists()
    assert not (tmp_upload_dir / (filename + ".tmp")).exists()


def test_upload_dict_no_filename(client):
    """
    Tests the error case where the 'file' part is sent with an empty filename.
    """
    response = client.post(
        "/upload_dict",
        files={"file": ("", b"<fix>content</fix>", "application/xml")}
    )
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_upload_dict_name_parameter_is_ignored(client, tmp_upload_dir, fix_dict_content):
    """
    Tests that the 'name' form parameter is currently ignored,
    and the filename from the 'file' upload is used instead.
    """
    upload_filename = "FIX44.xml"
    ignored_name = "this_should_be_ignored.xml"
    
    response = client.post(
        "/upload_dict",
        data={"name": ignored_name}, # Pass the 'name' parameter
        files={"file": (upload_filename, io.BytesIO(fix_dict_content), "application/xml")},
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    
    # Verify the filename from the *file* was used, not the 'name' param
    assert response.json()["upload_filename"] == upload_filename
    
    # Verify the file was saved with the correct name
    assert (tmp_upload_dir / upload_filename).exists()
    assert not (tmp_upload_dir / ignored_name).exists()


def test_upload_rate_limit(client, fix_dict_content, monkeypatch, tmp_upload_dir):
    """
    Tests that the rate limit for the upload endpoint is enforced.
    """
    # 1. Set a very strict rate limit for this test
    # We must patch the function *used* by the limiter
    from fixparser import main
    monkeypatch.setattr(main, 'DICT_DIR', tmp_upload_dir)
    monkeypatch.setenv("UPLOAD_LIMIT", "1/second")
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    # 2. Make the first request (should succeed)
    response1 = client.post(
        "/upload_dict",
        files={"file": ("file1.xml", io.BytesIO(fix_dict_content), "application/xml")},
    )
    assert response1.status_code == status.HTTP_201_CREATED
    
    # 3. Make the second request immediately (should fail)
    response2 = client.post(
        "/upload_dict",
        files={"file": ("file2.xml", io.BytesIO(fix_dict_content), "application/xml")},
    )
    
    assert response2.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Rate limit exceeded" in response2.text