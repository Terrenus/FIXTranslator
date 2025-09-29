# Monitoring & Dashboarding

This section describes suggested metrics, instrumentation and a sample Grafana dashboard for operations teams.

## Metrics to expose (Prometheus style)
- `fixparser_parses_total` (counter) — total parsed messages
- `fixparser_parse_errors_total` (counter) — parser errors
- `fixparser_parse_latency_ms` (histogram) — latencies
- `fixparser_requests_inflight` (gauge)
- `fixparser_messages_by_msgtype` (counter with label `msgtype`)

## Expose metrics
- Add an endpoint `/metrics` exporting Prometheus format (or use `prometheus_client`).
- Example code: use `prometheus_client.CollectorRegistry()` and mount `/metrics`.

## Sample Grafana panels
1. **Throughput** — Rate (per second) of `fixparser_parses_total` (1m / 5m)
2. **Errors** — `fixparser_parse_errors_total` (delta over 5m)
3. **Latency** — P50/P95/P99 from `fixparser_parse_latency_ms` histogram
4. **Top MsgTypes** — table of `fixparser_messages_by_msgtype` top 10
5. **Last parsed messages** — a log tail panel reading parsed JSON (or Splunk/Datadog view)

## Export dashboard
- Create panels in Grafana and export as JSON; store under `docs/monitoring/grafana_dashboard.json` for repo reference.

## Alerts (examples)
- Alert if `parse_errors / parses_total > 0.01` (1%)
- Alert if `parse_latency_p99 > 500ms` (customize per SLA)