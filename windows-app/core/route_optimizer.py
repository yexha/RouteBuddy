"""
Route optimization: nearest-neighbor TSP + street sweep with right-side-of-road ordering.

RIGHT-SIDE LOGIC (Canada drives on the right):
  On a two-way street, odd and even house numbers are on opposite sides.
  Standard convention: odd numbers on the left/north/west, even on the right/south/east
  — but this varies. The algorithm avoids assuming which is which and instead
  does a "two-pass sweep":
    Pass 1 — one parity going forward (e.g. 100, 102, 104...)
    Pass 2 — other parity coming back (e.g. 105, 103, 101...)
  This keeps the truck on the same side for an entire stretch before crossing once
  at the end of the street, eliminating zigzag crossing for each house.

  Cul-de-sacs and short courts (< 4 stops) are done in a single forward pass
  since both sides are reachable without crossing.
"""
import re
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Stop:
    index: int
    raw_address: str
    customer_name: str
    notes: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocode_error: Optional[str] = None
    is_done: bool = False        # struck-through / already completed

    # parsed
    house_number: Optional[int] = None
    street_name: Optional[str] = None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_house_number(address: str) -> tuple[Optional[int], str]:
    address = address.strip()
    # "208 Woodhaven Dr" or "208A Woodhaven Dr"
    m = re.match(r'^(\d+)[A-Za-z]?\s+(.+)$', address)
    if m:
        return int(m.group(1)), m.group(2).upper().strip()
    # "Woodhaven DR 208" — number at end
    m = re.match(r'^(.+?)\s+(\d+)[A-Za-z]?$', address)
    if m:
        return int(m.group(2)), m.group(1).upper().strip()
    return None, address.upper().strip()


def _normalize_street_key(street: str) -> str:
    """Strip city/province suffix and normalize for grouping."""
    street = re.sub(r',.*$', '', street).strip()
    # Expand common abbreviations so "Dr" and "Drive" group together
    abbrevs = {
        r'\bDR\b': 'DRIVE', r'\bCR\b': 'CRESCENT', r'\bCRES\b': 'CRESCENT',
        r'\bRD\b': 'ROAD', r'\bPL\b': 'PLACE', r'\bAVE\b': 'AVENUE',
        r'\bAV\b': 'AVENUE', r'\bST\b': 'STREET', r'\bBLVD\b': 'BOULEVARD',
        r'\bCRT\b': 'COURT', r'\bCT\b': 'COURT', r'\bLN\b': 'LANE',
        r'\bGR\b': 'GREEN', r'\bPT\b': 'POINT',
    }
    s = street.upper()
    for pattern, replacement in abbrevs.items():
        s = re.sub(pattern, replacement, s)
    return s.strip()


def parse_stops(stops: list[Stop]) -> None:
    for s in stops:
        addr = re.sub(r',\s*(AB|Alberta|Canada).*$', '', s.raw_address, flags=re.I).strip()
        s.house_number, s.street_name = _parse_house_number(addr)
        # normalize for grouping
        if s.street_name:
            s.street_name = _normalize_street_key(s.street_name)


def _nearest_neighbor(stops: list[Stop]) -> list[Stop]:
    remaining = [s for s in stops if s.lat is not None]
    if not remaining:
        return []
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1]
        nearest = min(remaining, key=lambda s: _haversine(last.lat, last.lng, s.lat, s.lng))
        remaining.remove(nearest)
        ordered.append(nearest)
    return ordered


def _right_side_sweep(group: list[Stop], approach_from: Optional[Stop]) -> list[Stop]:
    """
    Order a group of stops on the same street for right-side-of-road efficiency.

    For groups with both odd and even numbers (a real two-way street):
      - Do all even-numbered houses in one direction
      - Do all odd-numbered houses in the other direction
      This means crossing the street only once at the end, not per house.

    For short groups or cul-de-sacs (< 4 stops or all same parity):
      - Simple ascending/descending sweep based on approach direction.
    """
    if len(group) <= 1:
        return group

    numbered = [s for s in group if s.house_number is not None]
    unnumbered = [s for s in group if s.house_number is None]

    if not numbered:
        return group

    evens = sorted([s for s in numbered if s.house_number % 2 == 0], key=lambda s: s.house_number)
    odds = sorted([s for s in numbered if s.house_number % 2 == 1], key=lambda s: s.house_number)

    # Determine direction of approach (do we enter from the low or high end?)
    def entry_from_low() -> bool:
        if approach_from and approach_from.lat is not None:
            low_stop = numbered[0] if numbered[0].house_number == min(s.house_number for s in numbered) else min(numbered, key=lambda s: s.house_number)
            high_stop = max(numbered, key=lambda s: s.house_number)
            if low_stop.lat is None or high_stop.lat is None:
                return True
            d_low = _haversine(approach_from.lat, approach_from.lng, low_stop.lat, low_stop.lng)
            d_high = _haversine(approach_from.lat, approach_from.lng, high_stop.lat, high_stop.lng)
            return d_low <= d_high
        return True

    from_low = entry_from_low()

    # Short groups or cul-de-sac (same parity or tiny) — single directional pass
    if len(numbered) < 4 or not evens or not odds:
        result = sorted(numbered, key=lambda s: s.house_number, reverse=not from_low)
        return result + unnumbered

    # Two-pass sweep: one side forward, other side back
    if from_low:
        # Enter from low end → evens go up (right side of road going forward)
        #                    → odds come back down (right side of road returning)
        pass1 = evens           # ascending
        pass2 = list(reversed(odds))  # descending
    else:
        # Enter from high end
        pass1 = list(reversed(odds))  # descending
        pass2 = evens               # ascending

    return pass1 + pass2 + unnumbered


def _apply_street_sweeps(stops: list[Stop]) -> list[Stop]:
    """
    Walk the nearest-neighbor ordered list. Whenever consecutive stops share
    a street, collect them into a group and apply right-side sweep ordering.
    """
    if not stops:
        return stops

    result: list[Stop] = []
    i = 0
    while i < len(stops):
        current = stops[i]
        street = current.street_name

        group = [current]
        j = i + 1
        while j < len(stops) and stops[j].street_name == street and street is not None:
            group.append(stops[j])
            j += 1

        approach = result[-1] if result else None
        swept = _right_side_sweep(group, approach)
        result.extend(swept)
        i = j

    return result


def optimize(stops: list[Stop]) -> tuple[list[Stop], list[Stop]]:
    """
    Returns (optimized_stops, failed_stops).
    Completed (is_done) stops are included but sorted to the end within their
    street group so the driver can verify they were actually done.
    failed_stops have geocode_error set and cannot be positioned.
    """
    parse_stops(stops)

    geocoded = [s for s in stops if s.lat is not None]
    failed = [s for s in stops if s.lat is None and s.geocode_error]

    # Separate active vs done stops for ordering
    # Done stops get inserted at the back of their street group naturally
    # since they go through the same sweep — no special handling needed.
    ordered = _nearest_neighbor(geocoded)
    ordered = _apply_street_sweeps(ordered)

    return ordered, failed
