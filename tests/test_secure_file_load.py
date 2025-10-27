import pytest 
from fixparser.parser import safe_join_and_resolve, UnsafePathError

def test_safe_join_allows_inside(tmp_path):
    base = tmp_path / "dicts"
    base.mkdir()
    p = base / "good.xml"
    p.write_text("<root></root>")
    res = safe_join_and_resolve(base, "good.xml")
    assert res == p.resolve()

def test_safe_join_blocks_traversal(tmp_path):
    base = tmp_path / "dicts"
    base.mkdir()
    with pytest.raises(UnsafePathError):
        safe_join_and_resolve(base, "../etc/passwd")