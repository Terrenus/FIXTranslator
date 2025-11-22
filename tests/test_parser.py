from fixparser import parser
from fixparser.parser import FixDictionary, human_summary, human_detail, flatten, parse_fix_message
import pytest
from unittest.mock import MagicMock

SAMPLE = "8=FIX.4.4|9=176|35=D|49=CLIENT12|56=BROKER03|34=215|52=20250927-12:30:05.123|11=12345|55=EUR/USD|54=1|38=1000000|40=2|44=1.1850|60=20250927-12:30:05|10=062|"

def test_parse_fix_message_basic():
    # returns dict with parsed_by_tag
    resp = parser.parse_fix_message(SAMPLE)
    assert "parsed_by_tag" in resp
    parsed = resp["parsed_by_tag"]
    # Ensure mandatory tags parsed
    assert "35" in parsed and parsed["35"]["value"] == "D"
    assert "49" in parsed and parsed["49"]["value"] == "CLIENT12"

def test_flatten_and_human_detail():
    resp = parser.parse_fix_message(SAMPLE)
    flat = parser.flatten(resp["parsed_by_tag"])
    # When no dictionary loaded the flatten will use TagX names
    # Confirm Tag35 (MsgType) is present
    assert any(k.endswith("35") or k == "Tag35" or "35" in k for k in [*flat.keys(),])
    detail = parser.human_detail(resp["parsed_by_tag"])
    assert "35" in detail  # ensure human_detail lists the MsgType tag formatted

def test_fixdictionary_load_json_failure(tmp_path):
    invalid_json_file = tmp_path / "invalid.json"
    invalid_json_file.write_text("{'not_valid_json':}") 
    
    d = FixDictionary()
    
    with pytest.raises(Exception): 
        d.load_json_dict(invalid_json_file)

def test_human_summary_missing_msgtype(monkeypatch):
    mock_dict = MagicMock(spec=FixDictionary)
    mock_dict.tag_name.side_effect = lambda t: {
        '8': 'BeginString', 
        '9': 'BodyLength', 
        '10': 'CheckSum', 
        '11': 'ClOrdID', 
        '38': 'OrderQty'
    }.get(t, f"Tag{t}")
    mock_dict.tag_enum_desc.return_value = None
    raw_message = "8=FIX.4.2|9=12|11=Client_ID_123|38=100|10=000|"
    parsed_result = parse_fix_message(raw_message.replace("|", "\x01"), dict_obj=mock_dict, strict=False)

    flat = flatten(parsed_result["parsed_by_tag"])
    summary = human_summary(flat)
    
    assert "-> |" in summary
    assert "ClOrdID=Client_ID_123" in summary 
    assert "Qty=100" in summary
    assert summary.strip() == '-> |(ClOrdID=Client_ID_123): Qty=100'

def test_human_detail_empty_input():
    parsed_by_tag = {}
    
    detail = human_detail(parsed_by_tag)
    
    # Should gracefully return an empty string or a default header
    assert detail == ""