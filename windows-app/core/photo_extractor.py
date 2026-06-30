"""
Extract addresses from a route-list photo using local OCR (EasyOCR + OpenCV).
No API key required — runs entirely on-device.

This extractor is ADDRESS-FOCUSED on purpose. It does NOT try to parse the photo
into Name / Address / Notes columns — that column-guessing was unreliable and
produced blanks and mismatched names. Instead it:

  1. Reads all text from the image (EasyOCR).
  2. Groups text into rows by vertical position.
  3. For each row, searches the whole row's text for something that looks like a
     real street address — a house number next to a street name ending in a
     street type (Drive, Place, Crescent, ...). Everything else on the row
     (customer names, town codes, gate notes) is ignored.
  4. Normalizes the address ("WOODHAVEN DR 208" -> "208 Woodhaven Drive").
  5. Flags rows whose text was crossed out (already done that day).

Heavy libraries (cv2, numpy, easyocr) are imported lazily so the address-parsing
logic can be unit-tested without them installed.
"""
import re
from pathlib import Path
from typing import Optional


# ── EasyOCR (lazy) ──────────────────────────────────────────────────────────
_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _reader


# ── Street types & abbreviation expansion ───────────────────────────────────
# Both full words and common abbreviations. Used as the anchor for "this is an
# address". Sorted longest-first when built into the regex so e.g. DRIVE is tried
# before DR.
_STREET_TYPES = [
    "BOULEVARD", "CRESCENT", "TERRACE", "GARDENS", "LANDING", "AVENUE", "COMMON",
    "CROSSING", "DRIVE", "STREET", "SQUARE", "CIRCLE", "COURT", "PLACE", "POINT",
    "GREEN", "MANOR", "TRAIL", "RIDGE", "VALLEY", "VISTA", "GROVE", "HOLLOW",
    "HEATH", "CLOSE", "COVE", "MEWS", "PARK", "PASS", "PATH", "RISE", "WALK",
    "LANE", "ROAD", "BLVD", "CRES", "LNDG", "GDNS", "TERR", "WAY", "ROW", "RUN",
    "BAY", "LINK", "HILL", "VIEW", "DR", "CR", "RD", "PL", "PT", "GR", "LN",
    "CT", "CRT", "AVE", "AV", "ST", "SQ", "CIR",
]
_TYPES_GROUP = "|".join(sorted(_STREET_TYPES, key=len, reverse=True))

_ABBREV_MAP = {
    "DR": "Drive", "CR": "Crescent", "CRES": "Crescent", "RD": "Road",
    "PL": "Place", "PT": "Point", "GR": "Green", "LN": "Lane", "CRT": "Court",
    "CT": "Court", "AVE": "Avenue", "AV": "Avenue", "ST": "Street",
    "BLVD": "Boulevard", "SQ": "Square", "CIR": "Circle", "GDNS": "Gardens",
    "LNDG": "Landing", "TERR": "Terrace", "TER": "Terrace", "EST": "Estate",
}

# Words that look like a street name in the fallback but are really notes.
_NOTE_WORDS = {"GATE", "WAIT", "DOG", "CALL", "CON", "DONE", "OK", "NEW", "SEE"}

# ── Address regexes ─────────────────────────────────────────────────────────
# Number first: "115 Sunset Place", "16 Cimarron Estates Way"
_NUM_FIRST = re.compile(
    r'\b(\d{1,5}[A-Za-z]?)\s+'
    r'((?:[A-Za-z][A-Za-z\'.\-]*\s+){0,4}(?:' + _TYPES_GROUP + r'))\b',
    re.IGNORECASE,
)
# Number last: "WOODHAVEN DR 208" (older clipboard format)
_NUM_LAST = re.compile(
    r'\b((?:[A-Za-z][A-Za-z\'.\-]*\s+){0,3}(?:' + _TYPES_GROUP + r'))\s+'
    r'(\d{1,5}[A-Za-z]?)\b',
    re.IGNORECASE,
)
# Fallback: number + a Capitalized word, for streets with no type ("2 Anderson").
# Case-sensitive on the word so we don't grab lowercase noise.
_NUM_WORD = re.compile(r'\b(\d{1,5})\s+([A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]+)?)\b')


