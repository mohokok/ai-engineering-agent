"""Controlled web search adapters, SSRF-safe URL validation, and untrusted page/PDF fetcher."""

from dataclasses import dataclass
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pymupdf
import httpx
from lxml import html as lxml_html

from app.providers.base import ProviderConfigError, ProviderError, sanitize_secret_text
from app.providers.secrets import SecretStore
from app.schemas.research import (
    AccessStatus,
    ReliabilityRating,
    SearchProviderName,
    SearchProviderOptionOut,
    SourcePriorityTier,
)

MAX_FETCH_BYTES = 10 * 1024 * 1024  # 10 MB cap per fetched page or PDF
MAX_EXTRACTED_CHARS = 12_000
FETCH_TIMEOUT_SECONDS = 15.0
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

_SEARCH_PROVIDER_METADATA: tuple[dict[str, Any], ...] = (
    {
        "id": "duckduckgo_lite",
        "label": "DuckDuckGo Lite (Free, Zero API Key)",
        "requires_api_key": False,
        "is_default": True,
        "pricing_summary": "Free, no API key or credit card required.",
        "notes": "Default search index; snippets are discarded and every target URL is fetched directly.",
    },
    {
        "id": "crossref",
        "label": "Crossref Open Scholarly API (Free, Zero API Key)",
        "requires_api_key": False,
        "is_default": False,
        "pricing_summary": "Free open metadata API for peer-reviewed papers and DOIs.",
        "notes": "Peer-reviewed engineering literature discovery; target pages still fetched before citation.",
    },
    {
        "id": "tavily",
        "label": "Tavily Search API (Optional API Key in Keyring)",
        "requires_api_key": True,
        "is_default": False,
        "pricing_summary": "1,000 free credits/month (no card); pay-as-you-go ~$0.008/credit or $30/month beyond.",
        "notes": "Requires owner-entered Tavily API key saved in Windows Credential Manager.",
    },
    {
        "id": "serper",
        "label": "Serper.dev Google SERP API (Optional API Key in Keyring)",
        "requires_api_key": True,
        "is_default": False,
        "pricing_summary": "2,500 one-time free starter queries (no card); prepaid packages beyond.",
        "notes": "Requires owner-entered Serper API key saved in Windows Credential Manager.",
    },
    {
        "id": "brave",
        "label": "Brave Search API (Optional API Key in Keyring)",
        "requires_api_key": True,
        "is_default": False,
        "pricing_summary": "$5/month recurring free credit (~1,000 queries, card required to activate); $5/1,000 after.",
        "notes": "Requires owner-entered Brave Search API key saved in Windows Credential Manager.",
    },
)

SOURCE_PRIORITY_SPEC: dict[SourcePriorityTier, tuple[int, ReliabilityRating, str]] = {
    "official_regulations": (1, "high_official_regulation", "regulation"),
    "standards_bodies": (2, "high_standards_body", "standard"),
    "government": (3, "high_government", "government"),
    "manufacturer": (4, "medium_manufacturer", "manufacturer"),
    "peer_reviewed": (5, "medium_peer_reviewed", "peer_reviewed"),
    "reputable": (6, "low_reputable_reference", "reference"),
    "unverified": (99, "unreviewed", "unverified"),
}

