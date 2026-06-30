"""
Route optimization: nearest-neighbor TSP with street-sweep grouping.

Street sweep = when multiple stops share the same street, sequence them in
house-number order in the direction of travel. This means the truck never
drives past a house and backtracks, and naturally handles passenger-side
stops by keeping the truck moving forward along each street.
"""
import re
from dataclasses import dataclass
from typing import Optional
import math


@dataclass
class Stop:
    index: int          # original position in imported list
    raw_address: str
    customer_name: str
    notes: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocode_error: Optional[str] = None

    # parsed from address
    house_number: Optional[int] = None
    street_name: Optional[str] = None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in km between two lat/lng points."""
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_house_number(address: str) -> tuple[Optional[int], str]:
    """Return (house_number, street_name) from an address string."""
    address = address.strip()
    # "208 Woodhaven Dr" — number first
    m = re.match(r'^(\d+)\s+(.+)$', address)
    if m:
        return int(m.group(1)), m.group(2).upper().strip()
    # "Woodhaven DR 208" — number last (clipboard format)
    m = re.match(r'^(.+?)\s+(\d+)$', address)
    if m:
        return int(m.group(2)), m.group(1).upper().strip()
    return None, address.upper().strip()


def parse_stops(stops: list[Stop]) -> None:
    """Parse house numbers and street names in-place."""
    for s in stops:
        # strip city/province suffix for parsing if present
        addr = re.sub(r',\s*(AB|Alberta|Canada).*$', '', s.raw_address, flags=re.I).strip()
        s.house_number, s.street_name = _parse_house_number(addr)


def _nearest_neighbor(stops: list[Stop]) -> list[Stop]:
    """
    Classic nearest-neighbor starting from the first geocoded stop.
    Returns a reordered copy of stops.
    """
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


def _street_sweep(stops: list[Stop]) -> list[Stop]:
    """
    After nearest-neighbor ordering, group consecutive same-street stops
    and sort them by house number in the direction of travel (ascending or
    descending based on which end the truck is approaching from).

    This prevents the truck from zigzagging past houses and backtracking.
    """
    if not stops:
        return stops

    result: list[Stop] = []
    i = 0
    while i < len(stops):
        current = stops[i]
        street = current.street_name

        # collect consecutive stops on the same street
        group = [current]
        j = i + 1
        while j < len(stops) and stops[j].street_name == street:
            group.append(stops[j])
            j += 1

        if len(group) > 1 and all(s.house_number is not None for s in group):
            # Determine travel direction from the stop before this group
            if result and result[-1].lat is not None and group[0].lat is not None:
                # Are we approaching from the low-number end or high-number end?
                # Use lat/lng of the entry point to decide
                low_stop = min(group, key=lambda s: s.house_number)
                high_stop = max(group, key=lambda s: s.house_number)
                d_to_low = _haversine(result[-1].lat, result[-1].lng, low_stop.lat, low_stop.lng)
                d_to_high = _haversine(result[-1].lat, result[-1].lng, high_stop.lat, high_stop.lng)
                ascending = d_to_low <= d_to_high
            else:
                ascending = True
            group.sort(key=lambda s: s.house_number, reverse=not ascending)

        result.extend(group)
        i = j

    return result


def optimize(stops: list[Stop]) -> tuple[list[Stop], list[Stop]]:
    """
    Returns (optimized_stops, failed_stops).
    failed_stops = stops that couldn't be geocoded (preserved at end of list with error).
    optimized_stops = geocoded stops in optimized order.
    """
    parse_stops(stops)
    geocoded = [s for s in stops if s.lat is not None]
    failed = [s for s in stops if s.lat is None]

    ordered = _nearest_neighbor(geocoded)
    ordered = _street_sweep(ordered)

    return ordered, failed
