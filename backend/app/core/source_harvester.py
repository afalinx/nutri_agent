"""Autonomous URL harvesting for allowlisted recipe sources."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings
from app.core.source_discovery import DiscoverySourceOutput
from app.core.source_policy import DomainPolicy, load_source_policy, match_domain_policy, validate_url_against_policy

_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE)
_SITEMAP_RE = re.compile(r"^\s*Sitemap:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_HREF_RE = re.compile(r"""href=["']([^"'#]+)["']""", re.IGNORECASE)
_URL_TOKEN_RE = re.compile(r"""(?:(?:https?://)[^\s"'<>]+|/[A-Za-z0-9_./?%:#=&+-]+)""")


async def _fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=settings.CATALOG_SOURCE_FETCH_TIMEOUT_SEC, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text[: settings.CATALOG_SOURCE_MAX_BYTES]


def _extract_sitemap_urls(robots_txt: str) -> list[str]:
    return [match.group(1).strip() for match in _SITEMAP_RE.finditer(robots_txt)]


def _extract_loc_urls(xml_text: str) -> list[str]:
    return [match.group(1).strip() for match in _LOC_RE.finditer(xml_text)]


def _extract_html_links(html_text: str, *, base_url: str) -> list[str]:
    links: list[str] = []
    for match in _HREF_RE.finditer(html_text):
        candidate = urljoin(base_url, match.group(1).strip())
        if candidate not in links:
            links.append(candidate)
    return links


def _extract_embedded_urls(html_text: str, *, base_url: str) -> list[str]:
    links: list[str] = []
    for match in _URL_TOKEN_RE.finditer(html_text):
        token = match.group(0).strip()
        if token.startswith("//"):
            continue
        candidate = urljoin(base_url, token)
        if candidate not in links:
            links.append(candidate)
    return links


async def _discover_from_sitemaps(domain_policy: DomainPolicy, *, query: str | None = None) -> list[str]:
    base_url = f"https://{domain_policy.domain}"
    sitemap_urls: list[str] = []
    try:
        robots_txt = await _fetch_text(f"{base_url}/robots.txt")
        sitemap_urls.extend(_extract_sitemap_urls(robots_txt))
    except Exception:
        sitemap_urls = []
    if not sitemap_urls:
        sitemap_urls = [f"{base_url}/sitemap.xml"]

    discovered: list[str] = []
    fallback_candidates: list[str] = []
    query_tokens = [token.lower() for token in (query or "").split() if token.strip()]
    for sitemap_url in sitemap_urls[:3]:
        try:
            xml_text = await _fetch_text(sitemap_url)
        except Exception:
            continue
        for url in _extract_loc_urls(xml_text):
            ok, _ = validate_url_against_policy(url)
            if not ok:
                continue
            lowered = url.lower()
            if query_tokens and any(token in lowered for token in query_tokens):
                if url not in discovered:
                    discovered.append(url)
            elif url not in fallback_candidates:
                fallback_candidates.append(url)
            if len(discovered) >= load_source_policy().max_pages_per_domain:
                return discovered
    if discovered:
        return discovered
    return fallback_candidates[: load_source_policy().max_pages_per_domain]


async def _discover_from_category_pages(domain_policy: DomainPolicy, *, query: str | None = None) -> list[str]:
    query_tokens = [token.lower() for token in (query or "").split() if token.strip()]
    discovered: list[str] = []
    fallback_candidates: list[str] = []
    max_pages = max(1, min(load_source_policy().max_pages_per_domain, 5))
    for entrypoint in domain_policy.category_entrypoints:
        for page_num in range(1, max_pages + 1):
            page_path = entrypoint if page_num == 1 else f"{entrypoint}?page={page_num}"
            page_url = urljoin(f"https://{domain_policy.domain}", page_path)
            try:
                html_text = await _fetch_text(page_url)
            except Exception:
                break
            page_had_candidates = False
            page_links = _extract_html_links(html_text, base_url=page_url)
            page_links.extend(link for link in _extract_embedded_urls(html_text, base_url=page_url) if link not in page_links)
            for link in page_links:
                ok, _ = validate_url_against_policy(link)
                if not ok:
                    continue
                page_had_candidates = True
                lowered = link.lower()
                path = urlparse(link).path.lower()
                if query_tokens and any(token in lowered or token in path for token in query_tokens):
                    if link not in discovered:
                        discovered.append(link)
                elif link not in fallback_candidates:
                    fallback_candidates.append(link)
                if len(discovered) >= load_source_policy().max_pages_per_domain:
                    return discovered
            if not page_had_candidates:
                break
    if discovered:
        return discovered
    return fallback_candidates[: load_source_policy().max_pages_per_domain]


async def discover_source_urls(*, query: str | None = None, domains: list[str] | None = None) -> list[DiscoverySourceOutput]:
    policy = load_source_policy()
    selected: list[DomainPolicy] = []
    if domains:
        for domain in domains:
            matched = match_domain_policy(domain)
            if matched is not None and matched not in selected:
                selected.append(matched)
    else:
        selected = list(policy.domains)

    outputs: list[DiscoverySourceOutput] = []
    for domain_policy in selected:
        discovered_urls: list[str] = []
        discovery_method: str | None = None
        if "sitemap" in domain_policy.methods:
            discovered_urls.extend(await _discover_from_sitemaps(domain_policy, query=query))
            if discovered_urls:
                discovery_method = "sitemap"
        if not discovered_urls and "category_pages" in domain_policy.methods:
            discovered_urls.extend(await _discover_from_category_pages(domain_policy, query=query))
            if discovered_urls:
                discovery_method = "category_pages"
        for url in discovered_urls:
            outputs.append(
                DiscoverySourceOutput(
                    url=url,
                    source_type="web",
                    discovery_query=query,
                    discovery_payload={"domain": domain_policy.domain, "method": discovery_method},
                    provenance={
                        "discovery_method": discovery_method or "unknown",
                        "trust_level": domain_policy.trust_level,
                        "policy_domain": domain_policy.domain,
                    },
                    discovered_by="source_harvester",
                )
            )
            if len(outputs) >= policy.max_urls_per_run:
                return outputs
    return outputs