_REGULATION_HOST_MARKERS = (
    "legislation.gov.uk",
    "legislation.gov",
    "eur-lex.europa.eu",
    "federalregister.gov",
    "law.cornell.edu",
)
_STANDARDS_HOSTS = (
    "iso.org",
    "iec.ch",
    "nfpa.org",
    "ashrae.org",
    "astm.org",
    "concrete.org",
    "bsigroup.com",
    "cen.eu",
    "who.int",
    "fgiguidelines.org",
    "iccsafe.org",
    "saso.gov.sa",
    "ansi.org",
    "ul.com",
    "cibse.org",
    "istructe.org",
    "eurocodes.jrc.ec.europa.eu",
)
_MANUFACTURER_HOSTS = (
    "schneider-electric.com",
    "abb.com",
    "siemens.com",
    "caterpillar.com",
    "grundfos.com",
    "daikin.com",
    "carrier.com",
    "trane.com",
    "hilti.com",
    "sika.com",
    "knauf.com",
    "rockwool.com",
    "legrand.com",
    "honeywell.com",
    "johnsoncontrols.com",
    "signify.com",
)
_PEER_REVIEWED_HOSTS = (
    "doi.org",
    "ieeexplore.ieee.org",
    "sciencedirect.com",
    "ascelibrary.org",
    "link.springer.com",
    "springer.com",
    "nature.com",
    "onlinelibrary.wiley.com",
    "tandfonline.com",
    "mdpi.com",
    "pubmed.ncbi.nlm.nih.gov",
)
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|your|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|system|prior)\s+(rules|instructions?)", re.IGNORECASE),
    re.compile(r"override\s+(system|safety|classification|rules)", re.IGNORECASE),
    re.compile(r"(set|change|mark)\s+classification\s+to\s+for\s+approval", re.IGNORECASE),
    re.compile(r"print\s+(your\s+)?(api\s+key|system\s+prompt|secret)", re.IGNORECASE),
    re.compile(r"تجاهل\s+(كافة|كل|جميع)?\s*التعليمات", re.IGNORECASE),
)
_BOT_OR_PAYWALL_MARKERS = (
    "cf-turnstile",
    "g-recaptcha",
    "h-captcha",
    "verify you are human",
    "please verify you are a human",
    "access denied",
    "enable javascript and cookies to continue",
    "subscription required to view",
    "subscribe to continue reading",
)
_DATE_META_NAMES = (
    "article:published_time",
    "og:published_time",
    "publish-date",
    "publication_date",
    "pubdate",
    "dc.date",
    "dc.date.issued",
    "date",
    "dcterms.created",
    "last-modified",
)


@dataclass(frozen=True)
class SearchCandidate:
    """Candidate web URL returned by a search engine (snippets intentionally omitted)."""

    url: str
    candidate_title: str
    source_priority_tier: SourcePriorityTier
    priority_rank: int
    publication_date_hint: str | None = None
    source_name_hint: str | None = None


@dataclass
class FetchedSourceRecord:
    """Verified or inaccessible page/PDF fetch outcome ready for LLM/DB storage."""

    url: str
    final_url: str
    source_name: str
    publication_date: str | None
    source_priority_tier: SourcePriorityTier
    priority_rank: int
    reliability_rating: ReliabilityRating
    source_type: str
    access_status: AccessStatus
    reviewed: bool
    http_status: int | None
    failure_reason: str | None
    extracted_text: str | None
    excerpt: str | None
    injection_signals: list[str]


def search_key_account_name(provider_id: str) -> str:
    """Keyring provider account slug for optional paid search providers."""
    return f"search_{provider_id.strip().lower()}"


def list_search_provider_options(secret_store: SecretStore) -> list[SearchProviderOptionOut]:
    """Return configured search provider catalog and non-secret keyring status."""
    options: list[SearchProviderOptionOut] = []
    for item in _SEARCH_PROVIDER_METADATA:
        req_key = bool(item["requires_api_key"])
        has_key = (
            secret_store.has_api_key(search_key_account_name(str(item["id"])))
            if req_key
            else False
        )
        options.append(
            SearchProviderOptionOut(
                id=item["id"],
                label=item["label"],
                requires_api_key=req_key,
                key_configured=has_key,
                is_default=bool(item["is_default"]),
                pricing_summary=item["pricing_summary"],
                notes=item["notes"],
            )
        )
    return options


