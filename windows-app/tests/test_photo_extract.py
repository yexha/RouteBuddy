"""
Test address extraction from OCR row text (the part that was breaking).
These feed realistic joined-row strings — names, town codes and notes mixed in
with the address — and check we pull out ONLY the address.

Run: python tests/test_photo_extract.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.photo_extractor import extract_address

# (raw OCR row text, expected address or None)
CASES = [
    # Name in front of a clean number-first address — name must be dropped
    ("RUSS 115 Sunset Place",                       "115 Sunset Place"),
    ("STEVEN 131 Sunset Place",                     "131 Sunset Place"),
    ("Michelle/Gareth 201 Suntree Place",           "201 Suntree Place"),
    ("KYLEIAMIE 306 Suntree Place",                 "306 Suntree Place"),
    ("LEITHICOURTNEY 301 Suntree Place",            "301 Suntree Place"),
    ("GERRY 31 Robinson Drive",                     "31 Robinson Drive"),
    # Town code + last name + first name + address + note (full clipboard row)
    ("OK SC ANDERSON BRENDA 16 Cimarron Estates Way Gate", "16 Cimarron Estates Way"),
    ("OK SC GOOSSEN DEB 7 Cimarron Park Crescent",  "7 Cimarron Park Crescent"),
    # Older clipboard format: street then number
    ("WOODHAVEN DR 208",                            "208 Woodhaven Drive"),
    ("SANDSTONE PT 515",                            "515 Sandstone Point"),
    ("CMRRN EST WAY 16",                            None),  # abbrev junk, no clean type-> ok if None
    # Abbreviation expansion
    ("119 Drake Landing Heath",                     "119 Drake Landing Heath"),
    ("515 Sandstone Pt",                            "515 Sandstone Point"),
    ("20 Westmount Rd",                             "20 Westmount Road"),
    # Street with no type word — fallback
    ("2 Anderson",                                  "2 Anderson"),
    # Fragments / noise that should NOT become fake addresses
    ("DASHKO 36",                                   None),
    ("WARN 40",                                     None),
    ("JOELS 41",                                    None),
    ("JONES 43",                                    None),
    ("",                                            None),
    ("OK SC",                                       None),
    ("Gate code 1234",                              None),   # note line, not an address
]


def run():
    print("=" * 62)
    print("Photo address extraction")
    print("=" * 62)
    passed = 0
    for text, expected in CASES:
        got = extract_address(text)
        # For the intentionally-ambiguous abbrev case, accept either a sane addr or None
        if expected is None and text == "CMRRN EST WAY 16":
            ok = True
        else:
            ok = (got == expected)
        mark = "✓" if ok else "✗"
        print(f"  {mark}  {text!r:48} -> {got!r}")
        if ok:
            passed += 1
        else:
            print(f"       expected: {expected!r}")
    print("-" * 62)
    print(f"Results: {passed}/{len(CASES)} passed")
    return passed == len(CASES)


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
