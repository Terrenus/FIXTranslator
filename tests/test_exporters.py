import pytest
from unittest.mock import patch, MagicMock
import fixparser.exporters as exporters 
from prometheus_client import REGISTRY
import importlib
import json
import logging
import requests

@pytest.fixture(autouse=True)
def clear_prometheus_metrics():
    """Reset Prometheus counters before each test."""
    collectors = list(REGISTRY._names_to_collectors.values())
    for c in collectors:
        try:
            REGISTRY.unregister(c)
        except Exception:
            pass
    yield
    # Clean up again after test
    for c in list(REGISTRY._names_to_collectors.values()):
        try:
            REGISTRY.unregister(c)
        except Exception:
            pass

def find_latest_json_log(caplog, exporter_name):
    for record in reversed(caplog.records):
        if record.name == 'fixparser' and record.levelname == 'INFO':
            try:
                log_data = json.loads(record.message)
                if log_data.get("exporter") == exporter_name:
                    return log_data
            except json.JSONDecodeError:
                continue
    return None

@pytest.fixture
def sample_event():
    return {"request_id": "abc123", "timestamp": 1234567890, "message": "hello world"}


def test_splunk_mock(monkeypatch, caplog):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    event = {"test": "splunk", "request_id": "test-splunk-123"}

    importlib.reload(exporters)
    
    with caplog.at_level(logging.INFO, logger='fixparser'):
        ok = exporters.send_to_splunk(event)
        
    assert ok is True
    
    found_log = False
    for record in caplog.records:
        if record.name == 'fixparser' and record.levelname == 'INFO':
            if record.message == "Exporting to Splunk":
                assert hasattr(record, 'exporter')
                assert record.exporter == 'splunk'
                
                assert hasattr(record, 'event')
                assert record.event == event
                
                assert hasattr(record, 'request_id')
                assert record.request_id == "test-splunk-123"
                
                found_log = True
                break
                
    assert found_log, "Splunk mock log not found in caplog records."

@patch("fixparser.exporters.requests.post")
def test_splunk_export_real_mode(mock_post, sample_event, monkeypatch):
    monkeypatch.setenv("EXPORT_MODE", "real")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    monkeypatch.setenv("SPLUNK_HEC_URL", "http://fake-splunk")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "token123")

    importlib.reload(exporters) 

    mock_post.return_value.raise_for_status = MagicMock(return_value=None)

    result = exporters.send_to_splunk(sample_event)
    assert result is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "http://fake-splunk" in args[0]
    assert "Splunk token123" in kwargs["headers"]["Authorization"]

@patch("fixparser.exporters.requests.post")
def test_splunk_export_failure(mock_post, sample_event, monkeypatch):
    monkeypatch.setenv("EXPORT_MODE", "real")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    monkeypatch.setenv("SPLUNK_HEC_URL", "http://fake-splunk")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "token123")
    
    importlib.reload(exporters) 

    # Mock the response object to raise an HTTPError
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError
    mock_post.return_value = mock_resp

    result = exporters.send_to_splunk(sample_event)
    
    # Assert that the function failed and the error counter incremented
    assert result is False
    assert exporters.EXPORT_ERRORS.labels("splunk")._value.get() == 1


def test_datadog_mock(monkeypatch, caplog):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    event = {"test": "datadog", "request_id": "test-datadog-456"}

    importlib.reload(exporters) 
    
    with caplog.at_level(logging.INFO, logger='fixparser'):
        ok = exporters.send_to_datadog(event)
        
    assert ok is True
    
    found_log = False
    for record in caplog.records:
        if record.name == 'fixparser' and record.levelname == 'INFO':
            if record.message == "Exporting to Datadog":
                assert hasattr(record, 'exporter')
                assert record.exporter == 'datadog'
                
                assert hasattr(record, 'event')
                assert record.event == event
                
                assert hasattr(record, 'request_id')
                assert record.request_id == "test-datadog-456"
                
                found_log = True
                break
                
    assert found_log, "Datadog mock log not found in caplog records."

@patch("fixparser.exporters.requests.post")
def test_datadog_export_real_mode(mock_post, sample_event, monkeypatch):
    monkeypatch.setenv("EXPORT_MODE", "real")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    monkeypatch.setenv("DATADOG_LOGS_URL", "https://fake-datadog")
    monkeypatch.setenv("DATADOG_API_KEY", "apikey123")

    importlib.reload(exporters) 

    mock_post.return_value.raise_for_status = MagicMock(return_value=None)

    result = exporters.send_to_datadog(sample_event)
    assert result is True
    mock_post.assert_called_once()
    headers = mock_post.call_args[1]["headers"]
    assert headers["DD-API-KEY"] == "apikey123"