def _is_disallowed_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def validate_public_http_url(url: str, *, allow_private_for_test: bool = False) -> str:
    """Validate HTTP(S) URL syntax and reject localhost/private SSRF targets."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'; only http:// and https:// are permitted.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("URL must contain a valid hostname.")
    if allow_private_for_test:
        return cleaned

    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError(f"Refusing internal or loopback host '{host}' for controlled internet research.")
    try:
        ip_val = ipaddress.ip_address(host)
        if _is_disallowed_ip(ip_val):
            raise ValueError(f"Refusing non-public IP address '{host}'.")
    except ValueError:
        # Hostname, not raw IP literal: verify DNS resolution does not point to private space.
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            return cleaned  # Let HTTP fetch fail cleanly and mark inaccessible/unreviewed
        for info in infos:
            sock_ip = str(info[4][0]).split("%", 1)[0]
            try:
                ip_resolved = ipaddress.ip_address(sock_ip)
            except ValueError:
                continue
            if _is_disallowed_ip(ip_resolved):
                raise ValueError(
                    f"Host '{host}' resolves to a restricted non-public address ({sock_ip}); blocked by SSRF policy."
                )
    return cleaned


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith(f".{d}") for d in domains)


def classify_source_priority(
    url: str,
    *,
    title: str = "",
    hint_tier: SourcePriorityTier | None = None,
) -> tuple[SourcePriorityTier, int, ReliabilityRating, str]:
    """Classify source into the Plan's 6-tier reliability hierarchy deterministically."""
    if hint_tier and hint_tier in SOURCE_PRIORITY_SPEC and hint_tier != "unverified":
        rank, rating, stype = SOURCE_PRIORITY_SPEC[hint_tier]
        return hint_tier, rank, rating, stype

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path_lower = (parsed.path or "").lower()
    title_lower = (title or "").lower()

    if (
        _host_matches(host, _REGULATION_HOST_MARKERS)
        or any(tok in path_lower for tok in ("/legislation", "/statute", "/regulation", "/decree"))
        or any(
            tok in title_lower
            for tok in (
                "official gazette",
                "building regulation",
                "building regulations",
                "decree",
                "statute",
                "اللائحة التنفيذية",
                "قانون البناء",
            )
        )
    ):
        tier: SourcePriorityTier = "official_regulations"
    elif _host_matches(host, _STANDARDS_HOSTS) or any(
        tok in title_lower for tok in ("standard specification", "eurocode", "nfpa ", "ashrae ", "iso ", "iec ", "aci 318")
    ):
        tier = "standards_bodies"
    elif (
        host.endswith(".gov")
        or ".gov." in host
        or host.endswith(".gob.es")
        or host.endswith(".gouv.fr")
        or host.endswith(".edu")
        or ".edu." in host
        or _host_matches(host, ("europa.eu", "un.org"))
    ):
        tier = "government"
    elif _host_matches(host, _MANUFACTURER_HOSTS) or any(
        tok in path_lower + " " + title_lower for tok in ("datasheet", "technical data sheet", "product catalogue", "catalog")
    ):
        tier = "manufacturer"
    elif _host_matches(host, _PEER_REVIEWED_HOSTS) or "doi.org/" in url.lower():
        tier = "peer_reviewed"
    else:
        tier = "reputable"

    rank, rating, stype = SOURCE_PRIORITY_SPEC[tier]
    return tier, rank, rating, stype


def _unwrap_duckduckgo_url(raw_href: str) -> str:
    href = raw_href.strip()
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        uddg_vals = qs.get("uddg")
        if uddg_vals:
            return unquote(uddg_vals[0]).strip()
    return href


def _search_duckduckgo_lite(
    client: httpx.Client,
    query: str,
    max_results: int,
) -> list[SearchCandidate]:
    resp = client.get(
        "https://lite.duckduckgo.com/lite/",
        params={"q": query},
        headers={"User-Agent": "curl/8.0"},
    )
    if resp.status_code == 202:
        raise ProviderError(
            "DuckDuckGo Lite returned HTTP 202 (rate-limited or anti-bot challenge); "
            "try Crossref, enter explicit URLs, or configure a Search API key (Tavily/Serper)."
        )
    if resp.status_code != 200:
        raise ProviderError(f"DuckDuckGo Lite returned HTTP {resp.status_code}.")
    lower_body = resp.text.lower()
    if "captcha" in lower_body or "anomaly" in lower_body:
        raise ProviderError(
            "DuckDuckGo Lite presented an anti-bot challenge; blocked without bypassing CAPTCHA."
        )
    doc = lxml_html.fromstring(resp.text)
    candidates: list[SearchCandidate] = []
    seen: set[str] = set()
    for anchor in doc.xpath("//a[contains(@class, 'result-link')]"):
        raw_href = str(anchor.get("href") or "")
        target = _unwrap_duckduckgo_url(raw_href)
        if not target.startswith(("http://", "https://")) or target in seen:
            continue
        title = " ".join("".join(anchor.itertext()).split())
        tier, rank, _, _ = classify_source_priority(target, title=title)
        seen.add(target)
        candidates.append(
            SearchCandidate(
                url=target,
                candidate_title=title or target,
                source_priority_tier=tier,
                priority_rank=rank,
                source_name_hint=urlparse(target).hostname or target,
            )
        )
        if len(candidates) >= max_results:
            break
    return candidates


