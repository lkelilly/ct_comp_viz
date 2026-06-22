"""
pubmed_api.py
─────────────
Enriches the trial DataFrame with PubMed publication links.

Workflow:
  1. Collect seed PMIDs from the ctgov_pmids column (raw IDs from CT.gov references module).
  2. ESearch PubMed for NCTs that had no CT.gov seed PMIDs → additional PMIDs.
  3. Combine seed + ESearch PMIDs → EFetch XML metadata.
  4. Parse each article for NCT accession number and regex-scan title/abstract as a fallback.
  5. Invert the PMID → NCTs mapping to NCT → {pmids, source}.
  6. Fill 'publications' for every row via NCT lookup.
  7. Assign source "pubmed registry" (DataBankList) or "pubmed abstract" (regex).
  8. Write results to 'primary_result_publication' and 'publication_source'.
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests
import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

_BASE_PARAMS = {
    "tool":  "ct_comp_viz",
    "email": "liuhan.ke@lilly.com",
    # "api_key": "",
}

_NCT_RE = re.compile(r"\bNCT\d{8}\b")
_EFETCH_BATCH = 500
_SLEEP_BETWEEN_BATCHES = 0.35

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_SECONDARY_KEYWORDS = [
    "post hoc", "post-hoc", "secondary analysis", "exploratory analysis",
    "subgroup analysis", "sub-group", "sensitivity analysis", "pooled analysis",
    "meta-analysis", "network meta-analysis", "integrated analysis",
    "individual patient data", "open-label extension", "extension study",
    "long-term follow-up", "follow-up analysis", "mediation analysis",
    "predictors of", "prognostic factors", "design and rationale",
    "study protocol", "baseline characteristics",
]

_AGGREGATION_KEYWORDS = ["pooled", "meta"]

_PRIORITY_JOURNALS = frozenset([
    "new england journal of medicine", "the new england journal of medicine",
    "lancet", "the lancet",
    "jama", "jama: the journal of the american medical association",
    "bmj", "bmj (clinical research ed.)",
    "annals of internal medicine",
    "nature medicine",
])


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_pub_date(pub_date_el: "ET.Element | None") -> "date | None":
    """Parse a PubMed <PubDate> element into a datetime.date, or None on failure."""
    if pub_date_el is None:
        return None
    year_el  = pub_date_el.find("Year")
    month_el = pub_date_el.find("Month")
    day_el   = pub_date_el.find("Day")
    # Fallback: <MedlineDate> e.g. "2020 Jan-Feb" or "2020 Winter"
    if year_el is None:
        med_el = pub_date_el.find("MedlineDate")
        if med_el is not None and med_el.text:
            m = re.match(r"(\d{4})\s+([A-Za-z]+)", med_el.text)
            if m:
                yr = int(m.group(1))
                mo = _MONTH_MAP.get(m.group(2).lower()[:3], 1)
                return date(yr, mo, 1)
        return None
    try:
        yr = int(year_el.text or "")
        mo = _MONTH_MAP.get((month_el.text or "").lower()[:3], 1) if month_el is not None else 1
        dy = int(day_el.text) if day_el is not None and day_el.text and day_el.text.isdigit() else 1
        return date(yr, mo, dy)
    except (ValueError, TypeError):
        return None

def _build_search_query(nct_numbers: list) -> str:
    """Build a PubMed OR query searching each NCT number in [si] and [tiab]."""
    terms = []
    for nct in nct_numbers:
        terms.append(f"{nct}[si]")
        terms.append(f"{nct}[tiab]")
    return " OR ".join(terms)


def _esearch(query: str) -> list:
    """POST query to PubMed ESearch; return list of PMID strings."""
    params = {
        **_BASE_PARAMS,
        "db":      "pubmed",
        "term":    query,
        "retmode": "json",
        "retmax":  "10000",
    }
    resp = requests.post(ESEARCH_URL, data=params, timeout=60)
    resp.raise_for_status()
    return resp.json().get("esearchresult", {}).get("idlist", [])


def _efetch_xml(pmids: list) -> ET.Element:
    """Batch-fetch PubMed XML for a list of PMIDs; return a synthetic root element."""
    root = ET.Element("PubmedArticleSet")
    for i in range(0, len(pmids), _EFETCH_BATCH):
        batch = pmids[i: i + _EFETCH_BATCH]
        params = {
            **_BASE_PARAMS,
            "db":      "pubmed",
            "id":      ",".join(batch),
            "retmode": "xml",
            "rettype": "pubmed",
        }
        resp = requests.post(EFETCH_URL, data=params, timeout=120)
        resp.raise_for_status()
        batch_root = ET.fromstring(resp.text)
        for article in batch_root.findall("PubmedArticle"):
            root.append(article)
        if i + _EFETCH_BATCH < len(pmids):
            time.sleep(_SLEEP_BETWEEN_BATCHES)
    return root


def _parse_pmid_to_ncts(xml_root: ET.Element) -> dict:
    """
    For each PubmedArticle extract NCT numbers and article metadata:
      1. DataBankList (formal ClinicalTrials.gov links) — high precision
      2. Regex scan of ArticleTitle + AbstractText — broader coverage
    Returns {pmid: {"ncts": [...], "registry_ncts": {...}, "title": str,
                    "pub_date": date|None, "journal": str}}.
    """
    result = {}
    for article in xml_root.findall("PubmedArticle"):
        pmid_el = article.find(".//PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()
        ncts = set()
        registry_ncts = set()

        # Formal DataBank links — high precision
        for db in article.findall(".//DataBank"):
            name_el = db.find("DataBankName")
            if name_el is not None and name_el.text == "ClinicalTrials.gov":
                for acc in db.findall(".//AccessionNumber"):
                    if acc.text:
                        registry_ncts.add(acc.text.strip())
        ncts.update(registry_ncts)

        # Regex scan on title + abstract — broader coverage
        title_el = article.find(".//ArticleTitle")
        title = (title_el.text or "") if title_el is not None else ""
        if title:
            ncts.update(_NCT_RE.findall(title))
        for abs_el in article.findall(".//AbstractText"):
            if abs_el.text:
                ncts.update(_NCT_RE.findall(abs_el.text))

        if not ncts:
            continue

        # Publication date — prefer JournalIssue/PubDate, fallback ArticleDate
        pub_date = _parse_pub_date(article.find(".//JournalIssue/PubDate"))
        if pub_date is None:
            pub_date = _parse_pub_date(article.find(".//ArticleDate"))

        # Journal full title
        journal_el = article.find(".//Journal/Title")
        journal = (journal_el.text or "").strip() if journal_el is not None else ""

        result[pmid] = {
            "ncts":          list(ncts),
            "registry_ncts": registry_ncts,
            "title":         title,
            "pub_date":      pub_date,
            "journal":       journal,
        }
    return result


def _invert_mapping(pmid_to_ncts: dict) -> dict:
    """
    Invert {pmid: {"ncts": [...], "registry_ncts": {...}, "title": ..., ...}}
    → {nct: {"articles": [{"pmid":..,"title":..,"pub_date":..,"journal":..,"registry_ncts":{..}}, ...],
             "source": "pubmed registry"|"pubmed abstract"}}.
    Source is "pubmed registry" if any article found the NCT via DataBankList.
    """
    nct_to_info: dict = {}
    for pmid, info in pmid_to_ncts.items():
        article = {
            "pmid":          pmid,
            "title":         info.get("title", ""),
            "pub_date":      info.get("pub_date"),
            "journal":       info.get("journal", ""),
            "registry_ncts": info.get("registry_ncts", set()),
        }
        for nct in info["ncts"]:
            entry = nct_to_info.setdefault(nct, {"articles": [], "source": "pubmed abstract"})
            entry["articles"].append(article)
            if nct in info["registry_ncts"]:
                entry["source"] = "pubmed registry"
    return nct_to_info


# ── Public API ────────────────────────────────────────────────────────────────

def pick_primary_publication(articles: list, primary_completion_date=None) -> str:
    """
    Select the single best primary-results publication from a list of article dicts.
    Each dict has keys: pmid, title, pub_date (date|None), journal, registry_ncts (set).

    Rules applied in order:
      1. Drop papers published before (primary_completion_date - 2 months). Grace period
         of 2 months is applied to the cutoff. Articles with no pub_date are kept.
         If 0 survive → return "no results yet | url1 | url2 ..."
      2. If exactly 1 survives → return its URL.
      3. Split into master-protocol papers (registry_ncts has >1 NCT) and non-master.
         Drop aggregation papers (title contains "pooled" or "meta") from both groups.
         Prefer non-master pool; fall back to master pool; fall back to all survivors.
         If 1 survives → return URL (prefixed "master protocol | " if it's a master article).
      4. Drop papers whose title contains any secondary-analysis keyword.
         If all would be dropped, keep the current pool unchanged.
         If 1 survives → return URL.
      5. Sort by pub_date ascending (None last), tie-break by priority journal membership.
         Return the winner's URL.
    """
    if not articles:
        return "NA"

    def _url(a: dict) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"

    # ── Rule 1: drop papers before primary_completion_date − 2 months ──────────
    all_urls = " | ".join(_url(a) for a in articles)
    cutoff = None
    if primary_completion_date is not None:
        try:
            from datetime import timedelta
            pcd = primary_completion_date
            if hasattr(pcd, "to_pydatetime"):
                pcd = pcd.to_pydatetime().date()
            elif hasattr(pcd, "date") and callable(pcd.date):
                pcd = pcd.date()
            pcd_date: date = pcd  # type: ignore[assignment]
            cutoff = date(pcd_date.year, pcd_date.month, pcd_date.day) - timedelta(days=60)
        except Exception:
            cutoff = None

    if cutoff is not None:
        survivors = [a for a in articles if a["pub_date"] is None or a["pub_date"] >= cutoff]
    else:
        survivors = list(articles)

    if not survivors:
        return f"no results yet, but found paper | {all_urls}"

    # ── Rule 2: single survivor ────────────────────────────────────────────────
    if len(survivors) == 1:
        return _url(survivors[0])

    # ── Rule 3: master protocol / aggregation filtering ────────────────────────
    def _is_aggregation(a: dict) -> bool:
        t = a["title"].lower()
        return any(kw in t for kw in _AGGREGATION_KEYWORDS)

    def _is_master(a: dict) -> bool:
        return len(a["registry_ncts"]) > 1

    non_master = [a for a in survivors if not _is_master(a) and not _is_aggregation(a)]
    master     = [a for a in survivors if  _is_master(a) and not _is_aggregation(a)]

    if non_master:
        pool = non_master
        pool_is_master = False
    elif master:
        pool = master
        pool_is_master = True
    else:
        # All were aggregation — fall back to all survivors
        pool = survivors
        pool_is_master = False

    if len(pool) == 1:
        prefix = "master protocol | " if pool_is_master else ""
        return f"{prefix}{_url(pool[0])}"

    # ── Rule 4: drop secondary-analysis papers ─────────────────────────────────
    def _is_secondary(a: dict) -> bool:
        t = a["title"].lower()
        return any(kw in t for kw in _SECONDARY_KEYWORDS)

    filtered = [a for a in pool if not _is_secondary(a)]
    if filtered:
        pool = filtered

    if len(pool) == 1:
        return _url(pool[0])

    # ── Rule 5: earliest after completion, tie-break by priority journal ────────
    def _sort_key(a: dict):
        # (pub_date or far-future, not-priority-journal)
        d = a["pub_date"] if a["pub_date"] is not None else date(9999, 12, 31)
        in_priority = a["journal"].lower().strip() in _PRIORITY_JOURNALS
        return (d, not in_priority)

    pool.sort(key=_sort_key)
    return _url(pool[0])


def add_publications(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich the trial DataFrame with publication data and provenance.

    Seed PMIDs from the ctgov_pmids column (CT.gov references module) are
    combined with ESearch results for NCTs that had no seed PMIDs, then all
    are run through the same EFetch + NCT-matching pipeline. Source is
    "pubmed registry" (DataBankList hit) or "pubmed abstract" (regex scan).

    Writes 'primary_result_publication' and 'publication_source'.
    Safe to call on both CT.gov-fetched and user-uploaded DataFrames.
    Network errors are caught silently.
    """
    df = df.copy()

    if "publications" not in df.columns:
        df["publications"] = "NA"

    nct_col = "nct_number" if "nct_number" in df.columns else None
    nct_source_map: dict = {}

    try:
        # Step 1: seed PMIDs from CT.gov references
        seed_pmids: list = []
        if "ctgov_pmids" in df.columns:
            for val in df["ctgov_pmids"].dropna():
                if isinstance(val, str) and val != "NA":
                    seed_pmids.extend(p.strip() for p in val.split(" | ") if p.strip())
        seed_pmids = list(dict.fromkeys(seed_pmids))

        # Step 2: ESearch for NCTs that have no CT.gov seed PMIDs
        esearch_pmids: list = []
        if nct_col is not None:
            if "ctgov_pmids" in df.columns:
                no_ctgov_mask = df["ctgov_pmids"].apply(
                    lambda v: not isinstance(v, str) or v == "NA"
                )
            else:
                no_ctgov_mask = pd.Series([True] * len(df), index=df.index)
            no_pub_ncts = (
                df.loc[no_ctgov_mask, nct_col]
                .dropna().unique().tolist()
            )
            no_pub_ncts = [n for n in no_pub_ncts if isinstance(n, str) and n.startswith("NCT")]
            if no_pub_ncts:
                esearch_pmids = _esearch(_build_search_query(no_pub_ncts))

        # Step 3: Combine + EFetch
        all_pmids = list(dict.fromkeys(seed_pmids + esearch_pmids))
        nct_map: dict = {}
        if all_pmids:
            xml_root = _efetch_xml(all_pmids)
            pmid_map = _parse_pmid_to_ncts(xml_root)
            nct_map  = _invert_mapping(pmid_map)
            nct_source_map = {nct: info["source"] for nct, info in nct_map.items()}

        # Step 4: Fill publications via NCT lookup
        if nct_col and nct_map:
            def _fill(row):
                nct = row.get(nct_col, "")
                if nct and nct in nct_map:
                    links = [
                        f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"
                        for a in nct_map[nct]["articles"]
                    ]
                    return " | ".join(links)
                return "NA"
            df["publications"] = df.apply(_fill, axis=1)

    except Exception:
        pass  # Leave publications unchanged on any network/parse error

    # Step 5: Write primary_result_publication and publication_source
    def _build_row(row):
        nct  = row.get(nct_col, "") if nct_col else ""
        pubs = row["publications"]
        if pubs == "NA" or nct not in nct_map:
            return "NA", "NA"
        articles = nct_map[nct]["articles"]
        primary  = pick_primary_publication(articles, row.get("primary_completion_date"))
        source   = nct_source_map.get(nct, "pubmed abstract")
        return primary, source

    df[["primary_result_publication", "publication_source"]] = df.apply(
        _build_row, axis=1, result_type="expand"
    )
    return df
