"""
indication_mapping.py
─────────────────────
Maps a trial's endpoints and conditions to a canonical indication label,
with override rules driven by primary outcome and study title text.

indication-rule.json schema
// it is made up three major lists: synonyms, priority rules, and overrides.
//     - `synonyms`: matching synonyms for conditions.
//     - `priority_rules`: rules that has priority for some specific indications.
//     - `overrides`: override simple condition matching with specific outcomes.
───────────────────────────
{
  "synonyms": {
    "Heart Failure": ["Heart Failure, Systolic", "HFpEF", ...],
    ...
  },
  "priority_rules": {
    "t2d_endpoint_terms":   ["hba1c"],
    "cwm_endpoint_terms":   ["body weight", "weight loss", ...],
    "cvot_mace_terms":      ["major adverse cardiovascular event", "mace", ...],
    "cvot_outcome_synonyms": ["cardiovascular outcome", "cardiovascular outcomes"],
    "ascvd_condition_terms": ["coronary artery", "ascvd", ...]
  },
  "overrides": [
    {
      "when_base_label": "Hyperlipidemia",
      "if_outcome_contains": ["ldl-c"],
      "then_label": "LDL-C lowering"
    },
    ...
  ]
}

Matching logic
──────────────
Step 1 — Canonicalize conditions via synonym lookup → sets base_label.
  All conditions text is checked (not just the first condition).
  Synonyms are checked in the order they appear in "synonyms".
  If a synonym matches → base_label = canonical indication name.
  If nothing matches  → base_label = raw first condition text verbatim.
  (NOT returning anythin yet, just set the `base_label`
      — outcome checks in Steps 2-4 still apply.)

Step 2 — Apply priority rules (highest priority):
  2a. T2D + HbA1c endpoint          → "Type 2 Diabetes"
  2b. CWM + weight endpoint          → "Chronic Weight Management"
  2c. MACE/cvot-trigger in outcome   → CVOT subtype based on condition

Step 3 — Apply JSON override rules in order (LDL-C, HoFH/HeFH, title-CVOT).
  First matching rule wins.

Step 4 — Secondary outcome fallback (override rules only).

Step 5 — Pharmacokinetics fallback (last resort):
  If primary or secondary outcome text mentions "pharmacokinetic(s)" or a
  standalone "PK" (word-boundary match) → "Pharmacokinetics".

To update synonyms, priority terms, or override rules, edit indication-rule.json
only — this file is only processing and rendering.
"""

import json
import os
import re

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

    raw_priority = data.get("priority_rules", {})
    priority_rules = {k: [t.lower() for t in v] for k, v in raw_priority.items()}

    return synonym_rules, override_rules, priority_rules


_SYNONYM_RULES, _OVERRIDE_RULES, _PRIORITY_RULES = _load_rules(_SYNONYMS_PATH)
# Lookup dict for outcome-first priority checks (Steps 2a/2b)
_SYNONYM_BY_LABEL = dict(_SYNONYM_RULES)