def _search_crossref(
    client: httpx.Client,
    query: str,
    max_results: int,
) -> list[SearchCandidate]:
    resp = client.get(
        "https://api.crossref.org/works",
        params={"query": query, "rows": max_results, "select": "DOI,title,URL,published,container-title"},
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    if resp.status_code != 200:
        raise ProviderError(f"Crossref API returned HTTP {resp.status_code}.")
    data = resp.json()
    items = (data.get("message") or {}).get("items") or []
    candidates: list[SearchCandidate] = []
    for item in items:
        url = str(item.get("URL") or "").strip()
        if not url and item.get("DOI"):
            url = f"https://doi.org/{item['DOI']}"
        if not url:
            continue
        titles = item.get("title") or []
        title = str(titles[0]).strip() if titles else url
        pub_date = None
        date_parts = ((item.get("published") or {}).get("date-parts") or [[]])[0]
        if date_parts:
            pub_date = "-".join(str(p).zfill(2) if i > 0 else str(p) for i, p in enumerate(date_parts[:3]))
        containers = item.get("container-title") or []
        src_hint = str(containers[0]).strip() if containers else "Crossref Peer-Reviewed"
        tier, rank, _, _ = classify_source_priority(url, title=title, hint_tier="peer_reviewed")
        candidates.append(
            SearchCandidate(
                url=url,
                candidate_title=title,
                source_priority_tier=tier,
                priority_rank=rank,
                publication_date_hint=pub_date,
                source_name_hint=src_hint,
            )
        )
    return candidates


def _search_with_key_provider(
    client: httpx.Client,
    provider_name: SearchProviderName,
    query: str,
    max_results: int,
    api_key: str,
) -> list[SearchCandidate]:
    rows: list[tuple[str, str]] = []
    if provider_name == "tavily":
        resp = client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results, "search_depth": "basic"},
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        if resp.status_code != 200:
            raise ProviderError(sanitize_secret_text(f"Tavily HTTP {resp.status_code}", api_key))
        for r in resp.json().get("results") or []:
            rows.append((str(r.get("url") or ""), str(r.get("title") or "")))
    elif provider_name == "serper":
        resp = client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": max_results},
            headers={"X-API-KEY": api_key, "User-Agent": DEFAULT_USER_AGENT},
        )
        if resp.status_code != 200:
            raise ProviderError(sanitize_secret_text(f"Serper HTTP {resp.status_code}", api_key))
        for r in resp.json().get("organic") or []:
            rows.append((str(r.get("link") or ""), str(r.get("title") or "")))
    elif provider_name == "brave":
        resp = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
        )
        if resp.status_code != 200:
            raise ProviderError(sanitize_secret_text(f"Brave HTTP {resp.status_code}", api_key))
        for r in ((resp.json().get("web") or {}).get("results") or []):
            rows.append((str(r.get("url") or ""), str(r.get("title") or "")))

    candidates: list[SearchCandidate] = []
    seen: set[str] = set()
    for url, title in rows:
        cleaned = url.strip()
        if not cleaned.startswith(("http://", "https://")) or cleaned in seen:
            continue
        seen.add(cleaned)
        tier, rank, _, _ = classify_source_priority(cleaned, title=title)
        candidates.append(
            SearchCandidate(
                url=cleaned,
                candidate_title=title.strip() or cleaned,
                source_priority_tier=tier,
                priority_rank=rank,
                source_name_hint=urlparse(cleaned).hostname or cleaned,
            )
        )
    return candidates


