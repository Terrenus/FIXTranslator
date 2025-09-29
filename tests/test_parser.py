from fixparser import parser

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
