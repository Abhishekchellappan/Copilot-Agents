import json
import os
import re
import requests
from requests.adapters import HTTPAdapter
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import (
    COLLAB_BASE_URL,
    COLLAB_PAT,
    COLLAB_DEFAULT_SPACE_KEY,
    COLLAB_HLD_SPACE_KEY,
    COLLAB_API_SPACE_KEY,
    COLLAB_HLD_PARENT_PAGE_ID,
    COLLAB_API_PARENT_PAGE_ID,
    HLD_INCLUDE_KEYWORDS,
    HLD_EXCLUDE_KEYWORDS,
    SYNC_METADATA_PATH,
)

_CACHED_WORKING_BASE_URL = None
_SESSION = None


def _get_session() -> requests.Session:
    """Get or initialize a requests.Session with connection pooling."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        adapter = HTTPAdapter(pool_connections=12, pool_maxsize=12, max_retries=2)
        _SESSION.mount("http://", adapter)
        _SESSION.mount("https://", adapter)
    return _SESSION


def _get_base_url_candidates(preferred_url: str = "") -> list:
    """
    Generate candidate Confluence REST API content URLs to try.
    Order: exact configured URL first, then /main variants (matching LG Collab),
    then fallbacks.
    """
    if _CACHED_WORKING_BASE_URL:
        return [_CACHED_WORKING_BASE_URL]

    raw = (preferred_url or COLLAB_BASE_URL).strip().rstrip("/")

    host_match = re.search(r"://([^/]+)", raw)
    host = host_match.group(1) if host_match else "collab.lge.com"

    # The configured URL goes first (highest priority)
    candidates = [raw]

    # Then try /main variants (LG Collab uses /main context path)
    for scheme in ["http", "https"]:
        for ctx in ["/main", "", "/wiki"]:
            url = f"{scheme}://{host}{ctx}/rest/api/content"
            if url not in candidates:
                candidates.append(url)

    return candidates


def _execute_confluence_request(
    method: str,
    endpoint_path: str,
    headers: dict,
    params: dict = None,
    json_data: dict = None,
    base_url_override: str = "",
    timeout: tuple = (5.0, 30.0),
) -> requests.Response:
    """
    Execute an HTTP request to Confluence.
    - Tries candidate URLs in order, caches the first working one.
    - Follows redirects (Apache on collab.lge.com does 302).
    - SSL verification disabled for internal corporate networks.
    """
    global _CACHED_WORKING_BASE_URL

    candidates = _get_base_url_candidates(base_url_override)
    last_err = None
    last_resp = None

    session = _get_session()

    for base in candidates:
        url = f"{base}/{endpoint_path.lstrip('/')}"
        print(f"📡 [Collab Sync] Trying {method} {url}...", flush=True)
        try:
            resp = session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=timeout,
                allow_redirects=True,
                verify=False,
            )
            print(f"📡 [Collab Sync] {url} -> HTTP {resp.status_code}", flush=True)
            if resp.status_code in (200, 201):
                _CACHED_WORKING_BASE_URL = base
                return resp
            elif resp.status_code == 401:
                raise PermissionError(
                    f"Collab returned HTTP 401 Unauthorized at {url}. "
                    "Please check your X-Collab-PAT token."
                )
            elif resp.status_code == 404:
                last_resp = resp
                continue
            else:
                # Any other status (e.g. 400, 403, 500) — return as-is
                _CACHED_WORKING_BASE_URL = base
                return resp
        except requests.exceptions.RequestException as e:
            print(f"⚠️ [Collab Sync] {url} failed: {e}", flush=True)
            last_err = e
            continue

    if last_resp is not None:
        raise RuntimeError(
            f"Collab API returned HTTP {last_resp.status_code} on all {len(candidates)} endpoints tried: "
            f"{', '.join(candidates[:3])}. Response: {last_resp.text[:300]}"
        )
    raise ConnectionError(
        f"Could not connect to Collab API on any endpoint. "
        f"Tried: {', '.join(candidates[:3])}. Last error: {last_err}"
    )


def _get_collab_headers(pat_override: str = "") -> dict:
    """Build Confluence REST API headers with Bearer token authentication."""
    pat = pat_override or COLLAB_PAT
    if not pat:
        raise ValueError(
            "Collab PAT is not configured. Set the COLLAB_PAT environment variable "
            "or pass X-Collab-PAT header."
        )
    return {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _load_sync_metadata() -> dict:
    """Load the sync metadata file tracking last sync timestamps per space/tree."""
    if os.path.exists(SYNC_METADATA_PATH):
        with open(SYNC_METADATA_PATH, "r") as f:
            return json.load(f)
    return {}


def _save_sync_metadata(metadata: dict):
    """Persist sync metadata to disk."""
    os.makedirs(os.path.dirname(SYNC_METADATA_PATH), exist_ok=True)
    with open(SYNC_METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)


def _strip_html_to_text(html_content: str) -> str:
    """Convert Confluence storage format (XHTML) to plain text for indexing."""
    text = re.sub(r"<[^>]+>", " ", html_content)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_excluded_folder(title: str) -> bool:
    """Return True if the page title matches any HLD_EXCLUDE_KEYWORDS (case-insensitive)."""
    t = title.lower()
    return any(kw.lower() in t for kw in HLD_EXCLUDE_KEYWORDS)


def _is_hld_folder(title: str) -> bool:
    """Return True if the page title matches any HLD_INCLUDE_KEYWORDS (case-insensitive)."""
    t = title.lower()
    return any(kw.lower() in t for kw in HLD_INCLUDE_KEYWORDS)


def _fetch_page_children_shallow(page_id: str, headers: dict, base_url_override: str, limit: int = 50) -> list:
    """
    Fetch ONLY the direct children (1 level deep) of a Confluence page.
    Returns a list of dicts: [{id, title}].
    Used to discover version folders and HLD sub-folders.
    """
    children = []
    start = 0
    while True:
        try:
            resp = _execute_confluence_request(
                method="GET",
                endpoint_path=f"{page_id}/child/page",
                headers=headers,
                params={"limit": limit, "start": start, "expand": "title"},
                base_url_override=base_url_override,
            )
            data = resp.json()
            results = data.get("results", [])
            for item in results:
                children.append({"id": item.get("id", ""), "title": item.get("title", "")})
            if len(results) < limit:
                break
            start += limit
        except Exception as e:
            print(f"⚠️ [Collab Sync] Could not fetch children of {page_id}: {e}", flush=True)
            break
    return children


def _fetch_all_descendants_recursive(
    ancestor_id: str,
    headers: dict,
    base_url_override: str,
    version_label: str = "",
    limit: int = 50,
) -> list:
    """
    Recursively fetch ALL pages under an ancestor using CQL (ancestor=...) with full pagination.
    Also includes the ancestor page itself.
    Tags each page with version_label metadata if provided.
    """
    all_pages = []

    # 1. Fetch the ancestor page itself
    try:
        parent_resp = _execute_confluence_request(
            method="GET",
            endpoint_path=f"{ancestor_id}",
            headers=headers,
            params={"expand": "body.storage,version,history.lastUpdated"},
            base_url_override=base_url_override,
        )
        if parent_resp.status_code in (200, 201):
            p = parent_resp.json()
            body_storage = p.get("body", {}).get("storage", {}).get("value", "")
            all_pages.append({
                "page_id": p.get("id", ""),
                "title": p.get("title", ""),
                "version": p.get("version", {}).get("number", 1),
                "last_modified": p.get("history", {}).get("lastUpdated", {}).get("when", ""),
                "body_text": _strip_html_to_text(body_storage),
                "url": p.get("_links", {}).get("webui", ""),
                "version_label": version_label,
            })
            print(f"📄 [Collab Sync] Indexed: '{p.get('title')}' [{version_label}]", flush=True)
    except Exception as e:
        print(f"⚠️ [Collab Sync] Could not fetch ancestor {ancestor_id}: {e}", flush=True)

    # 2. Recursively fetch ALL descendants via CQL with concurrent pagination
    cql = f'ancestor="{ancestor_id}" AND type="page"'
    
    # First batch: discover totalSize and collect page 1
    try:
        first_resp = _execute_confluence_request(
            method="GET",
            endpoint_path="search",
            headers=headers,
            params={"cql": cql, "limit": limit, "start": 0, "expand": "body.storage,version"},
            base_url_override=base_url_override,
        )
        first_data = first_resp.json()
        first_results = first_data.get("results", [])
        total_size = first_data.get("totalSize", len(first_results))
        print(f"📊 [Collab Sync] Tree {ancestor_id}: {total_size} total descendant pages found in Confluence.", flush=True)

        for page in first_results:
            body_storage = page.get("body", {}).get("storage", {}).get("value", "")
            version_info = page.get("version", {})
            all_pages.append({
                "page_id": page.get("id", ""),
                "title": page.get("title", ""),
                "version": version_info.get("number", 1),
                "last_modified": version_info.get("when", ""),
                "body_text": _strip_html_to_text(body_storage),
                "url": page.get("_links", {}).get("webui", ""),
                "version_label": version_label,
            })

        # If there are remaining pages, fetch them concurrently using ThreadPoolExecutor
        if total_size > limit:
            remaining_offsets = list(range(limit, total_size, limit))
            print(
                f"⚡ [Collab Sync] Fast parallel fetch: downloading {len(remaining_offsets)} batches "
                f"({total_size - limit} pages) using 6 concurrent workers...",
                flush=True,
            )

            def _fetch_offset_batch(offset: int) -> list:
                r = _execute_confluence_request(
                    method="GET",
                    endpoint_path="search",
                    headers=headers,
                    params={"cql": cql, "limit": limit, "start": offset, "expand": "body.storage,version"},
                    base_url_override=base_url_override,
                )
                return r.json().get("results", [])

            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_offset = {executor.submit(_fetch_offset_batch, off): off for off in remaining_offsets}
                for future in as_completed(future_to_offset):
                    try:
                        batch_results = future.result()
                        for page in batch_results:
                            body_storage = page.get("body", {}).get("storage", {}).get("value", "")
                            version_info = page.get("version", {})
                            all_pages.append({
                                "page_id": page.get("id", ""),
                                "title": page.get("title", ""),
                                "version": version_info.get("number", 1),
                                "last_modified": version_info.get("when", ""),
                                "body_text": _strip_html_to_text(body_storage),
                                "url": page.get("_links", {}).get("webui", ""),
                                "version_label": version_label,
                            })
                    except Exception as batch_err:
                        print(f"⚠️ [Collab Sync] Batch fetch error: {batch_err}", flush=True)

            print(f"⚡ [Collab Sync] Concurrent fetch finished: {len(all_pages)} pages collected for {ancestor_id}.", flush=True)

    except Exception as e:
        print(f"⚠️ [Collab Sync] CQL error fetching descendants of {ancestor_id}: {e}", flush=True)

    return all_pages


def fetch_hld_pages_recursive(
    hld_root_id: str,
    pat_override: str = "",
    base_url_override: str = "",
) -> dict:
    """
    Smart recursive HLD fetcher:
    1. Fetches direct children of hld_root_id (version folders: webOS 27, webOS 26, ...).
    2. For each version folder, fetches ITS children to find HLD sub-folders.
    3. Skips any folder matching HLD_EXCLUDE_KEYWORDS (LLD, Low-Level Design, etc.).
    4. For each HLD folder found, recursively indexes all nested descendants via CQL.
    5. Automatically handles future versions (webOS 28+) without any code changes.

    Returns:
        {
            "pages": [...],
            "summary": {
                "versions_found": [...],
                "hld_folders_indexed": [...],
                "lld_folders_skipped": [...],
            }
        }
    """
    headers = _get_collab_headers(pat_override)
    all_hld_pages = []
    versions_found = []
    hld_folders_indexed = []
    lld_folders_skipped = []

    print(f"🌳 [Collab Sync] Discovering version folders under root: {hld_root_id}...", flush=True)

    # Step 1: Get direct children of the root (e.g. webOS 27, webOS 26, webOS 25...)
    version_folders = _fetch_page_children_shallow(hld_root_id, headers, base_url_override)
    print(f"🌳 [Collab Sync] Found {len(version_folders)} version/section folders under root.", flush=True)

    def process_vfolder(vfolder):
        v_found = []
        lld_skipped = []
        hld_indexed = []
        pages = []
        vfolder_id = vfolder["id"]
        vfolder_title = vfolder["title"]

        # Skip any version folder that is itself an excluded type
        if _is_excluded_folder(vfolder_title):
            print(f"   ⛔ [Filter] Skipping excluded root-level folder: '{vfolder_title}'", flush=True)
            lld_skipped.append(vfolder_title)
            return (pages, v_found, hld_indexed, lld_skipped)

        print(f"   🔍 [Discovery] Found version folder: '{vfolder_title}'", flush=True)
        v_found.append(vfolder_title)

        # Step 2: Get children of each version folder (HLD, LLD, review pages...)
        sub_folders = _fetch_page_children_shallow(vfolder_id, headers, base_url_override)

        hld_found_in_version = False
        for sfolder in sub_folders:
            sfolder_id = sfolder["id"]
            sfolder_title = sfolder["title"]

            # Explicitly skip excluded folders (LLD, Low-Level Design, etc.)
            if _is_excluded_folder(sfolder_title):
                print(f"      ⛔ [Filter] Skipping LLD branch: '{sfolder_title}' (Ignored)", flush=True)
                lld_skipped.append(f"{vfolder_title} → {sfolder_title}")
                continue

            # Only index folders matching HLD include keywords
            if _is_hld_folder(sfolder_title):
                print(f"      ✅ [Filter] Found HLD branch: '{sfolder_title}' -> Recursively indexing...", flush=True)
                hld_indexed.append(f"{vfolder_title} → {sfolder_title}")
                hld_found_in_version = True
                fetched_pages = _fetch_all_descendants_recursive(
                    ancestor_id=sfolder_id,
                    headers=headers,
                    base_url_override=base_url_override,
                    version_label=vfolder_title,
                )
                pages.extend(fetched_pages)
            else:
                print(f"      ⏭️ [Filter] Skipping non-HLD folder: '{sfolder_title}'", flush=True)

        if not hld_found_in_version:
            print(f"   ℹ️ [Discovery] No HLD subfolder found directly in '{vfolder_title}', skipping.", flush=True)

        return (pages, v_found, hld_indexed, lld_skipped)

    # Process all version folders in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(process_vfolder, version_folders))
        
    for r_pages, r_v_found, r_hld_indexed, r_lld_skipped in results:
        all_hld_pages.extend(r_pages)
        versions_found.extend(r_v_found)
        hld_folders_indexed.extend(r_hld_indexed)
        lld_folders_skipped.extend(r_lld_skipped)

    print(
        f"✅ [Collab Sync] HLD recursive fetch complete: "
        f"{len(all_hld_pages)} total pages across {len(hld_folders_indexed)} HLD folders. "
        f"Skipped {len(lld_folders_skipped)} LLD/excluded folders.",
        flush=True,
    )

    return {
        "pages": all_hld_pages,
        "summary": {
            "versions_found": versions_found,
            "hld_folders_indexed": hld_folders_indexed,
            "lld_folders_skipped": lld_folders_skipped,
        },
    }


def fetch_api_pages_recursive(
    api_root_id: str,
    pat_override: str = "",
    base_url_override: str = "",
) -> list:
    """
    Recursively fetch ALL API documentation pages under the api_root_id using CQL.
    No filtering — every page under the API root is an API spec.
    Returns a list of page dicts.
    """
    headers = _get_collab_headers(pat_override)
    print(f"🔌 [Collab Sync] Recursively fetching all API docs under root: {api_root_id}...", flush=True)
    pages = _fetch_all_descendants_recursive(
        ancestor_id=api_root_id,
        headers=headers,
        base_url_override=base_url_override,
        version_label="API",
    )
    print(f"✅ [Collab Sync] API recursive fetch complete: {len(pages)} pages indexed.", flush=True)
    return pages


def fetch_space_pages(
    space_key: str = "",
    ancestor_id: str = "",
    last_modified_after: str = "",
    pat_override: str = "",
    base_url_override: str = "",
    limit: int = 50,
) -> list:
    """
    Fetch pages from a Confluence space or specific parent page tree (ancestor),
    optionally filtered by modification date.
    Returns a list of dicts: [{page_id, title, version, last_modified, body_text}].
    """
    space = space_key or COLLAB_DEFAULT_SPACE_KEY
    headers = _get_collab_headers(pat_override)
    all_pages = []

    # METHOD 1: Direct Tree Fetch via /content/{id} and /content/{id}/child/page
    # Instant, 100% reliable, and works on all Confluence versions without CQL indexing delays!
    if ancestor_id:
        print(f"🌳 [Collab Sync] Fetching direct page tree for ID: {ancestor_id}...", flush=True)
        try:
            # 1. Fetch parent page itself
            parent_resp = _execute_confluence_request(
                method="GET",
                endpoint_path=f"{ancestor_id}",
                headers=headers,
                params={"expand": "body.storage,version,history.lastUpdated"},
                base_url_override=base_url_override,
            )
            if parent_resp.status_code in (200, 201):
                p = parent_resp.json()
                body_storage = p.get("body", {}).get("storage", {}).get("value", "")
                all_pages.append({
                    "page_id": p.get("id", ""),
                    "title": p.get("title", ""),
                    "version": p.get("version", {}).get("number", 1),
                    "last_modified": p.get("history", {}).get("lastUpdated", {}).get("when", ""),
                    "body_text": _strip_html_to_text(body_storage),
                    "url": p.get("_links", {}).get("webui", ""),
                })
                print(f"📄 [Collab Sync] Added parent: '{p.get('title')}' (ID: {ancestor_id})", flush=True)

            # 2. Fetch child pages
            child_resp = _execute_confluence_request(
                method="GET",
                endpoint_path=f"{ancestor_id}/child/page",
                headers=headers,
                params={"limit": limit, "expand": "body.storage,version,history.lastUpdated"},
                base_url_override=base_url_override,
            )
            if child_resp.status_code in (200, 201):
                children = child_resp.json().get("results", [])
                for cp in children:
                    body_storage = cp.get("body", {}).get("storage", {}).get("value", "")
                    all_pages.append({
                        "page_id": cp.get("id", ""),
                        "title": cp.get("title", ""),
                        "version": cp.get("version", {}).get("number", 1),
                        "last_modified": cp.get("history", {}).get("lastUpdated", {}).get("when", ""),
                        "body_text": _strip_html_to_text(body_storage),
                        "url": cp.get("_links", {}).get("webui", ""),
                    })
                    print(f"📄 [Collab Sync] Added child: '{cp.get('title')}' (ID: {cp.get('id')})", flush=True)

            if all_pages:
                print(f"✅ [Collab Sync] Finished tree sync for {ancestor_id}: {len(all_pages)} pages found!", flush=True)
                return all_pages
        except Exception as direct_err:
            print(f"⚠️ [Collab Sync] Direct tree fetch notice: {direct_err}. Trying CQL search...", flush=True)

    # METHOD 2: CQL Search Query
    if ancestor_id:
        cql = f'(ancestor="{ancestor_id}" OR id="{ancestor_id}") AND type="page"'
    elif space:
        cql = f'space="{space}" AND type="page"'
    else:
        cql = 'type="page"'

    if last_modified_after:
        cql += f' AND lastmodified >= "{last_modified_after}"'

    start = 0

    while True:
        params = {
            "cql": cql,
            "limit": limit,
            "start": start,
            "expand": "body.storage,version,history.lastUpdated",
        }

        print(f"📡 [Collab Sync] CQL search start={start}...", flush=True)
        response = _execute_confluence_request(
            method="GET",
            endpoint_path="search",
            headers=headers,
            params=params,
            base_url_override=base_url_override,
        )

        data = response.json()
        results = data.get("results", [])

        if not results:
            print("📄 [Collab Sync] No more CQL results.", flush=True)
            break

        for page in results:
            body_storage = page.get("body", {}).get("storage", {}).get("value", "")
            version_info = page.get("version", {})
            history_info = page.get("history", {}).get("lastUpdated", {})

            all_pages.append({
                "page_id": page.get("id", ""),
                "title": page.get("title", ""),
                "version": version_info.get("number", 1),
                "last_modified": history_info.get("when", ""),
                "body_text": _strip_html_to_text(body_storage),
                "url": page.get("_links", {}).get("webui", ""),
            })
            print(f"📄 [Collab Sync] Added: '{page.get('title')}'", flush=True)

        if data.get("size", 0) < limit or len(results) < limit:
            break
        start += limit

    print(f"✅ [Collab Sync] Total pages collected: {len(all_pages)}", flush=True)
    return all_pages


def fetch_single_page(page_id: str, pat_override: str = "", base_url_override: str = "") -> dict:
    """Fetch a single Confluence page by its ID."""
    headers = _get_collab_headers(pat_override)

    response = _execute_confluence_request(
        method="GET",
        endpoint_path=f"{page_id}",
        headers=headers,
        params={"expand": "body.storage,version"},
        base_url_override=base_url_override,
        timeout=15,
    )

    page = response.json()
    body_storage = page.get("body", {}).get("storage", {}).get("value", "")

    return {
        "page_id": page.get("id", ""),
        "title": page.get("title", ""),
        "version": page.get("version", {}).get("number", 1),
        "body_text": _strip_html_to_text(body_storage),
        "body_html": body_storage,
    }


def publish_new_page(
    title: str,
    space_key: str,
    content_html: str,
    parent_page_id: str = "",
    previous_page_id: str = "",
    pat_override: str = "",
    base_url_override: str = "",
) -> dict:
    """
    Create a brand-new Confluence page (NON-DESTRUCTIVE — never overwrites existing).
    Optionally links back to a previous baseline page with a supersedes banner.

    Returns: {page_id, title, url}
    """
    headers = _get_collab_headers(pat_override)
    space = space_key or COLLAB_DEFAULT_SPACE_KEY

    # If there is a previous baseline, prepend a banner
    if previous_page_id:
        try:
            prev_page = fetch_single_page(previous_page_id, pat_override, base_url_override)
            prev_title = prev_page.get("title", "Previous Version")
            banner = (
                '<ac:structured-macro ac:name="info">'
                "<ac:rich-text-body>"
                f"<p>📌 <strong>This document supersedes:</strong> "
                f'<a href="/pages/viewpage.action?pageId={previous_page_id}">'
                f"{prev_title}</a></p>"
                "</ac:rich-text-body>"
                "</ac:structured-macro>"
            )
            content_html = banner + "\n" + content_html
        except Exception:
            pass

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space},
        "body": {
            "storage": {
                "value": content_html,
                "representation": "storage",
            }
        },
    }

    if parent_page_id:
        payload["ancestors"] = [{"id": parent_page_id}]

    response = _execute_confluence_request(
        method="POST",
        endpoint_path="",
        headers=headers,
        json_data=payload,
        base_url_override=base_url_override,
        timeout=30,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to create page (HTTP {response.status_code}): {response.text}"
        )

    result = response.json()
    return {
        "page_id": result.get("id", ""),
        "title": result.get("title", ""),
        "url": result.get("_links", {}).get("webui", ""),
    }


def get_incremental_updates(
    hld_parent_id: str = "",
    api_parent_id: str = "",
    space_key: str = "",
    force_full: bool = False,
    pat_override: str = "",
    base_url_override: str = "",
) -> dict:
    """
    Perform targeted sync using fully recursive HLD tree traversal with LLD filtering.
    - HLD: Discovers all version folders (webOS 27, 26, 25...), finds HLD sub-folders for
      each, skips LLD, and recursively fetches all nested documents down to infinite depth.
    - API: Recursively fetches all pages under the API root.
    - force_full=True re-indexes everything; False skips if already synced.

    Returns: {
        "hld_pages": [...],
        "api_pages": [...],
        "hld_summary": {versions_found, hld_folders_indexed, lld_folders_skipped}
    }
    """
    hld_parent = hld_parent_id or COLLAB_HLD_PARENT_PAGE_ID
    api_parent = api_parent_id or COLLAB_API_PARENT_PAGE_ID
    metadata = _load_sync_metadata()

    hld_sync_key = f"hld_tree_{hld_parent}"
    api_sync_key = f"api_tree_{api_parent}"

    # Always fetch latest documents via recursive crawler
    # (LLD is excluded, HLD and API are recursively fetched)
    hld_result = fetch_hld_pages_recursive(
        hld_root_id=hld_parent,
        pat_override=pat_override,
        base_url_override=base_url_override,
    )
    hld_pages = hld_result["pages"]
    hld_summary = hld_result["summary"]

    # Recursively fetch API pages (all descendants, no filtering)
    api_pages = fetch_api_pages_recursive(
        api_root_id=api_parent,
        pat_override=pat_override,
        base_url_override=base_url_override,
    )

    # Update sync metadata
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    metadata[hld_sync_key] = {
        "last_sync_time": now_str,
        "pages_synced": len(hld_pages),
        "versions": hld_summary.get("versions_found", []),
        "hld_folders": hld_summary.get("hld_folders_indexed", []),
        "lld_skipped": hld_summary.get("lld_folders_skipped", []),
    }
    metadata[api_sync_key] = {"last_sync_time": now_str, "pages_synced": len(api_pages)}
    _save_sync_metadata(metadata)

    return {
        "hld_pages": hld_pages,
        "api_pages": api_pages,
        "hld_summary": hld_summary,
    }


def markdown_to_confluence_storage(markdown_text: str) -> str:
    """
    Convert Markdown text to Confluence Storage Format (XHTML).
    Handles headings, bold, italic, code blocks, lists, tables, and links.
    """
    lines = markdown_text.split("\n")
    html_lines = []
    in_code_block = False
    in_table = False
    code_lang = ""

    for line in lines:
        # Code block toggle
        if line.strip().startswith("```"):
            if not in_code_block:
                code_lang = line.strip()[3:].strip() or "text"
                html_lines.append(
                    f'<ac:structured-macro ac:name="code">'
                    f'<ac:parameter ac:name="language">{code_lang}</ac:parameter>'
                    f"<ac:plain-text-body><![CDATA["
                )
                in_code_block = True
            else:
                html_lines.append("]]></ac:plain-text-body></ac:structured-macro>")
                in_code_block = False
            continue

        if in_code_block:
            html_lines.append(line)
            continue

        # Headings
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            html_lines.append(f"<h{level}>{text}</h{level}>")
            continue

        # Table rows
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Skip separator rows (|---|---|)
            if all(re.match(r"^[-:]+$", c) for c in cells):
                continue
            if not in_table:
                html_lines.append("<table><tbody>")
                in_table = True
            row = "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
            html_lines.append(row)
            continue
        elif in_table:
            html_lines.append("</tbody></table>")
            in_table = False

        # Empty line
        if not line.strip():
            html_lines.append("")
            continue

        # Inline formatting
        processed = line
        processed = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", processed)
        processed = re.sub(r"\*(.+?)\*", r"<em>\1</em>", processed)
        processed = re.sub(r"`([^`]+)`", r"<code>\1</code>", processed)
        processed = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', processed
        )

        # Bullet list
        bullet_match = re.match(r"^(\s*)[-*]\s+(.+)$", processed)
        if bullet_match:
            text = bullet_match.group(2)
            html_lines.append(f"<ul><li>{text}</li></ul>")
            continue

        # Numbered list
        num_match = re.match(r"^(\s*)\d+\.\s+(.+)$", processed)
        if num_match:
            text = num_match.group(2)
            html_lines.append(f"<ol><li>{text}</li></ol>")
            continue

        # Blockquote
        if processed.startswith(">"):
            text = processed[1:].strip()
            html_lines.append(
                f'<ac:structured-macro ac:name="info">'
                f"<ac:rich-text-body><p>{text}</p></ac:rich-text-body>"
                f"</ac:structured-macro>"
            )
            continue

        # Regular paragraph
        html_lines.append(f"<p>{processed}</p>")

    if in_table:
        html_lines.append("</tbody></table>")

    return "\n".join(html_lines)
