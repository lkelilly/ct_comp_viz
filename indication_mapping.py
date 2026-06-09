"""
indication_mapping.py
─────────────────────
Loads indication synonyms from synonyms.json and maps a raw conditions
string to a canonical indication label.

synonyms.json schema
────────────────────
{
  "priority": ["Heart Failure", "Cardiovascular Disease", ...],
  "synonyms": {
    "Heart Failure": ["Heart Failure, Systolic", "HFpEF", ...],
    "Type 2 Diabetes": ["T2DM", "Diabetes Mellitus, Type 2", ...],
    ...
  }
}

Matching logic
──────────────
Each synonym is matched as a case-insensitive substring of the
conditions string.  Indications are evaluated in the order given by
"priority", so a study with both "Heart Failure" and "Diabetes" maps
to "Heart Failure" — the higher-priority indication wins.

To update synonyms or priorities, edit synonyms.json only — no Python
changes required.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SYNONYMS_PATH = os.path.join(_HERE, "synonyms.json")

_FALLBACK = "Other"


def _load_rules(path: str):
    """
    Load synonyms.json and return an ordered list of
    (canonical_indication, [lowercase_synonym, ...]) tuples.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    priority = data.get("priority", [])
    synonyms = data.get("synonyms", {})

    # Build ordered list: indications in priority order, then any
    # remaining ones that were in synonyms but not in priority.
    ordered_indications = list(priority) + [
        k for k in synonyms if k not in priority
    ]

    rules = []
    for indication in ordered_indications:
        terms = synonyms.get(indication, [indication])
        rules.append((indication, [t.lower() for t in terms]))

    return rules


# Load once at import time; module-level cache.
_RULES = _load_rules(_SYNONYMS_PATH)


def map_indication(conditions_str: str) -> str:
    """
    Map a raw conditions string to a canonical indication label.

    The conditions string may be pipe-separated (e.g. from CT.gov API)
    or free-text.  Matching is case-insensitive substring search.
    The first indication in priority order whose synonym appears in the
    string is returned.

    Parameters
    ----------
    conditions_str : str
        Raw `conditions` value, e.g.
        "Obesity or Overweight | Type 2 Diabetes Mellitus"

    Returns
    -------
    str
        Canonical indication label, or "Other" if no synonym matches.
    """
    if not isinstance(conditions_str, str) or not conditions_str.strip():
        return _FALLBACK

    text = conditions_str.lower()

    for indication, synonyms_lower in _RULES:
        for synonym in synonyms_lower:
            if synonym in text:
                return indication

    return _FALLBACK


def reload():
    """Force a reload of synonyms.json (useful during development)."""
    global _RULES
    _RULES = _load_rules(_SYNONYMS_PATH)
