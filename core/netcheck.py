"""运行前连通性预检：门户认证状态 + 出版社站点可达性。

设计原则：预检永远不能阻塞主流程。探测失败只影响“模式标记”，
API 通道（OpenAlex/Crossref）能通就照常出报告。
"""
from __future__ import annotations

import concurrent.futures as futures

import requests

PUBLISHER_HOSTS = {
    "ACS": "https://pubs.acs.org",
    "Wiley": "https://onlinelibrary.wiley.com",
    "Nature": "https://www.nature.com",
    "Science": "https://www.science.org",
    "Elsevier": "https://www.sciencedirect.com",
    "RSC": "https://pubs.rsc.org",
}

API_HOSTS = {
    "OpenAlex": "https://api.openalex.org/works?per-page=1",
    "Crossref": "https://api.crossref.org/works?rows=1",
}

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _probe(url: str, timeout: float = 6.0) -> bool:
    try:
        r = requests.get(url, timeout=timeout, headers=_UA, allow_redirects=False)
        return r.status_code < 500
    except Exception:
        return False


def _probe_many(urls: dict[str, str], timeout: float = 6.0) -> dict[str, bool]:
    if not urls:
        return {}
    with futures.ThreadPoolExecutor(max_workers=len(urls)) as pool:
        jobs = {name: pool.submit(_probe, url, timeout) for name, url in urls.items()}
        return {name: job.result() for name, job in jobs.items()}


def check(cfg: dict) -> dict:
    """返回 {api, publishers, portal_pages, login, mode, warning}"""
    pc = cfg.get("portal", {})
    api = _probe_many(API_HOSTS, timeout=8.0)
    pubs = _probe_many(PUBLISHER_HOSTS, timeout=5.0) if pc.get("check", True) else {}
    portals = []
    for url in pc.get("urls") or []:
        portals.append({"url": url, "reachable": _probe(url, timeout=4.0)})

    # 出版社打不开 & 允许自动登录 → 先认证再复测
    login_results: list[dict] = []
    if pubs and not any(pubs.values()) and pc.get("auto_login"):
        from . import portal

        login_results = portal.auto_login(cfg)
        if any(r.get("ok") for r in login_results):
            pubs = _probe_many(PUBLISHER_HOSTS, timeout=6.0)

    api_ok = any(api.values())
    pub_ok = any(pubs.values())

    if pub_ok:
        mode = "full"          # 出版社站点可达，可开直连通道
        warning = ""
    elif api_ok:
        mode = "api_only"      # 只能走元数据 API
        warning = (
            "出版社站点当前不可达（多半是校园网门户未认证）。本报告只用了 OpenAlex/Crossref "
            "元数据，可能有 0~2 天延迟。登录门户后重新运行即可抓取当日最新。"
        )
        failed = [r for r in login_results if not r.get("ok")]
        if failed:
            detail = "；".join(f"{r.get('site')}：{r.get('msg')}" for r in failed[:2])
            warning += f"（自动登录未成功：{detail}）"
    else:
        mode = "offline"
        warning = "网络不可用：OpenAlex 与 Crossref 均无法访问，请先登录校园网门户。"

    return {
        "api": api,
        "publishers": pubs,
        "portal_pages": portals,
        "login": login_results,
        "mode": mode,
        "warning": warning,
    }
