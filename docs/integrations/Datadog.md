# Datadog integration

Datadog accepts logs via HTTP. We recommend sending parsed JSON in the `attributes` field.

## Steps

1. Generate a Datadog Logs API key from Integrations → APIs.

2. Example: send parsed event to Datadog
```bash
API_KEY="<DATADOG_API_KEY>"
PARSED=$(curl -s -X POST http://localhost:9000/parse -H "Content-Type: application/json" -d '{"raw":"8=...|...|"}' | jq -c '.flat')
curl -s -X POST "https://http-intake.logs.datadoghq.com/v1/input/$API_KEY" \
-H "Content-Type: application/json" \
-d "{\"message\":\"\", \"ddsource\":\"fixtranslator\", \"service\":\"trading\", \"attributes\": $PARSED}"
```

3. Datadog Pipeline
    - Create a pipeline that JSON-parses attributes and maps fields to log facets:
        - Add a JSON parser processor targeting attributes.
        - Remap attributes.Symbol → fix.symbol (tag).
        - Create log-based metrics for important fields (e.g., rejects).

4. Example Live Tail query:
```
source:fixtranslator service:trading fix.symbol:"EUR/USD"
```

5. Tips
    - Use Datadog Live Tail to watch incoming FIX logs during demos.

    - Provide a saved view / dashboard showing common KPIs (messages per second, rejects, avg latency).