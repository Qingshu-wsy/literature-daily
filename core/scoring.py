"""主题匹配与打分。

规则很直白，方便你随时调：
  anchors 必须命中其一 → 才算这个主题（防误判，比如 "emitter" 单独出现不算 OLED）
  标题命中 +3 / 摘要命中 +1 / anchor 命中再 +2
  期刊分层、综述、你的收藏反馈各自加减分
"""
from __future__ import annotations

import re
import unicodedata

DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-", "\u00a0": " "})


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(DASHES)
    text = text.replace("₂", "2").replace("₃", "3").replace("₄", "4")
    # 摘要分词常把化学式拆开：CO 2 / H 2 O 2 → CO2 / H2O2
    text = re.sub(r"(?<=[A-Za-z])\s+(?=\d)", "", text)
    text = re.sub(r"(?<=\d)\s+(?=[A-Z])", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _last_word_pattern(word: str) -> str:
    """处理复数：battery→batteries，framework→frameworks。"""
    if len(word) > 1 and word.endswith("y") and word[-2] not in "aeou":
        return re.escape(word[:-1]) + r"(?:y|ies)"
    if word.endswith("s"):
        return re.escape(word)
    return re.escape(word) + r"s?"


def compile_term(term: str) -> re.Pattern:
    """把 'covalent organic framework' 编成能容忍连字符/复数/大小写的正则。"""
    norm = normalize(term)
    parts = [p for p in re.split(r"[\s\-]+", norm) if p]
    if not parts:
        return re.compile(r"(?!x)x")
    body = r"[\s\-]*".join(_last_word_pattern(p) if i == len(parts) - 1 else re.escape(p)
                           for i, p in enumerate(parts))
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.I)


class TopicSpec:
    def __init__(self, cfg: dict, defaults: dict | None = None):
        d = defaults or {}
        self.name = cfg["name"]
        self.color = cfg.get("color", "#666")
        self.query = (cfg.get("query") or "").strip()
        self.min_topic_score = float(cfg.get("min_topic_score", d.get("min_topic_score", 4)))
        self.min_score = float(cfg.get("min_score", d.get("min_score", 5)))
        self.require_title_hit = bool(cfg.get("require_title_hit", d.get("require_title_hit", True)))
        self.backup_queries = [q for q in (cfg.get("backup_queries") or []) if q]
        anchors = cfg.get("anchors", []) or []
        groups: list[list[str]] = []
        if anchors:
            groups.append(anchors)
        for g in cfg.get("require_all", []) or []:
            if g:
                groups.append(g)
        self.groups = [[compile_term(t) for t in g] for g in groups]
        self.raw_groups = groups
        self.exclude = [compile_term(t) for t in (cfg.get("exclude") or [])]
        self.keywords = [(t, compile_term(t)) for t in cfg.get("keywords", []) or []]

    def build_query(self) -> str:
        """没有手写 query 时，用 anchors + require_all 拼一个。"""
        if self.query:
            return self.query
        terms: list[str] = []
        for g in self.raw_groups:
            for t in g:
                t = t.strip()
                if not t:
                    continue
                terms.append(f'"{t}"' if " " in t else t)
        return "|".join(t for t in dict.fromkeys(terms))

    def backup_terms(self) -> list[str]:
        """Crossref 备用通道用的检索词（Crossref 不支持布尔式，只能给短语）。"""
        if self.backup_queries:
            return self.backup_queries
        phrase = self.build_query().split("|")[0].strip().strip('"').replace("-", " ")
        return [phrase] if phrase else []


class TopicMatcher:
    def __init__(self, topics_cfg: list[dict], scoring: dict):
        self.scoring = scoring
        self.topics = [TopicSpec(t, scoring) for t in topics_cfg]
        self.title_hit = float(scoring.get("title_hit", 3))
        self.abstract_hit = float(scoring.get("abstract_hit", 1))
        self.anchor_bonus = float(scoring.get("anchor_bonus", 2))
        self.title_anchor_bonus = float(scoring.get("title_anchor_bonus", 2))
        self.min_topic_score = float(scoring.get("min_topic_score", 4))
        self.min_score = float(scoring.get("min_score", 5))
        self.review_bonus = float(scoring.get("review_bonus", 1))
        self.strong_topic_score = float(scoring.get("strong_topic_score", 12))

    def _score_topic(self, topic: TopicSpec, title: str, abstract: str):
        text = f"{title} {abstract}"
        if not topic.groups:
            return 0.0, []
        if any(p.search(text) for p in topic.exclude):
            return 0.0, []
        # 每组都必须命中至少一个词（多组之间是“与”的关系）
        for group in topic.groups:
            if not any(p.search(text) for p in group):
                return 0.0, []

        anchor_in_title = any(p.search(title) for group in topic.groups for p in group)
        hits: list[str] = []
        title_hits: list[str] = []
        score = self.anchor_bonus
        if anchor_in_title:
            score += self.title_anchor_bonus

        for label, pattern in topic.keywords:
            in_title = bool(pattern.search(title))
            in_abstract = bool(pattern.search(abstract))
            if in_title:
                score += self.title_hit
                hits.append(label)
                title_hits.append(label)
            elif in_abstract:
                score += self.abstract_hit
                hits.append(label)

        # 标题里必须出现主题词（锚点或关键词），否则视为“顺带提及”
        if topic.require_title_hit and score < self.strong_topic_score:
            if not (anchor_in_title or title_hits):
                return 0.0, []

        return score, hits

    def match(self, item: dict) -> dict:
        """给单条文献打上 topics / matched_terms / topic_scores。"""
        title = normalize(item.get("title_en", ""))
        abstract = normalize(item.get("abstract_en", ""))
        topic_scores: dict[str, float] = {}
        terms: list[str] = []

        for topic in self.topics:
            s, hits = self._score_topic(topic, title, abstract)
            if s >= topic.min_topic_score:
                topic_scores[topic.name] = round(s, 1)
                for h in hits:
                    if h not in terms:
                        terms.append(h)

        item["topic_scores"] = topic_scores
        item["topics"] = list(topic_scores.keys())
        item["matched_terms"] = terms
        item["score"] = max(topic_scores.values()) if topic_scores else 0.0
        return item