def search_web_candidates(
    query: str,
    *,
    provider_name: SearchProviderName,
    max_results: int,
    secret_store: SecretStore,
    http_transport: httpx.BaseTransport | None = None,
) -> list[SearchCandidate]:
    """Run web search cleanly discarding snippets, then rank URLs by reliability priority."""
    api_key: str | None = None
    if provider_name in ("tavily", "serper", "brave"):
        api_key = secret_store.get_api_key(search_key_account_name(provider_name))
        if not api_key:
            raise ProviderConfigError(
                f"Search provider '{provider_name}' requires an API key in Windows Credential Manager (Settings), "
                "or switch to free 'duckduckgo_lite' / 'crossref'."
            )

    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            transport=http_transport,
        ) as client:
            if provider_name == "duckduckgo_lite":
                raw = _search_duckduckgo_lite(client, query, max_results)
            elif provider_name == "crossref":
                raw = _search_crossref(client, query, max_results)
            elif api_key is not None:
                raw = _search_with_key_provider(client, provider_name, query, max_results, api_key)
            else:
                raise ProviderConfigError(f"Unsupported search provider: {provider_name}")
    except ProviderError:
        raise
    except httpx.HTTPError as exc:
        raise ProviderError(
            sanitize_secret_text(
                f"Search provider '{provider_name}' network error ({exc.__class__.__name__}: {exc})",
                api_key,
            )
        ) from exc

    return sorted(raw, key=lambda c: c.priority_rank)


def _extract_html_metadata_and_text(
    raw_bytes: bytes,
    *,
    fallback_url: str,
    last_modified: str | None = None,
) -> tuple[str, str | None, str, str | None]:
    """Extract (source_name, publication_date, clean_text, raw_lower_check) from HTML safely."""
    decoded = raw_bytes.decode("utf-8", errors="replace")
    lower_raw = decoded.lower()
    tree = lxml_html.fromstring(decoded)

    title_nodes = tree.xpath("//title/text()")
    page_title = " ".join(str(title_nodes[0]).split()) if title_nodes else ""

    site_name = ""
    for meta in tree.xpath("//meta"):
        prop = str(meta.get("property") or meta.get("name") or "").strip().lower()
        if prop in {"og:site_name", "application-name"} and meta.get("content"):
            site_name = " ".join(str(meta.get("content")).split())
            break
    source_name = page_title or site_name or (urlparse(fallback_url).hostname or fallback_url)

    pub_date: str | None = None
    for meta in tree.xpath("//meta"):
        key = str(meta.get("property") or meta.get("name") or meta.get("http-equiv") or "").strip().lower()
        if key in _DATE_META_NAMES and meta.get("content"):
            pub_date = " ".join(str(meta.get("content")).split())[:64]
            break
    if not pub_date:
        for script_text in tree.xpath("//script[@type='application/ld+json']/text()"):
            try:
                parsed_ld = json.loads(str(script_text))
                if isinstance(parsed_ld, dict) and parsed_ld.get("datePublished"):
                    pub_date = str(parsed_ld["datePublished"]).strip()[:64]
                    break
            except Exception:
                continue
    if not pub_date and last_modified:
        pub_date = last_modified.strip()[:64]

    # Strip active/hidden tags and HTML comments before reading visible page text
    for tag in ("script", "style", "noscript", "template", "iframe", "svg"):
        for el in tree.xpath(f"//{tag}"):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
    from lxml import etree

    for comment in tree.xpath("//comment()"):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)

    body_nodes = tree.xpath("//body")
    root_el = body_nodes[0] if body_nodes else tree
    text = " ".join(etree.tostring(root_el, method="text", encoding="unicode").split())
    return source_name[:512], pub_date, text[:MAX_EXTRACTED_CHARS], lower_raw


