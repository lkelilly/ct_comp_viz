"""
ct_api.py
─────────
ClinicalTrials.gov API v2 connection layer.

Uses requests (synchronous) run inside a thread executor, preventing
Shiny async event loop from being blocked.
"""

import re
import requests
import time

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
_MAX_PAGE_SIZE = 1000

# Session is reused across pages for connection pooling
_session = requests.Session()
_session.headers.update({
    "Accept": "application/json",
})


class CTGovAPIError(Exception):
    pass

class CTGovNetworkError(Exception):
    pass


# ── Public async entry point ──────────────────────────────────────────────────

async def fetch_studies(
    query_cond=None,   query_intr=None,  query_term=None,   query_titles=None,
    query_spons=None,  query_locn=None,  query_id=None,     query_outc=None,
    query_other_id=None,
    filter_phase=None,       filter_status=None,    filter_study_type=None,
    filter_funder=None,      filter_sex=None,       filter_healthy=False,
    filter_results=None,     filter_age_min=None,   filter_age_max=None,
    filter_start_from=None,  filter_start_to=None,
    filter_completion_from=None, filter_completion_to=None,
    sort_order="LastUpdatePostDate:desc",
    max_results=500,
    progress_callback=None,
    retry_callback=None,
):
    """
    Async wrapper — runs the blocking fetch in a thread so Shiny stays responsive.
    Returns (studies: list[dict], total_count: int).
    """
    import asyncio
    loop = asyncio.get_event_loop()

    params = _build_params(
        query_cond, query_intr, query_term, query_titles,
        query_spons, query_locn, query_id, query_outc, query_other_id,
        filter_phase, filter_status, filter_study_type, filter_funder,
        filter_sex, filter_healthy, filter_results,
        filter_age_min, filter_age_max,
        filter_start_from, filter_start_to,
        filter_completion_from, filter_completion_to,
        sort_order, max_results,
    )

    # Wrap the sync paginator so we can call the async progress_callback /
    # retry_callback from inside a thread. We collect events in queues and
    # drain them on the event loop side after each page / retry.
    import queue
    progress_q = queue.Queue()
    retry_q    = queue.Queue()

    def _sync_progress(fetched, total):
        progress_q.put((fetched, total))

    def _sync_on_retry(attempt, max_attempts, reason):
        retry_q.put((attempt, max_attempts, reason))

    def _blocking_fetch():
        return _paginate(params, max_results, _sync_progress, _sync_on_retry)

    # Run the blocking call in a thread pool
    result_future = loop.run_in_executor(None, _blocking_fetch)

    async def _drain_queues():
        while not progress_q.empty():
            fetched, tot = progress_q.get_nowait()
            if progress_callback:
                await progress_callback(fetched, tot)
        while not retry_q.empty():
            attempt, max_attempts, reason = retry_q.get_nowait()
            if retry_callback:
                await retry_callback(attempt, max_attempts, reason)

    error = None
    while True:
        await _drain_queues()

        # Check if the thread finished
        if result_future.done():
            try:
                studies, total = result_future.result()
            except Exception as e:
                error = e
            break

        await asyncio.sleep(0.3)   # yield to event loop; check again soon

    # Final drain
    await _drain_queues()

    if error:
        raise error

    return studies, total


# ── Sync internals ────────────────────────────────────────────────────────────

def _paginate(params, max_results, progress_cb, on_retry=None):
    studies     = []
    total_count = None
    page_token  = None

    while True:
        if page_token:
            params = dict(params, pageToken=page_token)

        data = _get(params, on_retry=on_retry)

        if total_count is None:
            total_count = data.get("totalCount", 0)

        page_studies = data.get("studies", [])
        studies.extend(page_studies)

        if progress_cb:
            progress_cb(len(studies), total_count)

        if len(studies) >= max_results:
            studies = studies[:max_results]
            break

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        time.sleep(0.2)

    return studies, total_count


