import pytest
from defusedxml import ElementTree as DefusedET
import io

def test_xxe_disallowed():
    xxe = b"""<?xml version="1.0"?>
    <!DOCTYPE root [
      <!ENTITY xxe SYSTEM "file:///etc/passwd">
    ]>
    <root>&xxe;</root>"""
    with pytest.raises(Exception):
        DefusedET.parse(io.BytesIO(xxe))