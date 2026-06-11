"""
indication_mapping.py
─────────────────────
Maps a trial's first condition to a canonical indication label, with
optional override rules driven by primary outcome and study title text.

synonyms.json schema
────────────────────
{
  "synonyms": {
    "Heart Failure": ["Heart Failure, Systolic", "HFpEF", ...],
    ...
  },
  "overrides": [
    {
      "when_base_label": "Type 2 Diabetes",
      "if_outcome_contains": ["MACE", "cardiovascular death"],
      "then_label": "ASCVD CVOT"
    },
    {
      "when_base_label": "Type 2 Diabetes",
      "if_title_contains": ["cardiovascular outcomes trial", "CVOT"],
      "then_label": "ASCVD CVOT"
    }
  ]
}

Matching logic
──────────────
Step 1 — Canonicalize the first condition via synonym lookup.
  Synonyms are checked in the order they appear in "synonyms".
  If a synonym matches → return the canonical indication name.
  If nothing matches  → keep the raw first condition text verbatim.

Step 2 — Apply override rules in order.
  Each rule fires when:
    - base label matches "when_base_label", AND
    - any term in "if_outcome_contains" appears in the outcome text, OR
    - any term in "if_title_contains" appears in the title text.
  First matching rule wins; returns "then_label".

To update synonyms or add/edit override rules, edit synonyms.json only —
no Python changes required.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SYNONYMS_PATH = os.path.join(_HERE, "indication-rule.json")

_FALLBACK = "Other"


def _load_rules(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    synonyms = data.get("synonyms", {})

    synonym_rules = [
        (indication, [t.lower() for t in terms])
        for indication, terms in synonyms.items()
    ]

    override_rules = [
        {
            "when_base_label":                rule.get("when_base_label", ""),
            "if_outcome_contains":            [t.lower() for t in rule.get("if_outcome_contains", [])],
            "if_secondary_outcome_contains":  [t.lower() for t in rule.get("if_secondary_outcome_contains", [])],
            "if_title_contains":              [t.lower() for t in rule.get("if_title_contains", [])],
            "then_label":                     rule.get("then_label", ""),
        }
        for rule in data.get("overrides", [])
    ]

    return synonym_rules, override_rules


_SYNONYM_RULES, _OVERRIDE_RULES = _load_rules(_SYNONYMS_PATH)


def map_indication(first_condition_str: str, outcome_str: str = "", title_str: str = "", secondary_outcome_str: str = "") -> str:
    """
    Map a trial's first condition to a canonical indication label.

    Parameters
    ----------
    first_condition_str : str
        The first entry from the conditions list, e.g. "Type 2 Diabetes Mellitus"
    outcome_str : str, optional
        Primary outcome measures text.
    title_str : str, optional
        Study title text.

    Returns
    -------
    str
        Canonical indication label, raw first condition text if no synonym
        matches, or "Other" if first_condition_str is empty.
    """
    first_cond = first_condition_str.strip() if isinstance(first_condition_str, str) else ""
    if not first_cond:
        return _FALLBACK

    cond_text     = first_cond.lower()
    outc_text     = outcome_str.lower()           if isinstance(outcome_str,           str) else ""
    titl_text     = title_str.lower()             if isinstance(title_str,             str) else ""
    sec_outc_text = secondary_outcome_str.lower() if isinstance(secondary_outcome_str, str) else ""

    # Step 1: synonym lookup → canonical label or verbatim text
    base_label = first_cond
    for indication, synonyms_lower in _SYNONYM_RULES:
        if any(syn in cond_text for syn in synonyms_lower):
            base_label = indication
            break

    # Step 2a: primary outcome and title — checked across all rules first
    for rule in _OVERRIDE_RULES:
        if rule["when_base_label"] and rule["when_base_label"] != base_label:
            continue
        if rule["if_outcome_contains"] and any(t in outc_text for t in rule["if_outcome_contains"]):
            return rule["then_label"]
        if rule["if_title_contains"] and any(t in titl_text for t in rule["if_title_contains"]):
            return rule["then_label"]

    # Step 2b: secondary outcome fallback — only if nothing matched above
    for rule in _OVERRIDE_RULES:
        if rule["when_base_label"] and rule["when_base_label"] != base_label:
            continue
        if rule["if_secondary_outcome_contains"] and any(t in sec_outc_text for t in rule["if_secondary_outcome_contains"]):
            return rule["then_label"]

    return base_label


def reload():
    """Force a reload of synonyms.json (useful during development)."""
    global _SYNONYM_RULES, _OVERRIDE_RULES
    _SYNONYM_RULES, _OVERRIDE_RULES = _load_rules(_SYNONYMS_PATH)