def _get(params, on_retry=None, max_retries=2):
    attempt = 0
    while True:
        try:
            resp = _session.get(BASE_URL, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            if attempt >= max_retries:
                raise CTGovNetworkError(f"Network error: {e}") from e
            if on_retry:
                on_retry(attempt + 1, max_retries, str(e))
            time.sleep(2 ** attempt)
            attempt += 1
            continue

        if resp.status_code >= 500 and attempt < max_retries:
            if on_retry:
                on_retry(attempt + 1, max_retries, f"HTTP {resp.status_code}")
            time.sleep(2 ** attempt)
            attempt += 1
            continue

        if resp.status_code != 200:
            raise CTGovAPIError(
                f"CT.gov API returned HTTP {resp.status_code}: {resp.text[:300]}"
            )

        return resp.json()


# ── Parameter builder ─────────────────────────────────────────────────────────

## current filters and stuff, subject to change if needed

# CT.gov's Essie parser AND-matches bare whitespace-separated words by default
# (e.g. "oral semaglutide" == "oral AND semaglutide"). Quoting a multi-word
# term forces exact-phrase matching instead, which is the behavior we want.
_ESSIE_SPECIAL_RE = re.compile(r'["\[\]()]|\b(?:AND|OR|NOT)\b', re.IGNORECASE)


def _quote_phrase(text):
    text = text.strip()
    if not text or " " not in text or _ESSIE_SPECIAL_RE.search(text):
        return text
    return f'"{text}"'


# Only these mark query_intr as "advanced Essie syntax" the user wrote on
# purpose — in that case we leave it as one opaque term rather than splitting
# on OR (mirrors the untouched-passthrough branch of _quote_phrase).
_ESSIE_ADVANCED_RE = re.compile(r'["\[\]()]|\b(?:AND|NOT)\b', re.IGNORECASE)


def split_compound_terms(query_intr, query_other_id):
    """
    Return the individual compound terms implied by the Intervention box and
    the alternative-compound-name box, so callers can fetch each one
    separately instead of sending one combined OR query to CT.gov.

    - query_other_id is split on "," or "|" (same delimiters _build_params
      already treats as OR separators).
    - query_intr is split on a bare "OR" only if it contains no other Essie
      syntax (quotes/brackets/AND/NOT); otherwise it's kept as one opaque
      term so power-user raw-Essie queries aren't broken apart.

    Returns a list[str] of stripped, unquoted terms (possibly empty, possibly
    length 1 — callers should treat len() <= 1 as "no split needed").
    """
    intr_terms = []
    if query_intr and query_intr.strip():
        text = query_intr.strip()
        if _ESSIE_ADVANCED_RE.search(text):
            intr_terms = [text]
        else:
            intr_terms = [t.strip() for t in re.split(r'\bOR\b', text, flags=re.IGNORECASE) if t.strip()]

    alt_terms = [o.strip() for o in re.split(r'[,|]+', query_other_id) if o.strip()] \
        if (query_other_id and query_other_id.strip()) else []

    return intr_terms + alt_terms


def _add_adv_filter(adv, items, area_field):
    active = [x for x in (items or []) if x]
    if active:
        expr = " OR ".join(f"AREA[{area_field}]{x}" for x in active)
        adv.append(f"({expr})" if len(active) > 1 else expr)


def _build_params(
    query_cond, query_intr, query_term, query_titles,
    query_spons, query_locn, query_id, query_outc, query_other_id,
    filter_phase, filter_status, filter_study_type, filter_funder,
    filter_sex, filter_healthy, filter_results,
    filter_age_min, filter_age_max,
    filter_start_from, filter_start_to,
    filter_completion_from, filter_completion_to,
    sort_order, max_results,
):
    params = {
        "format":     "json",
        "countTotal": "true",
        "pageSize":   min(max_results, _MAX_PAGE_SIZE),
    }

    if sort_order:
        params["sort"] = sort_order

    _add_text(params, "query.cond",   query_cond)
    _add_text(params, "query.term",   query_term)
    _add_text(params, "query.titles", query_titles)
    _add_text(params, "query.spons",  query_spons)
    _add_text(params, "query.locn",   query_locn)
    _add_text(params, "query.id",     query_id)
    _add_text(params, "query.outc",   query_outc)

    if filter_status:
        active = [s for s in filter_status if s]
        if active:
            params["filter.overallStatus"] = "|".join(active)

    adv = []

    # OR deliminator: , and | — split literally on either, then phrase-quote
    # each term so multi-word terms on either side of the OR stay intact.
    _intr = _quote_phrase(query_intr.strip()) if (query_intr and query_intr.strip()) else ""
    _alts = [_quote_phrase(o.strip()) for o in re.split(r'[,|]+', query_other_id) if o.strip()] \
            if (query_other_id and query_other_id.strip()) else []

    if _intr and _alts:
        _add_text(params, "query.intr", " OR ".join([_intr] + _alts))
    elif _intr:
        _add_text(params, "query.intr", _intr)
    elif _alts:
        _add_text(params, "query.intr", " OR ".join(_alts))

    _add_adv_filter(adv, filter_phase,      "Phase")
    _add_adv_filter(adv, filter_study_type, "StudyType")
    _add_adv_filter(adv, filter_funder,     "LeadSponsorClass")

    if filter_sex and filter_sex != "All":
        adv.append(f"AREA[Sex]{filter_sex}")

    if filter_healthy:
        adv.append("AREA[HealthyVolunteers]true")

    if filter_results == "With results":
        adv.append("AREA[HasResults]true")
    elif filter_results == "Without results":
        adv.append("AREA[HasResults]false")

    if filter_age_min is not None:
        adv.append(f"AREA[MinimumAge]RANGE[{int(filter_age_min)} years, MAX]")
    if filter_age_max is not None:
        adv.append(f"AREA[MaximumAge]RANGE[MIN, {int(filter_age_max)} years]")

    if filter_start_from:
        adv.append(f"AREA[StartDate]RANGE[{filter_start_from}, MAX]")
    if filter_start_to:
        adv.append(f"AREA[StartDate]RANGE[MIN, {filter_start_to}]")
    if filter_completion_from:
        adv.append(f"AREA[PrimaryCompletionDate]RANGE[{filter_completion_from}, MAX]")
    if filter_completion_to:
        adv.append(f"AREA[PrimaryCompletionDate]RANGE[MIN, {filter_completion_to}]")

    if adv:
        params["filter.advanced"] = " AND ".join(adv)

    return params


def _add_text(params, key, value):
    if value and isinstance(value, str) and value.strip():
        params[key] = _quote_phrase(value.strip())


# ── Results status lookup ────────────────────────────────────────────────────

def fetch_results_status(nct_ids):
    """Query CT.gov for a list of NCT IDs and return {nct_id: bool} indicating
    whether each study has posted results. Batches requests in groups of 50
    (CT.gov query.id limit). Runs synchronously — call from a thread if needed."""
    if not nct_ids:
        return {}

    results = {}
    batch_size = 50

    for start in range(0, len(nct_ids), batch_size):
        batch = nct_ids[start:start + batch_size]
        # CT.gov query.id accepts space-separated NCT IDs (OR semantics)
        id_query = " OR ".join(batch)
        params = {
            "format": "json",
            "query.id": id_query,
            "pageSize": len(batch),
            "fields": "NCTId,HasResults",
            "countTotal": "true",
        }

        try:
            data = _get(params)
            for study in data.get("studies", []):
                nct = (study.get("protocolSection", {})
                       .get("identificationModule", {})
                       .get("nctId", ""))
                has_results = study.get("hasResults", False)
                if nct:
                    results[nct] = has_results
        except Exception:
            # On failure, mark batch as unknown (no results)
            for nct in batch:
                results.setdefault(nct, False)

        if start + batch_size < len(nct_ids):
            time.sleep(0.2)

    return results