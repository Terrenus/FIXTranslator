import os
import json
import logging
import time
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form, Response, HTTPException, Security, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Annotated, Literal
from .exporters import EXPORT_ENABLED, export_event
from .parser import FixDictionary, parse_fix_message, flatten, human_summary, human_detail
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

app = FastAPI(title="FIX Parser Demo")

API_KEY_HEADER = APIKeyHeader(name="x-api-key", auto_error=False)

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

MAX_BODY_SIZE = 1 * 1024 * 1024 

ALLOWED_ORIGINS = ["https://your-company.example"] if not os.getenv("DEV") else ["*"]

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # read limited chunk to avoid reading entire huge bodies
        body = await request.body()
        if len(body) > MAX_BODY_SIZE:
            return PlainTextResponse("Request body too large", status_code=413)
        return await call_next(request)

app.add_middleware(MaxBodySizeMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

def _get_valid_api_keys() -> set:
    keys = os.getenv("API_KEYS", "")
    if not keys:
        return set()
    return {k.strip() for k in keys.split(",") if k.strip()}

def require_api_key(api_key: Optional[str] = Depends(API_KEY_HEADER)) -> Optional[str]:
    allowed = _get_valid_api_keys()
    if allowed:
        if not api_key or api_key not in allowed:
            print("!!! FAILING: API Key is not in 'allowed'.")
            raise HTTPException(status_code=401, detail="Invalid API key")
        # SUCCESS: Return the API key string
        return api_key
    
    # Logic for when API keys are NOT configured (development/bypass)
    if os.getenv("DISABLE_APIKEY_CHECK", "0") == "1":
        print("!!! WARNING: API_KEYS empty but DISABLE_APIKEY_CHECK is set. Bypassing check.")
        return None
    
    # Default secure fallback if no key is set and no bypass is active
    print("!!! FAILING: 'allowed' variable is empty, and bypass is off. API key required.")
    raise HTTPException(status_code=401, detail="API key required")

def get_parse_mode(mode: Optional[str] = 'lenient') -> Literal['strict', 'lenient']:
    """
    Validates the 'mode' query parameter. Must be 'strict' or 'lenient'.
    Defaults to 'lenient'.
    """
    if mode is None:
        return 'lenient'
    
    mode_lower = mode.lower()
    if mode_lower not in ('strict', 'lenient'):
        raise HTTPException(
            status_code=400, 
            detail="Invalid mode. Must be 'strict' or 'lenient'."
        )
    return mode_lower

# Config: dictionary directory (can be overridden with env var for tests)
DICT_DIR = Path(os.environ.get("FIXPARSER_DICT_DIR", Path(__file__).parent / "dicts"))
DICT_DIR.mkdir(parents=True, exist_ok=True)

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


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

@app.post("/upload_dict")
async def upload_dict(file: UploadFile = File(...), name: Optional[str] = Form(None)):
    """
    Upload a dictionary file (QuickFIX XML or JSON).
    - file: upload the XML/JSON file
    - name: optional filename to save as (must end with .xml or .json)
    Returns {"ok": True, "filename": "<saved>"}
    """
    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    filename = file.filename

    if not (filename.lower().endswith(".xml") or filename.lower().endswith(".json")):
        raise HTTPException(status_code=400, detail="unsupported file type (only .xml and .json allowed)")

    saved_path = DICT_DIR / filename

    try:
        with saved_path.open("wb") as f:
            f.write(await file.read())

        d = FixDictionary()
        if filename.lower().endswith(".xml"):
            d.load_quickfix_xml(saved_path, base_dir=DICT_DIR)
        else:
            d.load_json_dict(saved_path, base_dir=DICT_DIR)
    except Exception as e:
        try:
            if saved_path.exists():
                saved_path.unlink()
        except Exception:
            pass
        logger.exception("Dictionary validation failed")
        raise HTTPException(status_code=400, detail=f"dictionary validation failed: {e}")


    return JSONResponse({"status": 200, "filename": filename})


@app.post("/parse")
async def parse_endpoint(
    request: Request, 
    mode: Annotated[Literal['strict', 'lenient'], Depends(get_parse_mode)],
    dict_name: Optional[str] = None, 
    api_key: Annotated[Optional[str], Security(require_api_key)] = None
    ):
    """
    Parse a single message (or fallback to body text).
    Accepts JSON or plain text. Optional query param ?dict_name=filename to use a specific dictionary.
    """
    if not api_key and not os.getenv("DISABLE_APIKEY", False):
        print("!!! FAILING: API_KEY is missing or empty and DISABLE_APIKEY is not set.")
        raise HTTPException(status_code=401, detail="API key missing")
    
    is_strict = mode == 'strict'

    body_bytes = await request.body()
    logger.info("Incoming /parse request: %d bytes", len(body_bytes))
    messages = []
    data = None

    # Try JSON decode
    try:
        if body_bytes:
            data = json.loads(body_bytes)
    except Exception:
        data = None

    if isinstance(data, dict):
        raw = data.get("raw") or data.get("log") or data.get("message")
        if raw:
            messages.append(raw.rstrip("\r\n"))
        elif body_bytes:
            return JSONResponse({"detail": [{"loc":["body", "raw"], "msg": "field required", "type":"value_error.missing"}]}, status_code=422)
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
        # Securely construct the dictionary path and prevent directory traversal
        dict_path = os.path.join(DICT_DIR, dict_name)
        dict_path_norm = os.path.abspath(os.path.normpath(dict_path))
        dict_dir_norm = os.path.abspath(DICT_DIR)
        if not dict_path_norm.startswith(dict_dir_norm + os.sep):
            raise HTTPException(status_code=403, detail="invalid dictionary path")
        if not os.path.exists(dict_path_norm):
            raise HTTPException(status_code=404, detail="dictionary not found")
        dict_obj = FixDictionary()
        if dict_name.lower().endswith(".xml"):
            dict_obj.load_quickfix_xml(dict_path_norm)
        else:
            dict_obj.load_json_dict(dict_path_norm)
        if dict_name.lower().endswith(".xml"):
            dict_obj.load_quickfix_xml(dict_path_norm)
        else:
            dict_obj.load_json_dict(dict_path_norm)
    else:
        dict_obj = global_default_dict

    results = []
    for raw in messages:
        IN_FLIGHT.inc()
        start = time.time()
        try:
            if not is_strict:
                raw_norm = raw.replace("|", "\x01")
            else:
                raw_norm = raw
            resp = parse_fix_message(raw_norm, dict_obj=dict_obj, strict=is_strict)
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
        except ValueError as e: 
            # Catch the ValueError raised by parse_fix_message for malformed input in strict mode
            PARSE_ERRORS.inc()
            error_message_for_client = "Parsing failed. The FIX message is malformed in strict mode."
            logger.warning("Parser error: %s", str(e)) 
            if not request.url.path.endswith("/batch"):
                raise HTTPException(status_code=400, detail=error_message_for_client)
            return JSONResponse({"raw": raw, "error": error_message_for_client}, status_code=400)
        except Exception:
            PARSE_ERRORS.inc()
            generic_client_error = "An unexpected server error occurred during parsing."
            logger.exception("Internal fatal parse error") # Use logger.exception to log traceback
            if not request.url.path.endswith("/batch"):
                raise HTTPException(status_code=500, detail=generic_client_error)
            results.append({"raw": raw, "error": generic_client_error})
        finally:
            elapsed = time.time() - start
            PARSE_LATENCY.observe(elapsed)
            IN_FLIGHT.dec()

    return JSONResponse(results[0] if len(results) == 1 else results)


@app.post("/parse/batch")
async def parse_batch(
    request: Request, 
    mode: Annotated[Literal['strict', 'lenient'], Depends(get_parse_mode)], 
    dict_name: Optional[str] = None,
    api_key: Annotated[Optional[str], Security(require_api_key)] = None
    ):
    """
    Accept an array payload (Fluent Bit style) or array of strings / objects:
    - [{"raw": "..."} , {"raw": "..."}] or ["raw1","raw2"]
    Optional dict_name query param to select uploaded dictionary file.
    Returns array of parsed results.
    """

    if not api_key and not os.getenv("DISABLE_APIKEY", False):
        raise HTTPException(status_code=401, detail="API key missing")
    
    is_strict = mode == 'strict'

    body_bytes = await request.body()
    messages = []
    data = None

    try:
        data = json.loads(body_bytes) if body_bytes else None
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
    else:
        return JSONResponse({"error": "expected JSON array"}, status_code=400)

    if not messages:
        return JSONResponse({"error": "no messages found in batch"}, status_code=400)

    dict_obj = None
    if dict_name:
        dict_path = os.path.join(DICT_DIR, dict_name)
        # Normalize the resolved path and check it's within DICT_DIR
        dict_path_abs = os.path.abspath(dict_path)
        dict_dir_abs = os.path.abspath(DICT_DIR)
        if not dict_path_abs.startswith(dict_dir_abs + os.sep):
            return JSONResponse({"error": "Invalid dictionary name"}, status_code=400)
        if not os.path.exists(dict_path_abs):
            raise HTTPException(status_code=404, detail="dictionary not found")
        dict_obj = FixDictionary()
        if dict_name.lower().endswith(".xml"):
            dict_obj.load_quickfix_xml(dict_path_abs)
        else:
            dict_obj.load_json_dict(dict_path_abs)
    else:
        dict_obj = global_default_dict

    results = []
    for raw in messages:
        IN_FLIGHT.inc()
        start = time.time()
        try:
            if not is_strict:
                raw_norm = raw.replace("|", "\x01")
            else:
                raw_norm = raw
            resp = parse_fix_message(raw_norm, dict_obj=dict_obj, strict=is_strict)
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
        except ValueError as e:
            # For batch, we just log the error and append a failure result, but keep processing the batch.
            PARSE_ERRORS.inc()
            error_message_for_client = "Parsing failed. The FIX message is malformed in strict mode."
            logger.warning("Parser error: %s", str(e)) 
            if not request.url.path.endswith("/batch"):
                raise HTTPException(status_code=400, detail=error_message_for_client)
            results.append({"raw": raw, "error": error_message_for_client, "status_code": 400})
        except Exception:
            PARSE_ERRORS.inc()
            generic_client_error = "An unexpected server error occurred during parsing."
            logger.exception("Internal fatal parse error") # Use logger.exception to log traceback
            if not request.url.path.endswith("/batch"):
                raise HTTPException(status_code=500, detail=generic_client_error)
            results.append({"raw": raw, "error": generic_client_error})
        finally:
            elapsed = time.time() - start
            PARSE_LATENCY.observe(elapsed)
            IN_FLIGHT.dec()

    return JSONResponse(results)


@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@app.get("/health/liveness")
async def liveness():
    return {"status": "alive"}

@app.get("/health/readiness")
async def readiness():
    try:
        sample = "8=FIX.4.2\x019=12\x0135=0\x0110=000\x01"
        await parse_fix_message(sample, dict_obj=None, strict=False)
        return {"status": "ready"}
    except Exception as exc:
        # return 503 so orchestration can detect and restart
        raise HTTPException(status_code=503, detail=f"parser check failed: {exc}")

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