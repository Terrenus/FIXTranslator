from fixparser.exporters import export_event

def test_export_event_dispatch(monkeypatch):
    called = []
    def fake_send(event): called.append(event)
    monkeypatch.setattr("fixparser.exporters.send_to_splunk", lambda e: called.append("splunk"))
    monkeypatch.setattr("fixparser.exporters.send_to_datadog", lambda e: called.append("datadog"))
    monkeypatch.setattr("fixparser.exporters.send_to_cloudwatch", lambda e: called.append("cw"))
    monkeypatch.setenv("EXPORT_ENABLED", "true")
    export_event({"msg": "ok"})
    assert "splunk" in called and "datadog" in called and "cw" in called
