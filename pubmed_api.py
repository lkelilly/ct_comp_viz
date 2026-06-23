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
  8. Fetch citation counts from the NIH iCite API and attach to each article.
  9. Apply filtering rules: keep all priority-journal articles unconditionally,
     then select <=2 non-priority publications per trial.
  10. Write results to 'relevant_publication' and 'publication_source'.
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests
import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ICITE_URL   = "https://icite.od.nih.gov/api/pubs"

_BASE_PARAMS = {
    "tool":  "ct_comp_viz",
    "email": "liuhan.ke@lilly.com",
    # "api_key": "",
}

_NCT_RE = re.compile(r"\bNCT\d{8}\b")
_EFETCH_BATCH = 500
_ICITE_BATCH  = 200          # iCite recommends <=200 PMIDs per request
_SLEEP_BETWEEN_BATCHES = 0.35

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

MAX_RELEVANT_PUBS = 2

# Secondary / post-hoc keywords — articles matching these are dropped (Rule 4).
_SECONDARY_KEYWORDS = [
    "post hoc", "post-hoc",
    "secondary analysis", "exploratory analysis",
    "subgroup analysis", "sub-group",
    "sensitivity analysis",
    "pooled analysis", "pooled",
    "integrated analysis",
    "individual patient data",
    "open-label extension", "extension study",
    "long-term follow-up", "follow-up analysis",
    "predictors of", "prognostic factors",
    "baseline characteristics",
    "mediation analysis",
]

# Design-paper keywords — these get special treatment in the date-filter step
# (Rule 3 exception): instead of being dropped, they are ranked by citation
# count and the most-cited one is kept.
_DESIGN_KEYWORDS = [
    "design and rationale",
    "study protocol",
    "study design",
    "trial design",
    "rationale and design",
    "protocol for",
    "design of",
]

_PRIORITY_JOURNALS = {
    "new england journal of medicine", "the new england journal of medicine",
    "lancet", "the lancet",
    "jama", "jama: the journal of the american medical association",
    "bmj", "bmj (clinical research ed.)",
    "annals of internal medicine",
    "nature medicine",
}


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


def _fetch_citation_counts(pmids: list) -> dict:
    """
    Query the NIH iCite API for citation counts.
    Returns {pmid_str: int} — missing PMIDs default to 0.
    """
    counts: dict = {}
    if not pmids:
        return counts
    for i in range(0, len(pmids), _ICITE_BATCH):
        batch = pmids[i: i + _ICITE_BATCH]
        try:
            resp = requests.get(
                ICITE_URL,
                params={"pmids": ",".join(batch)},
                timeout=60,
            )
            resp.raise_for_status()
            for item in resp.json().get("data", []):
                pid = str(item.get("pmid", ""))
                counts[pid] = int(item.get("citation_count", 0) or 0)
        except Exception:
            pass  # Graceful degradation — missing counts treated as 0
        if i + _ICITE_BATCH < len(pmids):
            time.sleep(_SLEEP_BETWEEN_BATCHES)
    return counts


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
    → {nct: {"articles": [...], "source": "pubmed registry"|"pubmed abstract"}}.
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

