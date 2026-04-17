"""Tests for policy-based autonomous source harvesting."""

from __future__ import annotations

import pytest

from app.core import source_harvester


def test_extract_sitemap_urls_from_robots():
    robots = """
    User-agent: *
    Sitemap: https://eda.ru/sitemap.xml
    Sitemap: https://eda.ru/sitemap-recipes.xml
    """
    urls = source_harvester._extract_sitemap_urls(robots)
    assert urls == ["https://eda.ru/sitemap.xml", "https://eda.ru/sitemap-recipes.xml"]


def test_extract_loc_urls_from_xml():
    xml = """
    <urlset>
      <url><loc>https://eda.ru/recepty/supy/borsh-123</loc></url>
      <url><loc>https://eda.ru/search?q=borsch</loc></url>
    </urlset>
    """
    urls = source_harvester._extract_loc_urls(xml)
    assert urls == ["https://eda.ru/recepty/supy/borsh-123", "https://eda.ru/search?q=borsch"]


def test_extract_html_links_from_category_page():
    html = """
    <html>
      <body>
        <a href="/recepty/supy/borsh-123">Борщ</a>
        <a href="https://eda.rambler.ru/recepty/salaty/cesar-555">Цезарь</a>
      </body>
    </html>
    """
    links = source_harvester._extract_html_links(html, base_url="https://eda.ru/recepty")
    assert "https://eda.ru/recepty/supy/borsh-123" in links
    assert "https://eda.rambler.ru/recepty/salaty/cesar-555" in links


def test_extract_embedded_urls_from_script_payload():
    html = """
    <script type="application/ld+json">
      {"itemListElement":[{"url":"https://eda.rambler.ru/recepty/supy/borsh-123"}]}
    </script>
    """
    links = source_harvester._extract_embedded_urls(html, base_url="https://eda.ru/recepty")
    assert "https://eda.rambler.ru/recepty/supy/borsh-123" in links


@pytest.mark.asyncio
async def test_discover_source_urls_filters_to_policy_matching_urls(monkeypatch):
    calls = []

    async def fake_fetch_text(url: str):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return "Sitemap: https://eda.ru/sitemap.xml"
        return """
        <urlset>
          <url><loc>https://eda.ru/recepty/supy/borsh-123</loc></url>
          <url><loc>https://eda.ru/search?q=borsch</loc></url>
          <url><loc>https://eda.ru/recepty/salaty/cesar-555</loc></url>
        </urlset>
        """

    monkeypatch.setattr(source_harvester, "_fetch_text", fake_fetch_text)

    outputs = await source_harvester.discover_source_urls(query="borsh", domains=["eda.ru"])

    assert len(outputs) == 1
    assert outputs[0].url == "https://eda.ru/recepty/supy/borsh-123"
    assert outputs[0].provenance["discovery_method"] == "sitemap"


@pytest.mark.asyncio
async def test_discover_source_urls_falls_back_to_category_pages(monkeypatch):
    async def fake_fetch_text(url: str):
        if url.endswith("/robots.txt"):
            return ""
        if url.endswith("/sitemap.xml"):
            raise RuntimeError("no sitemap")
        return """
        <html>
          <body>
            <a href="/recepty/supy/borsh-123">Борщ</a>
            <a href="/search?q=borsh">Search</a>
          </body>
        </html>
        """

    monkeypatch.setattr(source_harvester, "_fetch_text", fake_fetch_text)

    outputs = await source_harvester.discover_source_urls(query="borsh", domains=["eda.ru"])

    assert len(outputs) == 1
    assert outputs[0].url == "https://eda.ru/recepty/supy/borsh-123"
    assert outputs[0].provenance["discovery_method"] == "category_pages"
