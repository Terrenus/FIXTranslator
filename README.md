# FIXTranslator

[![Build Status](https://github.com/Terrenus/FIXTranslator/actions/workflows/ci.yml/badge.svg)](https://github.com/Terrenus/FIXTranslator/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Terrenus/FIXTranslator)](https://github.com/Terrenus/FIXTranslator/releases)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![PyPi](https://img.shields.io/pypi/v/fixtranslator)](https://pypi.org/project/fixtranslator)

FIXTranslator parses FIX (Financial Information eXchange) protocol logs (4.x and 5.x / FIXT) into structured JSON and human-readable output, and forwards parsed events to common logging platforms (Splunk, Datadog, CloudWatch, ELK). It preserves the original raw FIX and provides connectors, example pipelines and a small web UI for side-by-side raw vs translated view.

This repo contains:
- `fixparser/` — Python FastAPI parser service (REST endpoints + minimal UI)
- `logstash/` & `fluentbit/` — example integration pipeline configs
- `docker/` — Dockerfile + docker-compose for local demo (parser, logstash, fluentbit, localstack)
- `docs/integrations/` — how-to guides for Splunk, Datadog, AWS, etc.
- CI / release workflows in `.github/workflows/`

---

## Quickstart (local, 5–10 min)

Requirements:
- Docker & docker-compose
- `jq` (optional but handy)
- (optional) `gh` CLI for releases

1. Clone:  

```bash
git clone https://github.com/Terrenus/FIXTranslator.git
cd FIXTranslator
```

2. Start demo services (parser + Logstash + Fluent Bit + LocalStack):

```bash
docker compose -f docker/docker-compose.yml up --build
```

3. Open UI:

- Parser UI: http://localhost:9000/ui — paste a |-separated FIX message or a SOH \x01 message and click Parse.

4. Use validate script:

```bash
./validate.sh http://localhost:9000/parse
```

5. Append a test FIX line to trigger Fluent Bit tails:

```bash
echo '8=FIX.4.4|9=176|35=D|49=CLIENT12|56=BROKER03|11=demo1|55=EUR/USD|54=1|38=1000|40=2|44=1.1850|60=20250929-12:00:00|10=000|' >> sample_fix_messages.txt
```

6. Check logs:

```bash
docker compose -f docker/docker-compose.yml logs -f fixparser fluentbit logstash
```

## Endpoints

- POST /parse — accepts single or batched messages (JSON or plain text); tolerant to keys raw, log, message and Fluent Bit batched arrays. Returns parsed JSON, flattened fields, summary, detail, and errors.

- POST /parse/batch — optional batch endpoint (array input).

- GET /ui — minimal HTML UI for side-by-side raw & translated display.

## Example: curl the parser

```bash
# single message
payload=$(jq -n --arg raw "8=FIX.4.4|9=176|35=D|49=CLIENT|56=BROKER|11=123|55=EUR/USD|54=1|38=1000|40=2|44=1.13|60=20250929-12:00:00|10=000|" '{"raw":$raw}')
curl -s -X POST http://localhost:9000/parse -H "Content-Type: application/json" -d "$payload" | jq

# batched (Fluent Bit style)
payload='[{"log":"8=FIX.4.4|9=176|35=D|49=CLIENT|56=BROKER|11=123|55=EUR/USD|54=1|38=1000|40=2|44=1.13|60=20250929-12:00:00|10=000|"}]'
curl -s -X POST http://localhost:9000/parse -H "Content-Type: application/json" -d "$payload" | jq
```

## Configuration

- Dictionaries: drop QuickFIX-style XML dictionary files under fixparser/dicts/ (e.g., FIX44.xml, FIX50SP2.xml). The parser will load available XMLs on startup.

- Environment variables (parser):

    - PORT — port to run on (default 9000)

    - CLOUDWATCH_ENDPOINT_URL — optional LocalStack endpoint for CloudWatch testing

    - SPLUNK_HEC_URL / SPLUNK_HEC_TOKEN — optional auto-forward configuration

    - DATADOG_API_KEY — optional auto-forward configuration

See fixparser/exporters.py for exporter helpers.

## Developing

Create and activate a venv:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Run server locally:

```bash
uvicorn fixparser.main:app --reload --port 9000
```

Run tests:

```bash
pytest -q
```

## Contributing & Code of Conduct

Please see CONTRIBUTING.md and CODE_OF_CONDUCT.md.

## License

Apache License 2.0 — see LICENSE.