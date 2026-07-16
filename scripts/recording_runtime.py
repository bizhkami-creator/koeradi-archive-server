"""録音プロセスのタイムアウト計算と安全なプロセスグループ終了。"""
import os
import signal
import subprocess
import time
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_RECORDING_SETTINGS = {
    "timeout_margin_minutes": 10, "minimum_timeout_minutes": 15,
    "maximum_timeout_minutes": 240, "terminate_grace_seconds": 30,
    "http_io_timeout_seconds": 30,
}

def _bounded_int(value, default, minimum, maximum):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)

def load_recording_settings():
    try:
        data = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    raw = data.get("recording") or {}
    return {
        "timeout_margin_minutes": _bounded_int(raw.get("timeout_margin_minutes"), 10, 1, 120),
        "minimum_timeout_minutes": _bounded_int(raw.get("minimum_timeout_minutes"), 15, 1, 240),
        "maximum_timeout_minutes": _bounded_int(raw.get("maximum_timeout_minutes"), 240, 15, 1440),
        "terminate_grace_seconds": _bounded_int(raw.get("terminate_grace_seconds"), 30, 5, 120),
        "http_io_timeout_seconds": _bounded_int(raw.get("http_io_timeout_seconds"), 30, 5, 300),
    }

def calculate_timeout_seconds(duration_minutes, settings=None):
    override = os.environ.get("KOERADI_RECORDING_TIMEOUT_SECONDS")
    if override:
        return _bounded_int(override, 60, 1, 86400)
    settings = settings or load_recording_settings()
    duration = _bounded_int(duration_minutes, 0, 0, settings["maximum_timeout_minutes"])
    minutes = max(duration + settings["timeout_margin_minutes"], settings["minimum_timeout_minutes"])
    return min(minutes, settings["maximum_timeout_minutes"]) * 60

def run_process_group(command, timeout_seconds, grace_seconds=30, **kwargs):
    """独立セッションで実行し、timeout時は子孫をTERM→KILLする。"""
    started = time.monotonic()
    proc = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        return proc.returncode, stdout, stderr, False, False, time.monotonic() - started, proc.pid
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        kill_sent = False
        try:
            stdout, stderr = proc.communicate(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            kill_sent = True
            stdout, stderr = proc.communicate()
        return 124, stdout, stderr, True, kill_sent, time.monotonic() - started, proc.pid
