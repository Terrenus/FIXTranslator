# fixparser/exporters.py
import requests
import json
import time
import boto3
import os
from botocore.exceptions import ClientError

def send_to_splunk(hec_url: str, hec_token: str, json_event: dict, sourcetype: str = "fix:parsed"):
    headers = {"Authorization": f"Splunk {hec_token}", "Content-Type":"application/json"}
    payload = {"event": json_event, "sourcetype": sourcetype, "time": time.time()}
    r = requests.post(hec_url, headers=headers, json=payload, verify=True, timeout=10)
    r.raise_for_status()
    return r.status_code

def send_to_datadog(api_key: str, json_event: dict, ddsource: str = "fix-parser", service: str = "fix"):
    url = f"https://http-intake.logs.datadoghq.com/v1/input/{api_key}"
    body = {"message": "", "ddsource": ddsource, "service": service, "attributes": json_event}
    r = requests.post(url, json=body, timeout=10)
    r.raise_for_status()
    return r.status_code

def send_to_cloudwatch(log_group: str, log_stream: str, json_event: dict, aws_region="eu-west-1"):
    endpoint = os.environ.get("CLOUDWATCH_ENDPOINT_URL")  # e.g. http://localstack:4566
    client = boto3.client("logs", region_name=aws_region, endpoint_url=endpoint) if endpoint else boto3.client("logs", region_name=aws_region)
    ts = int(time.time() * 1000)
    try:
        client.create_log_group(logGroupName=log_group)
    except ClientError:
        pass
    try:
        client.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
    except ClientError:
        pass
    # naive sequence token handling omitted (for demo)
    event = {"timestamp": ts, "message": json.dumps(json_event)}
    resp = client.put_log_events(logGroupName=log_group, logStreamName=log_stream, logEvents=[event])
    return resp