def _extract_pdf_metadata_and_text(
    raw_bytes: bytes,
    *,
    fallback_url: str,
    last_modified: str | None = None,
) -> tuple[str, str | None, str]:
    """Extract PDF title, creation date, and bounded plain text via PyMuPDF."""
    doc = pymupdf.open(stream=raw_bytes, filetype="pdf")
    try:
        meta = doc.metadata or {}
        title = " ".join(str(meta.get("title") or "").split())
        raw_date = str(meta.get("creationDate") or meta.get("modDate") or "").strip()
        pub_date: str | None = None
        if raw_date.startswith("D:") and len(raw_date) >= 10:
            pub_date = f"{raw_date[2:6]}-{raw_date[6:8]}-{raw_date[8:10]}"
        elif raw_date:
            pub_date = raw_date[:64]
        elif last_modified:
            pub_date = last_modified.strip()[:64]
        chunks: list[str] = []
        total_len = 0
        for pno, page in enumerate(doc, start=1):
            page_txt = " ".join((page.get_text("text") or "").split())
            if page_txt:
                piece = f"[Page {pno}] {page_txt}"
                chunks.append(piece)
                total_len += len(piece)
                if total_len >= MAX_EXTRACTED_CHARS:
                    break
        text = "\n".join(chunks)[:MAX_EXTRACTED_CHARS]
        source_name = title or (urlparse(fallback_url).hostname or fallback_url)
        return source_name[:512], pub_date, text
    finally:
        doc.close()


def _detect_injection_signals(text: str) -> list[str]:
    hits: list[str] = []
    for pat in _INJECTION_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append(m.group(0)[:120])
    return hits


