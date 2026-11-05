"""Build an optional user-defined search topic from GUI settings."""
from __future__ import annotations

import copy
import re


CUSTOM_TOPIC_MARKER = "_gui_custom_topic"
CUSTOM_DIRECTION = "自定义方向"


def parse_terms(value: str | list[str] | None) -> list[str]:
    """Split GUI keyword input on lines, commas, or semicolons and remove duplicates."""
    if isinstance(value, list):
        raw_terms = value
    elif isinstance(value, str):
        raw_terms = re.split(r"[\r\n,，;；]+", value)
    elif value is None:
        raw_terms = []
    else:
        raise ValueError("自定义关键词必须是文本或字符串列表")

    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in raw_terms:
        term = str(raw_term).strip()
        key = term.casefold()
        if term and key not in seen:
            terms.append(term)
            seen.add(key)
    return terms


def custom_topic_name(settings: dict) -> str:
    return " ".join(parse_terms(settings.get("custom_keyword_terms")))


def normalize_custom_selection(settings: dict, existing_topic_names: set[str]) -> dict:
    """Migrate older saved selections that used the joined keyword string as the option."""
    updated = copy.deepcopy(settings)
    selected = str(updated.get("search_topic") or "")
    name = custom_topic_name(updated)
    legacy_name = str(updated.get("custom_topic_name") or "")
    if selected == CUSTOM_DIRECTION:
        return updated
    if selected in {legacy_name, name} and selected not in existing_topic_names:
        if selected:
            updated["search_topic"] = CUSTOM_DIRECTION
    return updated


def apply_custom_topic(cfg: dict, settings: dict) -> dict:
    """Append the GUI-defined OR topic only while the custom direction is selected."""
    updated = copy.deepcopy(cfg)
    topics = [topic for topic in updated.get("topics", []) if not topic.get(CUSTOM_TOPIC_MARKER)]
    updated["topics"] = topics

    if settings.get("search_topic") != CUSTOM_DIRECTION:
        return updated

    terms = parse_terms(settings.get("custom_keyword_terms"))
    if not terms:
        raise ValueError("自定义方向至少需要填写一个关键词")

    name = custom_topic_name(settings)
    if not name:
        return updated
    if any(str(topic.get("name", "")).casefold() == name.casefold() for topic in topics):
        raise ValueError(f"自定义主题名称「{name}」与已有研究方向重复")

    escaped_terms = [term.replace("\\", "\\\\").replace('"', '\\"') for term in terms]
    query = "|".join(f'"{term}"' for term in escaped_terms)
    topics.append(
        {
            "name": name,
            "color": "#64748B",
            "query": query,
            "backup_queries": terms,
            "anchors": terms,
            "keywords": terms,
            "require_title_hit": True,
            CUSTOM_TOPIC_MARKER: True,
        }
    )
    return updated