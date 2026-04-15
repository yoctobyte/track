from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


DEFAULT_CONFIG: dict[str, object] = {
    "title": "TRACK",
    "subtitle": "Technical Resource And Control Knowledge Kit",
    "bind": "0.0.0.0",
    "port": 5000,
    "public_base_url": "https://track.praktijkpioniers.com",
    "routing_mode": "reverse-proxy",
    "environments": [
        {
            "id": "testing",
            "name": "Testing",
            "description": "Primary development environment and experimental workspace.",
            "badge": "private",
            "apps": [
                {
                    "id": "map3d",
                    "name": "Map3D",
                    "summary": "Capture spatial evidence, reconstruct spaces, and browse 3D results.",
                    "local_url": "http://127.0.0.1:5001/",
                    "public_path": "/map3d/",
                    "start_script": "./map3d/run-testing.sh",
                    "status": "active",
                },
                {
                    "id": "museumcontrol",
                    "name": "Museum Control",
                    "summary": "Operate kiosk devices, inspect status, and reach local web controls.",
                    "local_url": "http://127.0.0.1:4575/",
                    "public_path": "/museumcontrol/",
                    "start_script": "./museumcontrol/run.sh",
                    "status": "imported",
                },
                {
                    "id": "netinventory",
                    "name": "NetInventory",
                    "summary": "Observe network environments, annotate findings, and build infrastructure memory.",
                    "local_url": "http://127.0.0.1:8888/",
                    "public_path": "/netinventory/",
                    "start_script": "./netinventory/run-track.sh",
                    "status": "imported",
                },
                {
                    "id": "devicecontrol",
                    "name": "DeviceControl",
                    "summary": "Run approved Ansible maintenance actions against enrolled devices.",
                    "local_url": "http://127.0.0.1:5021/",
                    "public_path": "/devicecontrol/",
                    "start_script": "./devicecontrol/run-testing.sh",
                    "status": "active",
                },
            ],
        },
        {
            "id": "museum",
            "name": "Museum",
            "description": "Operational museum environment with isolated capture and reconstruction data.",
            "badge": "active",
            "apps": [
                {
                    "id": "map3d",
                    "name": "Map3D",
                    "summary": "Museum-side capture and reconstruction entrypoint.",
                    "local_url": "http://127.0.0.1:5011/",
                    "public_path": "/map3d/",
                    "start_script": "./map3d/run-museum.sh",
                    "status": "active",
                },
                {
                    "id": "museumcontrol",
                    "name": "Museum Control",
                    "summary": "Museum-side device operations and status dashboard.",
                    "local_url": "",
                    "public_path": "/museumcontrol/",
                    "start_script": "",
                    "status": "planned",
                },
                {
                    "id": "netinventory",
                    "name": "NetInventory",
                    "summary": "Museum-side network observation and annotation surface.",
                    "local_url": "",
                    "public_path": "/netinventory/",
                    "start_script": "",
                    "status": "planned",
                },
                {
                    "id": "devicecontrol",
                    "name": "DeviceControl",
                    "summary": "Museum-side Ansible operations for enrolled devices.",
                    "local_url": "http://127.0.0.1:5031/",
                    "public_path": "/devicecontrol/",
                    "start_script": "./devicecontrol/run-museum.sh",
                    "status": "active",
                },
            ],
        },
        {
            "id": "lab",
            "name": "Lab",
            "description": "Reserved environment for future isolated deployments and testing.",
            "badge": "planned",
            "apps": [
                {
                    "id": "map3d",
                    "name": "Map3D",
                    "summary": "Lab-side spatial capture and reconstruction.",
                    "local_url": "http://127.0.0.1:5012/",
                    "public_path": "/map3d/",
                    "start_script": "./map3d/run-lab.sh",
                    "status": "active",
                },
                {
                    "id": "museumcontrol",
                    "name": "Museum Control",
                    "summary": "Lab-side device control and proxy entrypoint.",
                    "local_url": "",
                    "public_path": "/museumcontrol/",
                    "start_script": "",
                    "status": "planned",
                },
                {
                    "id": "netinventory",
                    "name": "NetInventory",
                    "summary": "Lab-side network and infrastructure observation tools.",
                    "local_url": "",
                    "public_path": "/netinventory/",
                    "start_script": "",
                    "status": "planned",
                },
                {
                    "id": "devicecontrol",
                    "name": "DeviceControl",
                    "summary": "Lab-side Ansible operations for enrolled devices.",
                    "local_url": "http://127.0.0.1:5032/",
                    "public_path": "/devicecontrol/",
                    "start_script": "./devicecontrol/run-lab.sh",
                    "status": "active",
                },
            ],
        },
    ],
}


def deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, object]:
    config = deepcopy(DEFAULT_CONFIG)
    config_path = BASE_DIR / "config.json"
    if config_path.exists():
        with config_path.open() as handle:
            loaded = json.load(handle)
        config = deep_merge(config, loaded)
    apply_environment_passwords(config)
    return config


def load_passwords() -> dict[str, str]:
    passwords: dict[str, str] = {}
    passwords_path = BASE_DIR / "passwords.json"
    if passwords_path.exists():
        with passwords_path.open() as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            passwords.update({str(key): str(value) for key, value in loaded.items()})
    return passwords


def save_passwords(passwords: dict[str, str]) -> None:
    passwords_path = BASE_DIR / "passwords.json"
    with passwords_path.open("w") as handle:
        json.dump(passwords, handle, indent=2)
        handle.write("\n")


def save_config(config: dict[str, object]) -> None:
    config_path = BASE_DIR / "config.json"
    with config_path.open("w") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")


def apply_environment_passwords(config: dict[str, object]) -> None:
    passwords = load_passwords()

    for env in config.get("environments", []):
        env_id = str(env.get("id", "")).strip()
        env_var = f"TRACKHUB_PASSWORD_{env_id.upper()}"
        if env_id in passwords:
            env["password"] = passwords[env_id]
        elif os.environ.get(env_var):
            env["password"] = os.environ[env_var]
        else:
            env["password"] = ""
