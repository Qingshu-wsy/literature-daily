"""配置加载：config.yaml + secrets.yaml（后者不入库，放密钥）。"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
CONFIG_PATH = ROOT / "config.yaml"
SECRETS_PATH = ROOT / "secrets.yaml"

DEFAULTS = {
    "search": {
        "lookback_days": 14,
        "per_topic_limit": 400,
        "types": ["article", "review"],
        "include_preprints": False,
        "email": "",
    },
    "openalex": {"api_key": ""},
    "publishers": {},
    "allow_other_publishers": False,
    "topics": [],
    "scoring": {
        "title_hit": 3,
        "abstract_hit": 1,
        "anchor_bonus": 2,
        "title_anchor_bonus": 2,
        "min_topic_score": 4,
        "min_score": 5,
        "review_bonus": 1,
        "feedback_weight": 1.5,
        "max_feedback_bonus": 3,
        "require_title_hit": True,
        "strong_topic_score": 12,
    },
    "journal_tiers": [],
    "translation": {
        "enabled": True,
        "backend": "auto",
        "mode": "both",
        "abstract_max_chars": 700,
        "max_items": 200,
        "workers": 3,
        "mymemory_email": "",
        "deepseek": {"api_key": "", "model": "deepseek-chat", "base_url": "https://api.deepseek.com"},
        "zhipu": {"api_key": "", "model": "glm-4-flash", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
        "baidu": {"appid": "", "secret": ""},
    },
    "output": {
        "dir": "out",
        "html": True,
        "excel": True,
        "open_after_run": True,
        "top_n_detail": 80,
        "max_per_topic": 40,
    },
    "portal": {
        "check": True,
        "auto_login": False,
        "urls": [],
        "sites": [],
        "hint": "",
    },
    "portal_credentials": {},
    "email": {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": 465,
        "use_ssl": True,
        "user": "",
        "password": "",
        "to": [],
        "subject_prefix": "[文献日报]",
        "max_items": 40,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(config_path: Path | str | None = None) -> dict:
    cfg = _merge(DEFAULTS, _read_yaml(Path(config_path) if config_path else CONFIG_PATH))
    secrets = _read_yaml(SECRETS_PATH)
    if secrets:
        credentials = secrets.get("portal_credentials") or {}
        if not isinstance(credentials, dict):
            raise ValueError("secrets.yaml 的 portal_credentials 必须是字典")
        for credential in credentials.values():
            if not isinstance(credential, dict):
                raise ValueError("secrets.yaml 中的门户凭据必须是字典")
            if "password_dpapi" in credential:
                from .credentials import decrypt_password

                credential["password"] = decrypt_password(credential.pop("password_dpapi"))
        translation_secrets = secrets.get("translation") or {}
        if not isinstance(translation_secrets, dict):
            raise ValueError("secrets.yaml 的 translation 必须是字典")
        for backend in ("deepseek", "zhipu", "baidu"):
            backend_secrets = translation_secrets.get(backend) or {}
            if not isinstance(backend_secrets, dict):
                raise ValueError(f"secrets.yaml 中 translation.{backend} 必须是字典")
            for key, encrypted_key in (("api_key", "api_key_dpapi"), ("secret", "secret_dpapi")):
                if encrypted_key in backend_secrets:
                    from .credentials import decrypt_password

                    backend_secrets[key] = decrypt_password(backend_secrets.pop(encrypted_key))
        email_secrets = secrets.get("email") or {}
        if not isinstance(email_secrets, dict):
            raise ValueError("secrets.yaml 的 email 必须是字典")
        if "password_dpapi" in email_secrets:
            from .credentials import decrypt_password

            email_secrets["password"] = decrypt_password(email_secrets.pop("password_dpapi"))
        cfg = _merge(cfg, secrets)  # secrets 覆盖 config
    return cfg


def out_dir(cfg: dict) -> Path:
    p = Path(cfg["output"]["dir"])
    if not p.is_absolute():
        p = ROOT / p
    return p
