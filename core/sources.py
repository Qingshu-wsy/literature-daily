"""数据采集：OpenAlex 检索 + Crossref 摘要补全。

为什么不用出版社 RSS：
  1) 门户未登录时出版社站点直接 TLS 重置，抓取必挂；
  2) RSS 结构各社不同、一年改版好几次，维护成本极高；
  3) OpenAlex/Crossref 由出版社直接喂数据，字段稳定、覆盖全。
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import date, timedelta

import requests

from .config import ROOT

OPENALEX_BASE = "https://api.openalex.org/works"
CROSSREF_BASE = "https://api.crossref.org/works"
CACHE_DIR = ROOT / "cache" / "openalex"

SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "publication_date",
        "type",
        "primary_location",
        "open_access",
        "best_oa_location",
        "authorships",
        "abstract_inverted_index",
        "cited_by_count",
    ]
)


# ---------------------------------------------------------------- 工具

def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def rebuild_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    pos: dict[int, str] = {}
    for word, idxs in inverted.items():
        for i in idxs:
            pos.setdefault(int(i), word)
    return " ".join(pos[i] for i in sorted(pos))


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    d = doi.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    return d.lower()


def publisher_url(doi: str) -> str:
    """DOI 能直接推出的出版社直达链接，推不出的回退到 doi.org。"""
    d = normalize_doi(doi)
    resolver = f"https://doi.org/{d}"
    if not d:
        return ""
    if d.startswith("10.1021"):
        return f"https://pubs.acs.org/doi/{d}"
    if d.startswith("10.1002"):
        return f"https://onlinelibrary.wiley.com/doi/{d}"
    if d.startswith("10.1038"):
        return "https://www.nature.com/articles/" + d.split("/", 1)[1]
    if d.startswith("10.1126"):
        return f"https://www.science.org/doi/{d}"
    if d.startswith("10.1039"):
        return f"https://pubs.rsc.org/en/content/articlelanding/{d}"
    return resolver


# ---------------------------------------------------------------- OpenAlex

class OpenAlexClient:
    def __init__(
        self,
        api_key: str = "",
        email: str = "",
        timeout: int = 45,
        cache_ttl: int = 6 * 3600,
    ):
        self.api_key = (api_key or "").strip()
        self.email = (email or "").strip()
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.session = requests.Session()
        ua = "lit-daily-screen/1.0"
        if self.email:
            ua += f" (mailto:{self.email})"
        self.session.headers.update({"User-Agent": ua})
        self.request_count = 0
        self.cache_hits = 0
        self.last_error = ""
        self.budget_exhausted = False

    # -- 本地缓存：同样的查询 6 小时内不重复花钱 -------------------------
    def _cache_path(self, params: dict):
        key = json.dumps(params, sort_keys=True, ensure_ascii=False)
        return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def _cache_read(self, params: dict) -> dict | None:
        if self.cache_ttl <= 0:
            return None
        path = self._cache_path(params)
        try:
            if path.exists() and (time.time() - path.stat().st_mtime) < self.cache_ttl:
                self.cache_hits += 1
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def _cache_write(self, params: dict, data: dict) -> None:
        if self.cache_ttl <= 0:
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._cache_path(params).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    # -- 底层 ----------------------------------------------------------
    def _get(self, params: dict, retries: int = 3) -> dict:
        cache_params = dict(params)
        cached = self._cache_read(cache_params)
        if cached is not None:
            return cached

        if self.api_key:
            params = {**params, "api_key": self.api_key}
        delay = 2.0
        for attempt in range(retries):
            self.request_count += 1
            try:
                r = self.session.get(OPENALEX_BASE, params=params, timeout=self.timeout)
            except Exception as exc:  # 网络问题，重试
                self.last_error = f"网络错误: {exc}"
                time.sleep(delay)
                delay *= 2
                continue

            if r.status_code == 200:
                data = r.json()
                if data.get("error"):
                    self.last_error = str(data.get("message") or data["error"])
                    raise RuntimeError(self.last_error)
                self._cache_write(cache_params, data)
                return data

            # 额度/权限/限流
            try:
                msg = r.json().get("message") or r.text[:200]
            except Exception:
                msg = r.text[:200]
            self.last_error = f"HTTP {r.status_code}: {msg}"
            # 预算用完重试也没用，直接标记并放弃（避免白等 6 秒）
            if "insufficient budget" in msg.lower() or "budget is used up" in msg.lower():
                self.budget_exhausted = True
                raise RuntimeError(self.last_error)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(self.last_error)

        raise RuntimeError(self.last_error or "OpenAlex 请求失败")

    # -- 检索 ----------------------------------------------------------
    def search_topic(
        self,
        query: str,
        start: date,
        end: date,
        types: list[str],
        limit: int = 300,
        page_size: int = 200,
    ) -> list[dict]:
        """按主题布尔查询 + 日期窗口抓取，自动翻页。"""
        filters = [
            f"title_and_abstract.search:{query}",
            f"from_publication_date:{start.isoformat()}",
            f"to_publication_date:{end.isoformat()}",
        ]
        if types:
            filters.append("type:" + "|".join(types))

        results: list[dict] = []
        page = 1
        while len(results) < limit:
            params = {
                "filter": ",".join(filters),
                "per-page": min(page_size, limit - len(results)),
                "page": page,
                "select": SELECT_FIELDS,
                "sort": "publication_date:desc",
            }
            data = self._get(params)
            batch = data.get("results") or []
            results.extend(batch)
            if len(batch) < params["per-page"]:
                break
            page += 1
            if page > 10:
                break
        return results[:limit]

    def by_doi(self, doi: str) -> dict | None:
        params = {"select": SELECT_FIELDS}
        url = f"{OPENALEX_BASE}/https://doi.org/{normalize_doi(doi)}"
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None


# ---------------------------------------------------------------- Crossref

def _crossref_date(msg: dict) -> str:
    for key in ("published", "issued", "published-print", "published-online"):
        parts = ((msg.get(key) or {}).get("date-parts") or [[]])[0]
        if parts and parts[0]:
            return "-".join(f"{int(p):02d}" if i else str(p) for i, p in enumerate(parts[:3]))
    return ""


def crossref_to_item(msg: dict) -> dict:
    doi = normalize_doi(msg.get("DOI"))
    title = _clean((msg.get("title") or [""])[0])
    journal = _clean((msg.get("container-title") or [""])[0])
    authors = []
    for a in msg.get("author") or []:
        name = " ".join(x for x in (a.get("given", ""), a.get("family", "")) if x).strip()
        if name:
            authors.append(name)
    return {
        "id": doi,
        "doi": doi,
        "title_en": title,
        "title_zh": "",
        "abstract_en": _clean(msg.get("abstract", "")),
        "abstract_zh": "",
        "journal": journal,
        "journal_issn": (msg.get("ISSN") or [""])[0],
        "publisher_raw": _clean(msg.get("publisher", "")),
        "publisher": "",
        "published": _crossref_date(msg),
        "type": "review" if "review" in (title or "").lower() else "article",
        "authors": authors,
        "url_publisher": publisher_url(doi),
        "url_doi": f"https://doi.org/{doi}" if doi else "",
        "url_pdf": "",
        "oa_url": "",
        "is_oa": False,
        "cited_by": msg.get("is-referenced-by-count") or 0,
        "openalex_id": "",
        "topics": [],
        "score": 0.0,
        "matched_terms": [],
        "channel": "crossref",
        "tl_dr": "",
    }


class CrossrefClient:
    """OpenAlex 额度用完/不可用时的备用检索通道（Crossref 不收钱、不限额度）。"""

    def __init__(self, email: str = "", timeout: int = 30):
        self.email = (email or "").strip()
        self.timeout = timeout
        self.request_count = 0

    def search_terms(self, phrases: list[str], start: date, end: date, limit: int = 120) -> list[dict]:
        """多短语检索并按 DOI 去重；Crossref 免费但会限流，所以串行 + 间隔。"""
        phrases = [p for p in dict.fromkeys(phrases) if p]
        if not phrases:
            return []
        per = max(20, limit // len(phrases))
        out: dict[str, dict] = {}
        last_err = ""
        for i, phrase in enumerate(phrases):
            if i:
                time.sleep(0.8)
            try:
                batch = self.search_topic(phrase, start, end, per)
            except Exception as exc:
                last_err = str(exc)
                continue
            for it in batch:
                key = it["doi"] or it["title_en"].lower()[:100]
                if key and key not in out:
                    out[key] = it
        if not out and last_err:
            raise RuntimeError(last_err)
        return list(out.values())

    def search_topic(self, query: str, start: date, end: date, limit: int = 120) -> list[dict]:
        phrase = query.split("|")[0].strip().strip('"').replace("-", " ")
        params = {
            "query.bibliographic": phrase,
            "filter": (
                f"from-pub-date:{start.isoformat()},until-pub-date:{end.isoformat()},"
                "type:journal-article"
            ),
            "rows": min(200, max(20, limit)),
            "select": (
                "DOI,title,container-title,publisher,issued,published,author,"
                "abstract,is-referenced-by-count,type,ISSN"
            ),
        }
        if self.email:
            params["mailto"] = self.email

        last_err = ""
        for attempt in range(3):
            self.request_count += 1
            r = requests.get(
                CROSSREF_BASE,
                params=params,
                timeout=self.timeout,
                headers={
                    "User-Agent": f"lit-daily-screen/1.0 (mailto:{self.email or 'none@example.com'})"
                },
            )
            if r.status_code == 200:
                return [crossref_to_item(m) for m in (r.json().get("message") or {}).get("items") or []]
            last_err = f"Crossref HTTP {r.status_code}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            break
        raise RuntimeError(last_err)


def crossref_abstract(doi: str, email: str = "", timeout: int = 20) -> str:
    """Crossref 补摘要（ACS/Springer 多数有，Elsevier 通常没有）。"""
    d = normalize_doi(doi)
    if not d:
        return ""
    try:
        r = requests.get(
            f"{CROSSREF_BASE}/{d}",
            params={"mailto": email} if email else None,
            timeout=timeout,
            headers={"User-Agent": f"lit-daily-screen/1.0 (mailto:{email or 'none@example.com'})"},
        )
        if r.status_code != 200:
            return ""
        return _clean((r.json().get("message") or {}).get("abstract", ""))
    except Exception:
        return ""


# ---------------------------------------------------------------- 归一化

NATURE_PREFIXES = ("10.1038/",)


def work_to_item(work: dict, topic_names: list[str] | None = None) -> dict:
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    doi = normalize_doi(work.get("doi"))
    oa = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in (work.get("authorships") or [])
        if (a.get("author") or {}).get("display_name")
    ]
    return {
        "id": doi or work.get("id", ""),
        "doi": doi,
        "title_en": _clean(work.get("title")),
        "title_zh": "",
        "abstract_en": rebuild_abstract(work.get("abstract_inverted_index")),
        "abstract_zh": "",
        "journal": (src.get("display_name") or loc.get("raw_source_name") or "").strip(),
        "journal_issn": src.get("issn_l") or "",
        "publisher_raw": (src.get("host_organization_name") or "").strip(),
        "publisher": "",
        "published": work.get("publication_date") or "",
        "type": work.get("type") or "",
        "authors": authors,
        "url_publisher": publisher_url(doi) or loc.get("landing_page_url") or "",
        "url_doi": f"https://doi.org/{doi}" if doi else "",
        "url_pdf": best.get("pdf_url") or "",
        "oa_url": oa.get("oa_url") or "",
        "is_oa": bool(oa.get("is_oa")),
        "cited_by": work.get("cited_by_count") or 0,
        "openalex_id": work.get("id", ""),
        "topics": list(topic_names or []),
        "score": 0.0,
        "matched_terms": [],
        "channel": "openalex",
        "tl_dr": "",
    }


def date_window(days: int, end: date | None = None) -> tuple[date, date]:
    end = end or date.today()
    return end - timedelta(days=max(0, days - 1)), end
