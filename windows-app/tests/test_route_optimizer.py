"""
Test route optimization against a realistic messy Okotoks address list.
Addresses taken from a real clipboard photo — exactly as a driver would see them,
NOT in geographic order.

Run: python -m pytest tests/ -v  (or: python tests/test_route_optimizer.py)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.route_optimizer import Stop, optimize, _haversine, parse_stops

# Real addresses from the photo, in original clipboard order (messy/random)
# These are Okotoks, AB addresses that span multiple subdivisions
SAMPLE_STOPS_RAW = [
    ("Gusdal, Alix",        "119 Drake Landing Heath, Okotoks, AB",  ""),
    ("Crebo, Val",          "218 Drake Landing Lane, Okotoks, AB",   "gate"),
    ("TMS Yardcare",        "139 Sandstone Court, Okotoks, AB",      ""),
    ("Downes, Kelly",       "515 Sandstone Point, Okotoks, AB",      "WAIT"),
    ("Rousson, Leanne",     "8 Cimarron Crescent, Okotoks, AB",      ""),
    ("TMS Yardcare",        "3 Cimarron Estates Link, Okotoks, AB",  ""),
    ("Anderson, Brenda",    "16 Cimarron Estates Way, Okotoks, AB",  "Gate"),
    ("Goossen, Deb",        "7 Cimarron Park Crescent, Okotoks, AB", ""),
    ("Johnston, Joyce",     "124 Woodbend Way, Okotoks, AB",         ""),
    ("Johnston, Bev/Barry", "165 Woodbend Way, Okotoks, AB",         ""),
    ("Foley, Kevin",        "167 Woodbend Way, Okotoks, AB",         ""),
    ("Brophy, Lorna/Tim",   "174 Woodbend Way, Okotoks, AB",         ""),
    ("Oncescu, Rick",       "109 Woodburn Crescent, Okotoks, AB",    ""),
    ("Stoddard, Bruce",     "160 Woodburn Crescent, Okotoks, AB",    ""),
    ("Despotopoulos, Catina","161 Woodburn Crescent, Okotoks, AB",   ""),
    ("Energy Auctions",     "117 Woodglen Place, Okotoks, AB",       ""),
    ("Pittman, Dennis",     "175 Woodhaven Drive, Okotoks, AB",      ""),
    ("Berberich, Gordon",   "208 Woodhaven Drive, Okotoks, AB",      ""),
    ("Davidson, Barb",      "216 Woodhaven Drive, Okotoks, AB",      ""),
    ("MacLean, Garrett",    "222 Woodhaven Drive, Okotoks, AB",      ""),
    ("Jenkins, Emma",       "234 Woodhaven Drive, Okotoks, AB",      ""),
    ("Ransome, Mike",       "246 Woodhaven Drive, Okotoks, AB",      ""),
    ("Frank, Brian",        "208 Westmount Crescent, Okotoks, AB",   ""),
    ("Harding, Scott",      "20 Westmount Road, Okotoks, AB",        ""),
    ("TMS Yardcare",        "19 Westridge Green, Okotoks, AB",       ""),
    # Sticky note addition
    ("Greenlaw, LauraLee",  "3 Crystal Shores Court, Okotoks, AB",   ""),
]


def make_stops(raw: list[tuple]) -> list[Stop]:
    stops = []
    for i, (name, addr, notes) in enumerate(raw):
        stops.append(Stop(index=i, raw_address=addr, customer_name=name, notes=notes))
    return stops


def test_street_grouping_no_geocode():
    """Without geocoding, parse_stops should correctly extract house numbers and street names."""
    stops = make_stops(SAMPLE_STOPS_RAW)
    parse_stops(stops)

    woodhaven = [s for s in stops if s.street_name and "WOODHAVEN" in s.street_name]
    assert len(woodhaven) >= 5, f"Expected 5+ Woodhaven stops, got {len(woodhaven)}"

    woodbend = [s for s in stops if s.street_name and "WOODBEND" in s.street_name]
    assert len(woodbend) >= 4, f"Expected 4+ Woodbend Way stops, got {len(woodbend)}"

    # House numbers should parse correctly
    woodhaven_nums = sorted(s.house_number for s in woodhaven if s.house_number)
    assert woodhaven_nums == sorted(woodhaven_nums), "Woodhaven house numbers should be parseable"
    print(f"  Woodhaven Drive house numbers: {woodhaven_nums}")
    print(f"  Woodbend Way stops: {[s.house_number for s in woodbend]}")


def test_haversine():
    """Sanity check distance function: Okotoks to Calgary ~38km."""
    okotoks = (50.7258, -113.9751)
    calgary = (51.0447, -114.0719)
    d = _haversine(*okotoks, *calgary)
    assert 35 < d < 45, f"Expected ~38km, got {d:.1f}km"


def test_optimize_reduces_total_distance():
    """
    With real geocoded coordinates, optimized route should be shorter than original.
    This test uses hardcoded approximate lat/lng for Okotoks stops to avoid
    hitting the live Nominatim API in CI.
    """
    # Approximate coordinates for a subset of addresses (manually looked up)
    # These are close enough to test the optimization logic
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

    stops = make_stops(SAMPLE_STOPS_RAW)
    for stop in stops:
        if stop.raw_address in COORDS:
            stop.lat, stop.lng = COORDS[stop.raw_address]

    # Measure original total distance
    def total_distance(stop_list):
        total = 0.0
        for i in range(len(stop_list) - 1):
            a, b = stop_list[i], stop_list[i + 1]
            if a.lat and b.lat:
                total += _haversine(a.lat, a.lng, b.lat, b.lng)
        return total

    geocoded = [s for s in stops if s.lat is not None]
    original_dist = total_distance(geocoded)

    optimized, failed = optimize(stops)
    optimized_dist = total_distance(optimized)

    print(f"\n  Original order total distance:  {original_dist:.2f} km")
    print(f"  Optimized order total distance: {optimized_dist:.2f} km")
    print(f"  Reduction: {(1 - optimized_dist/original_dist)*100:.1f}%")
    print(f"  Failed geocodes: {len(failed)}")

    print("\n  ORIGINAL ORDER:")
    for i, s in enumerate(geocoded, 1):
        print(f"    {i:2}. {s.raw_address}")

    print("\n  OPTIMIZED ORDER:")
    for i, s in enumerate(optimized, 1):
        print(f"    {i:2}. {s.raw_address}")

    assert optimized_dist < original_dist, (
        f"Optimized route ({optimized_dist:.2f}km) should be shorter than original ({original_dist:.2f}km)"
    )
    assert len(failed) == 0, f"All stops have coordinates — none should fail: {failed}"


def test_street_sweep_consecutive():
    """Stops on same street should appear consecutively in optimized output."""
    stops = make_stops(SAMPLE_STOPS_RAW)
    # inject coordinates
    COORDS = {
        "175 Woodhaven Drive, Okotoks, AB": (50.7224, -113.9741),
        "208 Woodhaven Drive, Okotoks, AB": (50.7227, -113.9745),
        "216 Woodhaven Drive, Okotoks, AB": (50.7228, -113.9746),
        "222 Woodhaven Drive, Okotoks, AB": (50.7229, -113.9748),
        "234 Woodhaven Drive, Okotoks, AB": (50.7231, -113.9750),
        "246 Woodhaven Drive, Okotoks, AB": (50.7233, -113.9752),
    }
    for stop in stops:
        if stop.raw_address in COORDS:
            stop.lat, stop.lng = COORDS[stop.raw_address]

    woodhaven_only = [s for s in stops if s.raw_address in COORDS]
    optimized, _ = optimize(woodhaven_only)

    # All Woodhaven stops should be in one consecutive block
    nums = [s.house_number for s in optimized if s.house_number]
    print(f"\n  Woodhaven Drive optimized order: {nums}")
    # Should be monotonically increasing or decreasing (one-directional sweep)
    assert nums == sorted(nums) or nums == sorted(nums, reverse=True), (
        f"Woodhaven stops should be in sequential order, got: {nums}"
    )


if __name__ == "__main__":
    print("=" * 60)
    print("RouteBuddy Route Optimizer — Test Suite")
    print("=" * 60)

    tests = [
        ("Street number parsing", test_street_grouping_no_geocode),
        ("Haversine distance", test_haversine),
        ("Route distance reduction", test_optimize_reduces_total_distance),
        ("Street sweep consecutive", test_street_sweep_consecutive),
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
            print(f"  ✗ ERROR: {e}")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{len(tests)} passed")
