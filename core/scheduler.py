"""Windows Task Scheduler integration for the daily literature run."""
from __future__ import annotations

import os
import re
import subprocess
import sys

from .config import ROOT

TASK_NAME = "LitDaily"


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("每日定时任务仅支持 Windows")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    _require_windows()
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _message(result: subprocess.CompletedProcess) -> str:
    return (result.stdout or result.stderr or "").strip()


def create_daily_task(time_text: str) -> str:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_text):
        raise ValueError("时间格式应为 24 小时制 HH:MM，例如 08:00")

    if getattr(sys, "frozen", False):
        action = f'"{sys.executable}" --run-scheduled'
    else:
        runner = ROOT / "run_scheduled.py"
        action = f'"{sys.executable}" "{runner}"'
    result = _run(
        [
            "schtasks",
            "/Create",
            "/F",
            "/SC",
            "DAILY",
            "/ST",
            time_text,
            "/TN",
            TASK_NAME,
            "/TR",
            action,
            "/RL",
            "LIMITED",
        ]
    )
    if result.returncode:
        raise RuntimeError(_message(result) or f"创建计划任务失败，退出码 {result.returncode}")
    return _message(result) or f"每日任务已设置为 {time_text}"


def delete_daily_task() -> str:
    result = _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    if result.returncode:
        raise RuntimeError(_message(result) or f"删除计划任务失败，退出码 {result.returncode}")
    return _message(result) or "每日任务已取消"


def daily_task_exists() -> bool:
    result = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    if result.returncode == 0:
        return True
    output = _message(result).lower()
    if "cannot find" in output or "找不到" in output or "不存在" in output:
        return False
    raise RuntimeError(output or f"查询计划任务失败，退出码 {result.returncode}")
