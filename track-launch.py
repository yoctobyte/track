#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
TRACKHUB_DIR = ROOT_DIR / "trackhub"

sys.path.insert(0, str(TRACKHUB_DIR))
from config import iter_launch_entries, load_config  # noqa: E402


def resolve_env(env_map: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, value in env_map.items():
        resolved[key] = value.replace("$ROOT_DIR", str(ROOT_DIR))
    return resolved


def main() -> int:
    config = load_config()
    launches = [entry for entry in iter_launch_entries(config) if entry.get("autostart", True)]

    child_processes: list[subprocess.Popen] = []

    def cleanup() -> None:
        for process in reversed(child_processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(child_processes):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def handle_signal(*_args):
        cleanup()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    for entry in launches:
        script_path = (ROOT_DIR / str(entry["script"])).resolve()
        if not script_path.exists() or not os.access(script_path, os.X_OK):
            print(f"Skipping non-executable start script for {entry['name']}: {entry['script']}")
            continue
        env = os.environ.copy()
        env.update(resolve_env(entry.get("env", {})))
        print(f"Starting subservice [{entry['name']}]: {entry['script']}")
        process = subprocess.Popen(
            [str(script_path)],
            cwd=str(ROOT_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child_processes.append(process)

    trackhub_run = (TRACKHUB_DIR / "run.sh").resolve()
    print("Starting TRACK hub...")
    hub_process = subprocess.Popen([str(trackhub_run)], cwd=str(TRACKHUB_DIR))
    child_processes.append(hub_process)
    try:
        return hub_process.wait()
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
