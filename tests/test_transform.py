# tests/test_transform.py
from etl.transform import normalize_priorities

def test_urgent_maps_to_p1():
    assert normalize_priorities_single("URGENT") == "P1-Critical"

def test_unknown_defaults_to_p3():
    assert normalize_priorities_single("BANANA") == "P3-Medium"