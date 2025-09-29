import requests
import time
import os

PARSER_URL = os.environ.get("FIX_PARSER_URL", "http://localhost:9000/parse")
SPLUNK_HEC = os.environ.get("SPLUNK_HEC_URL", "https://splunk:8088/services/collector")
SPLUNK_TOKEN = os.environ.get("SPLUNK_TOKEN", "")

def post_to_parser(raw):
    r = requests.post(PARSER_URL, json={"raw": raw}, timeout=10)
    r.raise_for_status()
    return r.json()

def post_to_splunk(json_event):
    headers = {"Authorization": f"Splunk {SPLUNK_TOKEN}", "Content-Type":"application/json"}
    payload = {"event": json_event, "sourcetype":"fix:parsed", "time": time.time()}
    r = requests.post(SPLUNK_HEC, headers=headers, json=payload, verify=False, timeout=10)
    r.raise_for_status()
    return r.status_code

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv)>1 else "/var/log/fix/sample_fix_messages.txt"
    with open(path) as fh:
        for line in fh:
            line=line.strip()
            if not line:
                continue
            parsed = post_to_parser(line)
            post_to_splunk(parsed.get("flat", parsed))
