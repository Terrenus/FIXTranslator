from fixparser import exporters

def test_splunk_mock(monkeypatch, caplog):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    event = {"test": "splunk"}
    ok = exporters.send_to_splunk(event)
    assert ok
    assert any("Exporter:Splunk MOCK" in m for m in caplog.messages)

def test_datadog_mock(monkeypatch, caplog):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    event = {"test": "datadog"}
    ok = exporters.send_to_datadog(event)
    assert ok
    assert any("Exporter:Datadog MOCK" in m for m in caplog.messages)

def test_cloudwatch_mock(monkeypatch, caplog):
    monkeypatch.setenv("EXPORT_MODE", "mock")
    event = {"test": "cloudwatch"}
    ok = exporters.send_to_cloudwatch(event)
    assert ok
    assert any("Exporter:CloudWatch MOCK" in m for m in caplog.messages)