def map_indication(conditions_str: str, outcome_str: str = "", title_str: str = "", secondary_outcome_str: str = "") -> str:
    """
    Map a trial's conditions to a canonical indication label.

    Parameters
    ----------
    conditions_str : str
        All conditions for the trial (pipe-separated or single value).
    outcome_str : str, optional
        Primary outcome measures text.
    title_str : str, optional
        Study title text.
    secondary_outcome_str : str, optional
        Secondary outcome measures text.

    Returns
    -------
    str
        Canonical indication label, raw first condition text if no synonym
        matches, or "Other" if conditions_str is empty.
    """
    conditions_str = conditions_str.strip() if isinstance(conditions_str, str) else ""
    if not conditions_str:
        return _FALLBACK

    # For display fallback use the first condition segment
    first_cond = conditions_str.split("|")[0].strip()

    first_cond_text = first_cond.lower()       # Step 1 synonym loop + base_label
    cond_text       = conditions_str.lower()   # Step 2a/2b condition verify + Step 2c ASCVD check
    outc_text     = outcome_str.lower()           if isinstance(outcome_str,           str) else ""
    titl_text     = title_str.lower()             if isinstance(title_str,             str) else ""
    sec_outc_text = secondary_outcome_str.lower() if isinstance(secondary_outcome_str, str) else ""

    # Step 1: synonym lookup on first condition only → sets base_label
    # (first condition anchors fallback and CVOT subtype; secondary conditions
    #  are checked explicitly in Steps 2a/2b via cond_text)
    base_label = first_cond
    for indication, synonyms_lower in _SYNONYM_RULES:
        if any(syn in first_cond_text for syn in synonyms_lower):
            base_label = indication
            break

    # Step 2a: Priority — HbA1c endpoint + T2D in any condition → Type 2 Diabetes
    # Outcome-first: avoids false trigger when obesity is a secondary condition.
    if any(t in outc_text for t in _PRIORITY_RULES.get("t2d_endpoint_terms", [])):
        if any(syn in cond_text for syn in _SYNONYM_BY_LABEL.get("Type 2 Diabetes", [])):
            return "Type 2 Diabetes"

    # Fallback patch: if base_label is T2D but outcome has no HbA1c, the primary
    # condition may be a T2D complication. Re-scan ALL conditions (skipping T2D)
    # in JSON synonym order for the first more-specific match.
    if base_label == "Type 2 Diabetes":
        for indication, synonyms_lower in _SYNONYM_RULES:
            if indication == "Type 2 Diabetes":
                continue
            if any(syn in cond_text for syn in synonyms_lower):
                return indication

    # Step 2b: Priority — weight endpoint + CWM in any condition → Chronic Weight Management
    # Outcome-first: avoids false trigger when obesity is a secondary condition
    if any(t in outc_text for t in _PRIORITY_RULES.get("cwm_endpoint_terms", [])):
        if any(syn in cond_text for syn in _SYNONYM_BY_LABEL.get("Chronic Weight Management", [])):
            return "Chronic Weight Management"

    # Step 2c: Priority — MACE / CVOT trigger in primary outcome → CVOT subtype
    cvot_triggers = (
        _PRIORITY_RULES.get("cvot_mace_terms", [])
        + _PRIORITY_RULES.get("cvot_outcome_synonyms", [])
    )
    if any(t in outc_text for t in cvot_triggers):
        if base_label == "Type 2 Diabetes":
            return "T2D CVOT"
        if base_label == "Chronic Weight Management":
            return "OBE CVOT"
        if any(t in cond_text for t in _PRIORITY_RULES.get("ascvd_condition_terms", [])):
            return "ASCVD CVOT"
        return "CVOT"

    # Step 3: JSON override rules — primary outcome and title
    for rule in _OVERRIDE_RULES:
        if rule["when_base_label"] and rule["when_base_label"] != base_label:
            continue
        if rule["if_outcome_contains"] and any(t in outc_text for t in rule["if_outcome_contains"]):
            return rule["then_label"]
        if rule["if_title_contains"] and any(t in titl_text for t in rule["if_title_contains"]):
            return rule["then_label"]

    # Step 4: secondary outcome fallback
    for rule in _OVERRIDE_RULES:
        if rule["when_base_label"] and rule["when_base_label"] != base_label:
            continue
        if rule["if_secondary_outcome_contains"] and any(t in sec_outc_text for t in rule["if_secondary_outcome_contains"]):
            return rule["then_label"]

    # Step 5: if other override/priority rules have not been specified, check for PK
    _pk_text = outc_text + " " + sec_outc_text
    if any(term in _pk_text for term in _PRIORITY_RULES.get("pk_terms", [])):
        return "Pharmacokinetics"
    if re.search(r"\bpk\b", _pk_text):
        return "Pharmacokinetics"

    return base_label
