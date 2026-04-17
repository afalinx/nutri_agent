"""Declarative source discovery policy for external recipe harvesting."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlparse

import yaml

POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "catalog_source_policy.yml"


@dataclass(frozen=True)
class DomainPolicy:
    domain: str
    trust_level: str
    locale: str | None
    aliases: tuple[str, ...]
    methods: tuple[str, ...]
    category_entrypoints: tuple[str, ...]
    recipe_url_patterns: tuple[str, ...]
    recipe_url_regexes: tuple[str, ...]
    blocked_path_patterns: tuple[str, ...]


@dataclass(frozen=True)
class SourcePolicy:
    require_https: bool
    max_urls_per_run: int
    max_pages_per_domain: int
    domains: tuple[DomainPolicy, ...]


def _normalize_domain(value: str) -> str:
    return value.strip().lower()


def _normalize_patterns(values: list[str] | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in (values or []) if v and v.strip())


@lru_cache(maxsize=1)
def load_source_policy() -> SourcePolicy:
    raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    domains = []
    for item in raw.get("domains") or []:
        domains.append(
            DomainPolicy(
                domain=_normalize_domain(item["domain"]),
                trust_level=item.get("trust_level") or "unknown",
                locale=item.get("locale"),
                aliases=tuple(_normalize_domain(alias) for alias in (item.get("aliases") or []) if alias),
                methods=tuple(item.get("methods") or ()),
                category_entrypoints=_normalize_patterns(item.get("category_entrypoints")),
                recipe_url_patterns=_normalize_patterns(item.get("recipe_url_patterns")),
                recipe_url_regexes=_normalize_patterns(item.get("recipe_url_regexes")),
                blocked_path_patterns=_normalize_patterns(item.get("blocked_path_patterns")),
            )
        )
    return SourcePolicy(
        require_https=bool(defaults.get("require_https", True)),
        max_urls_per_run=int(defaults.get("max_urls_per_run", 100)),
        max_pages_per_domain=int(defaults.get("max_pages_per_domain", 50)),
        domains=tuple(domains),
    )


def match_domain_policy(hostname: str | None) -> DomainPolicy | None:
    if not hostname:
        return None
    normalized = _normalize_domain(hostname)
    policy = load_source_policy()
    for domain_policy in policy.domains:
        allowed_hosts = (domain_policy.domain, *domain_policy.aliases)
        if any(normalized == host or normalized.endswith(f".{host}") for host in allowed_hosts):
            return domain_policy
    return None


def validate_url_against_policy(url: str) -> tuple[bool, dict]:
    parsed = urlparse(url)
    policy = load_source_policy()
    if policy.require_https and parsed.scheme != "https":
        return False, {"reason_codes": ["source_url_not_https"], "notes": ["Only https source URLs are allowed"]}
    domain_policy = match_domain_policy(parsed.hostname)
    if domain_policy is None:
        return False, {
            "reason_codes": ["source_domain_not_allowed"],
            "notes": [f"Source domain is not allowlisted: {(parsed.hostname or '').lower()}"],
        }

    path = parsed.path or "/"
    if any(pattern in path for pattern in domain_policy.blocked_path_patterns):
        return False, {
            "reason_codes": ["source_path_blocked"],
            "notes": [f"Source path is blocked by policy: {path}"],
        }
    if domain_policy.recipe_url_patterns and not any(pattern in path for pattern in domain_policy.recipe_url_patterns):
        return False, {
            "reason_codes": ["source_path_not_recipe_like"],
            "notes": [f"Source path does not match recipe patterns: {path}"],
        }
    if domain_policy.recipe_url_regexes and not any(re.search(pattern, path) for pattern in domain_policy.recipe_url_regexes):
        return False, {
            "reason_codes": ["source_path_not_recipe_page"],
            "notes": [f"Source path does not match recipe page shape: {path}"],
        }

    return True, {
        "reason_codes": [],
        "notes": [],
        "domain": domain_policy.domain,
        "trust_level": domain_policy.trust_level,
        "locale": domain_policy.locale,
        "methods": list(domain_policy.methods),
    }
