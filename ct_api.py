"""
ct_api.py
─────────
ClinicalTrials.gov API v2 connection layer.

Uses requests (synchronous) run inside a thread executor, preventing
Shiny async event loop from being blocked.
"""

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
    filter_enroll_min=None,  filter_enroll_max=None,
    filter_start_from=None,  filter_start_to=None,
    filter_completion_from=None, filter_completion_to=None,
    sort_order="LastUpdatePostDate:desc",
    max_results=500,
    progress_callback=None,
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
        filter_enroll_min, filter_enroll_max,
        filter_start_from, filter_start_to,
        filter_completion_from, filter_completion_to,
        sort_order, max_results,
    )

    # Wrap the sync paginator so we can call the async progress_callback
    # from inside a thread. We collect (fetched, total) tuples in a queue
    # and drain them on the event loop side after each page.
    import queue
    progress_q = queue.Queue()

    def _sync_progress(fetched, total):
        progress_q.put((fetched, total))

    def _blocking_fetch():
        return _paginate(params, max_results, _sync_progress)

    # Run the blocking call in a thread pool
    result_future = loop.run_in_executor(None, _blocking_fetch)

    error = None
    while True:
        # Drain any progress updates that arrived
        while not progress_q.empty():
            fetched, tot = progress_q.get_nowait()
            if progress_callback:
                await progress_callback(fetched, tot)

        # Check if the thread finished
        if result_future.done():
            try:
                studies, total = result_future.result()
            except Exception as e:
                error = e
            break

        await asyncio.sleep(0.3)   # yield to event loop; check again soon

    # Final progress drain
    while not progress_q.empty():
        fetched, tot = progress_q.get_nowait()
        if progress_callback:
            await progress_callback(fetched, tot)

    if error:
        raise error

    return studies, total


# ── Sync internals ────────────────────────────────────────────────────────────

def _paginate(params, max_results, progress_cb):
    studies     = []
    total_count = None
    page_token  = None

    while True:
        if page_token:
            params = dict(params, pageToken=page_token)

        data = _get(params)

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

    return studies, (total_count or 0)


def _get(params):
    try:
        resp = _session.get(BASE_URL, params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        raise CTGovNetworkError(f"Network error: {e}") from e

    if resp.status_code != 200:
        raise CTGovAPIError(
            f"CT.gov API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    return resp.json()


# ── Parameter builder ─────────────────────────────────────────────────────────

## current filters and stuff, subject to change if needed

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
    filter_enroll_min, filter_enroll_max,
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

    _intr  = query_intr.strip()  if (query_intr  and query_intr.strip())  else ""
    _alts  = [o.strip() for o in query_other_id.replace(",", " ").split() if o.strip()] \
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

    if filter_enroll_min is not None:
        adv.append(f"AREA[EnrollmentCount]RANGE[{int(filter_enroll_min)}, MAX]")
    if filter_enroll_max is not None:
        adv.append(f"AREA[EnrollmentCount]RANGE[MIN, {int(filter_enroll_max)}]")

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
        params[key] = value.strip()