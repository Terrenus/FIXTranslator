import os
import json
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .parser import FixDictionary, parse_fix_message, flatten, human_summary, human_detail

app = FastAPI(title="FIX Parser Demo")

logger = logging.getLogger("fixparser")
logger.setLevel(logging.INFO)

# Load dictionaries from dicts/ (if any)
DICT_DIR = os.path.join(os.path.dirname(__file__), "dicts")
fix_dict = FixDictionary()
if os.path.isdir(DICT_DIR):
    for fname in os.listdir(DICT_DIR):
        if fname.lower().endswith(".xml"):
            try:
                fix_dict.load_quickfix_xml(os.path.join(DICT_DIR, fname))
                logger.info("Loaded dictionary: %s", fname)
            except Exception as e:
                logger.warning("dict load error %s: %s", fname, e)


@app.post("/parse")
async def parse_endpoint(request: Request):
    """
    Accepts:
      - JSON bodies like {"raw":"..."} OR {"log":"..."} OR {"message":"..."} or Datadog {"attributes": {...}}
      - JSON arrays (Fluent Bit batches)
      - Plain text POST with raw FIX in body
    Returns parsed JSON (single object or array).
    """
    body_bytes = await request.body()
    logger.info("Incoming /parse request: %d bytes", len(body_bytes))
    messages = []

    # Try JSON decode
    data = None
    try:
        if body_bytes:
            data = json.loads(body_bytes)
    except Exception:
        data = None

    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                raw = entry.get("raw") or entry.get("log") or entry.get("message")
                if raw:
                    messages.append(raw.rstrip("\r\n"))
            elif isinstance(entry, str):
                messages.append(entry.rstrip("\r\n"))
    elif isinstance(data, dict):
        # datadog-like shape
        if "attributes" in data and isinstance(data["attributes"], dict):
            raw = data["attributes"].get("message") or data["attributes"].get("log")
            if raw:
                messages.append(raw.rstrip("\r\n"))
        else:
            raw = data.get("raw") or data.get("log") or data.get("message")
            if raw:
                messages.append(raw.rstrip("\r\n"))
    else:
        # Treat body as plain text
        try:
            text = body_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                messages.append(text)
        except Exception:
            pass

    if not messages:
        return JSONResponse({"error": "no raw message found in request"}, status_code=400)

    results = []
    for raw in messages:
        raw_norm = raw.replace("|", "\x01")
        resp = parse_fix_message(raw_norm, dict_obj=fix_dict)
        flat = flatten(resp["parsed_by_tag"])
        results.append({
            "raw": raw_norm.replace("\x01", "|"),
            "parsed": resp["parsed_by_tag"],
            "flat": flat,
            "summary": human_summary(flat),
            "detail": human_detail(resp["parsed_by_tag"]),
            "errors": resp["errors"]
        })

    return JSONResponse(results if len(results) > 1 else results[0])


@app.get("/ui", response_class=HTMLResponse)
async def ui_get():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "ui.html")
    if os.path.isfile(template_path):
        html = open(template_path, "r", encoding="utf-8").read()
    else:
        html = "<html><body><h3>FIX Parser UI template not found</h3></body></html>"
    return HTMLResponse(html)


@app.post("/ui", response_class=HTMLResponse)
async def ui_post(request: Request):
    form = await request.form()
    raw = form.get("raw") or ""
    resp = parse_fix_message(raw.replace("|", "\x01"), dict_obj=fix_dict)
    flat = flatten(resp["parsed_by_tag"])
    template_path = os.path.join(os.path.dirname(__file__), "templates", "ui.html")
    if os.path.isfile(template_path):
        html_template = open(template_path, "r", encoding="utf-8").read()
    else:
        html_template = "<html><body><pre>%%DETAIL%%</pre></body></html>"
    return HTMLResponse(
        html_template
        .replace("%%RAW%%", raw.replace("\x01", "|"))
        .replace("%%SUMMARY%%", human_summary(flat))
        .replace("%%DETAIL%%", human_detail(resp["parsed_by_tag"]))
        .replace("%%JSON%%", json.dumps(flat, indent=2))
    )


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<h3>FIX Parser Demo</h3><p>Go to <a href='/ui'>/ui</a></p>")