def pick_relevant_publications(articles: list, primary_completion_date=None) -> str:
    """
    Select relevant publications from a list of article dicts.
    Each dict has keys: pmid, title, pub_date (date|None), journal,
    registry_ncts (set), citation_count (int, default 0).

    Logic overview:
      1. Separate priority-journal articles. These are always kept and never dropped.
      2. If priority articles already fill the quota (>= MAX_RELEVANT_PUBS),
         return only those — no non-priority filtering needed.
      3. Otherwise, compute remaining_slots = MAX_RELEVANT_PUBS - len(priority).
         Apply rules 3–5 to non-priority articles to fill those slots:
           3a. Drop articles published before (primary_completion_date - 2 months).
               Articles with no pub_date are kept.  
               Exception: design papersamong the dropped are ranked by citation; 
               the most-cited one is kept. 
           3b. Drop secondary / post-hoc analyses (_SECONDARY_KEYWORDS). Meta-analyses are NOT dropped.
           3c. If still more than remaining_slots, rank by citation count and take the top remaining_slots.

    Display order: priority articles first (by citation desc), then
    non-priority articles (by citation desc).

    Returns pipe-separated PubMed URLs, or "NA" if no articles.
    """
    if not articles:
        return "NA"

    def _url(a: dict) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"

    def _is_priority(a: dict) -> bool:
        return a["journal"].lower().strip() in _PRIORITY_JOURNALS

    def _is_design(a: dict) -> bool:
        t = a["title"].lower()
        return any(kw in t for kw in _DESIGN_KEYWORDS)

    def _is_secondary(a: dict) -> bool:
        t = a["title"].lower()
        return any(kw in t for kw in _SECONDARY_KEYWORDS)

    def _cite_count(a: dict) -> int:
        return a.get("citation_count", 0)

    # ── Step 1: split into priority vs non-priority ───────────────────────
    priority_articles = sorted(
        [a for a in articles if _is_priority(a)],
        key=_cite_count, reverse=True,
    )
    non_priority = [a for a in articles if not _is_priority(a)]

    # ── Step 2: if priority already fills the quota, return them only ─────
    if len(priority_articles) >= MAX_RELEVANT_PUBS:
        return " | ".join(_url(a) for a in priority_articles)

    remaining_slots = MAX_RELEVANT_PUBS - len(priority_articles)

    # ── Step 2b: if non-priority already fits, keep all — skip filtering ──
    if len(non_priority) <= remaining_slots:
        non_priority.sort(key=_cite_count, reverse=True)
        return " | ".join(_url(a) for a in priority_articles + non_priority)

    # ── Step 3a: date filter on non-priority articles ─────────────────────
    cutoff = None
    if primary_completion_date is not None:
        try:
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
        passed_date = [a for a in non_priority if a["pub_date"] is None or a["pub_date"] >= cutoff]
        dropped     = [a for a in non_priority if a["pub_date"] is not None and a["pub_date"] < cutoff]

        # Exception: among dropped articles, rescue the most-cited design paper
        design_dropped = [a for a in dropped if _is_design(a)]
        rescued_design = None
        if design_dropped:
            design_dropped.sort(key=_cite_count, reverse=True)
            rescued_design = design_dropped[0]

        pool = passed_date
        if rescued_design is not None:
            pool.append(rescued_design)
    else:
        pool = list(non_priority)

    # ── Step 3b: drop secondary / post-hoc analyses ───────────────────────
    filtered = [a for a in pool if not _is_secondary(a)]
    if filtered:
        pool = filtered
    # (If all would be dropped, keep the pool unchanged)

    # ── Step 3c: if still more than remaining_slots, rank by citation ─────
    pool.sort(key=_cite_count, reverse=True)
    if len(pool) > remaining_slots:
        pool = pool[:remaining_slots]

    # ── Combine: priority (by citation) then non-priority (by citation) ───
    combined = priority_articles + pool
    if not combined:
        return "NA"
    return " | ".join(_url(a) for a in combined)


def add_publications(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich the trial DataFrame with publication data and provenance.

    Seed PMIDs from the ctgov_pmids column (CT.gov references module) are
    combined with ESearch results for NCTs that had no seed PMIDs, then all
    are run through the same EFetch + NCT-matching pipeline. iCite citation
    counts are fetched and attached. Source is "pubmed registry" (DataBankList
    hit) or "pubmed abstract" (regex scan).

    Writes 'relevant_publication' and 'publication_source'.
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

            # Step 3b: Fetch citation counts from iCite and attach to articles
            unique_pmids = list(pmid_map.keys())
            cite_counts = _fetch_citation_counts(unique_pmids)
            for nct, info in nct_map.items():
                for article in info["articles"]:
                    article["citation_count"] = cite_counts.get(article["pmid"], 0)

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

    # Step 5: Write relevant_publication and publication_source
    def _build_row(row):
        nct  = row.get(nct_col, "") if nct_col else ""
        pubs = row["publications"]
        if pubs == "NA" or nct not in nct_map:
            return "No Article Found", "NA"
        articles = nct_map[nct]["articles"]
        relevant = pick_relevant_publications(articles, row.get("primary_completion_date"))
        source   = nct_source_map.get(nct, "pubmed abstract")
        return relevant, source

    df[["relevant_publication", "publication_source"]] = df.apply(
        _build_row, axis=1, result_type="expand"
    )
    return df