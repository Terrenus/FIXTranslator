from defusedxml import ElementTree as DefusedET
from typing import Dict, Any
from pathlib import Path
from typing import Union
import json

SOH = "\x01"

class UnsafePathError(ValueError):
    pass

def safe_join_and_resolve(base_dir: Union[str, Path], user_path: Union[str, Path]) -> Path:
    base = Path(base_dir).resolve()
    user_path_obj = Path(user_path)

    if user_path_obj.is_absolute():
        candidate = user_path_obj.resolve()
    else:
        candidate = (base / user_path_obj).resolve()

    try:
        candidate.relative_to(base)
    except Exception:
        raise UnsafePathError(f"requested path {user_path!r} escapes base directory")
    return candidate

class FixDictionary:
    """
    Loads QuickFIX-style XML dictionary files (and optionally JSON dicts)
    to map tag -> name and some metadata.
    """
    def __init__(self):
        self.tags: Dict[str, Dict[str, Any]] = {}
    
    def load_quickfix_xml(self, xml_path: Union[str, Path], base_dir: Union[str, Path] = "dicts"):
        base_dir = Path(base_dir)  # or wherever your dictionaries are stored
        xml_path = Path(xml_path)
        if not xml_path.is_absolute():
            candidate = (base_dir / xml_path.name).resolve()
        else:
            candidate = xml_path.resolve()
        candidate = safe_join_and_resolve(base_dir, candidate)
        if not candidate.exists():
            raise FileNotFoundError(str(candidate))
        tree = DefusedET.parse(str(candidate))
        root = tree.getroot()
        for field in root.findall(".//fields/field"):
            name = field.get("name")
            tag = field.get("number")
            ftype = field.get("type")
            record = {"name": name, "type": ftype, "enum": {}}
            for val in field.findall("value"):
                enum = val.get("enum")
                desc = val.get("description") or enum
                if enum:
                    record["enum"][enum] = desc
            self.tags[tag] = record

    def load_json_dict(self, json_path: Union[str, Path], base_dir: Union[str, Path] = "dicts"):
        base_dir = Path(base_dir)
        json_path = Path(json_path)
        if not json_path.is_absolute():
            candidate = (base_dir / json_path.name).resolve()
        else:
            candidate = json_path.resolve()
        candidate = safe_join_and_resolve(base_dir, candidate)
        if not candidate.exists():
            raise FileNotFoundError(str(candidate))
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "fields" in data:
            fields = data["fields"]
        else:
            fields = data
        for tag, meta in fields.items():
            name = meta.get("name") or meta.get("label") or f"Tag{tag}"
            ftype = meta.get("type")
            enum = meta.get("enum", {})
            self.tags[str(tag)] = {"name": name, "type": ftype, "enum": enum}

    def tag_name(self, tag: str) -> str:
        return self.tags.get(tag, {}).get("name", f"Tag{tag}")

    def tag_enum_desc(self, tag: str, value: str) -> str:
        return self.tags.get(tag, {}).get("enum", {}).get(value)


def normalize_separators(raw: str) -> str:
    if '|' in raw and SOH not in raw:
        return raw.replace('|', SOH)
    return raw

def parse_fix_message(raw: str, dict_obj: FixDictionary = None) -> Dict[str, Any]:
    raw = normalize_separators(raw)
    parts = [p for p in raw.split(SOH) if p]
    parsed = {}
    errors = []
    for p in parts:
        if '=' not in p:
            errors.append(f"Malformed token (no '='): {p}")
            continue
        tag, val = p.split('=', 1)
        name = dict_obj.tag_name(tag) if dict_obj else f"Tag{tag}"
        enum_desc = dict_obj.tag_enum_desc(tag, val) if dict_obj else None
        parsed[tag] = {"name": name, "value": val, "enum": enum_desc}

    # Basic validation
    for must in ["8", "9", "35", "10"]:
        if must not in parsed:
            errors.append(f"Missing required tag {must}")

    return {"parsed_by_tag": parsed, "errors": errors, "raw": raw}

def flatten(parsed_by_tag: Dict[str, Dict[str,str]]) -> Dict[str, Any]:
    out = {}
    for tag, meta in parsed_by_tag.items():
        key = meta.get("name") or f"Tag{tag}"
        val = meta.get("value")
        if key in out:
            if isinstance(out[key], list):
                out[key].append(val)
            else:
                out[key] = [out[key], val]
        else:
            out[key] = val
    return out

def human_summary(flat_json: Dict[str,Any]) -> str:
    ts = flat_json.get("SendingTime") or flat_json.get("TransactTime") or ""
    sender = flat_json.get("SenderCompID") or ""
    target = flat_json.get("TargetCompID") or ""
    mtype = flat_json.get("MsgType") or ""
    mt_map = {"D": "NewOrderSingle", "8": "ExecutionReport", "F": "OrderCancelRequest", "G": "OrderCancelReplaceRequest"}
    mdesc = mt_map.get(mtype, mtype)
    sym = flat_json.get("Symbol") or flat_json.get("SecurityID") or ""
    side = flat_json.get("Side") or ""
    side_map = {"1":"BUY", "2":"SELL"}
    side_read = side_map.get(side, side)
    qty = flat_json.get("OrderQty") or flat_json.get("LeavesQty") or ""
    price = flat_json.get("Price") or ""
    summary = f"{ts} {sender} -> {target} {mdesc} {('('+flat_json.get('ClOrdID')+')') if flat_json.get('ClOrdID') else ''}: {sym} {side_read} {qty} @ {price}"
    return summary

def human_detail(parsed_by_tag: Dict[str,Dict[str,str]]) -> str:
    lines = []
    priority = ["8","35","49","56","34","52","11","17","55","54","38","40","44","39","150","10"]
    for t in priority:
        if t in parsed_by_tag:
            meta = parsed_by_tag[t]
            line = f"{meta['name']}({t}) = {meta['value']}"
            if meta.get("enum"):
                line += f"  // {meta['enum']}"
            lines.append(line)
    for t, meta in parsed_by_tag.items():
        if t in priority:
            continue
        lines.append(f"{meta['name']}({t}) = {meta['value']}")
    return "\n".join(lines)
