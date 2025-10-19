import os
import json
import logging
import time
from fastapi import FastAPI, Request, UploadFile, File, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from .exporters import EXPORT_ENABLED, export_event
from .parser import FixDictionary, parse_fix_message, flatten, human_summary, human_detail
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="FIX Parser Demo")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("fixparser")
logger.setLevel(logging.INFO)

PARSES_TOTAL = Counter("fixparser_parses_total", "Total number of FIX parse attempts")
PARSE_ERRORS = Counter("fixparser_parse_errors_total", "Total number of FIX parse errors")
PARSE_LATENCY = Histogram("fixparser_parse_latency_seconds", "Histogram of FIX parse latencies")
IN_FLIGHT = Gauge("fixparser_inflight_requests", "Number of in-flight parse requests")

# Config: dictionary directory (can be overridden with env var for tests)
DICT_DIR = os.environ.get("FIXPARSER_DICT_DIR", os.path.join(os.path.dirname(__file__), "dicts"))
os.makedirs(DICT_DIR, exist_ok=True)

# Load any dictionaries present at startup into a global if desired (not required)
global_default_dict = FixDictionary()
# Try to load known dicts but don't fail startup
for fname in os.listdir(DICT_DIR) if os.path.isdir(DICT_DIR) else []:
    fpath = os.path.join(DICT_DIR, fname)
    try:
        if fname.lower().endswith(".xml"):
            global_default_dict.load_quickfix_xml(fpath)
            logger.info("Loaded dictionary at startup: %s", fname)
        elif fname.lower().endswith(".json"):
            global_default_dict.load_json_dict(fpath)
            logger.info("Loaded JSON dictionary at startup: %s", fname)
    except Exception as e:
        logger.warning("dict load error %s: %s", fname, e)


@app.post("/upload_dict")
async def upload_dict(file: UploadFile = File(...), name: Optional[str] = Form(None)):
    """
    Upload a dictionary file (QuickFIX XML or JSON).
    - file: upload the XML/JSON file
    - name: optional filename to save as (must end with .xml or .json)
    Returns {"ok": True, "filename": "<saved>"}
    """
    filename = name or file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="missing filename")
    if not (filename.lower().endswith(".xml") or filename.lower().endswith(".json")):
        raise HTTPException(status_code=400, detail="unsupported file type (only .xml and .json allowed)")
    save_path = os.path.join(DICT_DIR, filename)
    contents = await file.read()
    try:
        with open(save_path, "wb") as fh:
            fh.write(contents)
    except Exception as e:
        logger.exception("Failed to save dict")
        raise HTTPException(status_code=500, detail=str(e))

    # Validate by attempting to load
    try:
        d = FixDictionary()
        if filename.lower().endswith(".xml"):
            d.load_quickfix_xml(save_path)
        else:
            d.load_json_dict(save_path)
    except Exception as e:
        # cleanup invalid file
        try:
            os.remove(save_path)
        except Exception:
            pass
        logger.exception("Dictionary validation failed")
        raise HTTPException(status_code=400, detail=f"dictionary validation failed: {e}")

    return JSONResponse({"ok": True, "filename": filename})


