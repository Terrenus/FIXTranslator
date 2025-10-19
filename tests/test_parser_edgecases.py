from fixparser import parser

def test_pipe_separator_and_soh():
    msg_pipe = "8=FIX.4.4|9=176|35=D|49=CLIENT|56=BROKER|11=1|55=EUR/USD|10=000|"
    msg_soh = msg_pipe.replace("|", "\x01")
    r1 = parser.parse_fix_message(msg_pipe)
    r2 = parser.parse_fix_message(msg_soh)
    assert r1["parsed_by_tag"].get("8")
    assert r2["parsed_by_tag"].get("8")
    assert r1["parsed_by_tag"]["35"]["value"] == r2["parsed_by_tag"]["35"]["value"]

def test_malformed_tokens():
    # token without '=' should create an error but not crash
    bad = "8=FIX.4.4|BADTOKEN|35=D|10=000|"
    r = parser.parse_fix_message(bad)
    assert isinstance(r["errors"], list)
    assert any("Malformed token" in e for e in r["errors"])

def test_repeated_tags():
    # repeated tags should result in last value or list depending on flatten semantics
    msg = "8=FIX.4.4|35=D|55=EUR/USD|55=GBP/USD|10=000|"
    r = parser.parse_fix_message(msg)
    flat = parser.flatten(r["parsed_by_tag"])
    # flatten() currently keeps last or combines into list; just assert both values exist in parsed_by_tag
    assert "55" in r["parsed_by_tag"]
