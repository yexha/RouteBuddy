"""
Test route optimization against realistic Okotoks address list (from real clipboard photo).
Run: python tests/test_route_optimizer.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.route_optimizer import Stop, optimize, _haversine, parse_stops, _right_side_sweep

# Real addresses from clipboard photo, in original (non-geographic) order
SAMPLE_STOPS_RAW = [
    ("Gusdal, Alix",         "119 Drake Landing Heath, Okotoks, AB",  ""),
    ("Crebo, Val",           "218 Drake Landing Lane, Okotoks, AB",   "gate"),
    ("TMS Yardcare",         "139 Sandstone Court, Okotoks, AB",      ""),
    ("Downes, Kelly",        "515 Sandstone Point, Okotoks, AB",      "WAIT"),
    ("Rousson, Leanne",      "8 Cimarron Crescent, Okotoks, AB",      ""),
    ("TMS Yardcare",         "3 Cimarron Estates Link, Okotoks, AB",  ""),
    ("Anderson, Brenda",     "16 Cimarron Estates Way, Okotoks, AB",  "Gate"),
    ("Goossen, Deb",         "7 Cimarron Park Crescent, Okotoks, AB", ""),
    ("Johnston, Joyce",      "124 Woodbend Way, Okotoks, AB",         ""),
    ("Johnston, Bev/Barry",  "165 Woodbend Way, Okotoks, AB",         ""),
    ("Foley, Kevin",         "167 Woodbend Way, Okotoks, AB",         ""),
    ("Brophy, Lorna/Tim",    "174 Woodbend Way, Okotoks, AB",         ""),
    ("Oncescu, Rick",        "109 Woodburn Crescent, Okotoks, AB",    ""),
    ("Stoddard, Bruce",      "160 Woodburn Crescent, Okotoks, AB",    ""),
    ("Despotopoulos, Catina","161 Woodburn Crescent, Okotoks, AB",    ""),
    ("Energy Auctions",      "117 Woodglen Place, Okotoks, AB",       ""),
    ("Pittman, Dennis",      "175 Woodhaven Drive, Okotoks, AB",      ""),
    ("Berberich, Gordon",    "208 Woodhaven Drive, Okotoks, AB",      ""),
    ("Davidson, Barb",       "216 Woodhaven Drive, Okotoks, AB",      ""),
    ("MacLean, Garrett",     "222 Woodhaven Drive, Okotoks, AB",      ""),
    ("Jenkins, Emma",        "234 Woodhaven Drive, Okotoks, AB",      ""),
    ("Ransome, Mike",        "246 Woodhaven Drive, Okotoks, AB",      ""),
    ("Frank, Brian",         "208 Westmount Crescent, Okotoks, AB",   ""),
    ("Harding, Scott",       "20 Westmount Road, Okotoks, AB",        ""),
    ("TMS Yardcare",         "19 Westridge Green, Okotoks, AB",       ""),
    ("Greenlaw, LauraLee",   "3 Crystal Shores Court, Okotoks, AB",   ""),
]

# Approximate coords (manually looked up) — avoid live Nominatim in tests
COORDS = {
    "119 Drake Landing Heath, Okotoks, AB":  (50.7235, -113.9422),
    "218 Drake Landing Lane, Okotoks, AB":   (50.7231, -113.9418),
    "139 Sandstone Court, Okotoks, AB":      (50.7258, -113.9553),
    "515 Sandstone Point, Okotoks, AB":      (50.7265, -113.9561),
    "8 Cimarron Crescent, Okotoks, AB":      (50.7176, -113.9812),
    "3 Cimarron Estates Link, Okotoks, AB":  (50.7182, -113.9798),
    "16 Cimarron Estates Way, Okotoks, AB":  (50.7185, -113.9801),
    "7 Cimarron Park Crescent, Okotoks, AB": (50.7179, -113.9816),
    "124 Woodbend Way, Okotoks, AB":         (50.7196, -113.9776),
    "165 Woodbend Way, Okotoks, AB":         (50.7202, -113.9781),
    "167 Woodbend Way, Okotoks, AB":         (50.7203, -113.9782),
    "174 Woodbend Way, Okotoks, AB":         (50.7205, -113.9785),
    "109 Woodburn Crescent, Okotoks, AB":    (50.7212, -113.9769),
    "160 Woodburn Crescent, Okotoks, AB":    (50.7218, -113.9773),
    "161 Woodburn Crescent, Okotoks, AB":    (50.7219, -113.9774),
    "117 Woodglen Place, Okotoks, AB":       (50.7208, -113.9756),
    "175 Woodhaven Drive, Okotoks, AB":      (50.7224, -113.9741),
    "208 Woodhaven Drive, Okotoks, AB":      (50.7227, -113.9745),
    "216 Woodhaven Drive, Okotoks, AB":      (50.7228, -113.9746),
    "222 Woodhaven Drive, Okotoks, AB":      (50.7229, -113.9748),
    "234 Woodhaven Drive, Okotoks, AB":      (50.7231, -113.9750),
    "246 Woodhaven Drive, Okotoks, AB":      (50.7233, -113.9752),
    "208 Westmount Crescent, Okotoks, AB":   (50.7155, -113.9834),
    "20 Westmount Road, Okotoks, AB":        (50.7148, -113.9829),
    "19 Westridge Green, Okotoks, AB":       (50.7142, -113.9841),
    "3 Crystal Shores Court, Okotoks, AB":   (50.7261, -113.9601),
}


def _make_stops(inject_coords=True) -> list[Stop]:
    stops = []
    for i, (name, addr, notes) in enumerate(SAMPLE_STOPS_RAW):
        s = Stop(index=i, raw_address=addr, customer_name=name, notes=notes)
        if inject_coords and addr in COORDS:
            s.lat, s.lng = COORDS[addr]
        stops.append(s)
    return stops


def total_distance(stop_list: list[Stop]) -> float:
    total = 0.0
    for i in range(len(stop_list) - 1):
        a, b = stop_list[i], stop_list[i + 1]
        if a.lat and b.lat:
            total += _haversine(a.lat, a.lng, b.lat, b.lng)
    return total


# ── Tests ────────────────────────────────────────────────────────────────────

def test_parse_house_numbers():
    stops = _make_stops(inject_coords=False)
    parse_stops(stops)
    woodhaven = [s for s in stops if s.street_name and "WOODHAVEN" in s.street_name]
    assert len(woodhaven) == 6, f"Expected 6 Woodhaven stops, got {len(woodhaven)}"
    nums = sorted(s.house_number for s in woodhaven)
    assert nums == [175, 208, 216, 222, 234, 246], f"Got: {nums}"
    print(f"  Woodhaven house numbers: {nums}")


def test_haversine_okotoks_to_calgary():
    d = _haversine(50.7258, -113.9751, 51.0447, -114.0719)
    assert 35 < d < 45, f"Expected ~38km, got {d:.1f}km"


def test_distance_reduction():
    stops = _make_stops()
    geocoded_original = [s for s in stops if s.lat is not None]
    original_dist = total_distance(geocoded_original)

    optimized, failed = optimize(stops)
    optimized_dist = total_distance(optimized)

    reduction_pct = (1 - optimized_dist / original_dist) * 100

    print(f"\n  Original total:  {original_dist:.2f} km")
    print(f"  Optimized total: {optimized_dist:.2f} km")
    print(f"  Reduction:       {reduction_pct:.1f}%")
    print(f"  Failed geocodes: {len(failed)}")

    print("\n  ORIGINAL ORDER:")
    for i, s in enumerate(geocoded_original, 1):
        print(f"    {i:2}. {s.raw_address}")

    print("\n  OPTIMIZED ORDER:")
    for i, s in enumerate(optimized, 1):
        print(f"    {i:2}. {s.raw_address}")

    assert optimized_dist < original_dist, f"Optimized ({optimized_dist:.2f}) should be < original ({original_dist:.2f})"
    assert len(failed) == 0, f"All stops have coords — none should fail: {failed}"


def test_right_side_sweep_woodhaven():
    """
    Woodhaven Drive: 175 (odd), 208/216/222/234/246 (even).
    Entering from the low end (175), the sweep should:
      Pass 1 — evens ascending: 208, 216, 222, 234, 246
      Pass 2 — odds descending: 175
    Or if entering from high end, reversed.
    Either way, no alternating odd/even zigzag.
    """
    woodhaven_data = [
        ("Pittman",    "175 Woodhaven Drive, Okotoks, AB", (50.7224, -113.9741)),
        ("Berberich",  "208 Woodhaven Drive, Okotoks, AB", (50.7227, -113.9745)),
        ("Davidson",   "216 Woodhaven Drive, Okotoks, AB", (50.7228, -113.9746)),
        ("MacLean",    "222 Woodhaven Drive, Okotoks, AB", (50.7229, -113.9748)),
        ("Jenkins",    "234 Woodhaven Drive, Okotoks, AB", (50.7231, -113.9750)),
        ("Ransome",    "246 Woodhaven Drive, Okotoks, AB", (50.7233, -113.9752)),
    ]
    group = []
    for i, (name, addr, coords) in enumerate(woodhaven_data):
        s = Stop(index=i, raw_address=addr, customer_name=name, notes="")
        s.lat, s.lng = coords
        group.append(s)
    parse_stops(group)

    approach = Stop(index=-1, raw_address="", customer_name="", notes="")
    approach.lat, approach.lng = (50.7220, -113.9738)  # approaching from south (low number end)

    swept = _right_side_sweep(group, approach)
    nums = [s.house_number for s in swept]
    print(f"\n  Woodhaven sweep result: {nums}")

    # Should NOT alternate odd/even: no pattern like [208, 175, 216, 208...]
    # Acceptable: all evens then odd, or odd then all evens, or simple ascending/descending
    # Check no zigzag: parity should not alternate more than once
    parities = [n % 2 for n in nums]
    transitions = sum(1 for i in range(len(parities) - 1) if parities[i] != parities[i+1])
    assert transitions <= 1, f"Too many parity transitions (zigzag): {nums} -> parities {parities}"


def test_cul_de_sac_single_pass():
    """Crystal Shores Court (3 stops) should be done in one simple pass — no splitting."""
    court_stops = []
    for i, n in enumerate([3, 7, 11]):
        s = Stop(index=i, raw_address=f"{n} Crystal Shores Court, Okotoks, AB", customer_name="", notes="")
        s.lat = 50.7261 + i * 0.0001
        s.lng = -113.9601
        court_stops.append(s)
    parse_stops(court_stops)
    swept = _right_side_sweep(court_stops, None)
    nums = [s.house_number for s in swept]
    print(f"\n  Cul-de-sac sweep: {nums}")
    # Small group — should be simple ascending or descending
    assert nums == sorted(nums) or nums == sorted(nums, reverse=True), f"Expected monotone, got {nums}"


def test_done_stops_included():
    """is_done stops should still appear in optimized output (for verification)."""
    stops = _make_stops()
    stops[0].is_done = True  # mark first stop as done
    optimized, failed = optimize(stops)
    done_in_result = [s for s in optimized if s.is_done]
    assert len(done_in_result) == 1, f"Expected 1 done stop in output, got {len(done_in_result)}"
    print(f"\n  Done stop correctly included: {done_in_result[0].raw_address}")


if __name__ == "__main__":
    print("=" * 65)
    print("RouteBuddy Route Optimizer — Test Suite")
    print("=" * 65)

    tests = [
        ("Address parsing",             test_parse_house_numbers),
        ("Haversine distance",           test_haversine_okotoks_to_calgary),
        ("Route distance reduction",     test_distance_reduction),
        ("Right-side sweep (Woodhaven)", test_right_side_sweep_woodhaven),
        ("Cul-de-sac single pass",       test_cul_de_sac_single_pass),
        ("Done stops included",          test_done_stops_included),
    ]

    passed = 0
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            fn()
            print(f"  ✓ PASSED")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}")
        except Exception as e:
            import traceback
            print(f"  ✗ ERROR: {e}")
            traceback.print_exc()

    print(f"\n{'=' * 65}")
    print(f"Results: {passed}/{len(tests)} passed")
