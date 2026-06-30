"""
Extract addresses from a clipboard/paper photo using Claude vision API.
Returns structured stop data for user review before adding to route.
"""
import base64
import json
import re
from pathlib import Path
from typing import Optional
import anthropic


EXTRACTION_PROMPT = """You are reading a handwritten or printed route/job list for a lawn care company.
Extract every address entry from this image.

For each entry return:
- customer_name: last name and/or first name as written (combine if both present)
- address: the street address ONLY, normalized to standard format "NUMBER STREET TYPE"
  (e.g. "208 Woodhaven Dr" even if the sheet shows "WOODHAVEN DR 208")
- notes: any handwritten notes, gate codes, highlighted text, sticky notes, or warnings visible
- struck_through: true if the line has a strikethrough drawn through it (completed/cancelled)

The address column may use abbreviations:
  DR=Drive, CR=Crescent, RD=Road, PL=Place, PT=Point, GR=Green, LN=Lane,
  WAY=Way, CRT=Court, EST=Estate, LNDG=Landing, HEATH=Heath

Ignore column headers. Include ALL rows, including struck-through ones (flag them).

Return ONLY a JSON array, no explanation:
[
  {
    "customer_name": "...",
    "address": "...",
    "notes": "...",
    "struck_through": false
  }
]"""


def extract_from_photo(image_path: str, api_key: str) -> list[dict]:
    """
    Send photo to Claude vision, return list of extracted stop dicts.
    Each dict: {customer_name, address, notes, struck_through}
    Raises on API error. Returns empty list if no addresses found.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    suffix = path.suffix.lower()
    media_type_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = media_type_map.get(suffix, "image/jpeg")

    with open(path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": EXTRACTION_PROMPT,
                    },
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()

    # strip markdown code fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned non-JSON response: {e}\nRaw: {raw[:500]}") from e

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got: {type(data)}")

    return data
