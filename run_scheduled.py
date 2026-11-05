"""Task Scheduler entry point with a persistent daily log."""
from __future__ import annotations

import contextlib
import json
import sys
import traceback
from datetime import datetime

from core.config import ROOT, load_config
from core.custom_topics import (
    CUSTOM_DIRECTION,
    custom_topic_name,
    normalize_custom_selection,
)

sys.path.insert(0, str(ROOT))


def build_arguments(settings: dict) -> list[str]:
    existing_topics = {
        str(topic.get("name", "")) for topic in load_config().get("topics", [])
    }
    settings = normalize_custom_selection(settings, existing_topics)
    windows = {
        "3天": 3,
        "7天": 7,
        "15天": 15,
        "半个月": 15,
        "1个月": 30,
        "3个月": 90,
        "半年": 180,
    }
    days = windows.get(settings.get("search_window", "3天"), 3)
    args = [
        str(ROOT / "run_daily.py"),
        "--no-open",
        "--days",
        str(days),
        "--top",
        "2000",
        "--max-per-topic",
        "2000",
        "--fetch-limit",
        str(min(2000, max(400, days * 12))),
    ]
    topic = settings.get("search_topic", "全部主题")
    if topic == CUSTOM_DIRECTION:
        topic = custom_topic_name(settings)
        if not topic:
            raise ValueError("自定义方向至少需要填写一个关键词")
    if topic and topic != "全部主题":
        args.extend(["--topic", topic])
    return args


def main() -> int:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "run.log"
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        log.write(f"\n{'=' * 20} {datetime.now():%Y-%m-%d %H:%M:%S} {'=' * 20}\n")
        try:
            import run_daily

            settings_path = ROOT / "state" / "gui_settings.json"
            settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
            sys.argv = build_arguments(settings)
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                return run_daily.main()
        except Exception:
            traceback.print_exc(file=log)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
