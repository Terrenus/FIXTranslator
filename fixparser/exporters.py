import os
import json
import logging
import requests
from prometheus_client import Counter

logger = logging.getLogger("fixparser.exporters")

EXPORT_MODE = os.getenv("EXPORT_MODE", "mock").lower()
EXPORT_ENABLED = os.getenv("EXPORT_ENABLED", "false").lower() in ("true", "1", "yes")

# Prometheus counters
EXPORT_TOTAL = Counter("fixparser_export_total", "Total number of exporter send attempts", ["target"])
EXPORT_ERRORS = Counter("fixparser_export_errors_total", "Exporter send failures", ["target"])

def _log_event(prefix, event):
    logger.info("[%s] %s", prefix, json.dumps(event, indent=2)[:300])

def send_to_splunk(event: dict):
    EXPORT_TOTAL.labels("splunk").inc()
    if EXPORT_MODE == "mock":
        _log_event("Exporter:Splunk MOCK", event)
        return True
    try:
        url = os.getenv("SPLUNK_HEC_URL", "http://localhost:8088/services/collector")
        token = os.getenv("SPLUNK_HEC_TOKEN", "demo-token")
        headers = {"Authorization": f"Splunk {token}", "Content-Type": "application/json"}
        payload = {"event": event}
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        r.raise_for_status()
        return True
    except Exception as e:
        EXPORT_ERRORS.labels("splunk").inc()
        logger.exception("Splunk exporter error: %s", e)
        return False

def send_to_datadog(event: dict):
    EXPORT_TOTAL.labels("datadog").inc()
    if EXPORT_MODE == "mock":
        _log_event("Exporter:Datadog MOCK", event)
        return True
    try:
        url = os.getenv("DATADOG_LOGS_URL", "https://http-intake.logs.datadoghq.com/v1/input")
        api_key = os.getenv("DATADOG_API_KEY", "demo-key")
        headers = {"DD-API-KEY": api_key, "Content-Type": "application/json"}
        payload = [event]
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        r.raise_for_status()
        return True
    except Exception as e:
        EXPORT_ERRORS.labels("datadog").inc()
        logger.exception("Datadog exporter error: %s", e)
        return False

def send_to_cloudwatch(event: dict):
    EXPORT_TOTAL.labels("cloudwatch").inc()
    if EXPORT_MODE == "mock":
        _log_event("Exporter:CloudWatch MOCK", event)
        return True
    try:
        import boto3
        group = os.getenv("CW_LOG_GROUP", "fixparser-demo")
        stream = os.getenv("CW_LOG_STREAM", "fixparser")
        logs = boto3.client("logs", region_name=os.getenv("AWS_REGION", "us-east-1"))
        logs.create_log_group(logGroupName=group)
        logs.create_log_stream(logGroupName=group, logStreamName=stream)
        logs.put_log_events(
            logGroupName=group,
            logStreamName=stream,
            logEvents=[{"timestamp": int(event.get("timestamp", 0)), "message": json.dumps(event)}],
        )
        return True
    except Exception as e:
        EXPORT_ERRORS.labels("cloudwatch").inc()
        logger.exception("CloudWatch exporter error: %s", e)
        return False

def export_event(event: dict):
    """Dispatch event to all exporters if enabled"""
    if not EXPORT_ENABLED:
        return
    send_to_splunk(event)
    send_to_datadog(event)
    send_to_cloudwatch(event)