"""文献日报 · 主程序

用法：
    python run_daily.py                 # 最近 3 天，全部主题
    python run_daily.py --days 7        # 回溯 7 天
    python run_daily.py --topic COF     # 只看某个主题
    python run_daily.py --all           # 包含已推送过的（不自动过滤）
    python run_daily.py --top 100       # 最多输出 100 篇
    python run_daily.py --no-translate  # 关闭翻译
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import shutil
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import mailer, netcheck, report, scoring, sources  # noqa: E402
from core.config import ROOT, load_config, out_dir  # noqa: E402
from core.custom_topics import (  # noqa: E402
    CUSTOM_DIRECTION,
    apply_custom_topic,
    custom_topic_name,
    normalize_custom_selection,
)
from core.store import Store  # noqa: E402
from core.translate import Translator, apply_translations  # noqa: E402


def log(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(msg.encode(enc, "replace").decode(enc), flush=True)


def collect(matcher, cfg: dict, args, net: dict | None = None) -> tuple[dict[str, dict], dict]:
    """按主题检索 → 归一化 → 去重，返回 {doi或标题: item}

    主通道 OpenAlex；额度用完或不可用时自动切 Crossref（不收钱），
    所以不会因为「共享额度被刷爆」就交白卷。
    """
    sc = cfg["search"]
    client = sources.OpenAlexClient(
        api_key=cfg.get("openalex", {}).get("api_key", ""),
        email=sc.get("email", ""),
    )
    fallback = sources.CrossrefClient(email=sc.get("email", ""))
    start, end = sources.date_window(int(args.days or sc.get("lookback_days", 3)))
    types = list(sc.get("types") or [])
    limit = int(getattr(args, "fetch_limit", 0) or sc.get("per_topic_limit", 300))

    log(f"[1/6] 检索窗口 {start} ~ {end}（OpenAlex，额度不足时自动切 Crossref）")
    works: dict[str, dict] = {}
    per_topic_stats: dict[str, int] = {}
    fallback_topics: list[str] = []

    for topic in matcher.topics:
        if args.topic and args.topic.lower() not in topic.name.lower():
            continue
        query = topic.build_query()
        batch: list[dict] = []
        if not client.budget_exhausted:
            try:
                batch = [sources.work_to_item(w) for w in client.search_topic(query, start, end, types, limit=limit)]
            except Exception as exc:
                log(f"      ! {topic.name} OpenAlex 失败：{str(exc)[:120]}")
        if not batch:
            try:
                batch = fallback.search_terms(topic.backup_terms(), start, end, limit=min(limit, 2000))
                if batch:
                    fallback_topics.append(topic.name)
            except Exception as exc:
                log(f"      ! {topic.name} Crossref 也失败：{exc}")

        per_topic_stats[topic.name] = len(batch)
        src = "Crossref" if topic.name in fallback_topics else "OpenAlex"
        log(f"      {topic.name}: 抓到 {len(batch)} 条（{src}）")
        for item in batch:
            key = item["doi"] or (item["title_en"].lower()[:120])
            if key and key not in works:
                works[key] = item

        if sc.get("include_preprints") and not args.topic and not client.budget_exhausted:
            try:
                pre = client.search_topic(query, start, end, ["preprint"], limit=60)
                for w in pre:
                    item = sources.work_to_item(w)
                    key = item["doi"] or (item["title_en"].lower()[:120])
                    if key and key not in works:
                        item["is_preprint"] = True
                        item["publisher"] = "Preprint"
                        works[key] = item
            except Exception:
                pass

    log(f"      合计去重后 {len(works)} 条，OpenAlex 请求 {client.request_count} 次"
        + (f"（缓存命中 {client.cache_hits}）" if client.cache_hits else ""))
    if fallback_topics:
        log(f"      ! 以下方向走了 Crossref 备用通道：{'、'.join(fallback_topics)}")
        log("        原因通常是 OpenAlex 免费额度用完（每天 UTC 0 点重置，北京时间早上 8 点）。")
        log("        建议申请免费 key 填到 secrets.yaml 的 openalex.api_key，额度独立且更大。")
        if net is not None:
            note = (
                f"OpenAlex 免费额度已用完（北京时间每天 08:00 重置），本次部分方向改用 Crossref："
                f"{'、'.join(fallback_topics)}。摘要可能偏少，点标题看官网即可。"
            )
            net["warning"] = (net.get("warning") + " " if net.get("warning") else "") + note
    if works and len(works) < 5 and client.last_error:
        log(f"      ! 提示：{client.last_error}")
    return works, per_topic_stats


def screen(works: dict[str, dict], matcher, cfg: dict, stats: dict) -> list[dict]:
    log("[2/6] 主题匹配与打分")
    out: list[dict] = []
    for item in works.values():
        item["score"] = 0.0
        matcher.match(item)
        if not item["topics"]:
            continue
        fin = scoring.finalize(item, cfg, stats)
        if fin:
            out.append(fin)
    out.sort(key=lambda x: (-x["score"], x["published"]))
    log(f"      通过评分门槛 {len(out)} 条")
    return out


def dedupe_titles(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it.get("doi") or "").lower() or " ".join((it.get("title_en") or "").lower().split())[:90]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def enrich_abstracts(items: list[dict], cfg: dict, limit: int = 40) -> int:
    """OpenAlex 没摘要的，用 Crossref 补（ACS/Springer 多数有）。"""
    todo = [i for i in items if not i.get("abstract_en") and i.get("doi")][:limit]
    if not todo:
        return 0
    log(f"[3/6] Crossref 补摘要（{len(todo)} 条）")
    email = cfg["search"].get("email", "")
    done = 0
    with futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(sources.crossref_abstract, i["doi"], email): i for i in todo}
        for job in futures.as_completed(jobs):
            item = jobs[job]
            try:
                ab = job.result()
            except Exception:
                ab = ""
            if ab:
                item["abstract_en"] = ab
                done += 1
    log(f"      补齐 {done} 条")
    return done


def limit_per_topic(items: list[dict], topic_names: list[str], cap: int, top_n: int) -> list[dict]:
    """每个方向各留前 N 篇，再合并。

    热门方向（光催化 50+）不会把冷门方向（锂硫 5 篇）挤出日报，
    这是“按方向配额”，不是按总分一刀切。
    """
    if cap <= 0:
        return items[:top_n]
    ordered = sorted(items, key=lambda x: (-x["score"], x["published"]))
    chosen: dict[str, dict] = {}
    for name in topic_names:
        taken = 0
        for it in ordered:
            if taken >= cap:
                break
            if name not in (it.get("topics") or []):
                continue
            taken += 1
            chosen.setdefault(it.get("id") or it.get("doi") or it["title_en"][:80], it)
    merged = sorted(chosen.values(), key=lambda x: (-x["score"], x["published"]))
    return merged[:top_n]


def main() -> int:
    ap = argparse.ArgumentParser(description="每日文献筛选")
    ap.add_argument("--days", type=int, default=0, help="回溯天数（默认取配置）")
    ap.add_argument("--topic", default="", help="只跑某个主题（按名字模糊匹配）")
    ap.add_argument("--top", type=int, default=0, help="最多输出多少篇")
    ap.add_argument("--max-per-topic", type=int, default=0, help="每个主题的输出上限")
    ap.add_argument("--fetch-limit", type=int, default=0, help="每个主题最多向数据源请求的文献数")
    ap.add_argument("--all", action="store_true", help="包含已推送过的文献")
    ap.add_argument("--include-reported", action="store_true", help="包含已报告文献，但仍过滤黑名单")
    ap.add_argument("--no-translate", action="store_true", help="关闭翻译")
    ap.add_argument("--no-open", action="store_true", help="跑完不自动打开报告")
    ap.add_argument("--email", action="store_true", help="跑完发送邮件日报")
    ap.add_argument("--config", default="", help="指定配置文件")
    args = ap.parse_args()

    cfg = load_config(args.config or None)
    gui_settings_path = ROOT / "state" / "gui_settings.json"
    if gui_settings_path.exists():
        gui_settings = json.loads(gui_settings_path.read_text(encoding="utf-8"))
        if not isinstance(gui_settings, dict):
            raise ValueError("本机 GUI 设置格式无效")
        base_topic_names = {str(topic.get("name", "")) for topic in cfg.get("topics", [])}
        gui_settings = normalize_custom_selection(gui_settings, base_topic_names)
        cfg = apply_custom_topic(cfg, gui_settings)
        if args.topic == CUSTOM_DIRECTION:
            args.topic = custom_topic_name(gui_settings)
    odir = out_dir(cfg)
    today = date.today().isoformat()

    log("=" * 62)
    log(f" 文献日报  {datetime.now():%Y-%m-%d %H:%M}")
    log("=" * 62)

    # ---- 预检 ----
    net = {"mode": "", "warning": ""}
    if cfg.get("portal", {}).get("check", True):
        log("[0/6] 网络与门户预检")
        net = netcheck.check(cfg)
        api_ok = ", ".join(f"{k}={'通' if v else '断'}" for k, v in net["api"].items())
        log(f"      API：{api_ok}")
        if net["publishers"]:
            pubs = ", ".join(f"{k}={'通' if v else '断'}" for k, v in net["publishers"].items())
            log(f"      出版社：{pubs}")
        log(f"      模式：{net['mode']}")
        for r in net.get("login", []) or []:
            log(f"      自动登录 {r.get('site','')}: {'成功' if r.get('ok') else '失败'} · {r.get('msg','')}")
        if net["warning"]:
            log(f"      ! {net['warning']}")
        if net["mode"] == "offline":
            log("      网络不可用，本次无法采集。请登录校园网门户后重试。")
            return 2

    # ---- 状态 ----
    store = Store()
    fb = store.ingest_feedback()
    if fb["liked"] or fb["disliked"]:
        log(f"      已吸收反馈：收藏 {fb['liked']} 条 / 忽略 {fb['disliked']} 条")

    matcher = scoring.TopicMatcher(cfg["topics"], cfg["scoring"])
    topic_cfg = [
        topic
        for topic in cfg["topics"]
        if not args.topic or args.topic.lower() in topic["name"].lower()
    ]
    stats = store.stats()

    # ---- 采集 + 打分 ----
    works, per_topic = collect(matcher, cfg, args, net)
    if not works:
        log("      没有抓到任何文献（可能查询过窄或 OpenAlex 额度用尽）。")
        log("      建议：申请免费 key 填入 config.yaml 的 openalex.api_key。")

    items = screen(works, matcher, cfg, stats)
    if args.topic:
        items = report.filter_papers_to_topics(items, topic_cfg)

    # ---- 过滤已推送 / 黑名单 ----
    if not args.all:
        before = len(items)
        if not args.include_reported:
            items = [i for i in items if not store.is_reported(i.get("doi", ""))]
        items = [i for i in items if not store.is_blacklisted(i.get("doi", ""))]
        log(f"[4/6] 过滤已推送 {before - len(items)} 条，剩 {len(items)} 条")

    items = dedupe_titles(items)

    top_n = args.top or int(cfg["output"].get("top_n_detail", 80))
    cap = args.max_per_topic or int(cfg["output"].get("max_per_topic", 0) or 0)
    topic_names = [topic["name"] for topic in topic_cfg]
    items = limit_per_topic(items, topic_names, cap, top_n)
    log(f"      按方向配额后 {len(items)} 条（每方向上限 {cap if cap > 0 else '不限'}）")

    # ---- 补摘要 ----
    if items:
        enrich_abstracts(items, cfg)

    # ---- 翻译 ----
    translated = 0
    if items and not args.no_translate:
        tr = Translator(cfg)
        if tr.enabled:
            log(f"[5/6] 翻译标题与摘要（后端 {tr.backend}）")
            translated = apply_translations(items, tr, cfg)
            if tr.errors:
                log(f"      ! 翻译异常（已自动降级）：{tr.errors[0][:120]}")
            log(f"      成功翻译 {translated}/{len(items)} 条")
        else:
            log("[5/6] 翻译已关闭")
    else:
        log("[5/6] 跳过翻译")

    items.sort(key=lambda x: (-x["score"], x["published"]))

    # ---- 输出 ----
    log("[6/6] 生成报告")
    payload = report.build_payload(items, topic_cfg, today, net, translated)

    data_path = odir / "data" / f"{today}.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    html_path = None
    if cfg["output"].get("html", True):
        html_path = report.write_html(payload, odir / "daily" / f"{today}.html")
        latest = odir / "daily" / "latest.html"
        try:
            shutil.copyfile(html_path, latest)
        except Exception:
            pass

    excel_path = None
    if cfg["output"].get("excel", True) and items:
        excel_path = report.write_excel(items, odir / "data" / f"{today}.xlsx", topic_cfg)

    # ---- 记账 ----
    store.mark_reported([i["doi"] for i in items if i.get("doi")], today)
    store.remember(items)
    store.save()

    # ---- 邮件（可选） ----
    mail_result = None
    if items and (args.email or cfg.get("email", {}).get("enabled")):
        mail_result = mailer.send(payload, cfg)

    # ---- 汇总 ----
    log("-" * 62)
    log(f" 今日新增 {len(items)} 篇")
    for t in payload["topics"]:
        log(f"   {t['name']:<8} {t['count']:>3} 篇")
    if translated:
        log(f"   已翻译 {translated} 篇")
    log(f" 数据：{data_path}")
    if html_path:
        log(f" 日报：{html_path}")
    if excel_path:
        log(f" 表格：{excel_path}")
    if mail_result:
        log(f" 邮件：{mail_result['msg']}")
    log("-" * 62)

    if html_path and cfg["output"].get("open_after_run", True) and not args.no_open:
        try:
            os.startfile(str(html_path))  # noqa: S606
        except Exception:
            webbrowser.open(html_path.as_uri())

    return 0


if __name__ == "__main__":
    sys.exit(main())
