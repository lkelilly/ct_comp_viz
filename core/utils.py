"""
utils.py
────────
Data processing utilities.

1. Flattens raw CT.gov API v2 JSON into a clean pandas DataFrame.
    - Paths verified against live API response structure.
2. Processes raw data sets users upload.
"""

import pandas as pd
import re

from .indication_mapping import map_indication, _SYNONYM_RULES


_PLACEBO_RE = re.compile(r'^\s*placebo\b', re.IGNORECASE)

_MASTER_PROTOCOL_KEYWORDS = ["master protocol", "platform trial", "platform study", "umbrella study"]

_MONTH_ONLY = re.compile(r'^\d{4}-\d{2}$')


def _valid_date(v):
    v = (v or "").strip()
    return v if re.match(r"^\d{4}-\d{2}-\d{2}$", v) else None


def build_filter_kwargs(input) -> dict:
    """
    Build the shared sidebar-filter portion of a fetch/filter kwargs dict.

    Reads only the filter + sort + max_results widgets (which have the same
    input IDs on the landing page and the main sidebar). Query-text fields
    differ by view, so each caller supplies those separately and merges:

        kwargs = dict(query_cond=..., ..., **build_filter_kwargs(input))
    """
    return dict(
        filter_phase=list(input.filter_phase()) if input.filter_phase() else [],
        filter_status=(
            input.filter_status().split("|") if input.filter_status() else []
        ),
        filter_study_type=list(input.filter_study_type()) if input.filter_study_type() else [],
        filter_funder=list(input.filter_funder()) if input.filter_funder() else [],
        filter_sex=input.filter_sex(),
        filter_healthy=input.filter_healthy(),
        filter_results=input.filter_results(),
        filter_age_min=input.filter_age_min(),
        filter_age_max=input.filter_age_max(),
        filter_start_from=_valid_date(input.filter_start_from()),
        filter_start_to=_valid_date(input.filter_start_to()),
        filter_completion_from=_valid_date(input.filter_completion_from()),
        filter_completion_to=_valid_date(input.filter_completion_to()),
        sort_order=input.sort_order(),
        max_results=int(input.max_results() or 500),
    )


def input_exists(input, name):
    """True if a (possibly dynamically-rendered) input exists and has a value
    available on this reactive flush."""
    try:
        input[name]()
        return True
    except Exception:
        return False


def resolve_selection(input, input_id, valid_values):
    """Active selection for a checkbox group, falling back to *all* valid values
    when the input doesn't exist yet, holds a stale selection from a previous
    dataset, or is empty. `valid_values` = the column's current unique values."""
    valid = set(valid_values)
    raw = list(input[input_id]()) if input_exists(input, input_id) else []
    return raw if raw and set(raw).issubset(valid) else sorted(valid)


def filter_by_selections(df, input, mappings):
    """Filter `df` by one or more checkbox-group selections. `mappings` is an
    iterable of (column, input_id) pairs. Columns absent from `df` are skipped;
    a selection covering every value is a no-op."""
    for col, input_id in mappings:
        if col not in df.columns:
            continue
        valid = df[col].dropna().unique()
        keep = resolve_selection(input, input_id, valid)
        if set(keep) != set(valid):
            df = df[df[col].isin(keep)]
    return df


def _is_isa_master_protocol(title: str, primary_outcome_text: str) -> bool:
    """Return True if this is a master protocol study with ISA in the primary outcome."""
    title_lower = (title or "").lower()
    if not any(kw in title_lower for kw in _MASTER_PROTOCOL_KEYWORDS):
        return False
    # ISA must appear as an exact uppercase token (not case-insensitive)
    return bool(re.search(r'\bISA\b', primary_outcome_text or ""))


def _get(d, *path, default=None):
    """Safely walk a nested dict path."""
    node = d
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
        if node is None:
            return default
    return node


def _extract_title_acronym(title: str, synonym_terms: frozenset = frozenset()) -> str:
    """Extract a trailing all-caps parenthetical from a title, e.g. 'Study (ACRONYM)' → 'ACRONYM'."""
    if not isinstance(title, str):
        return ""
    m = re.search(r'\(([A-Z][A-Z0-9\-]+)\)\s*$', title.strip())
    if not m:
        return ""
    candidate = m.group(1)
    if re.search(r'\d{4,}', candidate):
        return ""
    if candidate.lower() in synonym_terms:
        return ""
    return candidate


