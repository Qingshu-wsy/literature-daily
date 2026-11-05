"""中英翻译层：可插拔后端 + 本地缓存 + 失败降级。

默认 auto：有道(免费) → MyMemory(免费) → 放弃（只显示英文）。
你以后填了 DeepSeek / 智谱 的 key，把 backend 改成 deepseek / zhipu 即可，代码不用动。

缓存：同一段英文只翻一次，第二天只翻新增的几十条。
"""
from __future__ import annotations

import concurrent.futures as futures
import hashlib
import json
import re
import time
from pathlib import Path

import requests

from .config import ROOT

CACHE_PATH = ROOT / "cache" / "translate.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}
MAX_CHARS = 1500

LLM_PROMPT = (
    "你是学术论文翻译助手。把下面的英文学术文本翻译成准确、通顺的简体中文，"
    "保留专业术语（如 COF、TADF、EQE、Tafel 等）的英文缩写，不要解释、不要加引号。"
)


def _is_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4:
        return False
    ascii_ratio = sum(1 for c in letters if c.isascii()) / len(letters)
    return ascii_ratio > 0.6


def tidy_zh(text: str) -> str:
    """机翻常见毛病：汉字之间、括号内外多空格。清一遍。"""
    if not text:
        return ""
    s = text
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"（\s+", "（", s)
    s = re.sub(r"\s+）", "）", s)
    s = re.sub(r"\s+([，。；：、！？》）])", r"\1", s)
    s = re.sub(r"([（《])\s+", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _split(text: str, limit: int = MAX_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for sent in re.split(r"(?<=[.;!?])\s+", text):
        if len(cur) + len(sent) + 1 > limit and cur:
            chunks.append(cur.strip())
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        chunks.append(cur.strip())
    return chunks


class Translator:
    def __init__(self, cfg: dict):
        t = cfg.get("translation", {})
        self.enabled = bool(t.get("enabled", True))
        self.backend = (t.get("backend") or "auto").lower()
        self.opts = t
        self.workers = int(t.get("workers", 3) or 3)
        self.cache: dict[str, str] = {}
        self._dirty = 0
        self.errors: list[str] = []
        self._disabled_reason = ""
        self._load()
        if self.backend == "none":
            self.enabled = False
            self._disabled_reason = "配置里关闭了翻译"

    # ---------------- 缓存 ----------------
    def _load(self) -> None:
        try:
            if CACHE_PATH.exists():
                self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            self.cache = {}

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
            self._dirty = 0
        except Exception:
            pass

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    # ---------------- 对外 ----------------
    def translate(self, text: str) -> str:
        text = (text or "").strip()
        if not self.enabled or not text or not _is_english(text):
            return ""
        key = self._key(text)
        if key in self.cache:
            return tidy_zh(self.cache[key])
        try:
            out = self._dispatch(text)
        except Exception as exc:
            if len(self.errors) < 5:
                self.errors.append(str(exc))
            out = ""
        if out:
            out = tidy_zh(out)
        if out:
            self.cache[key] = out
            self._dirty += 1
            if self._dirty >= 30:
                self.save()
        return out

    def translate_many(self, texts: list[str]) -> dict[str, str]:
        """并发翻译，返回 {原文: 译文}（失败的取空串）。"""
        uniq = [t for t in dict.fromkeys(texts) if t and _is_english(t)]
        if not uniq or not self.enabled:
            return {}
        if self.backend in ("deepseek", "zhipu"):
            try:
                return self._llm_batch(uniq)
            except Exception as exc:
                self.errors.append(str(exc))
                return {}
        out: dict[str, str] = {}
        with futures.ThreadPoolExecutor(max_workers=max(1, self.workers)) as pool:
            jobs = {pool.submit(self.translate, t): t for t in uniq}
            for job in futures.as_completed(jobs):
                src = jobs[job]
                try:
                    res = job.result()
                except Exception:
                    res = ""
                if res:
                    out[src] = res

        # 有道偶尔限流返回空，串行补一轮（此时多半会落到 MyMemory）
        missing = [t for t in uniq if t not in out]
        if missing:
            time.sleep(1.0)
            for t in missing:
                try:
                    res = self._dispatch(t)
                except Exception:
                    res = ""
                if res:
                    res = tidy_zh(res)
                    out[t] = res
                    self.cache[self._key(t)] = res
                    self._dirty += 1
                time.sleep(0.2)
        self.save()
        return out

    # ---------------- 后端分发 ----------------
    def _dispatch(self, text: str) -> str:
        if self.backend == "auto":
            for fn in (self._youdao, self._mymemory):
                try:
                    res = fn(text)
                    if res:
                        return res
                except Exception:
                    continue
            return ""
        if self.backend == "youdao":
            return self._youdao(text)
        if self.backend == "mymemory":
            return self._mymemory(text)
        if self.backend == "baidu":
            return self._baidu(text)
        raise RuntimeError(f"未知翻译后端: {self.backend}")

    def _youdao(self, text: str) -> str:
        parts = []
        for chunk in _split(text):
            r = requests.post(
                "https://fanyi.youdao.com/translate",
                params={"doctype": "json", "type": "AUTO"},
                data={"i": chunk},
                headers=UA,
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("errorCode") not in (0, "0", None):
                raise RuntimeError(f"youdao errorCode={data.get('errorCode')}")
            rows = data.get("translateResult") or []
            parts.append("".join(seg.get("tgt", "") for line in rows for seg in line))
            time.sleep(0.15)
        out = "".join(parts).strip()
        if not out:  # 有道偶发空结果（限流），交给下一个后端
            raise RuntimeError("youdao 返回空结果")
        return out

    def _mymemory(self, text: str) -> str:
        # 单次上限 500 字符，按句切块翻完再拼，避免摘要被硬截断
        chunks = _split(text, 450)[:4]
        parts: list[str] = []
        for chunk in chunks:
            params = {"q": chunk, "langpair": "en|zh-CN"}
            email = self.opts.get("mymemory_email")
            if email:
                params["de"] = email
            r = requests.get(
                "https://api.mymemory.translated.net/get", params=params, headers=UA, timeout=20
            )
            data = r.json()
            if data.get("responseStatus") not in (200, "200"):
                raise RuntimeError(f"mymemory: {data.get('responseDetails')}")
            parts.append(((data.get("responseData") or {}).get("translatedText", "") or "").strip())
            time.sleep(0.3)
        return "".join(p for p in parts if p).strip()

    def _baidu(self, text: str) -> str:
        import hashlib as _h

        opt = self.opts.get("baidu", {})
        appid, secret = opt.get("appid"), opt.get("secret")
        if not appid or not secret:
            raise RuntimeError("百度翻译缺少 appid/secret")
        salt = str(int(time.time() * 1000))
        sign = _h.md5((appid + text + salt + secret).encode()).hexdigest()
        r = requests.post(
            "https://fanyi-api.baidu.com/api/trans/vip/translate",
            data={"q": text, "from": "en", "to": "zh", "appid": appid, "salt": salt, "sign": sign},
            timeout=20,
        )
        data = r.json()
        if "trans_result" not in data:
            raise RuntimeError(f"baidu: {data.get('error_msg')}")
        return "".join(x["dst"] for x in data["trans_result"])

    # ---------------- LLM 批量 ----------------
    def _llm_batch(self, texts: list[str]) -> dict[str, str]:
        opt = self.opts.get(self.backend, {})
        key = (opt.get("api_key") or "").strip()
        if not key:
            raise RuntimeError(f"{self.backend} 未配置 api_key（写在 secrets.yaml）")

        base = opt.get("base_url", "").rstrip("/")
        model = opt.get("model", "")
        url = f"{base}/chat/completions" if "bigmodel" in base else f"{base}/chat/completions"
        out: dict[str, str] = {}
        batch_size = 12
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            payload = {
                "model": model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": LLM_PROMPT},
                    {
                        "role": "user",
                        "content": "把下面 JSON 数组里的每一条翻译成中文，严格按同样顺序返回 JSON 数组，只输出数组：\n"
                        + json.dumps(batch, ensure_ascii=False),
                    },
                ],
            }
            r = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=90,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
            try:
                arr = json.loads(content)
            except Exception:
                continue
            if isinstance(arr, list) and len(arr) == len(batch):
                for src, dst in zip(batch, arr):
                    if isinstance(dst, str) and dst:
                        out[src] = dst
                        self.cache[self._key(src)] = dst
                        self._dirty += 1
            time.sleep(0.3)
        self.save()
        return out


def apply_translations(items: list[dict], translator: Translator, cfg: dict) -> int:
    """给条目补 title_zh / abstract_zh，返回成功翻译的条数。"""
    t = cfg.get("translation", {})
    max_items = int(t.get("max_items", 200) or 200)
    abs_chars = int(t.get("abstract_max_chars", 700) or 0)
    mode = t.get("mode", "both")
    if mode not in ("title", "abstract", "both"):
        raise ValueError(f"未知翻译范围: {mode}")

    todo = items[:max_items]
    titles = (
        [i.get("title_en", "") for i in todo if i.get("title_en")]
        if mode in ("title", "both")
        else []
    )
    abstracts = []
    if abs_chars > 0 and mode in ("abstract", "both"):
        abstracts = [i.get("abstract_en", "")[:abs_chars] for i in todo if i.get("abstract_en")]

    tmap = translator.translate_many(titles + abstracts)
    if not tmap:
        translator.save()
        return 0

    done = 0
    for item in todo:
        tz = tmap.get(item.get("title_en", ""), "") if mode in ("title", "both") else ""
        az = ""
        if abs_chars > 0 and mode in ("abstract", "both") and item.get("abstract_en"):
            az = tmap.get(item["abstract_en"][:abs_chars], "")
        item["title_zh"] = tz
        item["abstract_zh"] = az
        if tz or az:
            done += 1
    translator.save()
    return done
