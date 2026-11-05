"""本地状态：已推送记录、文章元数据缓存、收藏反馈学习。"""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

STATE_PATH = ROOT / "state" / "state.json"
ARTICLES_CACHE = ROOT / "cache" / "articles.json"
FEEDBACK_DIR = ROOT / "feedback"

EMPTY_STATE = {
    "version": 1,
    "reported": {},          # doi -> 首次进入日报的日期
    "blacklist": [],         # 你点过"不感兴趣"的 doi
    "feedback": {
        "journals": {},
        "publishers": {},
        "topics": {},
        "terms": {},
        "journal_topics": {},
    },
}


def _read(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


class Store:
    def __init__(self):
        self.state = _read(STATE_PATH, json.loads(json.dumps(EMPTY_STATE)))
        self.articles = _read(ARTICLES_CACHE, {})

    # ---------------- 已推送 ----------------
    def is_reported(self, doi: str) -> bool:
        return doi in self.state.get("reported", {})

    def mark_reported(self, dois: list[str], day: str) -> None:
        for d in dois:
            self.state["reported"].setdefault(d, day)

    def is_blacklisted(self, doi: str) -> bool:
        return doi in set(self.state.get("blacklist", []))

    # ---------------- 文章缓存 ----------------
    def remember(self, items: list[dict]) -> None:
        for it in items:
            if not it.get("doi"):
                continue
            self.articles[it["doi"]] = {
                "title_en": it.get("title_en", ""),
                "journal": it.get("journal", ""),
                "publisher": it.get("publisher", ""),
                "topics": it.get("topics", []),
                "matched_terms": it.get("matched_terms", []),
                "published": it.get("published", ""),
            }

    # ---------------- 反馈 ----------------
    def _bump(self, bucket: str, key: str, delta: int) -> None:
        fb = self.state["feedback"].setdefault(bucket, {})
        fb[key] = fb.get(key, 0) + delta

    def ingest_feedback(self) -> dict:
        """读取 feedback/*.json（由 HTML 日报的“导出反馈”生成），更新偏好权重。"""
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        liked = disliked = 0
        for path in FEEDBACK_DIR.glob("*.json"):
            data = _read(path, None)
            if not isinstance(data, dict):
                continue
            for doi in data.get("liked", []) or []:
                meta = self.articles.get(doi)
                if not meta:
                    continue
                liked += 1
                self._bump("journals", meta.get("journal", ""), 1)
                self._bump("publishers", meta.get("publisher", ""), 1)
                for t in meta.get("topics", []):
                    self._bump("topics", t, 1)
                    self._bump("journal_topics", f"{meta.get('journal','')}|{t}", 1)
                for term in meta.get("matched_terms", []):
                    self._bump("terms", term, 1)

            for doi in data.get("disliked", []) or []:
                meta = self.articles.get(doi)
                disliked += 1
                if doi not in self.state["blacklist"]:
                    self.state["blacklist"].append(doi)
                if not meta:
                    continue
                self._bump("journals", meta.get("journal", ""), -1)
                self._bump("publishers", meta.get("publisher", ""), -1)
                for t in meta.get("topics", []):
                    self._bump("topics", t, -1)
                    self._bump("journal_topics", f"{meta.get('journal','')}|{t}", -1)

            done = path.with_suffix(path.suffix + ".done")
            try:
                path.replace(done)
            except Exception:
                pass
        return {"liked": liked, "disliked": disliked}

    # ---------------- 保存 ----------------
    def save(self) -> None:
        _write(STATE_PATH, self.state)
        _write(ARTICLES_CACHE, self.articles)

    def stats(self) -> dict:
        return self.state.get("feedback", {})
