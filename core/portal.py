"""校园网门户（深信服 AC）自动认证。

原理：门户网页里的密码是 RC4 加密后 POST 到 /ac_portal/login.php。
参数：opr=pwdLogin & userName=账号 & pwd=RC4(密码, 时间戳) & auth_tag=时间戳

安全约定：
  - 只在「配置里显式打开 auto_login 且填了账号密码」时才尝试
  - 失败不重试（避免连续错密码锁号），只返回门户给的原因
  - 账号密码只从 secrets.yaml 读，不写日志
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlsplit

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def rc4_hex(text: str, key: str) -> str:
    """与门户 pcauth.js 里的 do_encrypt_rc4 等价（标准 RC4，输出小写 hex）。"""
    key_bytes = [ord(c) for c in key] or [0]
    sbox = list(range(256))
    j = 0
    for i in range(256):
        j = (j + sbox[i] + key_bytes[i % len(key_bytes)]) % 256
        sbox[i], sbox[j] = sbox[j], sbox[i]
    a = b = 0
    out = []
    for ch in text:
        a = (a + 1) % 256
        b = (b + sbox[a]) % 256
        sbox[a], sbox[b] = sbox[b], sbox[a]
        k = sbox[(sbox[a] + sbox[b]) % 256]
        out.append("%02x" % (ord(ch) ^ k))
    return "".join(out)


def _base_url(portal_url: str) -> str:
    parts = urlsplit(portal_url)
    return f"{parts.scheme}://{parts.netloc}"


def _parse_response(text: str) -> dict:
    """门户返回形如 dr1003({"success":true,...}) 或纯 JSON。"""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"success": False, "msg": text[:200]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"success": False, "msg": text[:200]}


def login(portal_url: str, username: str, password: str, timeout: int = 10) -> dict:
    """返回 {ok, msg}；不会抛异常。"""
    if not username or not password:
        return {"ok": False, "msg": "未填写账号或密码"}

    base = _base_url(portal_url)
    ts = str(int(time.time() * 1000))
    payload = {
        "opr": "pwdLogin",
        "userName": username,
        "pwd": rc4_hex(password, ts),
        "auth_tag": ts,
        "rememberPwd": "0",
    }
    try:
        r = requests.post(
            f"{base}/ac_portal/login.php",
            data=payload,
            headers={**UA, "Referer": portal_url, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
            allow_redirects=False,
        )
    except Exception as exc:
        return {"ok": False, "msg": f"连接门户失败：{exc}"}

    if r.status_code != 200:
        return {"ok": False, "msg": f"门户返回 HTTP {r.status_code}"}

    data = _parse_response(r.text)
    ok = bool(data.get("success")) or str(data.get("result", "")).lower() in ("success", "ok", "1")
    msg = str(data.get("msg") or data.get("message") or ("认证成功" if ok else "认证被拒绝"))
    return {"ok": ok, "msg": msg}


def publisher_reachable(timeout: float = 5.0) -> bool:
    """出版社站点能不能打开——这是判断“数据库权限是否生效”的唯一可靠信号。"""
    try:
        r = requests.get("https://pubs.acs.org", headers=UA, timeout=timeout, allow_redirects=False)
        return r.status_code < 500
    except Exception:
        return False


def auto_login(cfg: dict) -> list[dict]:
    """按配置依次尝试各门户；返回每次尝试的结果。"""
    pc = cfg.get("portal", {})
    if not pc.get("auto_login"):
        return []
    creds = cfg.get("portal_credentials", {}) or {}
    results = []
    for site in pc.get("sites", []) or []:
        name = site.get("name", "")
        portal_url = (site.get("url") or "").strip()
        if not portal_url:
            results.append({"site": name, "ok": False, "msg": "未填写门户登录网址"})
            continue
        c = creds.get(name) or {}
        user, pwd = (c.get("username") or ""), (c.get("password") or "")
        if not user or not pwd:
            results.append({"site": name, "ok": False, "msg": "未配置账号密码（secrets.yaml）"})
            continue
        res = login(portal_url, user, pwd)
        results.append({"site": name, **res})
        if res.get("ok"):
            time.sleep(1.0)
            if publisher_reachable():
                break
    return results


def save_credentials(name: str, username: str, password: str) -> None:
    """给 GUI 用：用当前 Windows 用户加密后保存门户凭据。"""
    from .config import SECRETS_PATH

    data: dict = {}
    if SECRETS_PATH.exists():
        import yaml

        data = yaml.safe_load(SECRETS_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("secrets.yaml 顶层必须是 YAML 字典")

    from .credentials import encrypt_password

    credentials = data.setdefault("portal_credentials", {})
    if not isinstance(credentials, dict):
        raise ValueError("secrets.yaml 中的 portal_credentials 必须是字典")
    credential = credentials.setdefault(name, {})
    if not isinstance(credential, dict):
        raise ValueError(f"secrets.yaml 中「{name}」的凭据格式无效")
    credential["username"] = username
    if password:
        credential.pop("password", None)
        credential["password_dpapi"] = encrypt_password(password)
    elif credential.get("password"):
        credential["password_dpapi"] = encrypt_password(credential.pop("password"))

    import yaml

    temporary = SECRETS_PATH.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(SECRETS_PATH)


def save_auto_login(enabled: bool) -> None:
    """Persist the GUI's auto-login choice without changing other secrets."""
    from .config import SECRETS_PATH

    import yaml

    data = {}
    if SECRETS_PATH.exists():
        data = yaml.safe_load(SECRETS_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("secrets.yaml 顶层必须是 YAML 字典")
    portal_settings = data.setdefault("portal", {})
    if not isinstance(portal_settings, dict):
        raise ValueError("secrets.yaml 中的 portal 必须是字典")
    portal_settings["auto_login"] = bool(enabled)
    temporary = SECRETS_PATH.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(SECRETS_PATH)


def save_translation_settings(
    enabled: bool,
    backend: str,
    abstract_max_chars: int,
    credentials: dict[str, dict[str, str]],
    mode: str = "both",
) -> None:
    """Persist translation choices and encrypt provider credentials for this Windows user."""
    from .config import SECRETS_PATH
    from .credentials import encrypt_password

    import yaml

    if backend not in ("auto", "youdao", "mymemory", "deepseek", "zhipu", "baidu"):
        raise ValueError("不支持的翻译后端")
    if mode not in ("title", "abstract", "both"):
        raise ValueError("翻译范围必须是 title、abstract 或 both")
    if abstract_max_chars < 0:
        raise ValueError("摘要翻译长度不能小于 0")

    data = {}
    if SECRETS_PATH.exists():
        data = yaml.safe_load(SECRETS_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("secrets.yaml 顶层必须是 YAML 字典")

    translation = data.setdefault("translation", {})
    if not isinstance(translation, dict):
        raise ValueError("secrets.yaml 中的 translation 必须是字典")
    translation["enabled"] = bool(enabled)
    translation["backend"] = backend
    translation["mode"] = mode
    translation["abstract_max_chars"] = abstract_max_chars

    for provider, fields in credentials.items():
        if provider not in ("deepseek", "zhipu", "baidu"):
            raise ValueError(f"不支持的翻译服务：{provider}")
        provider_settings = translation.setdefault(provider, {})
        if not isinstance(provider_settings, dict):
            raise ValueError(f"secrets.yaml 中的 translation.{provider} 必须是字典")
        for field, value in fields.items():
            if field not in ("api_key", "appid", "secret"):
                raise ValueError(f"不支持的凭据字段：{field}")
            if value:
                encrypted_field = field + "_dpapi"
                provider_settings.pop(field, None)
                provider_settings[encrypted_field] = encrypt_password(value)

    temporary = SECRETS_PATH.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(SECRETS_PATH)


def save_portal_settings(auto_login: bool, sites: list[dict[str, str]]) -> None:
    from .config import SECRETS_PATH

    import yaml

    data = {}
    if SECRETS_PATH.exists():
        data = yaml.safe_load(SECRETS_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("secrets.yaml 顶层必须是 YAML 字典")

    portal_settings = data.setdefault("portal", {})
    if not isinstance(portal_settings, dict):
        raise ValueError("secrets.yaml 中的 portal 必须是字典")
    portal_settings["auto_login"] = bool(auto_login)
    portal_settings["sites"] = [
        {"name": site["name"], "url": site["url"].strip()} for site in sites
    ]
    portal_settings["urls"] = [site["url"].strip() for site in sites if site["url"].strip()]

    temporary = SECRETS_PATH.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(SECRETS_PATH)


def save_email_settings(
    enabled: bool,
    smtp_host: str,
    smtp_port: int,
    use_ssl: bool,
    user: str,
    password: str,
    recipients: list[str],
) -> None:
    from .config import SECRETS_PATH
    from .credentials import encrypt_password

    import yaml

    if not 1 <= smtp_port <= 65535:
        raise ValueError("SMTP 端口范围应为 1–65535")
    data = {}
    if SECRETS_PATH.exists():
        data = yaml.safe_load(SECRETS_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("secrets.yaml 顶层必须是 YAML 字典")

    email_settings = data.setdefault("email", {})
    if not isinstance(email_settings, dict):
        raise ValueError("secrets.yaml 中的 email 必须是字典")
    email_settings.update(
        {
            "enabled": bool(enabled),
            "smtp_host": smtp_host.strip(),
            "smtp_port": smtp_port,
            "use_ssl": bool(use_ssl),
            "user": user.strip(),
            "to": [recipient.strip() for recipient in recipients if recipient.strip()],
        }
    )
    if password:
        email_settings.pop("password", None)
        email_settings["password_dpapi"] = encrypt_password(password)
    elif email_settings.get("password"):
        email_settings["password_dpapi"] = encrypt_password(email_settings.pop("password"))

    temporary = SECRETS_PATH.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(SECRETS_PATH)