def _match_compound(interventions_str: str, query_intr: str = "") -> str:
    """Derive compound name from interventions string and user's search query."""
    if not isinstance(interventions_str, str) or not interventions_str.strip():
        return ""
    # Normalize separators (CSV export uses "|", API-derived uses " | ")
    parts = [p.strip() for p in interventions_str.split('|') if p.strip()]
    parts = [p for p in parts if not _PLACEBO_RE.match(p)]
    if not parts:
        return "Only Placebo Found"
    if not query_intr or not query_intr.strip():
        first_part = parts[0]
        if ':' in first_part:
            name_part = first_part.split(':', 1)[1].strip()
            first_token = name_part.split()[0] if name_part else first_part.split()[0]
        else:
            first_token = first_part.split()[0]
        return first_token.title()

    if re.search(r'\bOR\b', query_intr, re.IGNORECASE):
        # OR logic: find which candidate term matches this study's interventions
        candidates = [t.strip() for t in re.split(r'\bOR\b', query_intr, flags=re.IGNORECASE) if t.strip()]
        for part in parts:
            if any(c.lower() in part.lower() for c in candidates):
                return part
        return parts[0]
    else:
        # AND logic: display user's search terms joined with AND
        terms = [t.strip() for t in re.split(r'[,\s]+', query_intr.strip()) if t.strip()]
        return " AND ".join(terms) if terms else parts[0]


def _join_list(items, key, sep=" | "):
    """Extract a field from a list of dicts and join as a string."""
    if not items or not isinstance(items, list):
        return ""
    parts = [str(i[key]) for i in items if isinstance(i, dict) and i.get(key)]
    return sep.join(parts) if parts else ""


def _join_interventions(items, sep=" | "):
    """Join interventions as 'TYPE: name', falling back to name if type is absent."""
    if not items or not isinstance(items, list):
        return ""
    parts = []
    for i in items:
        if isinstance(i, dict) and i.get("name"):
            t = i.get("type", "")
            parts.append(f"{t}: {i['name']}" if t else i["name"])
    return sep.join(parts) if parts else ""


def _join_outcomes(items, sep=" | "):
    """Join outcome measure + timeFrame, omitting description."""
    if not items or not isinstance(items, list):
        return ""
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        measure = item.get("measure", "")
        timeframe = item.get("timeFrame", "")
        if measure:
            parts.append(f"{measure} ({timeframe})" if timeframe else measure)
    return sep.join(parts) if parts else ""


def _join_outcomes_full(items, sep=" | "):
    """Join outcome measure + timeFrame + description (full text)."""
    if not items or not isinstance(items, list):
        return ""
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        measure     = item.get("measure", "")
        timeframe   = item.get("timeFrame", "")
        description = item.get("description", "")
        if measure:
            entry = f"{measure} ({timeframe})" if timeframe else measure
            if description:
                entry = f"{entry}: {description}"
            parts.append(entry)
    return sep.join(parts) if parts else ""


def _split_eligibility(text: str) -> tuple:
    """Split eligibilityCriteria raw string into (inclusion, exclusion) strings."""
    if not isinstance(text, str) or not text.strip():
        return "", ""
    inc_match = re.search(r'Inclusion Criteria[:\s]*(.*?)(?=Exclusion Criteria|$)', text, re.IGNORECASE | re.DOTALL)
    exc_match = re.search(r'Exclusion Criteria[:\s]*(.*?)$', text, re.IGNORECASE | re.DOTALL)
    inc = inc_match.group(1).strip() if inc_match else ""
    exc = exc_match.group(1).strip() if exc_match else ""
    return inc, exc


