"""Tests for declarative source discovery policy."""

from __future__ import annotations

from app.core import source_policy


def test_match_domain_policy_allows_exact_domain():
    source_policy.load_source_policy.cache_clear()
    policy = source_policy.match_domain_policy("eda.ru")
    assert policy is not None
    assert policy.domain == "eda.ru"


def test_match_domain_policy_allows_subdomain():
    source_policy.load_source_policy.cache_clear()
    policy = source_policy.match_domain_policy("m.eda.ru")
    assert policy is not None
    assert policy.domain == "eda.ru"


def test_match_domain_policy_allows_alias_domain():
    source_policy.load_source_policy.cache_clear()
    policy = source_policy.match_domain_policy("eda.rambler.ru")
    assert policy is not None
    assert policy.domain == "eda.ru"


def test_validate_url_against_policy_rejects_blocked_path():
    source_policy.load_source_policy.cache_clear()
    ok, report = source_policy.validate_url_against_policy("https://eda.ru/search?q=borsch")
    assert ok is False
    assert report["reason_codes"] == ["source_path_blocked"]


def test_validate_url_against_policy_requires_recipe_path():
    source_policy.load_source_policy.cache_clear()
    ok, report = source_policy.validate_url_against_policy("https://gastronom.ru/text/abc")
    assert ok is False
    assert report["reason_codes"] == ["source_path_blocked"]


def test_validate_url_against_policy_accepts_recipe_url():
    source_policy.load_source_policy.cache_clear()
    ok, report = source_policy.validate_url_against_policy("https://eda.ru/recepty/supy/borsh-123")
    assert ok is True
    assert report["trust_level"] == "trusted_editorial"


def test_validate_url_against_policy_rejects_category_page():
    source_policy.load_source_policy.cache_clear()
    ok, report = source_policy.validate_url_against_policy("https://eda.rambler.ru/recepty/supy")
    assert ok is False
    assert report["reason_codes"] == ["source_path_not_recipe_page"]
