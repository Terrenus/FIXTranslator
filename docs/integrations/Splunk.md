# Splunk integration (HEC)

This guide shows how to forward parsed FIX JSON into Splunk using HEC.

## Steps

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