def _format_address(number: str, street_raw: str) -> str:
    """('208', 'WOODHAVEN DR') -> '208 Woodhaven Drive'."""
    words = re.sub(r'\s+', ' ', street_raw).strip().split()
    expanded = [_ABBREV_MAP.get(w.upper(), w.title()) for w in words]
    return f"{number} {' '.join(expanded)}".strip()


def extract_address(text: str) -> Optional[str]:
    """
    Find and normalize a street address inside a line of OCR text, or None.
    Names, town codes and notes around the address are discarded.
    """
    t = re.sub(r'\s+', ' ', text).strip()
    if not t:
        return None

    m = _NUM_FIRST.search(t)
    if m:
        return _format_address(m.group(1), m.group(2))

    m = _NUM_LAST.search(t)
    if m:
        return _format_address(m.group(2), m.group(1))

    m = _NUM_WORD.search(t)
    if m and m.group(2).split()[0].upper() not in _NOTE_WORDS:
        return _format_address(m.group(1), m.group(2))

    return None


# ── Strikethrough detection (done entries) ──────────────────────────────────
def _detect_struck_boxes(img_gray, boxes) -> set:
    """Return indices of OCR boxes that have a horizontal line through them."""
    import cv2
    import numpy as np

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    morph = cv2.dilate(cv2.erode(img_gray, kernel), kernel)
    _, thresh = cv2.threshold(morph, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h_lines = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > 60 and h < 8:
            h_lines.append((y, y + h, x, x + w))

    struck = set()
    for idx, (box, _text, _conf) in enumerate(boxes):
        pts = np.array(box)
        bx_min, bx_max = int(pts[:, 0].min()), int(pts[:, 0].max())
        by_min, by_max = int(pts[:, 1].min()), int(pts[:, 1].max())
        by_mid = (by_min + by_max) // 2
        for (ly_min, ly_max, lx_min, lx_max) in h_lines:
            if ly_min <= by_mid <= ly_max and lx_min < bx_max and lx_max > bx_min:
                struck.add(idx)
                break
    return struck


# ── Row reconstruction ──────────────────────────────────────────────────────
def _group_into_rows(boxes, tolerance_px: int = 14):
    """Group OCR boxes into rows by Y midpoint. Returns rows of (x_mid, text, idx)."""
    import numpy as np

    rows = []
    for idx, (box, text, _conf) in enumerate(boxes):
        pts = np.array(box)
        y_mid = float(pts[:, 1].mean())
        x_mid = float(pts[:, 0].mean())
        placed = False
        for row in rows:
            if abs(y_mid - row["y"]) <= tolerance_px:
                row["items"].append((x_mid, text, idx))
                placed = True
                break
        if not placed:
            rows.append({"y": y_mid, "items": [(x_mid, text, idx)]})

    rows.sort(key=lambda r: r["y"])
    for row in rows:
        row["items"].sort(key=lambda e: e[0])
    return rows


_HEADER_TOKENS = ("TOWN", "LAST NAME", "ADDRESS", "BND", "CUSTOMER", "NAME")


# ── Main entry point ────────────────────────────────────────────────────────
def extract_from_photo(image_path: str) -> tuple[list[dict], list[str]]:
    """
    Returns (addresses, skipped).
      addresses: [{"address": str, "struck_through": bool}, ...]
      skipped:   row texts that had a number but no parseable address (so nothing
                 is silently dropped — surfaced to the user for review).
    Raises FileNotFoundError / ValueError on unreadable files.
    """
    import cv2

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not read image (unsupported or corrupt): {image_path}")

    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    raw_boxes = _get_reader().readtext(img)  # [(box, text, conf), ...]
    if not raw_boxes:
        return [], []

    struck = _detect_struck_boxes(img_gray, raw_boxes)
    rows = _group_into_rows(raw_boxes)

    addresses: list[dict] = []
    skipped: list[str] = []

    for row in rows:
        texts = [e[1] for e in row["items"]]
        indices = [e[2] for e in row["items"]]
        combined = " ".join(texts).strip()
        upper = combined.upper()

        if any(tok in upper for tok in _HEADER_TOKENS):
            continue

        addr = extract_address(combined)
        if addr:
            addresses.append({
                "address": addr,
                "struck_through": any(i in struck for i in indices),
            })
        elif any(ch.isdigit() for ch in combined):
            # Had a number but we couldn't make an address of it — surface it.
            skipped.append(combined)

    return addresses, skipped
