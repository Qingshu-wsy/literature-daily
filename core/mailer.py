"""邮件推送：把当天日报发到邮箱（QQ / 163 / Gmail 均可）。

只依赖标准库 smtplib。默认关闭，开启方式二选一：
  1) config.yaml 里 email.enabled: true
  2) 运行时加 --email

QQ / 163 的 password 填「SMTP 授权码」，不是登录密码：
  QQ邮箱 → 设置 → 账户 → 开启 SMTP 服务 → 生成授权码
"""
from __future__ import annotations

import html
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

TOPIC_ORDER_FALLBACK = "#8A939D"


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _topic_color(payload: dict, name: str) -> str:
    for t in payload.get("topics") or []:
        if t.get("name") == name:
            return t.get("color") or TOPIC_ORDER_FALLBACK
    return TOPIC_ORDER_FALLBACK


def build_subject(payload: dict, prefix: str) -> str:
    counts = " / ".join(f"{t['name']} {t['count']}" for t in payload.get("topics") or [] if t.get("count"))
    head = f"{prefix} {payload['date']} · 新增 {len(payload.get('papers') or [])} 篇"
    return f"{head} · {counts}" if counts else head


def build_html(payload: dict, max_items: int = 40) -> str:
    """按主题分块，每块最多 max_items 条；只用内联样式（邮件客户端不认 <style>）。"""
    papers = payload.get("papers") or []
    by_topic: dict[str, list[dict]] = {}
    for p in papers:
        for t in p.get("topics") or []:
            by_topic.setdefault(t, []).append(p)

    parts = [
        f'<div style="font:14px/1.6 -apple-system,Segoe UI,Microsoft YaHei,sans-serif;color:#1b1f23">',
        f'<h2 style="margin:0 0 4px;font-size:18px">文献日报 · {_esc(payload["date"])}</h2>',
        '<p style="margin:0 0 16px;color:#6b7480;font-size:12.5px">'
        f'共 {len(papers)} 篇 · 生成于 {_esc(payload.get("generated", ""))}'
        '</p>',
    ]
    for topic in payload.get("topics") or []:
        name = topic.get("name")
        rows = sorted(by_topic.get(name) or [], key=lambda x: -x.get("score", 0))[:max_items]
        if not rows:
            continue
        color = topic.get("color") or TOPIC_ORDER_FALLBACK
        parts.append(
            f'<h3 style="margin:18px 0 8px;font-size:15px;border-left:4px solid {color};'
            f'padding-left:8px">{_esc(name)} <span style="color:#8a939d;font-weight:400">'
            f'({topic.get("count", len(rows))})</span></h3>'
        )
        for p in rows:
            url = p.get("url_publisher") or p.get("url_doi") or ("https://doi.org/" + p.get("doi", ""))
            title_zh = p.get("title_zh") or p.get("title_en") or ""
            title_en = p.get("title_en") or ""
            meta = " · ".join(
                x for x in [p.get("journal"), p.get("published"), f"相关度 {p.get('score', '')}"] if x
            )
            parts.append(
                '<div style="margin:0 0 10px;padding:8px 10px;border:1px solid #e6e8eb;border-radius:8px">'
                f'<a href="{_esc(url)}" style="color:#1f6fb2;text-decoration:none;font-weight:600">'
                f'{_esc(title_zh)}</a>'
                + (
                    f'<div style="color:#8b939d;font-size:12px;margin-top:2px">{_esc(title_en)}</div>'
                    if p.get("title_zh")
                    else ""
                )
                + f'<div style="color:#6b7480;font-size:11.5px;margin-top:4px">{_esc(meta)}</div>'
                '</div>'
            )

    parts.append(
        '<p style="margin:18px 0 0;color:#9aa2ab;font-size:11.5px">'
        "点标题直达出版社页面（需已登录校园网门户）。完整报告见本机 out/daily/latest.html。"
        "</p></div>"
    )
    return "".join(parts)


def send(payload: dict, cfg: dict) -> dict:
    """返回 {ok, msg}；不发邮件时 ok=False。"""
    ec = cfg.get("email", {}) or {}
    host = (ec.get("smtp_host") or "").strip()
    port = int(ec.get("smtp_port") or 465)
    user = (ec.get("user") or "").strip()
    password = ec.get("password") or ""
    to = [x for x in (ec.get("to") or []) if x and "@" in x]

    missing = [
        label
        for label, value in (("smtp_host", host), ("user", user), ("password", password))
        if not value
    ]
    if missing or not to:
        return {"ok": False, "msg": "邮件配置不完整（缺 " + ", ".join(missing + ([] if to else ["to"])) + "）"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(build_subject(payload, ec.get("subject_prefix", "[文献日报]")), "utf-8")
    msg["From"] = formataddr(("文献日报", user))
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)

    text = "\n".join(
        f"[{p.get('score')}] {p.get('title_zh') or p.get('title_en')}\n    {p.get('url_publisher')}"
        for p in (payload.get("papers") or [])
    )
    msg.attach(MIMEText(text or "今日无新增", "plain", "utf-8"))
    msg.attach(MIMEText(build_html(payload, int(ec.get("max_items", 40) or 40)), "html", "utf-8"))

    try:
        if ec.get("use_ssl", True):
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls()
        with server:
            server.login(user, password)
            server.sendmail(user, to, msg.as_string())
        return {"ok": True, "msg": f"已发送到 {', '.join(to)}"}
    except Exception as exc:
        return {"ok": False, "msg": f"发送失败：{exc}"}