@app.post("/parse")
async def parse_endpoint(request: Request, dict_name: Optional[str] = None):
    """
    Parse a single message (or fallback to body text).
    Accepts JSON or plain text. Optional query param ?dict_name=filename to use a specific dictionary.
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

    if isinstance(data, dict):
        raw = data.get("raw") or data.get("log") or data.get("message")
        if raw:
            messages.append(raw.rstrip("\r\n"))
    elif isinstance(data, list):
        # if list passed but user called /parse (single), treat first element
        entry = data[0] if data else None
        if isinstance(entry, dict):
            raw = entry.get("raw") or entry.get("log") or entry.get("message")
            if raw:
                messages.append(raw.rstrip("\r\n"))
        elif isinstance(entry, str):
            messages.append(entry.rstrip("\r\n"))
    else:
        # plain text
        try:
            text = body_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                messages.append(text)
        except Exception:
            pass

    if not messages:
        return JSONResponse({"error": "no raw message found in request"}, status_code=400)

    dict_obj = None
    if dict_name:
        dict_path = os.path.join(DICT_DIR, dict_name)
        if not os.path.exists(dict_path):
            raise HTTPException(status_code=404, detail="dictionary not found")
        dict_obj = FixDictionary()
        if dict_name.lower().endswith(".xml"):
            dict_obj.load_quickfix_xml(dict_path)
        else:
            dict_obj.load_json_dict(dict_path)
    else:
        dict_obj = global_default_dict

    results = []
    for raw in messages:
        IN_FLIGHT.inc()
        start = time.time()
        try:
            raw_norm = raw.replace("|", "\x01")
            resp = parse_fix_message(raw_norm, dict_obj=dict_obj)
            flat = flatten(resp["parsed_by_tag"])
            results.append({
                "raw": raw_norm.replace("\x01", "|"),
                "parsed": resp["parsed_by_tag"],
                "flat": flat,
                "summary": human_summary(flat),
                "detail": human_detail(resp["parsed_by_tag"]),
                "errors": resp["errors"]
            })
            if EXPORT_ENABLED:
                export_event({
                    "summary": human_summary(flat),
                    "flat": flat,
                    "raw": raw_norm.replace("\x01", "|"),
                    "errors": resp["errors"],
                })
            PARSES_TOTAL.inc()
            if resp.get("errors"):
                PARSE_ERRORS.inc(len(resp.get("errors", [])))
        except Exception as e:
            PARSE_ERRORS.inc()
            logger.exception("parse error")
            results.append({"raw": raw, "error": str(e)})
        finally:
            elapsed = time.time() - start
            PARSE_LATENCY.observe(elapsed)
            IN_FLIGHT.dec()

    return JSONResponse(results[0] if len(results) == 1 else results)


@app.post("/parse/batch")
async def parse_batch(request: Request, dict_name: Optional[str] = None):
    """
    Accept an array payload (Fluent Bit style) or array of strings / objects:
    - [{"raw": "..."} , {"raw": "..."}] or ["raw1","raw2"]
    Optional dict_name query param to select uploaded dictionary file.
    Returns array of parsed results.
    """
    body_bytes = await request.body()
    try:
        data = json.loads(body_bytes) if body_bytes else None
    except Exception:
        data = None

    messages = []
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                raw = entry.get("raw") or entry.get("log") or entry.get("message")
                if raw:
                    messages.append(raw.rstrip("\r\n"))
            elif isinstance(entry, str):
                messages.append(entry.rstrip("\r\n"))
    else:
        return JSONResponse({"error": "expected JSON array"}, status_code=400)

    if not messages:
        return JSONResponse({"error": "no messages found in batch"}, status_code=400)

    dict_obj = None
    if dict_name:
        dict_path = os.path.join(DICT_DIR, dict_name)
        if not os.path.exists(dict_path):
            raise HTTPException(status_code=404, detail="dictionary not found")
        dict_obj = FixDictionary()
        if dict_name.lower().endswith(".xml"):
            dict_obj.load_quickfix_xml(dict_path)
        else:
            dict_obj.load_json_dict(dict_path)
    else:
        dict_obj = global_default_dict

    results = []
    for raw in messages:
        IN_FLIGHT.inc()
        start = time.time()
        try:
            raw_norm = raw.replace("|", "\x01")
            resp = parse_fix_message(raw_norm, dict_obj=dict_obj)
            flat = flatten(resp["parsed_by_tag"])
            results.append({
                "raw": raw_norm.replace("\x01", "|"),
                "parsed": resp["parsed_by_tag"],
                "flat": flat,
                "summary": human_summary(flat),
                "detail": human_detail(resp["parsed_by_tag"]),
                "errors": resp["errors"]
            })
            if EXPORT_ENABLED:
                export_event({
                    "summary": human_summary(flat),
                    "flat": flat,
                    "raw": raw_norm.replace("\x01", "|"),
                    "errors": resp["errors"],
                })
            PARSES_TOTAL.inc()
            if resp.get("errors"):
                PARSE_ERRORS.inc(len(resp.get("errors", [])))
        except Exception as e:
            PARSE_ERRORS.inc()
            logger.exception("parse error")
            results.append({"raw": raw, "error": str(e)})
        finally:
            elapsed = time.time() - start
            PARSE_LATENCY.observe(elapsed)
            IN_FLIGHT.dec()

    return JSONResponse(results)


@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/ui", response_class=HTMLResponse)
async def ui_get():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "ui.html")
    if os.path.isfile(template_path):
        html = open(template_path, "r", encoding="utf-8").read()
    else:
        html = "<html><body><h3>FIX Parser UI template not found</h3></body></html>"
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<h3>FIX Parser Demo</h3><p>Go to <a href='/ui'>/ui</a></p>")