@patch("fixparser.exporters.requests.post")
def test_datadog_export_failure(mock_post, sample_event, monkeypatch):
    monkeypatch.setenv("EXPORT_MODE", "real")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    monkeypatch.setenv("DATADOG_LOGS_URL", "http://fake-datadog")
    monkeypatch.setenv("DATADOG_API_KEY", "apikey123")
    
    importlib.reload(exporters) 

    # Mock the response object to raise an HTTPError
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError
    mock_post.return_value = mock_resp

    result = exporters.send_to_datadog(sample_event)
    
    # Assert that the function failed and the error counter incremented
    assert result is False
    assert exporters.EXPORT_ERRORS.labels("datadog")._value.get() == 1

def test_cloudwatch_mock(monkeypatch, caplog):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    event = {"test": "cloudwatch", "request_id": "test-cloudwatch-789"}

    importlib.reload(exporters)
    
    with caplog.at_level(logging.INFO, logger='fixparser'):
        ok = exporters.send_to_cloudwatch(event)
        
    assert ok is True
    
    found_log = False
    for record in caplog.records:
        if record.name == 'fixparser' and record.levelname == 'INFO':
            if record.message == "Exporting to CloudWatch":
                assert hasattr(record, 'exporter')
                assert record.exporter == 'cloudwatch'
                
                assert hasattr(record, 'event')
                assert record.event == event
                
                assert hasattr(record, 'request_id')
                assert record.request_id == "test-cloudwatch-789"
                
                found_log = True
                break
                
    assert found_log, "CloudWatch mock log not found in caplog records." 

@patch("fixparser.exporters.boto3.client")
def test_cloudwatch_export_real_mode(mock_boto_client, sample_event, monkeypatch):
    monkeypatch.setenv("EXPORT_MODE", "real")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("CW_LOG_GROUP", "my-group")
    monkeypatch.setenv("CW_LOG_STREAM", "my-stream")

    importlib.reload(exporters) 

    mock_logs_client = MagicMock()
    mock_boto_client.return_value = mock_logs_client

    result = exporters.send_to_cloudwatch(sample_event)
    assert result is True
    mock_boto_client.assert_called_with("logs", region_name="us-east-1")
    mock_logs_client.put_log_events.assert_called_once()
    call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
    assert call_kwargs["logGroupName"] == "my-group"
    assert call_kwargs["logStreamName"] == "my-stream"

@patch("fixparser.exporters.boto3.client")
def test_cloudwatch_export_failure(mock_boto_client, sample_event, monkeypatch):
    monkeypatch.setenv("EXPORT_MODE", "real")
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("CW_LOG_GROUP", "my-group")
    monkeypatch.setenv("CW_LOG_STREAM", "my-stream")

    importlib.reload(exporters) 

    # Mock the client and make the put_log_events method raise an exception
    mock_logs_client = MagicMock()
    mock_logs_client.put_log_events.side_effect = Exception("AWS error")
    mock_boto_client.return_value = mock_logs_client

    result = exporters.send_to_cloudwatch(sample_event)
    
    # Assert that the function failed and the error counter incremented
    assert result is False
    assert exporters.EXPORT_ERRORS.labels("cloudwatch")._value.get() == 1


def test_export_event_dispatches_all(monkeypatch, sample_event):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    monkeypatch.setenv("EXPORT_ENABLED", "true")

    mock_splunk = MagicMock(return_value=True)
    mock_datadog = MagicMock(return_value=True)
    mock_cw = MagicMock(return_value=True)

    monkeypatch.setattr(exporters, "send_to_splunk", mock_splunk)
    monkeypatch.setattr(exporters, "send_to_datadog", mock_datadog)
    monkeypatch.setattr(exporters, "send_to_cloudwatch", mock_cw)
    

    exporters.export_event(sample_event)

    mock_splunk.assert_called_once_with(sample_event)
    mock_datadog.assert_called_once_with(sample_event)
    mock_cw.assert_called_once_with(sample_event)

def test_export_event_disabled(monkeypatch, sample_event):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    monkeypatch.setenv("EXPORT_ENABLED", "false")

    importlib.reload(exporters) 

    mock_splunk = MagicMock(return_value=True)
    mock_datadog = MagicMock(return_value=True)
    mock_cw = MagicMock(return_value=True)

    monkeypatch.setattr(exporters, "send_to_splunk", mock_splunk)
    monkeypatch.setattr(exporters, "send_to_datadog", mock_datadog)
    monkeypatch.setattr(exporters, "send_to_cloudwatch", mock_cw)
    

    result = exporters.export_event(sample_event)

    assert result is None

    mock_splunk.assert_not_called()
    mock_datadog.assert_not_called()
    mock_cw.assert_not_called()