def fetch_page_evidence(
    url: str,
    *,
    candidate_title: str = "",
    hint_tier: SourcePriorityTier | None = None,
    pub_date_hint: str | None = None,
    http_transport: httpx.BaseTransport | None = None,
) -> FetchedSourceRecord:
    """Fetch a single URL directly and classify it cleanly as reviewed or inaccessible/unreviewed."""
    allow_private = http_transport is not None
    default_tier, default_rank, default_rating, default_stype = classify_source_priority(
        url, title=candidate_title, hint_tier=hint_tier
    )
    fallback_name = candidate_title.strip() or (urlparse(url).hostname or url)

    try:
        safe_url = validate_public_http_url(url, allow_private_for_test=allow_private)
    except ValueError as exc:
        return FetchedSourceRecord(
            url=url,
            final_url=url,
            source_name=fallback_name[:512],
            publication_date=pub_date_hint,
            source_priority_tier="unverified",
            priority_rank=99,
            reliability_rating="unreviewed",
            source_type=default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=None,
            failure_reason=f"Blocked URL ({exc})",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )

    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=5,
            transport=http_transport,
        ) as client:
            resp = client.get(safe_url, headers={"User-Agent": DEFAULT_USER_AGENT})
    except httpx.TimeoutException:
        return FetchedSourceRecord(
            url=url,
            final_url=safe_url,
            source_name=fallback_name[:512],
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            reliability_rating="unreviewed",
            source_type=default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=None,
            failure_reason="Request timed out; document unreviewed.",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )
    except Exception as exc:
        return FetchedSourceRecord(
            url=url,
            final_url=safe_url,
            source_name=fallback_name[:512],
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            reliability_rating="unreviewed",
            source_type=default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=None,
            failure_reason=f"Network/fetch failure ({exc.__class__.__name__}); document unreviewed.",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )

    final_url = str(resp.url)
    try:
        validate_public_http_url(final_url, allow_private_for_test=allow_private)
    except ValueError as exc:
        return FetchedSourceRecord(
            url=url,
            final_url=final_url,
            source_name=fallback_name[:512],
            publication_date=pub_date_hint,
            source_priority_tier="unverified",
            priority_rank=99,
            reliability_rating="unreviewed",
            source_type=default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=resp.status_code,
            failure_reason=f"Redirect target rejected ({exc}); document unreviewed.",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )

    if resp.status_code >= 400:
        return FetchedSourceRecord(
            url=url,
            final_url=final_url,
            source_name=fallback_name[:512],
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            reliability_rating="unreviewed",
            source_type=default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=resp.status_code,
            failure_reason=f"HTTP {resp.status_code} response; document could not be accessed and was NOT reviewed.",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )

    raw_bytes = resp.content[: MAX_FETCH_BYTES + 1]
    if len(raw_bytes) > MAX_FETCH_BYTES:
        return FetchedSourceRecord(
            url=url,
            final_url=final_url,
            source_name=fallback_name[:512],
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            reliability_rating="unreviewed",
            source_type=default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=resp.status_code,
            failure_reason=f"Document exceeded {MAX_FETCH_BYTES // (1024 * 1024)} MB limit; unreviewed.",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )

    content_type = str(resp.headers.get("content-type") or "").lower()
    last_mod = resp.headers.get("last-modified")
    is_pdf = "application/pdf" in content_type or raw_bytes.startswith(b"%PDF-") or final_url.lower().endswith(".pdf")

    try:
        if is_pdf:
            src_name, pub_date, text = _extract_pdf_metadata_and_text(
                raw_bytes, fallback_url=final_url, last_modified=last_mod
            )
        elif "html" in content_type or "text/plain" in content_type or not content_type:
            if "text/plain" in content_type and not raw_bytes.lstrip().startswith(b"<"):
                src_name = fallback_name[:512]
                pub_date = last_mod.strip()[:64] if last_mod else pub_date_hint
                text = " ".join(raw_bytes.decode("utf-8", errors="replace").split())[:MAX_EXTRACTED_CHARS]
                lower_raw = text.lower()
            else:
                src_name, pub_date, text, lower_raw = _extract_html_metadata_and_text(
                    raw_bytes, fallback_url=final_url, last_modified=last_mod
                )
            if any(marker in lower_raw for marker in _BOT_OR_PAYWALL_MARKERS) and len(text) < 1200:
                return FetchedSourceRecord(
                    url=url,
                    final_url=final_url,
                    source_name=(src_name or fallback_name)[:512],
                    publication_date=pub_date or pub_date_hint,
                    source_priority_tier=default_tier,
                    priority_rank=default_rank,
                    reliability_rating="unreviewed",
                    source_type="pdf" if is_pdf else default_stype,
                    access_status="inaccessible",
                    reviewed=False,
                    http_status=resp.status_code,
                    failure_reason="Paywall, login gate, or anti-bot challenge detected; document unreviewed.",
                    extracted_text=None,
                    excerpt=None,
                    injection_signals=[],
                )
        else:
            return FetchedSourceRecord(
                url=url,
                final_url=final_url,
                source_name=fallback_name[:512],
                publication_date=pub_date_hint,
                source_priority_tier=default_tier,
                priority_rank=default_rank,
                reliability_rating="unreviewed",
                source_type=default_stype,
                access_status="inaccessible",
                reviewed=False,
                http_status=resp.status_code,
                failure_reason=f"Unsupported content-type '{content_type}'; document unreviewed.",
                extracted_text=None,
                excerpt=None,
                injection_signals=[],
            )
    except Exception as exc:
        return FetchedSourceRecord(
            url=url,
            final_url=final_url,
            source_name=fallback_name[:512],
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            reliability_rating="unreviewed",
            source_type=default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=resp.status_code,
            failure_reason=f"Failed to parse document ({exc.__class__.__name__}); unreviewed.",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )

    if not text.strip():
        return FetchedSourceRecord(
            url=url,
            final_url=final_url,
            source_name=(src_name or fallback_name)[:512],
            publication_date=pub_date or pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            reliability_rating="unreviewed",
            source_type="pdf" if is_pdf else default_stype,
            access_status="inaccessible",
            reviewed=False,
            http_status=resp.status_code,
            failure_reason="Document returned empty readable text; marked unreviewed.",
            extracted_text=None,
            excerpt=None,
            injection_signals=[],
        )

    tier, rank, rating, stype = classify_source_priority(
        final_url, title=src_name, hint_tier=hint_tier
    )
    if is_pdf:
        stype = "pdf"
    signals = _detect_injection_signals(text)
    excerpt = text[:1200].strip()

    return FetchedSourceRecord(
        url=url,
        final_url=final_url,
        source_name=src_name or fallback_name[:512],
        publication_date=pub_date or pub_date_hint,
        source_priority_tier=tier,
        priority_rank=rank,
        reliability_rating=rating,
        source_type=stype,
        access_status="accessible",
        reviewed=True,
        http_status=resp.status_code,
        failure_reason=None,
        extracted_text=text,
        excerpt=excerpt,
        injection_signals=signals,
    )
