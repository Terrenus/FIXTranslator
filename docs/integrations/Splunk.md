# Splunk integration (HEC)

This guide shows how to forward parsed FIX JSON into Splunk using HEC.

### Steps

1. Enable HEC in Splunk Web:
   - Settings → Data Inputs → HTTP Event Collector → `New Token`.
   - Name: `fixtranslator`
   - Set `sourcetype` to `fix:parsed` (or create an index)
   - Copy the token value.

2. Send parsed event to Splunk HEC:
   - Use the parser to create `flat` JSON and forward to Splunk:
```bash
# post to parser and forward to Splunk
PARSED=$(curl -s -X POST http://localhost:9000/parse -H "Content-Type: application/json" -d '{"raw":"8=...|...|"}' | jq -c '.flat')
curl -k -H "Authorization: Splunk <SPLUNK_HEC_TOKEN>" -H "Content-Type: application/json" \
-d "{\"event\": $PARSED, \"sourcetype\":\"fix:parsed\"}" \
https://splunk.example:8088/services/collector
```
3. Splunk App / TA (recommended)

    - Create a Splunk Technology Add-on (TA) that:
        - Accepts fix:parsed HEC events.
        - Provides saved searches and dashboards.
    - Example searches:
```spl
    # recent fix messages
sourcetype="fix:parsed" | table _time fix_SenderCompID fix_TargetCompID fix_MsgType fix_Symbol fix_OrderQty fix_Price

# rejects last 24h
sourcetype="fix:parsed" fix_MsgType="3" OR fix_MsgType="9" | stats count by fix_SenderCompID, fix_RejectReason
```
4. Tips
    - Send raw alongside parsed JSON (store as raw_fix) so veteran operators can inspect original FIX.
    - Configure retention/indexing per message volume.

---

### Exporter Integration

FIXTranslator now supports automatic Splunk export through its internal exporter system.  
When `EXPORT_ENABLED=true`, parsed messages are automatically sent to the Splunk HTTP Event Collector (HEC).

**Environment Variables**

| Variable | Description | Example |
|-----------|-------------|----------|
| `EXPORT_ENABLED` | Enable all exporters | `true` |
| `EXPORT_MODE` | `mock` (default) or `live` | `live` |
| `SPLUNK_HEC_URL` | Splunk HEC endpoint | `https://splunk:8088/services/collector` |
| `SPLUNK_HEC_TOKEN` | HEC token | `ABC123-XYZ456` |

**Mock Example (for local demo):**

```bash
EXPORT_ENABLED=true EXPORT_MODE=mock \
uvicorn fixparser.main:app --port 9000
```
This will print to console:
```
[Exporter:Splunk MOCK] Event would be sent to http://localhost:8088/services/collector
```

**Live Example (real Splunk):**

```bash
EXPORT_ENABLED=true EXPORT_MODE=live \
SPLUNK_HEC_URL="https://splunk.example.com:8088/services/collector" \
SPLUNK_HEC_TOKEN="YOUR_HEC_TOKEN" \
uvicorn fixparser.main:app --port 9000
```
**Search Example:**

```spl
index=main sourcetype="fixparser" | stats count by summary,55,35
```