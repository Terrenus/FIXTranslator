import os
import json
import uuid
import time
from dotenv import load_dotenv
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form, Response, HTTPException, Security, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from typing import Optional, Annotated, Literal
from .logger_config import logger
from .exporters import EXPORT_ENABLED, export_event
from . import parser
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette import status

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=env_path)

def get_parse_limit() -> str:
    return os.getenv("PARSE_LIMIT", "200/minute")

def get_upload_limit() -> str:
    return os.getenv("UPLOAD_LIMIT", "20/hour")

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="FIX Parser Demo")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

API_KEY_HEADER = APIKeyHeader(name="x-api-key", auto_error=False)

def get_max_body_size() -> int:
    env_val = os.getenv("MAX_BODY_SIZE")
    if env_val:
        try:
            # Try to convert the env variable to an integer
            return int(env_val)
        except ValueError:
            logger.error("Invalid MAX_BODY_SIZE environment variable. Defaulting to 1MB.")
            # Fallback if the environment variable is present but not a valid number
            return 1 * 1024 * 1024
    
    return 1 * 1024 * 1024

def get_allowed_origins() -> list:
    """Returns allowed origins based on DEV environment variable."""
    return ["*"] if os.getenv("DEV") else ["https://your-company.example"]

ALLOWED_ORIGINS = get_allowed_origins()

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        max_size = get_max_body_size()
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                if int(content_length) > max_size:
                    return JSONResponse(
                        {"detail": f"Request body size exceeds the maximum limit of {max_size} bytes."},
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    )
            except ValueError:
                pass

        original_receive = request._receive
        bytes_read = 0
        
        async def limited_receive() -> dict:
            nonlocal bytes_read
            
            message = await original_receive()
            
            if message["type"] == "http.request" and "body" in message:
                chunk_size = len(message.get("body", b""))
                bytes_read += chunk_size
                
                if bytes_read > max_size:
                    logger.warning("Request body size exceeded while streaming.", extra={ # TO TEST
                        "max_size": max_size,
                        "bytes_read": bytes_read,
                        "request_id": getattr(request.state, "request_id", "unknown") # TO TEST
                    })

                    raise RuntimeError("Request body size limit exceeded during stream.") # TO TEST

            return message

        request._receive = limited_receive
        
        try:
            return await call_next(request)
        except RuntimeError as e:
            if "size limit exceeded" in str(e): # TO TEST
                return JSONResponse( # TO TEST
                    {"detail": f"Request body size exceeds the maximum limit of {max_size} bytes."}, # TO TEST
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE, # TO TEST
                )
            raise # TO TEST

