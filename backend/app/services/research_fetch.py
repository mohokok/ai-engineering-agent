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
MAX_EXCERPT_CHARS = 2_400
MIN_SUBSTANTIVE_CHARS = 160
MIN_SUBSTANTIVE_WORDS = 25
MIN_PROSE_CHARS = 120
MIN_PROSE_WORDS = 18
MIN_PROSE_RATIO = 0.25
FETCH_TIMEOUT_SECONDS = 15.0
DEFAULT_USER_AGENT = (
    "LocalAIEngineeringAgent/0.8 (Consultancy Research Client; +local-desktop-app)"
)
_PRIMARY_FETCH_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}
_RETRY_MINIMAL_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
}
OWNER_MANUAL_UPLOAD_ACTION = (
    "download the document yourself and upload it in Projects & Files; it will be cited as owner-provided"
)

_SEARCH_PROVIDER_METADATA: tuple[dict[str, Any], ...] = (
    {
        "id": "duckduckgo_lite",
        "label": "DuckDuckGo Lite (Best-Effort Free, Zero API Key)",
        "requires_api_key": False,
        "is_default": True,
        "pricing_summary": "Free, no API key or credit card required (best-effort only).",
        "notes": "Best-effort free search; if rate-limited, recommend Tavily (free API key entered in Settings), Crossref, or direct URLs.",
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
    "attention required!",
)
_LOGIN_PAYWALL_PATTERNS = (
    "sign in to your personal account",
    "sign in to your account",
    "sign in now",
    "sign up now",
    "sign in",
    "log in",
    "username or email",
    "forgot password",
    "change password",
    "current password",
    "password",
    "create an account",
    "don't have a personal account",
    "with a personal account, you can",
    "incorrect email address",
    "register for access",
    "institutional access",
    "institutional login",
    "access through your institution",
    "shibboleth",
    "openathens",
    "subscription required",
    "subscribe to continue",
    "purchase this article",
    "buy this chapter",
    "add to cart",
    "full text access requires",
    "save download print citation",
)
_COOKIE_WALL_PATTERNS = (
    "accept cookies",
    "accept all cookies",
    "reject all cookies",
    "cookie preferences",
    "cookie settings",
    "manage cookies",
    "we use cookies to",
    "your privacy choices",
)
_COUNTRY_LIST_MARKERS = (
    "afghanistan",
    "aland islands",
    "albania",
    "algeria",
    "american samoa",
    "andorra",
    "angola",
    "anguilla",
    "antarctica",
    "antigua and barbuda",
    "argentina",
    "armenia",
    "aruba",
    "azerbaijan",
    "bahamas",
    "bahrain",
    "bangladesh",
    "barbados",
    "belarus",
    "belize",
    "benin",
    "bermuda",
    "bhutan",
    "bolivia",
    "botswana",
    "brunei",
    "bulgaria",
    "burkina faso",
    "burundi",
    "cambodia",
    "cameroon",
    "cape verde",
)
_PHOTO_ARCHIVE_MARKERS = (
    "photo archive",
    "photograph archive",
    "digital collections",
    "digital archive",
    "image archive",
    "lantern slide",
    "rights statement",
    "archival photograph",
    "visual resources",
)
_BOOK_LANDING_MARKERS = (
    "bloomsbury collections",
    "encyclopedia-chapter",
    "buy print",
    "buy ebook",
    "recommend to your library",
    "request permissions",
    "purchase access",
)
_EN_QUERY_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "what", "which", "who", "how", "when", "where", "all", "any", "check",
    "find", "search", "lookup", "verify", "review", "per", "about", "into",
    "over", "under", "between", "using", "based", "note", "notes",
})
_AR_QUERY_STOPWORDS = frozenset({
    "في", "من", "على", "إلى", "الى", "عن", "مع", "أو", "او", "أن", "إن",
    "هذا", "هذه", "ذلك", "تلك", "الذي", "التي", "حول", "عبر", "وفق", "كل",
})
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
    work_type: str | None = None
    provider_name: str | None = None
    tier_claim_label: str = "Domain/URL heuristic (provider/automated claim — unverified)"


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
    tier_is_provider_claim: bool = True
    tier_claim_label: str = "Domain/URL heuristic (provider/automated claim — unverified)"


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
    if hint_tier == "unverified":
        return "unverified", 99, "unrated", "unverified"
    if hint_tier and hint_tier in SOURCE_PRIORITY_SPEC:
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
        headers=_PRIMARY_FETCH_HEADERS,
    )
    if resp.status_code != 200:
        raise ProviderError(
            f"DuckDuckGo Lite (best-effort only) returned HTTP {resp.status_code}. "
            "Recommend entering a free Tavily Search API key in Settings, trying Crossref Peer-Reviewed, "
            "passing direct URLs, or uploading the document in Projects & Files as owner-provided."
        )
    lower_body = resp.text.lower()
    if "captcha" in lower_body or "anomaly" in lower_body:
        raise ProviderError(
            "DuckDuckGo Lite (best-effort only) presented an anti-bot challenge (blocked without bypassing). "
            "Recommend entering a free Tavily Search API key in Settings, trying Crossref Peer-Reviewed, "
            "or passing direct URLs / owner-provided uploads."
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
                provider_name="duckduckgo_lite",
                tier_claim_label="Claimed from URL/domain heuristic (unverified)",
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
        params={"query": query, "rows": max_results, "select": "DOI,title,URL,published,container-title,type"},
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
        src_hint = str(containers[0]).strip() if containers else "Crossref Record"
        work_type = str(item.get("type") or "other").strip().lower()
        # Do NOT blindly claim every Crossref record (e.g. 'book-chapter', 'other', photo archive) is peer-reviewed
        if work_type in {"journal-article", "proceedings-article"}:
            claimed_hint: SourcePriorityTier = "peer_reviewed"
        elif work_type in {"book-chapter", "book", "monograph", "edited-book", "reference-entry", "report"}:
            claimed_hint = "reputable"
        else:
            claimed_hint = "unverified"
        tier, rank, _, _ = classify_source_priority(url, title=title, hint_tier=claimed_hint)
        claim_label = f"Provider claim (crossref: {work_type}) — unverified until full text reviewed"
        candidates.append(
            SearchCandidate(
                url=url,
                candidate_title=title,
                source_priority_tier=tier,
                priority_rank=rank,
                publication_date_hint=pub_date,
                source_name_hint=src_hint,
                work_type=work_type,
                provider_name="crossref",
                tier_claim_label=claim_label,
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
                provider_name=provider_name,
                tier_claim_label=f"Provider claim ({provider_name}) + URL heuristic — unverified",
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
        extra_hint = (
            " Recommend entering a free Tavily Search API key in Settings or using Crossref / direct URLs."
            if provider_name == "duckduckgo_lite"
            else ""
        )
        raise ProviderError(
            sanitize_secret_text(
                f"Search provider '{provider_name}' network error ({exc.__class__.__name__}: {exc}).{extra_hint}",
                api_key,
            )
        ) from exc

    return sorted(raw, key=lambda c: c.priority_rank)


def _extract_html_metadata_and_text(
    raw_bytes: bytes,
    *,
    fallback_url: str,
    last_modified: str | None = None,
) -> tuple[str, str | None, str, str, str]:
    """Extract (source_name, publication_date, clean_body_text, full_visible_text, lower_raw) from HTML."""
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

    # Strip active/hidden tags and HTML comments before reading visible text
    for tag in ("script", "style", "noscript", "template", "iframe", "svg"):
        for el in tree.xpath(f"//{tag}"):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
    for comment in tree.xpath("//comment()"):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)

    body_nodes = tree.xpath("//body")
    body_el = body_nodes[0] if body_nodes else tree
    full_visible_raw = " ".join(tok.strip() for tok in body_el.itertext() if tok and tok.strip())
    full_visible_text = re.sub(r"\s+([.,;:!?؟])", r"\1", " ".join(full_visible_raw.split()))

    # Strip navigation, footer, form, and dropdown chrome to isolate substantive prose
    for xp in (
        ".//nav",
        ".//footer",
        ".//aside",
        ".//form",
        ".//select",
        ".//dialog",
        ".//*[@role='navigation']",
        ".//*[@role='banner']",
        ".//*[@role='contentinfo']",
    ):
        for el in body_el.xpath(xp):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    main_candidates = body_el.xpath(".//main | .//article | .//*[@role='main']")
    selected_root = body_el
    if main_candidates:
        combined_main = " ".join(
            tok.strip()
            for node in main_candidates
            for tok in node.itertext()
            if tok and tok.strip()
        )
        combined_main = re.sub(r"\s+([.,;:!?؟])", r"\1", " ".join(combined_main.split()))
        if len(combined_main) >= MIN_SUBSTANTIVE_CHARS:
            selected_root = None
            text = combined_main
        else:
            text = ""
    else:
        text = ""

    if selected_root is not None:
        raw_clean = " ".join(tok.strip() for tok in selected_root.itertext() if tok and tok.strip())
        text = re.sub(r"\s+([.,;:!?؟])", r"\1", " ".join(raw_clean.split()))

    text = re.sub(
        r"^(?:skip to main content|skip to content|skip to navigation)\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return (
        source_name[:512],
        pub_date,
        text[:MAX_EXTRACTED_CHARS],
        full_visible_text[: MAX_EXTRACTED_CHARS * 2],
        lower_raw,
    )


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


_BOILERPLATE_SEGMENT_MARKERS = (
    "sign in to your personal account",
    "sign in to your account",
    "forgot password",
    "change password",
    "current password",
    "don't have a personal account",
    "with a personal account, you can",
    "incorrect email address",
    "sign up now",
    "sign up via",
    "accept all cookies",
    "accept cookies",
    "cookie preferences",
    "subscription required",
    "this item is only available to the members of institutions",
    "save download print citation",
    "are you sure you want to remove the page",
    "john doe",
)
_BOILERPLATE_WORDS = frozenset({
    "sign", "login", "log", "password", "forgot", "cookie", "cookies", "accept",
    "select", "country", "afghanistan", "albania", "algeria", "andorra", "angola",
    "home", "navigation", "menu", "privacy", "terms", "register", "subscribe",
})


def _extract_prose_segments(clean_body_text: str) -> list[str]:
    """Identify sentence-like prose segments, ignoring nav/login/cookie/country boilerplate."""
    segments = [seg.strip() for seg in re.split(r"(?<=[.!?؟])\s+|\n+", clean_body_text) if seg.strip()]
    if len(segments) == 1 and len(clean_body_text) >= MIN_SUBSTANTIVE_CHARS:
        # Handle single-block technical/PDF pages that lack terminal period splits nicely
        segments = [clean_body_text.strip()]
    prose: list[str] = []
    for seg in segments:
        if len(seg) < 40:
            continue
        seg_lower = seg.lower()
        if any(marker in seg_lower for marker in _BOILERPLATE_SEGMENT_MARKERS):
            continue
        words = re.findall(r"[\w\u0600-\u06FF'-]+", seg)
        if len(words) < 7:
            continue
        boiler_count = sum(1 for w in words if w.lower() in _BOILERPLATE_WORDS)
        if boiler_count / len(words) >= 0.35:
            continue
        has_lower_prose = sum(1 for w in words if len(w) >= 2 and w.isalpha() and w.islower()) >= 2
        has_arabic_prose = sum(1 for w in words if any("\u0600" <= ch <= "\u06ff" for ch in w)) >= 2
        if has_lower_prose or has_arabic_prose:
            prose.append(seg)
    return prose


def assess_page_content_quality(
    full_visible_text: str,
    clean_body_text: str,
    *,
    lower_raw_html: str = "",
    url: str = "",
    is_pdf: bool = False,
) -> tuple[bool, str | None, str | None]:
    """Reject login/paywall/cookie walls, country dropdowns, photo archives, and thin/non-prose pages."""
    body = " ".join(clean_body_text.split())
    full = " ".join(full_visible_text.split())
    lower_body = body.lower()
    lower_full = full.lower()
    lower_raw = lower_raw_html or lower_full

    word_tokens = re.findall(r"[\w\u0600-\u06FF'-]+", body)
    is_photo_archive = (not is_pdf) and any(
        m in lower_body or m in lower_full or m in url.lower() for m in _PHOTO_ARCHIVE_MARKERS
    )
    if is_photo_archive and len(body) < 1_000:
        return (
            False,
            f"login wall / paywall / cookie wall / no substantive text (photo or digital archive landing page without technical prose) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            "photo_archive",
        )

    if len(body) < MIN_SUBSTANTIVE_CHARS or len(word_tokens) < MIN_SUBSTANTIVE_WORDS:
        return (
            False,
            f"login wall / paywall / cookie wall / no substantive text (only {len(body)} chars / {len(word_tokens)} words extracted) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            None,
        )

    prose_segments = _extract_prose_segments(body)
    prose_chars = sum(len(s) for s in prose_segments)
    prose_words = sum(len(re.findall(r"[\w\u0600-\u06FF'-]+", s)) for s in prose_segments)
    prose_ratio = prose_chars / max(len(body), 1)

    country_hits = sum(1 for c in _COUNTRY_LIST_MARKERS if c in lower_full)
    has_country_dropdown = country_hits >= 5 or (
        country_hits >= 3 and ("select country" in lower_full or "country*" in lower_full)
    )
    if has_country_dropdown and (prose_chars < 900 or prose_ratio < 0.55):
        return (
            False,
            f"login wall / paywall / cookie wall / no substantive text (registration country list / login form detected) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            None,
        )

    has_bot_marker = any(m in lower_raw or m in lower_full for m in _BOT_OR_PAYWALL_MARKERS)
    if has_bot_marker and (prose_chars < 600 or prose_ratio < 0.45):
        return (
            False,
            f"login wall / paywall / cookie wall / no substantive text (paywall or anti-bot gate detected) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            None,
        )

    body_login_hits = sum(1 for p in _LOGIN_PAYWALL_PATTERNS if p in lower_body)
    full_login_hits = sum(1 for p in _LOGIN_PAYWALL_PATTERNS if p in lower_full)
    body_cookie_hits = sum(1 for p in _COOKIE_WALL_PATTERNS if p in lower_body)

    explicit_login_gate = any(
        k in lower_body
        for k in (
            "sign in to your personal account",
            "forgot password",
            "incorrect email address",
            "subscription required",
            "full text access requires",
        )
    )
    if (
        (explicit_login_gate and (prose_chars < 900 or prose_ratio < 0.60))
        or (body_login_hits >= 2 and (prose_chars < 600 or prose_ratio < 0.50))
        or (full_login_hits >= 3 and (prose_chars < 500 or prose_ratio < 0.45))
        or (body_cookie_hits >= 2 and (prose_chars < 450 or prose_ratio < 0.45))
    ):
        return (
            False,
            f"login wall / paywall / cookie wall / no substantive text (sign-in, paywall, or cookie gate detected) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            None,
        )

    if (
        not prose_segments
        or prose_words < MIN_PROSE_WORDS
        or prose_chars < MIN_PROSE_CHARS
        or prose_ratio < MIN_PROSE_RATIO
    ):
        return (
            False,
            f"login wall / paywall / cookie wall / no substantive text (low ratio of sentence-like prose: {prose_ratio:.0%}) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            None,
        )

    return True, None, None


def extract_query_terms(query: str) -> list[str]:
    """Extract normalized meaningful English/Arabic query terms (excluding common stopwords)."""
    raw_tokens = re.findall(r"[\w\u0600-\u06FF.-]{2,}", query.lower())
    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_tokens:
        tok = raw.strip(".-")
        if len(tok) < 2:
            continue
        if tok in _EN_QUERY_STOPWORDS or tok in _AR_QUERY_STOPWORDS:
            continue
        if tok not in seen:
            seen.add(tok)
            terms.append(tok)
    return terms


def _term_matches_body(term: str, body_lower: str) -> bool:
    if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", body_lower):
        return True
    if any("\u0600" <= ch <= "\u06ff" for ch in term) and term.startswith("ال") and len(term) >= 4:
        stripped_ar = term[2:]
        if re.search(rf"(?<!\w)(?:ال)?{re.escape(stripped_ar)}", body_lower):
            return True
    if term.isascii() and term.isalpha() and len(term) >= 5:
        stem = term.rstrip("s")
        if stem != term and re.search(rf"(?<!\w){re.escape(stem)}s?(?!\w)", body_lower):
            return True
        if len(term) >= 6 and term[:5] in body_lower:
            return True
    return False


def is_text_relevant_to_query(clean_body_text: str, query: str) -> bool:
    """Verify substantive body text (never title alone) addresses meaningful query terms."""
    terms = extract_query_terms(query)
    if not terms:
        return True
    body_lower = clean_body_text.lower()
    body_has_latin = any("a" <= ch <= "z" for ch in body_lower)
    body_has_ar = any("\u0600" <= ch <= "\u06ff" for ch in body_lower)

    active_terms = [
        t
        for t in terms
        if (any("\u0600" <= ch <= "\u06ff" for ch in t) and body_has_ar)
        or (any("a" <= ch <= "z" or "0" <= ch <= "9" for ch in t) and body_has_latin)
    ]
    if not active_terms:
        active_terms = terms

    matched_terms = [t for t in active_terms if _term_matches_body(t, body_lower)]
    if len(active_terms) <= 3:
        return len(matched_terms) >= 1
    if len(matched_terms) >= 2:
        return True
    if len(matched_terms) == 1:
        occurrences = len(re.findall(rf"(?<!\w){re.escape(matched_terms[0])}", body_lower))
        return occurrences >= 2
    return False


def _inaccessible_record(
    *,
    url: str,
    final_url: str,
    source_name: str,
    publication_date: str | None,
    source_priority_tier: SourcePriorityTier,
    priority_rank: int,
    source_type: str,
    http_status: int | None,
    reason: str,
    access_status: AccessStatus = "inaccessible",
    reliability_rating: ReliabilityRating = "unreviewed",
    tier_claim_label: str = "Domain/URL heuristic (provider/automated claim — unverified)",
) -> FetchedSourceRecord:
    return FetchedSourceRecord(
        url=url,
        final_url=final_url,
        source_name=source_name[:512],
        publication_date=publication_date,
        source_priority_tier=source_priority_tier,
        priority_rank=priority_rank,
        reliability_rating=reliability_rating,
        source_type=source_type,
        access_status=access_status,
        reviewed=False,
        http_status=http_status,
        failure_reason=reason,
        extracted_text=None,
        excerpt=None,
        injection_signals=[],
        tier_is_provider_claim=True,
        tier_claim_label=tier_claim_label,
    )


def fetch_page_evidence(
    url: str,
    *,
    query: str = "",
    candidate_title: str = "",
    hint_tier: SourcePriorityTier | None = None,
    pub_date_hint: str | None = None,
    work_type: str | None = None,
    search_provider: str | None = None,
    tier_claim_label: str | None = None,
    http_transport: httpx.BaseTransport | None = None,
) -> FetchedSourceRecord:
    """Fetch a single URL directly, apply content-quality & relevance gates, and classify reviewed/unreviewed."""
    allow_private = http_transport is not None
    default_tier, default_rank, _, default_stype = classify_source_priority(
        url, title=candidate_title, hint_tier=hint_tier
    )
    fallback_name = candidate_title.strip() or (urlparse(url).hostname or url)
    resolved_claim_label = tier_claim_label or (
        f"Provider claim ({search_provider}: {work_type or default_tier}) — unverified"
        if search_provider
        else f"URL/domain heuristic ({default_tier}) — unverified claim"
    )
    base_stype = f"{search_provider}:{work_type}" if (search_provider == "crossref" and work_type) else default_stype

    try:
        safe_url = validate_public_http_url(url, allow_private_for_test=allow_private)
    except ValueError as exc:
        return _inaccessible_record(
            url=url,
            final_url=url,
            source_name=fallback_name,
            publication_date=pub_date_hint,
            source_priority_tier="unverified",
            priority_rank=99,
            source_type=base_stype,
            http_status=None,
            reason=f"Blocked URL ({exc})",
            tier_claim_label=resolved_claim_label,
        )

    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=5,
            transport=http_transport,
        ) as client:
            resp = client.get(safe_url, headers=_PRIMARY_FETCH_HEADERS)
            if resp.status_code in (403, 406, 429):
                # Retry ONCE cleanly with standard Accept-Encoding and an explicitly Referer-less request
                with httpx.Client(
                    timeout=FETCH_TIMEOUT_SECONDS,
                    follow_redirects=True,
                    max_redirects=5,
                    transport=http_transport,
                ) as retry_client:
                    resp = retry_client.get(safe_url, headers=_RETRY_MINIMAL_HEADERS)
    except httpx.TimeoutException:
        return _inaccessible_record(
            url=url,
            final_url=safe_url,
            source_name=fallback_name,
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            source_type=base_stype,
            http_status=None,
            reason=f"Request timed out (unreviewed); {OWNER_MANUAL_UPLOAD_ACTION}.",
            tier_claim_label=resolved_claim_label,
        )
    except Exception as exc:
        return _inaccessible_record(
            url=url,
            final_url=safe_url,
            source_name=fallback_name,
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            source_type=base_stype,
            http_status=None,
            reason=f"Network/fetch failure ({exc.__class__.__name__}) — document unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            tier_claim_label=resolved_claim_label,
        )

    final_url = str(resp.url)
    try:
        validate_public_http_url(final_url, allow_private_for_test=allow_private)
    except ValueError as exc:
        return _inaccessible_record(
            url=url,
            final_url=final_url,
            source_name=fallback_name,
            publication_date=pub_date_hint,
            source_priority_tier="unverified",
            priority_rank=99,
            source_type=base_stype,
            http_status=resp.status_code,
            reason=f"Redirect target rejected ({exc}) — unreviewed.",
            tier_claim_label=resolved_claim_label,
        )

    if resp.status_code >= 400:
        return _inaccessible_record(
            url=url,
            final_url=final_url,
            source_name=fallback_name,
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            source_type=base_stype,
            http_status=resp.status_code,
            reason=f"HTTP {resp.status_code} response — document could not be accessed and was NOT reviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            tier_claim_label=resolved_claim_label,
        )

    raw_bytes = resp.content[: MAX_FETCH_BYTES + 1]
    if len(raw_bytes) > MAX_FETCH_BYTES:
        return _inaccessible_record(
            url=url,
            final_url=final_url,
            source_name=fallback_name,
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            source_type=base_stype,
            http_status=resp.status_code,
            reason=f"Document exceeded {MAX_FETCH_BYTES // (1024 * 1024)} MB limit (unreviewed); {OWNER_MANUAL_UPLOAD_ACTION}.",
            tier_claim_label=resolved_claim_label,
        )

    content_type = str(resp.headers.get("content-type") or "").lower()
    last_mod = resp.headers.get("last-modified")
    is_pdf = "application/pdf" in content_type or raw_bytes.startswith(b"%PDF-") or final_url.lower().endswith(".pdf")

    try:
        if is_pdf:
            src_name, pub_date, text = _extract_pdf_metadata_and_text(
                raw_bytes, fallback_url=final_url, last_modified=last_mod
            )
            full_visible_text = text
            lower_raw = text.lower()
        elif "html" in content_type or "text/plain" in content_type or not content_type:
            if "text/plain" in content_type and not raw_bytes.lstrip().startswith(b"<"):
                src_name = fallback_name[:512]
                pub_date = last_mod.strip()[:64] if last_mod else pub_date_hint
                text = " ".join(raw_bytes.decode("utf-8", errors="replace").split())[:MAX_EXTRACTED_CHARS]
                full_visible_text = text
                lower_raw = text.lower()
            else:
                src_name, pub_date, text, full_visible_text, lower_raw = _extract_html_metadata_and_text(
                    raw_bytes, fallback_url=final_url, last_modified=last_mod
                )
        else:
            return _inaccessible_record(
                url=url,
                final_url=final_url,
                source_name=fallback_name,
                publication_date=pub_date_hint,
                source_priority_tier=default_tier,
                priority_rank=default_rank,
                source_type=base_stype,
                http_status=resp.status_code,
                reason=f"Unsupported content-type '{content_type}' — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
                tier_claim_label=resolved_claim_label,
            )
    except Exception as exc:
        return _inaccessible_record(
            url=url,
            final_url=final_url,
            source_name=fallback_name,
            publication_date=pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            source_type=base_stype,
            http_status=resp.status_code,
            reason=f"Failed to parse document ({exc.__class__.__name__}) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            tier_claim_label=resolved_claim_label,
        )

    if not text.strip():
        return _inaccessible_record(
            url=url,
            final_url=final_url,
            source_name=src_name or fallback_name,
            publication_date=pub_date or pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            source_type="pdf" if is_pdf else base_stype,
            http_status=resp.status_code,
            reason=f"login wall / paywall / cookie wall / no substantive text (document returned empty body) — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            tier_claim_label=resolved_claim_label,
        )

    # 1. Content-quality gate: reject login walls, cookie walls, country lists, photo archives, and thin/non-prose pages
    quality_ok, quality_reason, detected_kind = assess_page_content_quality(
        full_visible_text,
        text,
        lower_raw_html=lower_raw,
        url=final_url,
        is_pdf=is_pdf,
    )
    if not quality_ok:
        return _inaccessible_record(
            url=url,
            final_url=final_url,
            source_name=src_name or fallback_name,
            publication_date=pub_date or pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=default_rank,
            source_type=detected_kind or ("pdf" if is_pdf else base_stype),
            http_status=resp.status_code,
            reason=quality_reason or f"login wall / paywall / cookie wall / no substantive text — unreviewed; {OWNER_MANUAL_UPLOAD_ACTION}.",
            access_status="inaccessible",
            reliability_rating="unrated" if detected_kind == "photo_archive" else "unreviewed",
            tier_claim_label=resolved_claim_label,
        )

    # 2. Relevance gate: substantive body text (never title alone) must address query terms
    if query.strip() and not is_text_relevant_to_query(text, query):
        return _inaccessible_record(
            url=url,
            final_url=final_url,
            source_name=src_name or fallback_name,
            publication_date=pub_date or pub_date_hint,
            source_priority_tier=default_tier,
            priority_rank=99,
            source_type="pdf" if is_pdf else base_stype,
            http_status=resp.status_code,
            reason=f"Not relevant to query '{query[:80]}' (substantive page text does not address query terms) — not cited.",
            access_status="not_relevant",
            reliability_rating="unrated",
            tier_claim_label=resolved_claim_label,
        )

    tier, rank, rating, stype = classify_source_priority(
        final_url, title=src_name, hint_tier=hint_tier
    )
    if is_pdf:
        stype = "pdf"
    elif base_stype.startswith("crossref:"):
        stype = base_stype

    # Never auto-rate Crossref non-articles or book/landing stubs as medium_peer_reviewed
    lower_text = text.lower()
    is_book_landing = any(m in lower_text for m in _BOOK_LANDING_MARKERS) or (
        work_type is not None and work_type not in {"journal-article", "proceedings-article"}
    )
    if is_book_landing:
        if tier == "peer_reviewed":
            tier = "reputable"
            rank = 6
        rating = "unrated"
        if not stype.startswith("crossref:"):
            stype = "book_landing"
    elif search_provider == "crossref":
        if work_type in {"journal-article", "proceedings-article"}:
            # Keep reliability unrated unless substantial full-article text (or PDF) was actually read
            if not is_pdf and len(text) < 600:
                rating = "unrated"
        else:
            rating = "unrated"

    signals = _detect_injection_signals(text)
    excerpt = text[:MAX_EXCERPT_CHARS].strip()

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
        tier_is_provider_claim=True,
        tier_claim_label=resolved_claim_label,
    )
