"""Session-locale presentation kept outside the language-neutral native core."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

DEFAULT_LOCALE = "en-US"
SUPPORTED_LOCALES = (
    "zh-CN",
    "en-US",
    "ja-JP",
    "ko-KR",
    "fr-FR",
    "de-DE",
    "es-ES",
    "ru-RU",
    "ar-SA",
)
_BASE_DEFAULTS = {tag.split("-")[0]: tag for tag in SUPPORTED_LOCALES}
_BCP47 = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def normalize_bcp47(value: Any) -> str:
    if not isinstance(value, str):
        return DEFAULT_LOCALE
    raw = value.split(".", 1)[0].replace("_", "-").strip()
    if not _BCP47.fullmatch(raw):
        return DEFAULT_LOCALE
    parts = raw.split("-")
    canonical = [parts[0].lower()]
    for part in parts[1:]:
        canonical.append(part.upper() if len(part) == 2 and part.isalpha() else part.title())
    tag = "-".join(canonical)
    if tag in SUPPORTED_LOCALES:
        return tag
    return _BASE_DEFAULTS.get(canonical[0], DEFAULT_LOCALE)


def detect_session_locale(session: Mapping[str, Any] | None) -> str:
    if not isinstance(session, Mapping):
        return DEFAULT_LOCALE
    scopes = [session]
    for key in ("metadata", "context", "client"):
        nested = session.get(key)
        if isinstance(nested, Mapping):
            scopes.append(nested)
    for scope in scopes:
        for key in ("locale", "language_tag", "language", "bcp47"):
            if key in scope:
                return normalize_bcp47(scope[key])
    return DEFAULT_LOCALE


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict[str, str]]:
    path = Path(__file__).with_name("i18n") / "catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _messages(locale: str) -> dict[str, str]:
    catalog = _catalog()
    return catalog.get(normalize_bcp47(locale), catalog[DEFAULT_LOCALE])


def render_reward_footer(
    event: dict[str, Any] | None,
    cumulative: dict[str, Any],
    locale: str,
) -> str:
    msg = _messages(locale)
    if event is None:
        return msg["no_settlement"].format(score=0, total=0)
    score = event["score"]["earned"]
    total = cumulative["cumulative_score"]
    elapsed = event["timing"]["solve_local_elapsed_ms"]
    evidence = "" if event["quality_gate"]["status"] == "PASS" else msg["evidence_insufficient"] + "\n"
    return evidence + msg["reward_footer"].format(elapsed=elapsed, score=score, total=total)


def render_settlement(result: dict[str, Any], locale: str) -> str:
    msg = _messages(locale)
    labels = {
        "decision": msg["decision"],
        "noul": msg["noul"],
        "choice": msg["choice"],
        "score": msg["score"],
    }
    items = []
    for qid, answer in sorted(result["answers"].items()):
        value = answer["value"]
        if answer.get("type") == "noul" and isinstance(value, bool):
            value = msg["yes"] if value else msg["no"]
        items.append(f"{labels.get(answer.get('type'), msg['decision'])} {qid}={value}")
    lead = " · ".join(items)
    footer = result.get("reward_summary") or msg["no_settlement"].format(score=0, total=0)
    return f"{msg['complete']} {lead}\n{footer}"
