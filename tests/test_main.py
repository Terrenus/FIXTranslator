import pytest
from unittest.mock import patch, ANY, MagicMock, AsyncMock
from prometheus_client import REGISTRY
import logging
from starlette import status
import fixparser.main as main

try:
    from fixparser._version import __version__ 
except Exception:
    # fallback so tests that patch fixparser.main.__version__ work
    __version__ = "0.0.0"

@pytest.fixture(scope="session", autouse=True)
def clear_prometheus_registry():
    for collector in list(REGISTRY._collector_to_names.keys()):
        REGISTRY.unregister(collector)
    yield # Run the tests

@patch('fixparser._version', "9.9.9")
def test_root_path(client):
    response = client.get("/")
    print(response)
    assert response.status_code == 200
    assert "FIX Parser Demo" in response.text

@patch("fixparser.parser.parse_fix_message")
@patch("fixparser.main.export_event")  # still patch event export to avoid side effects
@patch("fixparser.parser.flatten", return_value={"35": "A"})
@patch("fixparser.parser.human_summary", return_value="Summary")
@patch("fixparser.parser.human_detail", return_value="Detail")
def test_parse_success(mock_detail, mock_summary, mock_flatten, mock_export, mock_parser, client, caplog):
    mock_parser.return_value = {"parsed_by_tag": {"35": "A"}, "errors": []}

    raw_fix = "8=FIX.4.2\x019=65\x0135=A\x0149=SENDER\x0156=TARGET\x0110=100\x01"

    with caplog.at_level(logging.INFO, logger='fixparser'):
        response = client.post("/parse", json={"raw": raw_fix})

    assert response.status_code == 200

    expected_dict = ANY
    mock_parser.assert_called_once_with(raw_fix.replace("|", "\x01"), dict_obj=expected_dict, strict=False)

    response_data = response.json()
    assert "request_id" in response_data
    assert response_data["raw"] == raw_fix.replace("\x01", "|")
    assert response_data["summary"] == "Summary"

def test_unsupported_method(client):
    response = client.put("/parse", json={"raw": "some_data"})
    assert response.status_code == 405
    assert "Method Not Allowed" in response.json().get("detail")

def test_parse_missing_body(client):
    response = client.post("/parse")
    assert response.status_code == 400
    assert 'error' in response.json() 
    assert response.json()['error'] == 'no raw message found in request'


def test_parse_invalid_mode_param(client):
    response = client.post("/parse?mode=BAD_MODE", json={"raw": "some_data"})
    assert response.status_code == 400
    assert "detail" in response.json()

def test_parse_unsupported_method(client):
    response = client.post("/unknown-endpoint")
    assert response.status_code == 404

@patch("fixparser.parser.parse_fix_message")
def test_parse_invalid_fix_format_valueerror(mock_parser, client):
    mock_parser.side_effect = ValueError("checksum failure")
    
    response = client.post("/parse", json={"raw": "bad-data"})
    
    mock_parser.assert_called_once()
    assert response.status_code == 400
    assert response.json()["detail"] == "Parsing failed. The FIX message is malformed in strict mode."


@patch("fixparser.parser.parse_fix_message")
def test_parse_internal_fatal_error(mock_parser, client, caplog):
    mock_parser.side_effect = Exception("Internal DB error")
    
    with caplog.at_level(logging.ERROR, logger='fixparser'):
        response = client.post("/parse", json={"raw": "bad-data"})
        
    assert response.status_code == 500
    assert response.json()["detail"] == "An unexpected server error occurred during parsing."

def test_metrics_endpoint(client):
    
    main.PARSES_TOTAL.inc(0)
    main.PARSE_ERRORS.inc(0)
    
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "fixparser_parses_total" in response.text 
    assert "fixparser_parse_errors_total" in response.text
    assert "fixparser_inflight_requests" in response.text
    
