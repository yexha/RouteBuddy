"""
Extract addresses from a clipboard/route-list photo using local OCR (EasyOCR + OpenCV).
No API key required — runs entirely on-device.

Approach:
  1. OpenCV detects horizontal strikethrough lines (done entries) by finding
     horizontal line segments in the image and checking if they overlap with text rows.
  2. EasyOCR reads all text blocks with bounding boxes.
  3. Text blocks are reconstructed into rows by grouping by Y coordinate.
  4. Each row is parsed for the ADDRESS column (rightmost column in the typical
     format: TOWN | LAST NAME | NAME | ADDRESS | NOTES).
  5. Address strings are normalized from "STREET NAME NUMBER" to "NUMBER Street Name".
"""
import re
import math
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# EasyOCR is imported lazily to avoid slow startup when not needed
_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _reader


# ── Strikethrough detection ─────────────────────────────────────────────────

def _detect_struck_rows(img_gray: np.ndarray, text_boxes: list) -> set[int]:
    """
    Return set of row indices (into text_boxes) whose text has a strikethrough line.
    Uses morphological line detection to find horizontal strokes across text.
    """
    # Detect horizontal lines via morphology
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    eroded = cv2.erode(img_gray, kernel)
    dilated = cv2.dilate(eroded, kernel)
    # threshold
    _, thresh = cv2.threshold(dilated, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Collect horizontal line bands (y_min, y_max, x_min, x_max)
    h_lines = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > 60 and h < 8:  # wide and thin = horizontal stroke
            h_lines.append((y, y + h, x, x + w))

    struck = set()
    for idx, box in enumerate(text_boxes):
        # box[0] = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        pts = np.array(box[0])
        bx_min = int(pts[:, 0].min())
        bx_max = int(pts[:, 0].max())
        by_min = int(pts[:, 1].min())
        by_max = int(pts[:, 1].max())
        by_mid = (by_min + by_max) // 2

        for (ly_min, ly_max, lx_min, lx_max) in h_lines:
            # Line must pass through vertical midpoint of text and overlap horizontally
            if ly_min <= by_mid <= ly_max and lx_min < bx_max and lx_max > bx_min:
                struck.add(idx)
                break
    return struck


# ── Address normalization ───────────────────────────────────────────────────

_ABBREV_MAP = {
    "DR": "Drive", "CR": "Crescent", "RD": "Road", "PL": "Place",
    "PT": "Point", "GR": "Green", "LN": "Lane", "WAY": "Way",
    "CRT": "Court", "CT": "Court", "EST": "Estate", "LNDG": "Landing",
    "HEATH": "Heath", "BV": "Boulevard", "AVE": "Avenue", "AV": "Avenue",
    "ST": "Street", "BLVD": "Boulevard", "CRES": "Crescent",
}


def _normalize_address(raw: str) -> str:
    """
    Convert clipboard format to standard Canadian format.
    "WOODHAVEN DR 208"  →  "208 Woodhaven Drive"
    "208 WOODHAVEN DR"  →  "208 Woodhaven Drive"
    """
    raw = raw.strip().upper()
    raw = re.sub(r'\s+', ' ', raw)

    # Check if number is at the end: "STREET NAME 208"
    m_end = re.match(r'^(.+?)\s+(\d+[A-Z]?)$', raw)
    # Check if number is at the start: "208 STREET NAME"
    m_start = re.match(r'^(\d+[A-Z]?)\s+(.+)$', raw)

    if m_end:
        number = m_end.group(2)
        street = m_end.group(1)
    elif m_start:
        number = m_start.group(1)
        street = m_start.group(2)
    else:
        return raw.title()

    # Expand abbreviations in street name
    parts = street.split()
    expanded = []
    for part in parts:
        expanded.append(_ABBREV_MAP.get(part, part.title()))
    street_clean = " ".join(expanded)

    return f"{number} {street_clean}"


# ── Row reconstruction from OCR boxes ───────────────────────────────────────

def _group_into_rows(boxes: list, tolerance_px: int = 12) -> list[list]:
    """
    Group OCR text boxes by their Y midpoint to reconstruct table rows.
    Returns list of rows, each row = list of (x_center, text, box_idx).
    """
    rows: list[list] = []
    for idx, (box, text, conf) in enumerate(boxes):
        pts = np.array(box)
        y_mid = float(pts[:, 1].mean())
        x_mid = float(pts[:, 0].mean())

        placed = False
        for row in rows:
            row_y = row[0][0]  # y_mid of first element
            if abs(y_mid - row_y) <= tolerance_px:
                row.append((y_mid, x_mid, text, idx))
                placed = True
                break
        if not placed:
            rows.append([(y_mid, x_mid, text, idx)])

    # Sort rows by Y, elements within each row by X
    rows.sort(key=lambda r: r[0][0])
    for row in rows:
        row.sort(key=lambda e: e[1])
    return rows


# ── Address column heuristics ───────────────────────────────────────────────

_STREET_TYPE_RE = re.compile(
    r'\b(DR|DRIVE|CR|CRES|CRESCENT|RD|ROAD|PL|PLACE|PT|POINT|GR|GREEN|'
    r'LN|LANE|WAY|CRT|CT|COURT|EST|ESTATE|LNDG|LANDING|HEATH|'
    r'BLVD|BOULEVARD|AVE|AVENUE|ST|STREET)\b', re.I
)
_NUMBER_RE = re.compile(r'\b\d{1,5}\b')
_TOWN_CODE_RE = re.compile(r'^OK\s*(NAR|NDL|NW|SC|SW|SE|NE|N|S|E|W)?$', re.I)


def _looks_like_address(text: str) -> bool:
    return bool(_STREET_TYPE_RE.search(text)) and bool(_NUMBER_RE.search(text))


def _looks_like_town_code(text: str) -> bool:
    return bool(_TOWN_CODE_RE.match(text.strip()))


def _looks_like_name(text: str) -> bool:
    # Short alpha-only strings are likely names
    return bool(re.match(r'^[A-Za-z/\-\s\.]+$', text.strip())) and len(text.strip()) > 1


# ── Main extraction function ─────────────────────────────────────────────────

def extract_from_photo(image_path: str) -> list[dict]:
    """
    Extract stops from a route list photo.
    Returns list of dicts: {customer_name, address, notes, struck_through}
    Raises on file error or OCR failure.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Load image
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Run OCR
    reader = _get_reader()
    raw_boxes = reader.readtext(img)  # returns [(box, text, confidence), ...]

    if not raw_boxes:
        return []

    # Detect struck-through boxes
    struck_indices = _detect_struck_rows(img_gray, [(b[0], b[1], b[2]) for b in raw_boxes])

    # Group into rows
    rows = _group_into_rows(raw_boxes)

    results = []
    for row in rows:
        # Each element: (y_mid, x_mid, text, original_box_idx)
        texts = [e[2].strip() for e in row]
        indices = [e[3] for e in row]

        # Skip header rows
        combined = " ".join(texts).upper()
        if any(h in combined for h in ["TOWN", "LAST NAME", "ADDRESS", "BND"]):
            continue

        # Skip very short rows (noise)
        if len(texts) < 2:
            continue

        # Is this row struck through? (any element struck = whole row struck)
        is_struck = any(i in struck_indices for i in indices)

        # Find address: look for the element that looks like a street address
        address_text = ""
        name_parts = []
        note_parts = []

        for text in texts:
            if _looks_like_address(text) and not address_text:
                address_text = text
            elif _looks_like_town_code(text):
                pass  # skip town codes like "OK SC"
            elif text.upper() in ("WAIT", "GATE", "CON", "DO"):
                note_parts.append(text)
            elif _looks_like_name(text) and not address_text:
                name_parts.append(text)

        if not address_text:
            # fallback: longest token with a number
            candidates = [(len(t), t) for t in texts if _NUMBER_RE.search(t)]
            if candidates:
                address_text = max(candidates)[1]

        if not address_text:
            continue

        normalized = _normalize_address(address_text)
        customer = " ".join(name_parts[:2]) if name_parts else ""
        notes = ", ".join(note_parts)

        results.append({
            "customer_name": customer.strip(),
            "address": normalized,
            "notes": notes,
            "struck_through": is_struck,
        })

    return results
