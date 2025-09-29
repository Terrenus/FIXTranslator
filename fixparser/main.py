# fixparser/main.py
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Template
import os
import json
from .parser import FixDictionary, parse_fix_message, flatten, human_summary, human_detail
from .exporters import send_to_splunk, send_to_datadog, send_to_cloudwatch
import logging

logger = logging.getLogger("fixparser")
logger.setLevel(logging.INFO)

app = FastAPI(title="FIXTranslator Demo")

# load dictionaries if provided in dicts/
DICT_DIR = os.path.join(os.path.dirname(__file__), "dicts")
fix_dict = FixDictionary()
# attempt to load any xml in dicts/
if os.path.isdir(DICT_DIR):
    for fname in os.listdir(DICT_DIR):
        if fname.lower().endswith(".xml"):
            try:
                fix_dict.load_quickfix_xml(os.path.join(DICT_DIR, fname))
            except Exception as e:
                print("dict load error", fname, e)

from fastapi import Request
from fastapi.responses import JSONResponse
import json

@app.post("/parse")
async def parse_endpoint(request: Request):
    body_bytes = await request.body()
    # try to decode JSON first
    messages = []
    
    logger.info("Incoming /parse request: %d bytes", len(body_bytes))

    try:
        data = json.loads(body_bytes)
    except Exception:
        data = None

    # Accept data shapes:
    # 1) JSON array of records: each record may have "raw" or "log" or "message"
    # 2) JSON object with keys "raw" / "log" / "message" or with 'attributes' dict (Datadog)
    # 3) Plain text body
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                raw = entry.get("raw") or entry.get("log") or entry.get("message")
                if raw:
                    messages.append(raw.rstrip("\r\n"))
            elif isinstance(entry, str):
                messages.append(entry.rstrip("\r\n"))
    elif isinstance(data, dict):
        # datadog style: {"attributes": {"message": "..."}}
        if "attributes" in data and isinstance(data["attributes"], dict):
            raw = data["attributes"].get("message") or data["attributes"].get("log")
            if raw:
                messages.append(raw.rstrip("\r\n"))
        else:
            raw = data.get("raw") or data.get("log") or data.get("message")
            if raw:
                messages.append(raw.rstrip("\r\n"))
    elif isinstance(body_bytes, (bytes, bytearray)):
        # treat body as plain text
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

    # return array only if we had an array; otherwise return single object
    return JSONResponse(results if len(results) > 1 else results[0])

@app.post("/parse/batch")
async def parse_batch(payload: dict):
    raws = payload.get("raws") or []
    out = []
    for raw in raws:
        resp = parse_fix_message(raw, dict_obj=fix_dict)
        flat = flatten(resp["parsed_by_tag"])
        out.append({
            "raw": resp["raw"].replace('\x01','|'),
            "flat": flat,
            "summary": human_summary(flat),
            "detail": human_detail(resp["parsed_by_tag"]),
            "errors": resp["errors"]
        })
    return JSONResponse(out)

# Simple UI endpoint
@app.get("/ui", response_class=HTMLResponse)
async def ui_get():
    html = open(os.path.join(os.path.dirname(__file__), "templates", "ui.html")).read()
    return HTMLResponse(html)

@app.post("/ui", response_class=HTMLResponse)
async def ui_post(request: Request):
    form = await request.form()
    raw = form.get("raw") or ""
    resp = parse_fix_message(raw, dict_obj=fix_dict)
    flat = flatten(resp["parsed_by_tag"])
    html_template = open(os.path.join(os.path.dirname(__file__), "templates", "ui.html")).read()
    return HTMLResponse(html_template.replace("%%RAW%%", raw.replace("\x01","|")).replace("%%SUMMARY%%", human_summary(flat)).replace("%%DETAIL%%", human_detail(resp["parsed_by_tag"])).replace("%%JSON%%", str(flat)))

# root
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<h3>FIX Parser Demo</h3><p>Go to <a href='/ui'>/ui</a></p>")