def test_parse_api_key_required_no_key(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "validkey") 
    
    response = client.post("/parse", json={"raw": "data"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"

def test_parse_api_key_required_invalid_key(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "validkey") 
    
    response = client.post("/parse", json={"raw": "data"}, headers={"x-api-key": "badkey"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"

@patch("fixparser.parser.parse_fix_message", return_value={"parsed_by_tag": {}, "errors": []})
def test_parse_api_key_valid(mock_parser, client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "testkey123") 
    
    response = client.post("/parse", json={"raw": "data"}, headers={"x-api-key": "testkey123"})
    assert response.status_code == 200
    mock_parser.assert_called_once()


@patch("fixparser.parser.parse_fix_message", return_value={"status": "ok"})
def test_health_readiness_ready(mock_parser, client):
    response = client.get("/health/readiness")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    mock_parser.assert_called_once()

@patch("fixparser.parser.parse_fix_message", side_effect=Exception("Parser is down"))
def test_health_readiness_unready(mock_parser, client):
    # Failure path (line 456)
    response = client.get("/health/readiness")
    assert response.status_code == 503
    assert "parser check failed" in response.json()["detail"]

def test_rate_limit_exceeded(client, monkeypatch):
    monkeypatch.setenv("PARSE_LIMIT", "1/second")
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    test_payload = {"raw": "8=FIX.4.2|9=12|35=0|10=000|"}

    response_ok = client.post("/parse", json=test_payload)
    assert response_ok.status_code == 200
    assert "parsed" in response_ok.json()

    response_fail = client.post("/parse", json=test_payload)
    assert response_fail.status_code == 429
    assert "Rate limit exceeded" in response_fail.text

def test_max_body_size_exceeded(client, monkeypatch):
    monkeypatch.setenv("MAX_BODY_SIZE", "100")
    from fixparser import main
    monkeypatch.setattr(main, 'get_max_body_size', lambda: 100)    
    large_body = b'a' * 101 
    
    response = client.post(
        "/parse",
        content=large_body,
        headers={"Content-Type": "application/octet-stream"}
        )
    
    assert response.status_code == 413
    assert "maximum limit" in response.text

def test_parse_api_key_bypass_enabled(client, monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False) # Ensure API_KEYS is not set
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    # Should succeed without an API key
    response = client.post("/parse", json={"raw": "data"})
    assert response.status_code == 200
    monkeypatch.delenv("DISABLE_APIKEY_CHECK", raising=False)

def test_parse_api_key_required_no_bypass(client, monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False) # Ensure API_KEYS is not set
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "0") # Ensure bypass is disabled
    
    # Should fail because API_KEYS is empty and bypass is off
    response = client.post("/parse", json={"raw": "data"})
    assert response.status_code == 401
    assert "API key required" in response.json()["detail"]
    monkeypatch.delenv("DISABLE_APIKEY_CHECK", raising=False)

def test_require_api_key_secure_fallback(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "0") 
    
    response = client.post("/parse", content=b'', headers={"Content-Type": "text/plain"})
    
    assert response.status_code == 401
    assert "API key required" in response.json()["detail"]

def test_get_max_body_size_invalid_env_value(monkeypatch, caplog):
    # Set MAX_BODY_SIZE to a non-integer string
    monkeypatch.setenv("MAX_BODY_SIZE", "not_a_number")
    from fixparser import main
    
    # Execute the function and check the return value
    max_size = main.get_max_body_size()
    
    # Should default to 1MB (1 * 1024 * 1024)
    assert max_size == 1048576
    
    # Check that the error was logged (Line 69)
    assert any("Invalid MAX_BODY_SIZE environment variable. Defaulting to 1MB." in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_max_body_size_middleware_stream_exceeded(async_client, monkeypatch):
    limit = 100
    payload_size = 1000
    from fixparser import main
    monkeypatch.setenv("MAX_BODY_SIZE", str(limit))
    monkeypatch.setattr(main, 'get_max_body_size', lambda: limit)

    large_payload = b'x' * payload_size
    
    response = await async_client.post(
        "/parse",
        content=large_payload,
        headers={"Content-Type": "application/octet-stream"},
    )
    
    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert "Request body size exceeds the maximum limit" in response.json()["detail"]

def test_get_max_body_size_default_value(monkeypatch):
    """
    Tests the default return path when MAX_BODY_SIZE environment variable is not set.
    Targets get_max_body_size: return 1 * 1024 * 1024 (final line).
    """
    from fixparser import main
    # Ensure the environment variable is not set
    monkeypatch.delenv("MAX_BODY_SIZE", raising=False)
    
    # 1MB in bytes
    expected_default = 1048576 
    
    assert main.get_max_body_size() == expected_default

def test_middleware_invalid_content_length(client):
    """
    Tests the middleware's handling of a non-numeric 'Content-Length' header.
    Targets MaxBodySizeMiddleware: except ValueError: pass.
    """
    # Send a request to a simple endpoint (like liveness) with a non-numeric header.
    # The middleware should catch the ValueError on int(content_length) and 'pass', 
    # allowing the request to proceed.
    
    response = client.get(
        "/health/liveness", 
        headers={"Content-Length": "not_an_integer"}
    )
    
    # Assert the request passed through successfully
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "alive"}

@pytest.mark.asyncio
async def test_streaming_body_logger_called(async_client, monkeypatch):

    from fixparser import main

    max_limit = 5
    expected_runtime_message = "Request body size limit exceeded during stream."
    monkeypatch.setenv("MAX_BODY_SIZE", str(max_limit))
    monkeypatch.setattr(main, "get_max_body_size", lambda: max_limit)

    async def streaming_body():
        yield b"123"      # OK (bytes_read = 3)
        yield b"456789"   # goes past limit, triggers logger + RuntimeError

    # PATCH LOGGER
    with patch("fixparser.main.logger.warning") as mock_log:
        with pytest.raises(RuntimeError) as excinfo:
            await async_client.post(
                "/parse",
                content=streaming_body(),
                headers={"Content-Type": "application/octet-stream"},
            )

    assert expected_runtime_message in str(excinfo.value)
    # Verify logger.warning was called
    mock_log.assert_called_once()

    msg, kwargs = mock_log.call_args[0], mock_log.call_args[1]

    assert "Request body size exceeded while streaming" in msg[0]
    assert kwargs["extra"]["max_size"] == max_limit
    assert kwargs["extra"]["bytes_read"] > max_limit
    assert "request_id" in kwargs["extra"]

@pytest.mark.asyncio
async def test_streaming_body_exception_converted_to_413(async_client, monkeypatch):
    from fixparser import main

    limit = 10
    monkeypatch.setenv("MAX_BODY_SIZE", str(limit))
    monkeypatch.setattr(main, "get_max_body_size", lambda: limit)

    payload = b"x" * (limit + 50) 

    response = await async_client.post(
        "/parse",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert "Request body size exceeds the maximum limit" in response.json()["detail"]

def test_get_parse_mode_lenient_none():
    input_mode = None
    expected_output = 'lenient'
    result = main.get_parse_mode(input_mode)
    result2 = main.get_parse_mode()
    

    assert result == expected_output
    assert result2 == expected_output

def test_parse_endpoint_dict_not_found(client):
    """Test failure when a specific dictionary is requested but not found."""
    raw_message = "8=FIX.4.2\x01"
    
    # Use patch as a context manager to control the scope and avoid injecting 
    # the mock object (which would clobber the 'client' fixture).
    with patch('fixparser.main.os.path.exists', return_value=False):
        response = client.post("/parse?dict_name=missing.xml", content=raw_message)
    
    assert response.status_code == 404
    assert "dictionary not found" in response.json()["detail"]

def test_parse_json_object_missing_raw_field(client):
    """Test JSON object input with a body but no recognized message key (raw/log/message)."""
    response = client.post("/parse", json={"other_key": "data"})
    
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "field required"

def test_parse_json_list_empty(client):
    """Test an empty JSON list body."""
    response = client.post("/parse", json=[])
    
    # An empty list results in an empty message list, leading to the 400 error.
    assert response.status_code == 400
    assert "no raw message found" in response.json()["error"]

@pytest.mark.asyncio
@patch('fixparser.parser.parse_fix_message')
async def test_parse_non_json_body_decoding_failure(mock_parser, client):
    
    mock_body_bytes = MagicMock(spec=bytes)
    mock_body_bytes.decode.side_effect = Exception("Simulated decoding error")
    mock_body_bytes.__len__.return_value = 10
    
    with patch('starlette.requests.Request.body', new_callable=AsyncMock) as mock_request_body_method:
        mock_request_body_method.return_value = mock_body_bytes
        response = client.post("/parse") 
    
    assert response.status_code == 400
    assert "no raw message found in request" in response.json()["error"]
    
    mock_parser.parse_fix_message.assert_not_called()

PARSE_DICT_TEST_CASES = [
    ([{"raw": "8=FIX.4.2\x01\r\n"}], "8=FIX.4.2\x01", "using 'raw' key"),
    ([{"log": "8=FIX.4.2\x01\n"}], "8=FIX.4.2\x01", "using 'log' key"),
    ([{"message": "8=FIX.4.2\x01"}], "8=FIX.4.2\x01", "using 'message' key"),
    # Test preference order: 'raw' over 'log'
    ([{"raw": "raw_msg", "log": "log_msg"}], "raw_msg", "preference 'raw'"),
]

@pytest.mark.parametrize("json_payload, expected_message, desc", PARSE_DICT_TEST_CASES)
@patch('fixparser.parser.human_detail', return_value="Detail")
@patch('fixparser.parser.human_summary', return_value="Summary")
@patch('fixparser.parser.flatten', return_value={"35": "A"})
@patch('fixparser.parser.parse_fix_message')
def test_parse_json_list_first_element_is_dict(mock_parser, mock_flatten, mock_summary, mock_detail, client, json_payload, expected_message, desc):
    # Configure the mock to return a proper dictionary structure
    mock_parser.return_value = {
        "parsed_by_tag": {"35": "A"},
        "errors": []
    }
    
    response = client.post("/parse", json=json_payload)
    
    assert response.status_code == 200, f"Failed case: {desc}. Response: {response.json()}"
    
    # Verify the parser was called with the extracted (and stripped) message
    mock_parser.assert_called_once()
    
    # The first argument (the message) should match
    assert mock_parser.call_args[0][0] == expected_message, f"Message mismatch for case: {desc}"

@patch('fixparser.parser.human_detail', return_value="Detail")
@patch('fixparser.parser.human_summary', return_value="Summary")
@patch('fixparser.parser.flatten', return_value={"35": "A"})
@patch('fixparser.parser.parse_fix_message')
def test_parse_json_list_first_element_is_string(mock_parser, mock_flatten, mock_summary, mock_detail, client):
    """
    Tests extraction when the first element of the list is a plain string.
    """
    # Configure the mock to return a proper dictionary structure
    mock_parser.return_value = {
        "parsed_by_tag": {"35": "A"},
        "errors": []
    }
    
    json_payload = ["8=FIX.4.2\x019=12\x0110=000\x01\r\n", "ignore this"]
    expected_message = "8=FIX.4.2\x019=12\x0110=000\x01" # \r\n stripped
    
    response = client.post("/parse", json=json_payload)
    
    assert response.status_code == 200
    
    mock_parser.assert_called_once()
    assert mock_parser.call_args[0][0] == expected_message


@patch('fixparser.parser.parse_fix_message')
def test_parse_json_list_empty_or_non_extractable(mock_parser, client):
    """
    Tests cases where no message can be extracted from the first list element, 
    leading to the final 400 error.
    """
    test_cases = [
        [], # Empty list
        [{"other_key": "data"}], # Dictionary with no matching keys
        [None], # List with None as first element
        [123], # List with non-string/non-dict as first element
    ]

    for json_payload in test_cases:
        response = client.post("/parse", json=json_payload)
        
        assert response.status_code == 400
        assert "no raw message found" in response.json()["error"]
        
        # Reset mock call count to ensure no pollution between iterations
        mock_parser.parse_fix_message.reset_mock()
        mock_parser.parse_fix_message.assert_not_called()

def test_get_allowed_origins_dev_mode(monkeypatch):
    """Test get_allowed_origins when DEV environment variable is set."""
    from fixparser import main
    
    monkeypatch.setenv("DEV", "1")
    assert main.get_allowed_origins() == ["*"]

def test_get_allowed_origins_production_mode(monkeypatch):
    """Test get_allowed_origins when DEV environment variable is not set."""
    from fixparser import main
    
    monkeypatch.delenv("DEV", raising=False)
    assert main.get_allowed_origins() == ["https://your-company.example"]

def test_parse_dict_path_traversal_attempt(client):
    """Test that directory traversal attempts are blocked."""
    raw_message = "8=FIX.4.2\x01"
    
    # Attempt directory traversal
    response = client.post("/parse?dict_name=../../etc/passwd", content=raw_message)
    
    assert response.status_code == 403
    assert "invalid dictionary path" in response.json()["detail"]

def test_parse_batch_dict_path_traversal_attempt(client):
    """Test that directory traversal attempts are blocked in batch endpoint."""
    # Test line 444
    response = client.post("/parse/batch?dict_name=../../../secrets.xml", json=["8=FIX.4.2\x01"])
    
    assert response.status_code == 400
    assert "Invalid dictionary name" in response.json()["error"]

@pytest.mark.asyncio
async def test_upload_dict_xml_success(async_client, tmp_path, monkeypatch):
    """Test successful XML dictionary upload."""
    from fixparser import main
    
    # Create a temporary dict directory
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <fix>
        <fields>
            <field number="8" name="BeginString" type="STRING"/>
        </fields>
    </fix>"""
    
    # Create a mock that will be returned when FixDictionary() is instantiated
    mock_dict_instance = MagicMock()
    mock_dict_instance.tags = {"8": "BeginString"}
    mock_dict_instance.load_quickfix_xml = MagicMock()
    
    # Patch the constructor to return our mock instance
    with patch('fixparser.main.parser.FixDictionary', return_value=mock_dict_instance):
        response = await async_client.post(
            "/upload_dict",
            data={"update": "false"},
            files={"file": ("test_dict.xml", xml_content, "application/xml")}
        )
    
    assert response.status_code == 201
    assert response.json()["upload_filename"] == "test_dict.xml"
    mock_dict_instance.load_quickfix_xml.assert_called_once()

@pytest.mark.asyncio
async def test_upload_dict_json_success(async_client, tmp_path, monkeypatch):
    """Test successful JSON dictionary upload."""
    from fixparser import main
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    json_content = b'{"tags": {"8": "BeginString"}}'
    
    mock_dict_instance = MagicMock()
    mock_dict_instance.tags = {"8": "BeginString"}
    mock_dict_instance.load_json_dict = MagicMock()
    
    with patch('fixparser.main.parser.FixDictionary', return_value=mock_dict_instance):
        response = await async_client.post(
            "/upload_dict",
            data={"update": "false"},
            files={"file": ("test_dict.json", json_content, "application/json")}
        )
    
    assert response.status_code == 201
    assert response.json()["upload_filename"] == "test_dict.json"
    mock_dict_instance.load_json_dict.assert_called_once()

@pytest.mark.asyncio
async def test_upload_dict_unsupported_file_type(async_client, tmp_path, monkeypatch, caplog):
    """Test upload with unsupported file type."""
    from fixparser import main
    import logging
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    txt_content = b'some text content'
    
    with caplog.at_level(logging.WARNING, logger='fixparser'):
        response = await async_client.post(
            "/upload_dict",
            data={"update": "false"},
            files={"file": ("test_dict.txt", txt_content, "text/plain")}
        )
    
    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"]
    
    # Verify warning was logged (line 360-365)
    assert any("Upload attempt with unsupported file type" in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_upload_dict_file_exists_no_update(async_client, tmp_path, monkeypatch, caplog):
    """Test upload when file exists and update=false."""
    from fixparser import main
    import logging
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    # Create existing file
    existing_file = temp_dict_dir / "existing_dict.xml"
    existing_file.write_text("existing content")
    
    xml_content = b'<fix></fix>'
    
    with caplog.at_level(logging.ERROR, logger='fixparser'):
        response = await async_client.post(
            "/upload_dict",
            data={"update": "false"},
            files={"file": ("existing_dict.xml", xml_content, "application/xml")}
        )
    
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    
    # Verify error was logged (line 375-379)
    assert any("Upload blocked: Dictionary file already exists" in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_upload_dict_file_exists_with_update(async_client, tmp_path, monkeypatch, caplog):
    """Test upload when file exists and update=true (line 369-373)."""
    from fixparser import main
    import logging
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    # Create existing file
    existing_file = temp_dict_dir / "existing_dict.xml"
    existing_file.write_text("existing content")
    
    xml_content = b"""<?xml version="1.0"?><fix><fields><field number="8" name="Test" type="STRING"/></fields></fix>"""
    
    with patch('fixparser.parser.FixDictionary') as MockDict:
        mock_instance = MagicMock()
        mock_instance.tags = {"8": "Test"}
        MockDict.return_value = mock_instance
        
        with caplog.at_level(logging.WARNING, logger='fixparser'):
            response = await async_client.post(
                "/upload_dict",
                data={"update": "true"},
                files={"file": ("existing_dict.xml", xml_content, "application/xml")}
            )
    
    assert response.status_code == 201
    
    # Verify warning was logged about overwriting
    assert any("Overwriting permitted via 'update=true'" in record.message for record in caplog.records)

# Test lines 390, 412: Dictionary validation errors
@pytest.mark.asyncio
async def test_upload_dict_validation_fails_empty_dict(async_client, tmp_path, monkeypatch, caplog):
    """Test upload when dictionary validation fails due to empty tags."""
    from fixparser import main
    import logging
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    xml_content = b'<fix></fix>'
    
    with patch('fixparser.parser.FixDictionary') as MockDict:
        mock_instance = MagicMock()
        mock_instance.tags = {}  # Empty tags as attribute
        MockDict.return_value = mock_instance
        
        with caplog.at_level(logging.ERROR, logger='fixparser'):
            response = await async_client.post(
                "/upload_dict",
                data={"update": "false"},
                files={"file": ("bad_dict.xml", xml_content, "application/xml")}
            )
    
    assert response.status_code == 400
    assert "dictionary validation failed" in response.json()["detail"]
    assert "contains no valid FIX messages" in response.json()["detail"]

@pytest.mark.asyncio
async def test_upload_dict_validation_exception(async_client, tmp_path, monkeypatch, caplog):
    """Test upload when dictionary loading raises an exception."""
    from fixparser import main
    import logging
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    xml_content = b'<fix></fix>'
    
    with patch('fixparser.parser.FixDictionary.load_quickfix_xml', side_effect=Exception("Parse error")):
        with caplog.at_level(logging.ERROR, logger='fixparser'):
            response = await async_client.post(
                "/upload_dict",
                data={"update": "false"},
                files={"file": ("bad_dict.xml", xml_content, "application/xml")}
            )
    
    assert response.status_code == 400
    assert "dictionary validation failed" in response.json()["detail"]
    
    # Verify exception was logged (line 404-409)
    assert any("Dictionary validation failed on upload" in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_upload_dict_unlink_fails(async_client, tmp_path, monkeypatch, caplog):
    """Test upload when temp file cleanup fails after validation error."""
    from fixparser import main
    import logging
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    xml_content = b'<fix></fix>'
    
    with patch('fixparser.parser.FixDictionary.load_quickfix_xml', side_effect=Exception("Parse error")):
        with patch('pathlib.Path.unlink', side_effect=Exception("Unlink failed")):
            with caplog.at_level(logging.ERROR, logger='fixparser'):
                response = await async_client.post(
                    "/upload_dict",
                    data={"update": "false"},
                    files={"file": ("bad_dict.xml", xml_content, "application/xml")}
                )
    
    assert response.status_code == 400
    
    # Verify unlink error was logged (line 395-401)
    assert any("Failed to unlink invalid dictionary post-error" in record.message for record in caplog.records)

# Test lines 419: API key check in batch endpoint
def test_parse_batch_api_key_missing(monkeypatch):
    """Test batch endpoint rejects request without API key when required."""
    
    monkeypatch.setenv("API_KEYS", "validkey")
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "0")
    
    from fixparser.main import app
    from fastapi.testclient import TestClient
    
    # Create client WITHOUT API key header
    test_client = TestClient(app)
    response = test_client.post("/parse/batch", json=["8=FIX.4.2\x01"])
    
    # Should fail with "Invalid API key" since no key was provided
    assert response.status_code == 401
    assert response.json()["detail"] in ["Invalid API key", "API key missing"]

# Test lines 454-455: Batch endpoint error handling
def test_parse_batch_expected_json_array(client, monkeypatch):
    """Test batch endpoint with non-array JSON body."""
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    # Send a single object instead of an array
    response = client.post("/parse/batch", json={"raw": "8=FIX.4.2\x01"})
    
    assert response.status_code == 400
    assert "expected JSON array" in response.json()["error"]

def test_parse_batch_no_messages_found(client, monkeypatch):
    """Test batch endpoint with empty or invalid array."""
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    # Send array with no extractable messages
    response = client.post("/parse/batch", json=[{"other_key": "value"}])
    
    assert response.status_code == 400
    assert "no messages found in batch" in response.json()["error"]

# Test lines 463-466: Batch endpoint dictionary loading (XML)
@patch('fixparser.parser.human_detail', return_value="Detail")
@patch('fixparser.parser.human_summary', return_value="Summary")
@patch('fixparser.parser.flatten', return_value={"35": "A"})
@patch('fixparser.parser.parse_fix_message')
def test_parse_batch_with_xml_dict(mock_parser, mock_flatten, mock_summary, mock_detail, client, tmp_path, monkeypatch):
    """Test batch endpoint loading XML dictionary."""
    from fixparser import main
    
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    dict_file = temp_dict_dir / "FIX44.xml"
    dict_file.write_text("<fix></fix>")
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    mock_parser.return_value = {"parsed_by_tag": {"35": "A"}, "errors": []}
    
    # Mock FixDictionary to avoid actual file loading
    mock_dict_instance = MagicMock()
    mock_dict_instance.tags = {"8": "BeginString"}
    
    with patch('fixparser.main.parser.FixDictionary', return_value=mock_dict_instance):
        response = client.post("/parse/batch?dict_name=FIX44.xml", json=["8=FIX.4.2\x01"])
    
    assert response.status_code == 200
    # Verify the XML loading method was called on the instance
    mock_dict_instance.load_quickfix_xml.assert_called_once()

@patch('fixparser.parser.human_detail', return_value="Detail")
@patch('fixparser.parser.human_summary', return_value="Summary")
@patch('fixparser.parser.flatten', return_value={"35": "A"})
@patch('fixparser.parser.parse_fix_message')
def test_parse_batch_with_json_dict(mock_parser, mock_flatten, mock_summary, mock_detail, client, tmp_path, monkeypatch):
    """Test batch endpoint loading JSON dictionary."""
    from fixparser import main
    
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    dict_file = temp_dict_dir / "FIX44.json"
    dict_file.write_text('{"tags": {}}')
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    mock_parser.return_value = {"parsed_by_tag": {"35": "A"}, "errors": []}
    
    mock_dict_instance = MagicMock()
    mock_dict_instance.tags = {"8": "BeginString"}
    
    with patch('fixparser.main.parser.FixDictionary', return_value=mock_dict_instance):
        response = client.post("/parse/batch?dict_name=FIX44.json", json=["8=FIX.4.2\x01"])
    
    assert response.status_code == 200
    # Verify the JSON loading method was called on the instance
    mock_dict_instance.load_json_dict.assert_called_once()

# Test lines 473-484: Batch endpoint parse errors in strict mode
@patch('fixparser.parser.parse_fix_message')
def test_parse_batch_valueerror_in_strict_mode(mock_parser, client, monkeypatch, caplog):
    """Test batch endpoint handling ValueError in strict mode."""
    import logging
    
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    mock_parser.side_effect = ValueError("Checksum mismatch")
    
    with caplog.at_level(logging.WARNING, logger='fixparser'):
        response = client.post("/parse/batch?mode=strict", json=["bad_message"])
    
    assert response.status_code == 200
    result = response.json()
    assert isinstance(result, list)
    assert "error" in result[0]
    assert "malformed in strict mode" in result[0]["error"]
    
    # Verify warning was logged (line 476-482)
    assert any("Parser error (strict mode)" in record.message for record in caplog.records)

@patch('fixparser.parser.parse_fix_message')
def test_parse_batch_generic_exception(mock_parser, client, monkeypatch, caplog):
    """Test batch endpoint handling generic exception."""
    import logging
    
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    mock_parser.side_effect = Exception("Database connection failed")
    
    with caplog.at_level(logging.ERROR, logger='fixparser'):
        response = client.post("/parse/batch", json=["some_message"])
    
    assert response.status_code == 200
    result = response.json()
    assert isinstance(result, list)
    assert "error" in result[0]
    assert "unexpected server error" in result[0]["error"]
    
    # Verify exception was logged (line 487)
    assert any("Internal fatal parse error" in record.message for record in caplog.records)

# Test lines 496: Batch with multiple messages including errors
@patch('fixparser.parser.human_detail', return_value="Detail")
@patch('fixparser.parser.human_summary', return_value="Summary")
@patch('fixparser.parser.flatten', return_value={"35": "A"})
@patch('fixparser.parser.parse_fix_message')
def test_parse_batch_mixed_success_and_errors(mock_parser, mock_flatten, mock_summary, mock_detail, client, monkeypatch):
    """Test batch with some successful parses and some errors."""
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    # First call succeeds, second fails
    mock_parser.side_effect = [
        {"parsed_by_tag": {"35": "A"}, "errors": []},
        ValueError("Bad format")
    ]
    
    response = client.post("/parse/batch", json=["good_msg", "bad_msg"])
    
    assert response.status_code == 200
    result = response.json()
    assert len(result) == 2
    assert "parsed" in result[0]  # First succeeded
    assert "error" in result[1]    # Second failed

@patch('fixparser.parser.human_detail', return_value="Detail")
@patch('fixparser.parser.human_summary', return_value="Summary")
@patch('fixparser.parser.flatten', return_value={"35": "A"})
@patch('fixparser.parser.parse_fix_message')
def test_parse_with_json_dict_file(mock_parser, mock_flatten, mock_summary, mock_detail, client, tmp_path, monkeypatch):
    """Test parse endpoint with JSON dictionary file."""
    from fixparser import main
    
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    temp_dict_dir = tmp_path / "dicts"
    temp_dict_dir.mkdir()
    dict_file = temp_dict_dir / "FIX44.json"
    dict_file.write_text('{"tags": {}}')
    monkeypatch.setattr(main, 'DICT_DIR', temp_dict_dir)
    
    mock_parser.return_value = {"parsed_by_tag": {"35": "A"}, "errors": []}
    
    mock_dict_instance = MagicMock()
    mock_dict_instance.tags = {"8": "BeginString"}
    
    with patch('fixparser.main.parser.FixDictionary', return_value=mock_dict_instance):
        response = client.post("/parse?dict_name=FIX44.json", json={"raw": "8=FIX.4.2\x01"})
    
    assert response.status_code == 200
    mock_dict_instance.load_json_dict.assert_called()

# Test lines 518-537: Parse endpoint with parse errors containing error list
@patch('fixparser.parser.human_detail', return_value="Detail")
@patch('fixparser.parser.human_summary', return_value="Summary")
@patch('fixparser.parser.flatten', return_value={"35": "A"})
@patch('fixparser.parser.parse_fix_message')
def test_parse_with_parser_errors(mock_parser, mock_flatten, mock_summary, mock_detail, client, monkeypatch):
    """Test parse endpoint when parser returns errors."""
    monkeypatch.setenv("DISABLE_APIKEY_CHECK", "1")
    
    # Parser succeeds but returns errors
    mock_parser.return_value = {
        "parsed_by_tag": {"35": "A"},
        "errors": ["Missing required field 49", "Invalid checksum"]
    }
    
    response = client.post("/parse", json={"raw": "8=FIX.4.2\x01"})
    
    assert response.status_code == 200
    result = response.json()
    assert "errors" in result
    assert len(result["errors"]) == 2
    assert "Missing required field 49" in result["errors"]

# Test get_parse_limit and get_upload_limit environment variables
def test_get_parse_limit_default(monkeypatch):
    """Test get_parse_limit returns default when env var not set."""
    
    monkeypatch.delenv("PARSE_LIMIT", raising=False)
    
    from fixparser import main
    assert main.get_parse_limit() == "200/minute"

def test_get_parse_limit_custom(monkeypatch):
    """Test get_parse_limit returns custom value from env var."""
    
    monkeypatch.setenv("PARSE_LIMIT", "500/hour")
    
    from fixparser import main
    assert main.get_parse_limit() == "500/hour"

def test_get_upload_limit_default(monkeypatch):
    """Test get_upload_limit returns default when env var not set."""
    
    monkeypatch.delenv("UPLOAD_LIMIT", raising=False)
    
    from fixparser import main
    assert main.get_upload_limit() == "20/hour"

def test_get_upload_limit_custom(monkeypatch):
    """Test get_upload_limit returns custom value from env var."""
    
    monkeypatch.setenv("UPLOAD_LIMIT", "50/hour")
    
    from fixparser import main
    assert main.get_upload_limit() == "50/hour"