def _extract_study(study: dict) -> dict:
    """Extract display fields from one raw API study object."""
    proto       = study.get("protocolSection", {})
    ident       = proto.get("identificationModule", {})
    status_mod  = proto.get("statusModule", {})
    desc        = proto.get("descriptionModule", {})
    design      = proto.get("designModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    outcomes    = proto.get("outcomesModule", {})
    conditions  = proto.get("conditionsModule", {})
    arms        = proto.get("armsInterventionsModule", {})
    eligibility = proto.get("eligibilityModule", {})
    references_mod = proto.get("referencesModule", {})

    # Identity
    nct_id  = ident.get("nctId", "")
    acronym = ident.get("acronym") or ""
    # Use briefTitle as primary — officialTitle is often very long or missing
    title   = ident.get("briefTitle") or ident.get("officialTitle", "")

    # Status & dates
    overall_status          = status_mod.get("overallStatus", "")
    has_results             = study.get("hasResults", False)
    start_date              = _get(status_mod, "startDateStruct",            "date", default="")
    primary_completion_date = _get(status_mod, "primaryCompletionDateStruct","date", default="")
    completion_date         = _get(status_mod, "completionDateStruct",       "date", default="")
    last_update_date        = _get(status_mod, "lastUpdatePostDateStruct",   "date", default="")

    # Design
    phases_list = design.get("phases") or []
    phase_str   = ", ".join(phases_list) if phases_list else "N/A"
    study_type  = design.get("studyType", "")
    enrollment  = _get(design, "enrollmentInfo", "count", default=None)

    # Conditions — list of strings
    cond_list       = conditions.get("conditions") or []
    cond_str        = " | ".join(cond_list) if cond_list else ""
    first_condition = cond_list[0].strip() if cond_list else ""

    # Eligibility criteria — split into inclusion and exclusion
    inc_criteria, exc_criteria = _split_eligibility(eligibility.get("eligibilityCriteria", ""))

    # Interventions — list of dicts with "type" and "name" keys
    intr_list  = arms.get("interventions") or []
    intr_str   = _join_interventions(intr_list)

    # Description
    brief_summary = desc.get("briefSummary", "")

    # Outcomes
    primary_raw   = outcomes.get("primaryOutcomes")   or []
    secondary_raw = outcomes.get("secondaryOutcomes") or []
    primary_str             = _join_outcomes_full(primary_raw)
    secondary_str           = _join_outcomes_full(secondary_raw)
    simplified_primary_str  = _join_outcomes(primary_raw)
    simplified_secondary_str = _join_outcomes(secondary_raw)

    if _is_isa_master_protocol(title, simplified_primary_str):
        simplified_primary_str = primary_str

    # Sponsor
    lead_sponsor = _get(sponsor_mod, "leadSponsor", "name",  default="")
    funder_type  = _get(sponsor_mod, "leadSponsor", "class", default="")

    # Secondary IDs (pipe-joined; used to derive lilly_id downstream)
    secondary_id_infos = ident.get("secondaryIdInfos") or []
    other_ids = " | ".join(item["id"] for item in secondary_id_infos if item.get("id"))
    lilly_id = next(
        (item["id"] for item in secondary_id_infos
         if item.get("domain") == "Eli Lilly and Company" and item.get("id")),
        None
    )

    # CT.gov reference PMIDs — raw IDs passed to the unified PubMed pipeline
    refs_list = references_mod.get("references") or []
    raw_pmids = [ref["pmid"] for ref in refs_list if ref.get("pmid")]
    ctgov_pmids = " | ".join(raw_pmids) if raw_pmids else "NA"

    return {
        "nct_number":                 nct_id,
        "acronym":                    acronym,
        "study_title":                title,
        "conditions":                 cond_str,
        "first_condition":            first_condition,
        "interventions":              intr_str,
        "enrollment":                 enrollment,
        "start_date":                 start_date,
        "primary_completion_date":    primary_completion_date,
        "completion_date":            completion_date,
        "phases":                     phase_str,
        "study_status":               overall_status,
        "study_type":                 study_type,
        "study_results":              "Yes" if has_results else "No",
        "brief_summary":              brief_summary,
        "primary_outcome_measures":          primary_str,
        "secondary_outcome_measures":        secondary_str,
        "simplified_primary_outcome":        simplified_primary_str,
        "simplified_secondary_outcome":      simplified_secondary_str,
        "inclusion_criteria":         inc_criteria,
        "exclusion_criteria":         exc_criteria,
        "sponsor":                    lead_sponsor,
        "funder_type":                funder_type,
        "other_ids":                  other_ids,
        "lilly_id":                   lilly_id,
        "ctgov_pmids":                ctgov_pmids,
        "publications":               "NA",
        "last_update_date":           last_update_date,
    }


def studies_to_dataframe(studies: list) -> pd.DataFrame:
    """
    Convert raw CT.gov API study list to a flat pandas DataFrame.
    Call immediately after fetch and raw JSON is discarded after this.
    """
    if not studies:
        return pd.DataFrame()

    rows = [_extract_study(s) for s in studies]
    df   = pd.DataFrame(rows)

    df["enrollment"] = pd.to_numeric(df["enrollment"], errors="coerce")

    col_order = [
        "nct_number", "acronym", "study_title",
        "conditions", "interventions", "enrollment",
        "start_date", "primary_completion_date", "completion_date",
        "phases", "study_status", "study_type", "study_results",
        "brief_summary",
        "primary_outcome_measures", "secondary_outcome_measures",
        "simplified_primary_outcome", "simplified_secondary_outcome",
        "inclusion_criteria", "exclusion_criteria",
        "sponsor", "funder_type", "other_ids", "lilly_id", "publications",
        "last_update_date",
    ]
    col_order = [c for c in col_order if c in df.columns]
    return df[col_order]


def read_uploaded_csv(path: str) -> pd.DataFrame:
    """Read a user-uploaded CSV and normalise column names."""
    df = pd.read_csv(path, header=0)
    df.columns = [c.strip().lower().replace(" ", "_").replace(".", "_")
                  for c in df.columns]
    return df


def process_raw_ctgov(df: pd.DataFrame, query_intr: str = "") -> pd.DataFrame:
    """
    Process a raw CT.gov DataFrame (from API or uploaded CSV) into the
    canonical form used by all tabs.

    Steps
    -----
    1. Standardise dates
    2. Fill acronym fallback
    3. Derive indication from conditions
    4. Add compound placeholder

    Parameters
    ----------
    df : pd.DataFrame
        Raw DataFrame straight from studies_to_dataframe() or read_uploaded_csv().

    Returns
    -------
    pd.DataFrame
        Processed DataFrame. Rows with all three date columns null/unparseable
        are dropped.
    """
    df = df.copy()

    # ── Step 1: Standardise dates ─────────────────────────────────────────────
    for col in ("start_date", "primary_completion_date", "completion_date", "last_update_date"):
        if col in df.columns:
            # Save original API string before conversion (e.g. "2026-06" or "2024-11-13")
            df[col + "_raw"] = df[col].apply(
                lambda v: v.strip() if isinstance(v, str) else ""
            )
            # Normalize month-only strings ("YYYY-MM") so pd.to_datetime can parse them
            df[col] = df[col].apply(
                lambda v: (v.strip() + "-01")
                if isinstance(v, str) and _MONTH_ONLY.match(v.strip()) else v
            )
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=False)

    # Drop rows where all three date columns are NaT / missing
    date_cols = [c for c in ("start_date", "primary_completion_date", "completion_date")
                 if c in df.columns]
    if date_cols:
        df = df.dropna(subset=date_cols, how="all")

    # ── Step 2: Derive Lilly compound ID (not displayed in `trail info`) ──────────────────────
    if "other_ids" in df.columns and "sponsor" in df.columns:
        def _get_lilly_id(row):
            if row["sponsor"] != "Eli Lilly and Company":
                return None
            if row.get("lilly_id"):
                return row["lilly_id"]
            parts = [p.strip() for p in str(row["other_ids"]).split("|")]
            return parts[1] if len(parts) > 1 else None
        df["lilly_id"] = df.apply(_get_lilly_id, axis=1)
    elif "lilly_id" not in df.columns:
        df["lilly_id"] = None

    # ── Step 3: Acronym fallback ──────────────────────────────────────────────
    if "nct_number" in df.columns:
        synonym_terms = frozenset(term for _, terms in _SYNONYM_RULES for term in terms)

        def _resolve_acronym(r):
            existing = r.get("acronym")
            if isinstance(existing, str):
                existing = existing.strip()
                # Keep existing value only if it looks like a real acronym:
                # not empty and not an NCT number (NCT followed by digits)
                if existing and not re.match(r'^NCT\d+$', existing, re.IGNORECASE):
                    return existing
            title_acronym = _extract_title_acronym(r.get("study_title") or "", synonym_terms)
            if title_acronym:
                return title_acronym
            if isinstance(r.get("lilly_id"), str) and r["lilly_id"].strip():
                return r["lilly_id"][-4:]
            return r.get("nct_number", "")
        df["acronym"] = df.apply(_resolve_acronym, axis=1)

    # ── Step 4: Derive indication ─────────────────────────────────────────────
    _indication_present = (
        "indication" in df.columns
        and df["indication"].notna().any()
        and df["indication"].astype(str).str.strip().ne("").any()
    )
    if not _indication_present:
        if "conditions" in df.columns:
            def _map_row(row):
                conds = row.get("conditions") or row.get("first_condition") or ""
                # Use simplified outcomes for matching if available, fall back to full
                outcome     = row.get("simplified_primary_outcome") or row.get("primary_outcome_measures") or ""
                title       = row.get("study_title") or ""
                sec_outcome = row.get("simplified_secondary_outcome") or row.get("secondary_outcome_measures") or ""
                return map_indication(conds, outcome, title, sec_outcome)
            df["indication"] = df.apply(_map_row, axis=1)
        else:
            df["indication"] = "Other"

    # ── Step 4a: ISA master-protocol — revert simplified outcome to full text ──
    if "simplified_primary_outcome" in df.columns and "study_title" in df.columns:
        isa_mask = df.apply(
            lambda r: _is_isa_master_protocol(
                r.get("study_title", ""),
                r.get("simplified_primary_outcome", "")
            ), axis=1
        )
        if isa_mask.any():
            full_col = df.get("primary_outcome_measures") if "primary_outcome_measures" in df.columns else None
            if full_col is not None:
                df.loc[isa_mask, "simplified_primary_outcome"] = full_col[isa_mask].fillna("")

    # ── Step 5: Derive compound from interventions ────────────────────────────
    _compound_present = (
        "compound" in df.columns
        and df["compound"].notna().any()
        and df["compound"].astype(str).str.strip().ne("").any()
    )
    if not _compound_present:
        if "interventions" in df.columns:
            df["compound"] = df["interventions"].apply(
                lambda x: _match_compound(x, query_intr)
            )
        else:
            df["compound"] = ""

    return df
