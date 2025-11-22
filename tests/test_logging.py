import logging

def test_json_logging_format(client, caplog):
    """
    Tests that the logger handler is configured to output valid JSON.
    NOTE: This test assumes the logger setup in fixparser/logger_config.py
    is correctly applied to the root/fixparser logger.
    """
    with caplog.at_level(logging.INFO, logger='fixparser'):
        response = client.get("/")
        assert response.status_code == 200
    
    start_log_record = None
    end_log_record = None

    for record in caplog.records:
        if record.name == 'fixparser':
            if record.message == "Request started" and hasattr(record, 'request_id'):
                start_log_record = record
            if record.message == "Request finished" and hasattr(record, 'status_code'):
                end_log_record = record

    assert start_log_record is not None, "Start log not found."
    assert end_log_record is not None, "End log not found."

    assert start_log_record.request_id == end_log_record.request_id
    assert end_log_record.status_code == 200
    assert hasattr(start_log_record, "path")
    assert hasattr(end_log_record, "status_code")
    

def test_exception_logging_contains_detail(client, caplog):
    """
    Tests that a ValueError triggers a safe client response (400) 
    but logs the detailed exception server-side.
    """
    MALFORMED_MESSAGE = "8=FIX.4.2|35=D|10=000|"
    
    # We expect a ValueError in strict mode because the pipe '|' is not SOH
    with caplog.at_level(logging.WARNING, logger='fixparser'):
        response = client.post("/parse?mode=strict", json={"raw": MALFORMED_MESSAGE})

    assert response.status_code == 400
    assert "FIX message is malformed in strict mode" in response.json().get("detail")

    found_log = False
    for record in caplog.records:
        if record.name == 'fixparser' and record.levelname == 'WARNING':
            if record.message == "Parser error (strict mode)":
                assert hasattr(record, 'exception_detail')
                assert "Missing SOH delimiters" in record.exception_detail
                assert hasattr(record, 'request_id')
                found_log = True
                break
            
    assert found_log, "Detailed exception log was not found or was malformed."