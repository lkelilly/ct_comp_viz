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

from indication_mapping import map_indication, _SYNONYM_RULES


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
    # Normalize separators (CSV export uses "|", API-derived uses " | ") and strip type prefixes
    raw_parts = [p.strip() for p in re.split(r'\s*\|\s*', interventions_str) if p.strip()]
    parts = [re.sub(r'^[A-Z_]+:\s*', '', p) for p in raw_parts]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if not query_intr or not query_intr.strip():
        return parts[0]

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

    # Identity
    nct_id  = ident.get("nctId", "")
    acronym = ident.get("acronym") or ""
    # Use briefTitle as primary — officialTitle is often very long or missing
    title   = ident.get("briefTitle") or ident.get("officialTitle", "")

    # Status & dates
    overall_status          = status_mod.get("overallStatus", "")
    has_results             = study.get("hasResults", False)
    start_date              = _get(status_mod, "startDateStruct",           "date", default="")
    primary_completion_date = _get(status_mod, "primaryCompletionDateStruct","date", default="")
    completion_date         = _get(status_mod, "completionDateStruct",       "date", default="")

    # Design
    phases_list = design.get("phases") or []
    phase_str   = ", ".join(phases_list) if phases_list else "N/A"
    study_type  = design.get("studyType", "")
    enrollment  = _get(design, "enrollmentInfo", "count", default=None)

    # Conditions — list of strings
    cond_list       = conditions.get("conditions") or []
    cond_str        = " | ".join(cond_list) if cond_list else ""
    first_condition = cond_list[0].strip() if cond_list else ""

    # Interventions — list of dicts with "name" key
    intr_list  = arms.get("interventions") or []
    intr_str   = _join_list(intr_list, "name")

    # Description
    brief_summary = desc.get("briefSummary", "")

    # Outcomes
    primary_raw   = outcomes.get("primaryOutcomes")   or []
    secondary_raw = outcomes.get("secondaryOutcomes") or []
    primary_str             = _join_outcomes_full(primary_raw)
    secondary_str           = _join_outcomes_full(secondary_raw)
    simplified_primary_str  = _join_outcomes(primary_raw)
    simplified_secondary_str = _join_outcomes(secondary_raw)

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
        "sponsor":                    lead_sponsor,
        "funder_type":                funder_type,
        "other_ids":                  other_ids,
        "lilly_id":                   lilly_id,
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
        "sponsor", "funder_type", "other_ids", "lilly_id",
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
    for col in ("start_date", "primary_completion_date", "completion_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=False)

    # Drop rows where all three date columns are NaT / missing
    date_cols = [c for c in ("start_date", "primary_completion_date", "completion_date")
                 if c in df.columns]
    if date_cols:
        df = df.dropna(subset=date_cols, how="all")

    # ── Step 2: Derive Lilly compound ID (backend only) ──────────────────────
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
    if "conditions" in df.columns:
        def _map_row(row):
            first_cond = row.get("first_condition") or ""
            if not first_cond:
                first_cond = str(row.get("conditions") or "").split(" | ")[0].strip()
            # Use simplified outcomes for matching if available, fall back to full
            outcome     = row.get("simplified_primary_outcome") or row.get("primary_outcome_measures") or ""
            title       = row.get("study_title") or ""
            sec_outcome = row.get("simplified_secondary_outcome") or row.get("secondary_outcome_measures") or ""
            return map_indication(first_cond, outcome, title, sec_outcome)
        df["indication"] = df.apply(_map_row, axis=1)
    else:
        df["indication"] = "Other"

    # ── Step 5: Derive compound from interventions ────────────────────────────
    if "interventions" in df.columns:
        df["compound"] = df["interventions"].apply(
            lambda x: _match_compound(x, query_intr)
        )
    else:
        df["compound"] = ""

    return df


def filter_upload_data(df: pd.DataFrame, kwargs: dict) -> pd.DataFrame:
    """
    Apply sidebar filter kwargs to an already-processed upload DataFrame.
    Returns a filtered, sorted, and capped copy. Never mutates the input.
    """
    import re

    mask = pd.Series(True, index=df.index)

    # ── Substring filters ─────────────────────────────────────────────────────
    def _sub(col, val):
        nonlocal mask
        if val and col in df.columns:
            mask &= df[col].fillna("").str.contains(val, case=False, na=False)

    _sub("conditions",    kwargs.get("query_cond"))
    _sub("interventions", kwargs.get("query_intr"))
    _sub("sponsor",       kwargs.get("query_spons"))
    _sub("study_title",   kwargs.get("query_titles"))
    _sub("nct_number",    kwargs.get("query_id"))

    term = kwargs.get("query_term")
    if term:
        text_cols = [c for c in ("study_title", "conditions", "interventions",
                                  "brief_summary", "sponsor") if c in df.columns]
        combined = df[text_cols].fillna("").agg(" ".join, axis=1)
        mask &= combined.str.contains(term, case=False, na=False)

    outc = kwargs.get("query_outc")
    if outc:
        outc_cols = [c for c in ("primary_outcome_measures", "secondary_outcome_measures")
                     if c in df.columns]
        if outc_cols:
            combined_outc = df[outc_cols].fillna("").agg(" ".join, axis=1)
            mask &= combined_outc.str.contains(outc, case=False, na=False)

    # query_locn, filter_sex, filter_healthy, filter_age_* → no columns, skip silently

    # ── Phase filter ──────────────────────────────────────────────────────────
    phases = [p for p in (kwargs.get("filter_phase") or []) if p]
    if phases and "phases" in df.columns:
        norm_selected = {re.sub(r"[^a-z0-9]", "", p.lower()) for p in phases}

        def _phase_tokens(cell):
            return {re.sub(r"[^a-z0-9]", "", t.lower()) for t in str(cell).split(",")}

        mask &= df["phases"].apply(lambda c: bool(_phase_tokens(c) & norm_selected))

    # ── Status filter ─────────────────────────────────────────────────────────
    statuses = [s for s in (kwargs.get("filter_status") or []) if s]
    if statuses and "study_status" in df.columns:
        mask &= df["study_status"].isin(statuses)

    # ── Study type filter ─────────────────────────────────────────────────────
    study_types = [t for t in (kwargs.get("filter_study_type") or []) if t]
    if study_types and "study_type" in df.columns:
        mask &= df["study_type"].isin(study_types)

    # ── Funder type filter ────────────────────────────────────────────────────
    funders = [f for f in (kwargs.get("filter_funder") or []) if f]
    if funders and "funder_type" in df.columns:
        mask &= df["funder_type"].isin(funders)

    # ── Results filter ────────────────────────────────────────────────────────
    results_val = kwargs.get("filter_results")
    if results_val and results_val != "Any" and "study_results" in df.columns:
        target = "Yes" if results_val == "With results" else "No"
        mask &= df["study_results"] == target

    # ── Enrollment range ──────────────────────────────────────────────────────
    enroll_min = kwargs.get("filter_enroll_min")
    enroll_max = kwargs.get("filter_enroll_max")
    if (enroll_min is not None or enroll_max is not None) and "enrollment" in df.columns:
        enroll = pd.to_numeric(df["enrollment"], errors="coerce")
        if enroll_min is not None:
            mask &= enroll.fillna(0) >= enroll_min
        if enroll_max is not None:
            mask &= enroll.fillna(0) <= enroll_max

    # ── Date ranges ───────────────────────────────────────────────────────────
    def _date_range(col, from_str, to_str):
        nonlocal mask
        if col not in df.columns:
            return
        series = df[col]
        if from_str:
            try:
                mask &= series.notna() & (series >= pd.Timestamp(from_str))
            except Exception:
                pass
        if to_str:
            try:
                mask &= series.notna() & (series <= pd.Timestamp(to_str))
            except Exception:
                pass

    _date_range("start_date",
                kwargs.get("filter_start_from"), kwargs.get("filter_start_to"))
    _date_range("primary_completion_date",
                kwargs.get("filter_completion_from"), kwargs.get("filter_completion_to"))

    df = df[mask].copy()

    # ── Sort ──────────────────────────────────────────────────────────────────
    sort_map = {
        "StartDate:desc":       ("start_date",  False),
        "StartDate:asc":        ("start_date",  True),
        "EnrollmentCount:desc": ("enrollment",  False),
    }
    sort_spec = sort_map.get(kwargs.get("sort_order") or "")
    if sort_spec is not None:
        col, asc = sort_spec
        if col in df.columns:
            df = df.sort_values(col, ascending=asc, na_position="last")

    # ── Cap results ───────────────────────────────────────────────────────────
    max_results = int(kwargs.get("max_results") or 500)
    return df.head(max_results).reset_index(drop=True)