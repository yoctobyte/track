#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
TRACKHUB_DIR = ROOT_DIR / "trackhub"
sys.path.insert(0, str(TRACKHUB_DIR))

from config import iter_launch_entries, load_config  # noqa: E402


def command_list(json_mode: bool) -> int:
    config = load_config()
    environments = config.get("environments", [])
    launches = list(iter_launch_entries(config))
    if json_mode:
        print(json.dumps({"environments": environments, "launches": launches}, indent=2))
        return 0

    for env in environments:
        print(f"[{env['id']}] {env['name']}")
        for app in env.get("apps", []):
            print(
                f"  - {app.get('id')} | path={app.get('public_path','')} | "
                f"local={app.get('local_url','')} | autostart={app.get('autostart', True)}"
            )
        print()
    print("Launch plan:")
    for entry in launches:
        print(
            f"  - {entry['name']} -> {entry['script']} "
            f"(autostart={entry['autostart']}, env={entry['env']})"
        )
    return 0


def command_validate() -> int:
    config = load_config()
    failures = 0
    for entry in iter_launch_entries(config):
        script_path = ROOT_DIR / entry["script"]
        if not script_path.exists():
            print(f"missing launch script: {entry['name']} -> {entry['script']}")
            failures += 1
        elif not script_path.is_file():
            print(f"invalid launch target: {entry['name']} -> {entry['script']}")
            failures += 1
        app_id = entry["app_id"]
        env_id = entry["environment_id"]
        launch_env = entry.get("env", {})
        env_data_keys = {
            "map3d": "MAP3D_DATA_DIR",
            "netinventory": "NETINVENTORY_HOST_DATA_DIR",
            "quicktrack": "QUICKTRACK_DATA_DIR",
        }
        if app_id in env_data_keys:
            key = env_data_keys[app_id]
            value = str(launch_env.get(key, ""))
            if f"/environments/{env_id}" not in value and f"\\environments\\{env_id}" not in value:
                print(f"shared data path risk: {entry['name']} must set {key} under data/environments/{env_id}")
                failures += 1
        if app_id == "devicecontrol" and str(launch_env.get("DEVICECONTROL_ENVIRONMENT", "")) != env_id:
            print(f"shared data path risk: {entry['name']} must set DEVICECONTROL_ENVIRONMENT={env_id}")
            failures += 1
    if failures:
        print(f"Validation failed: {failures} launch target(s) invalid.")
        return 1
    print("TRACK config validation passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect central TRACK environment and launch config.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Show configured environments, apps, and launch entries.")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    subparsers.add_parser("validate", help="Validate configured launch script targets.")

    args = parser.parse_args()
    if args.command == "list":
        return command_list(args.json)
    if args.command == "validate":
        return command_validate()
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
