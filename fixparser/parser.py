# fixparser/parser.py
import re
from lxml import etree
from typing import Dict, Tuple, List, Any
import os

SOH = "\x01"

class FixDictionary:
    """
    Loads QuickFIX-style XML dictionary files to map tag -> name and some metadata.
    """

    def __init__(self):
        # maps tag number string -> {'name':name, 'type':type, 'enum':{value:desc}}
        self.tags = {}

    def load_quickfix_xml(self, xml_path: str):
        if not os.path.exists(xml_path):
            raise FileNotFoundError(xml_path)
        tree = etree.parse(xml_path)
        root = tree.getroot()
        for field in root.findall(".//fields/field"):
            name = field.get("name")
            tag = field.get("number")
            ftype = field.get("type")
            record = {"name": name, "type": ftype, "enum": {}}
            for val in field.findall("value"):
                rec = val.get("enum"), val.get("description") or val.get("enum")
                record["enum"][rec[0]] = rec[1]
            self.tags[tag] = record

    def tag_name(self, tag: str) -> str:
        return self.tags.get(tag, {}).get("name", f"Tag{tag}")

    def tag_enum_desc(self, tag: str, value: str) -> str:
        return self.tags.get(tag, {}).get("enum", {}).get(value)

# Basic parser
def normalize_separators(raw: str) -> str:
    # Accept pipe '|' as visual SOH too
    if '|' in raw and SOH not in raw:
        return raw.replace('|', SOH)
    return raw

def parse_fix_message(raw: str, dict_obj: FixDictionary = None) -> Dict[str, Any]:
    raw = normalize_separators(raw)
    parts = [p for p in raw.split(SOH) if p]
    parsed = {}
    errors = []
    # naive extraction
    for p in parts:
        if '=' not in p:
            errors.append(f"Malformed token (no '='): {p}")
            continue
        tag, val = p.split('=', 1)
        name = dict_obj.tag_name(tag) if dict_obj else f"Tag{tag}"
        enum_desc = dict_obj.tag_enum_desc(tag, val) if dict_obj else None
        parsed[tag] = {"name": name, "value": val, "enum": enum_desc}
    # Basic validation: must have 8,9,35,10
    for must in ["8","9","35","10"]:
        if must not in parsed:
            errors.append(f"Missing required tag {must}")
    # optionally verify BodyLength and CheckSum (not implemented full)
    return {"parsed_by_tag": parsed, "errors": errors, "raw": raw}

def flatten(parsed_by_tag: Dict[str, Dict[str,str]]) -> Dict[str, Any]:
    out = {}
    for tag, meta in parsed_by_tag.items():
        key = meta.get("name") or f"Tag{tag}"
        val = meta.get("value")
        # ensure uniqueness if duplicate names
        if key in out:
            if isinstance(out[key], list):
                out[key].append(val)
            else:
                out[key] = [out[key], val]
        else:
            out[key] = val
    return out

def human_summary(flat_json: Dict[str,Any]) -> str:
    # Coarse summary using common fields
    ts = flat_json.get("SendingTime") or flat_json.get("TransactTime") or ""
    sender = flat_json.get("SenderCompID") or ""
    target = flat_json.get("TargetCompID") or ""
    mtype = flat_json.get("MsgType") or ""
    # Map common msg types to description (partial)
    mt_map = {
        "D": "NewOrderSingle",
        "8": "ExecutionReport",
        "F": "OrderCancelRequest",
        "G": "OrderCancelReplaceRequest",
    }
    mdesc = mt_map.get(mtype, mtype)
    # business fields example
    sym = flat_json.get("Symbol") or flat_json.get("SecurityID") or ""
    side = flat_json.get("Side") or ""
    side_map = {"1":"BUY", "2":"SELL"}
    side_read = side_map.get(side, side)
    qty = flat_json.get("OrderQty") or flat_json.get("LeavesQty") or flat_json.get("OrderQtyData") or ""
    price = flat_json.get("Price") or ""
    summary = f"{ts} {sender} -> {target} {mdesc} {('('+flat_json.get('ClOrdID')+')') if flat_json.get('ClOrdID') else ''}: {sym} {side_read} {qty} @ {price}"
    return summary

def human_detail(parsed_by_tag: Dict[str,Dict[str,str]]) -> str:
    lines = []
    # stable ordering: try important tags first
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
