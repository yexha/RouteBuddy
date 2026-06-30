"""
Nominatim geocoder with Alberta/Canada bias and swappable provider interface.
"""
import time
import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class GeoResult:
    address: str
    lat: float
    lng: float
    display_name: str
    confidence: float = 1.0


class GeocodeError(Exception):
    pass


class NominatimGeocoder:
    BASE_URL = "https://nominatim.openstreetmap.org/search"
    RATE_LIMIT_SEC = 1.1  # nominatim policy: max 1 req/sec

    def __init__(self, city_bias: str = "", user_agent: str = "RouteBuddy/1.0"):
        self.city_bias = city_bias  # e.g. "Okotoks, AB" or "Calgary, AB"
        self.user_agent = user_agent
        self._last_request = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.RATE_LIMIT_SEC:
            time.sleep(self.RATE_LIMIT_SEC - elapsed)
        self._last_request = time.monotonic()

    def geocode(self, address: str) -> GeoResult:
        self._throttle()
        query = f"{address}, {self.city_bias}, Canada" if self.city_bias else f"{address}, Canada"
        params = {
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "ca",
            "addressdetails": 0,
        }
        headers = {"User-Agent": self.user_agent}
        try:
            resp = requests.get(self.BASE_URL, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            results = resp.json()
        except requests.RequestException as e:
            raise GeocodeError(f"Network error: {e}") from e

        if not results:
            raise GeocodeError(f"No results found for: {address!r} (city bias: {self.city_bias!r})")

        r = results[0]
        return GeoResult(
            address=address,
            lat=float(r["lat"]),
            lng=float(r["lon"]),
            display_name=r.get("display_name", ""),
            confidence=float(r.get("importance", 0.5)),
        )


# Swappable interface — swap provider by changing this function
def get_geocoder(city_bias: str = "") -> NominatimGeocoder:
    return NominatimGeocoder(city_bias=city_bias)