app.add_middleware(MaxBodySizeMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_id_and_log_access(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    logger.info("Request started", extra={
        "request_id": request_id, 
        "path": request.url.path,
        "method": request.method,
        "client_ip": get_remote_address(request)
    })

    response = await call_next(request)

    logger.info("Request finished", extra={
        "request_id": request_id, 
        "status_code": response.status_code
    })
    return response
        

PARSES_TOTAL = Counter("fixparser_parses_total", "Total number of FIX parse attempts")
PARSE_ERRORS = Counter("fixparser_parse_errors_total", "Total number of FIX parse errors")
PARSE_LATENCY = Histogram("fixparser_parse_latency_seconds", "Histogram of FIX parse latencies")
IN_FLIGHT = Gauge("fixparser_inflight_requests", "Number of in-flight parse requests")

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

def _get_valid_api_keys() -> set:
    keys = os.getenv("API_KEYS", "")
    if not keys:
        return set()
    return {k.strip() for k in keys.split(",") if k.strip()}

def require_api_key(api_key: Optional[str] = Depends(API_KEY_HEADER)) -> Optional[str]:
    allowed = _get_valid_api_keys()
    if os.getenv("DISABLE_APIKEY_CHECK", "0") == "1":
        return
    if allowed:
        if not api_key or api_key not in allowed:
            raise HTTPException(status_code=401, detail="Invalid API key")
        # SUCCESS: Return the API key string
        return api_key
    
    # Default secure fallback if no key is set and no bypass is active
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
global_default_dict = parser.FixDictionary()
# Try to load known dicts but don't fail startup
for fname in os.listdir(DICT_DIR) if os.path.isdir(DICT_DIR) else []:
    fpath = os.path.join(DICT_DIR, fname)
    try:
        if fname.lower().endswith(".xml"):
            global_default_dict.load_quickfix_xml(fpath, base_dir=DICT_DIR) 
            logger.info("Loaded dictionary at startup", extra={"dict": fname})
        elif fname.lower().endswith(".json"):
            global_default_dict.load_json_dict(fpath, base_dir=DICT_DIR) 
            logger.info("Loaded JSON dictionary at startup", extra={"dict": fname})
    except Exception as e:
            logger.warning("dict load error",  extra={"dict": fname, "error": str(e)})

@app.post("/upload_dict")
@limiter.limit(get_upload_limit)
async def upload_dict(
    request: Request, 
    file: UploadFile = File(...), 
    update: bool = Form(False)):
    """
    Upload a dictionary file (QuickFIX XML or JSON).
    - file: upload the XML/JSON file
    - name: optional filename to save as (must end with .xml or .json)
    Returns {"ok": True, "filename": "<saved>"}
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    filename = os.path.basename(file.filename)

    if not (filename.lower().endswith(".xml") or filename.lower().endswith(".json")):
        logger.warning("Upload attempt with unsupported file type", extra={
            "request_id": request_id,
            "upload_filename": filename,
            "client_ip": get_remote_address(request)
        })
        raise HTTPException(status_code=400, detail="unsupported file type (only .xml and .json allowed)")

    saved_path = DICT_DIR / filename
    temp_path = saved_path.with_suffix(saved_path.suffix + ".tmp")

    if saved_path.exists():
        if update:
            # Overwrite allowed: Log a warning and proceed with save
            logger.warning("Dictionary upload file already exists. Overwriting permitted via 'update=true'.", extra={
            "request_id": request_id,
            "upload_filename": filename,
        })
        else:
            logger.error("Upload blocked: Dictionary file already exists and 'update' flag is false.", extra={
            "request_id": request_id,
            "upload_filename": filename,
        })
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, # 409 Conflict: resource already exists
                detail=f"Dictionary file '{filename}' already exists. Use 'update=true' to overwrite."
            )

    try:
        with temp_path.open("wb") as f:
            f.write(await file.read())

        d = parser.FixDictionary()
        if filename.lower().endswith(".xml"):
            d.load_quickfix_xml(temp_path, base_dir=DICT_DIR)
        else:
            d.load_json_dict(temp_path, base_dir=DICT_DIR)

        if not d.tags:
            raise ValueError("Dictionary loaded but contains no valid FIX messages or fields.")
            
        os.rename(temp_path, saved_path)

    except Exception as e:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception as unlink_e:
            logger.error("Failed to unlink invalid dictionary post-error", extra={
                "request_id": request_id,
                "upload_filename": filename,
                "unlink_error": str(unlink_e)
            })
            
        logger.exception("Dictionary validation failed on upload", extra={
            "request_id": request_id,
            "upload_filename": filename,
            "error": str(e)
        })
        raise HTTPException(status_code=400, detail=f"dictionary validation failed: {e}")

    logger.info("Successfully uploaded and validated dictionary", extra={
        "request_id": request_id,
        "upload_filename": filename
    })
    
    return JSONResponse(
        {"status": "created", "upload_filename": filename}, 
        status_code=status.HTTP_201_CREATED
    )


@app.post("/parse")
@limiter.limit(get_parse_limit)
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
    if not api_key and not os.getenv("DISABLE_APIKEY_CHECK", False):
        raise HTTPException(status_code=401, detail="API key missing")
    
    request_id = request.state.request_id
    is_strict = mode == 'strict'
    body_bytes = await request.body()
    logger.info("Incoming /parse request", extra={"bytes_received": len(body_bytes), "request_id": request_id})
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
        dict_obj = parser.FixDictionary()
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
            resp = parser.parse_fix_message(raw_norm, dict_obj=dict_obj, strict=is_strict)
            flat = parser.flatten(resp["parsed_by_tag"])
            results.append({
                "request_id": request_id,
                "raw": raw_norm.replace("\x01", "|"),
                "parsed": resp["parsed_by_tag"],
                "flat": flat,
                "summary": parser.human_summary(flat),
                "detail": parser.human_detail(resp["parsed_by_tag"]),
                "errors": resp["errors"]
            })
            if EXPORT_ENABLED:
                export_event({
                    "request_id": request_id,
                    "summary": parser.human_summary(flat),
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
            logger.warning("Parser error (strict mode)", extra={
                "error_type": "ValueError", 
                "exception_detail": str(e),
                "request_id": request_id,
                "raw_message_sample": raw[:50]
            }) 
            if not request.url.path.endswith("/batch"):
                raise HTTPException(status_code=400, detail=error_message_for_client)
            return JSONResponse({"raw": raw, "error": error_message_for_client}, status_code=400)
        except Exception:
            PARSE_ERRORS.inc()
            generic_client_error = "An unexpected server error occurred during parsing."
            logger.exception("Internal fatal parse error", extra={"request_id": request_id, "raw_message_sample": raw[:50]}) # Use logger.exception to log traceback
            if not request.url.path.endswith("/batch"):
                raise HTTPException(status_code=500, detail=generic_client_error)
            results.append({"raw": raw, "error": generic_client_error})
        finally:
            elapsed = time.time() - start
            PARSE_LATENCY.observe(elapsed)
            IN_FLIGHT.dec()

    return JSONResponse(results[0] if len(results) == 1 else results)


@app.post("/parse/batch")
@limiter.limit(get_parse_limit)
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

    if not api_key and not os.getenv("DISABLE_APIKEY_CHECK", False):
        raise HTTPException(status_code=401, detail="API key missing")
    
    request_id = request.state.request_id
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
        dict_path_abs = os.path.abspath(dict_path)
        dict_dir_abs = os.path.abspath(DICT_DIR)
        if not dict_path_abs.startswith(dict_dir_abs + os.sep):
            return JSONResponse({"error": "Invalid dictionary name"}, status_code=400)
        if not os.path.exists(dict_path_abs):
            raise HTTPException(status_code=404, detail="dictionary not found")
        dict_obj = parser.FixDictionary()
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
            resp = parser.parse_fix_message(raw_norm, dict_obj=dict_obj, strict=is_strict)
            flat = parser.flatten(resp["parsed_by_tag"])
            results.append({
                "request_id": request_id,
                "raw": raw_norm.replace("\x01", "|"),
                "parsed": resp["parsed_by_tag"],
                "flat": flat,
                "summary": parser.human_summary(flat),
                "detail": parser.human_detail(resp["parsed_by_tag"]),
                "errors": resp["errors"]
            })
            if EXPORT_ENABLED:
                export_event({
                    "request_id": request_id,
                    "summary": parser.human_summary(flat),
                    "flat": flat,
                    "raw": raw_norm.replace("\x01", "|"),
                    "errors": resp["errors"],
                })
            PARSES_TOTAL.inc()
            if resp.get("errors"):
                PARSE_ERRORS.inc(len(resp.get("errors", [])))
        except ValueError as e:
            PARSE_ERRORS.inc()
            error_message_for_client = "Parsing failed. The FIX message is malformed in strict mode."
            logger.warning("Parser error (strict mode)", extra={
                "error_type": "ValueError", 
                "exception_detail": str(e),
                "request_id": request_id,
                "raw_message_sample": raw[:50]
            })
            if not request.url.path.endswith("/batch"):
                raise HTTPException(status_code=400, detail=error_message_for_client)
            results.append({"raw": raw, "error": error_message_for_client, "status_code": 400})
        except Exception:
            PARSE_ERRORS.inc()
            generic_client_error = "An unexpected server error occurred during parsing."
            logger.exception("Internal fatal parse error", extra={"request_id": request_id, "raw_message_sample": raw[:50]}) # Use logger.exception to log traceback
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
        parser.parse_fix_message(sample, dict_obj=None, strict=False)
        return {"status": "ready"}
    except Exception as exc:
        # return 503 so orchestration can detect and restart
        raise HTTPException(status_code=503, detail=f"parser check failed: {exc}")

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")