def journal_bonus(journal: str, tiers: list[dict]) -> float:
    if not journal:
        return 0.0
    for tier in tiers or []:
        for pat in tier.get("match", []) or []:
            try:
                if re.search(pat, journal, re.I):
                    return float(tier.get("bonus", 0))
            except re.error:
                continue
    return 0.0


def classify_publisher(host_raw: str, journal: str, publishers: dict) -> str:
    host = (host_raw or "").lower()
    if host:
        for name, patterns in (publishers or {}).items():
            for pat in patterns or []:
                if pat.lower() in host:
                    return name
    j = (journal or "").lower()
    if j.startswith("nature") or j.startswith("npj ") or j.startswith("npj"):
        return "Nature"
    if j.startswith("communications ") and any(
        k in j for k in ("chemistry", "physics", "materials", "biology", "earth")
    ):
        return "Nature"
    return "Other"


def feedback_bonus(item: dict, stats: dict, weight: float, cap: float) -> float:
    """根据历史收藏/屏蔽记录微调分数（有上限，避免一家独大）。"""
    if not stats:
        return 0.0
    total = 0.0
    total += stats.get("journals", {}).get(item.get("journal", ""), 0)
    total += stats.get("publishers", {}).get(item.get("publisher", ""), 0)
    for t in item.get("topics", []) or []:
        total += stats.get("topics", {}).get(t, 0)
        total += stats.get("journal_topics", {}).get(f"{item.get('journal','')}|{t}", 0)
    for term in item.get("matched_terms", []) or []:
        total += stats.get("terms", {}).get(term, 0)
    if total == 0:
        return 0.0
    bonus = max(-cap, min(cap, total * weight / 3.0))
    return round(bonus, 2)


def topic_thresholds(cfg: dict) -> dict[str, float]:
    """每个主题的出榜分数线：topic 里没写就用全局 scoring.min_score。"""
    default = float(cfg.get("scoring", {}).get("min_score", 5))
    return {
        t.get("name"): float(t.get("min_score", default))
        for t in (cfg.get("topics") or [])
        if t.get("name")
    }


def finalize(item: dict, cfg: dict, stats: dict | None = None) -> dict | None:
    """补全出版社、期刊加分、反馈分；不合格返回 None。

    分数线是「按主题」判的：一篇论文只要在某个主题上过了该主题的线就保留，
    其它没过线的主题会被摘掉。这样冷门方向（锂硫、CO2 还原）不会被热门方向挤掉。
    """
    sc = cfg["scoring"]
    item["publisher_raw"] = item.get("publisher_raw") or ""
    item["publisher"] = classify_publisher(
        item.get("publisher_raw", ""), item.get("journal", ""), cfg.get("publishers", {})
    )

    if item["publisher"] == "Other" and not cfg.get("allow_other_publishers"):
        if not item.get("is_preprint"):
            return None

    topic_scores = dict(item.get("topic_scores") or {})
    if not topic_scores:
        return None

    jb = journal_bonus(item.get("journal", ""), cfg.get("journal_tiers", []))
    tb = sc.get("review_bonus", 1) if item.get("type") == "review" else 0
    fb = feedback_bonus(item, stats or {}, float(sc.get("feedback_weight", 1.5)),
                        float(sc.get("max_feedback_bonus", 3)))
    extra = jb + tb + fb

    thresholds = topic_thresholds(cfg)
    kept: dict[str, float] = {}
    for name, base in topic_scores.items():
        total = round(base + extra, 1)
        if total >= thresholds.get(name, float(sc.get("min_score", 5))):
            kept[name] = base
    if not kept:
        return None

    item["journal_bonus"] = jb
    item["feedback_bonus"] = fb
    item["topic_scores"] = kept
    item["topics"] = list(kept.keys())
    item["score"] = round(max(kept.values()) + extra, 1)
    return item
