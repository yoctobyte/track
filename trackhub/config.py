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
                    "launch_script": "./map3d/run.sh",
                    "launch_env": {
                        "MAP3D_INSTANCE": "testing",
                        "MAP3D_PORT_HTTP": "5001",
                        "MAP3D_PORT_HTTPS": "5444",
                    },
                    "autostart": True,
                    "status": "active",
                },
                {
                    "id": "museumcontrol",
                    "name": "Museum Control",
                    "summary": "Operate kiosk devices, inspect status, and reach local web controls.",
                    "local_url": "http://127.0.0.1:4575/",
                    "public_path": "/museumcontrol/",
                    "launch_script": "./museumcontrol/run.sh",
                    "autostart": True,
                    "status": "imported",
                },
                {
                    "id": "netinventory",
                    "name": "NetInventory Host",
                    "summary": "Collect uploads, publish client downloads, and centralize network observation data.",
                    "local_url": "http://127.0.0.1:8888/",
                    "public_path": "/netinventory/",
                    "launch_script": "./netinventory-host/run.sh",
                    "public_proxy_paths": ["/api/simple-ingest"],
                    "launch_env": {
                        "NETINVENTORY_HOST_INSTANCE": "testing",
                        "NETINVENTORY_HOST_PORT": "8888",
                        "NETINVENTORY_HOST_DATA_DIR": "./netinventory-host/data/environments/testing",
                    },
                    "autostart": True,
                    "status": "imported",
                },
                {
                    "id": "netinventory-client",
                    "name": "NetInventory Client",
                    "summary": "Run the attended laptop-side network inspection tool locally during field work.",
                    "local_url": "http://127.0.0.1:8889/",
                    "public_path": "/netinventory-client/",
                    "launch_script": "./netinventory-client/run-track.sh",
                    "launch_env": {
                        "NETINVENTORY_UI_PORT": "8889",
                        "NETINV_PUBLIC_PATH": "/netinventory-client/",
                    },
                    "autostart": True,
                    "visible": True,
                    "local_shortcut": True,
                    "status": "imported",
                },
                {
                    "id": "devicecontrol",
                    "name": "DeviceControl",
                    "summary": "Run approved Ansible maintenance actions against enrolled devices.",
                    "local_url": "http://127.0.0.1:5021/",
                    "public_path": "/devicecontrol/",
                    "launch_script": "./devicecontrol/run.sh",
                    "launch_env": {
                        "DEVICECONTROL_INSTANCE": "testing",
                        "DEVICECONTROL_ENVIRONMENT": "testing",
                        "DEVICECONTROL_PORT": "5021",
                        "DEVICECONTROL_DATA_DIR": "./devicecontrol/data",
                    },
                    "autostart": True,
                    "status": "active",
                },
                {
                    "id": "tracksync",
                    "name": "TrackSync",
                    "summary": "Coordinate multi-host TRACK sync between stable, development, and backup servers.",
                    "local_url": "http://127.0.0.1:5099/",
                    "public_path": "/tracksync/",
                    "launch_script": "./tracksync/run.sh",
                    "launch_env": {
                        "TRACKSYNC_PORT": "5099",
                        "TRACKSYNC_DATA_DIR": "./tracksync/data",
                    },
                    "autostart": False,
                    "status": "experimental",
                },
                {
                    "id": "quicktrack",
                    "name": "QuickTrack",
                    "summary": "Capture timestamped photo observations with optional notes, sender ID, and explicit GPS attachment.",
                    "local_url": "http://127.0.0.1:5107/",
                    "public_path": "/quicktrack/",
                    "launch_script": "./quicktrack/run.sh",
                    "launch_env": {
                        "QUICKTRACK_PORT": "5107",
                        "QUICKTRACK_DATA_DIR": "./quicktrack/data/environments/testing",
                    },
                    "autostart": False,
                    "status": "experimental",
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
                    "launch_script": "./map3d/run.sh",
                    "launch_env": {
                        "MAP3D_INSTANCE": "museum",
                        "MAP3D_PORT_HTTP": "5011",
                        "MAP3D_PORT_HTTPS": "5454",
                        "MAP3D_DATA_DIR": "./map3d/data/environments/museum",
                    },
                    "autostart": False,
                    "status": "active",
                },
                {
                    "id": "museumcontrol",
                    "name": "Museum Control",
                    "summary": "Museum-side device operations and status dashboard.",
                    "local_url": "http://127.0.0.1:4575/",
                    "public_path": "/museumcontrol/",
                    "launch_script": "./museumcontrol/run.sh",
                    "autostart": True,
                    "status": "active",
                },
                {
                    "id": "netinventory",
                    "name": "NetInventory Host",
                    "summary": "Museum-side intake and publishing surface for network observation data.",
                    "local_url": "http://127.0.0.1:8891/",
                    "public_path": "/netinventory/",
                    "launch_script": "./netinventory-host/run.sh",
                    "public_proxy_paths": ["/api/simple-ingest"],
                    "launch_env": {
                        "NETINVENTORY_HOST_INSTANCE": "museum",
                        "NETINVENTORY_HOST_PORT": "8891",
                        "NETINVENTORY_HOST_DATA_DIR": "./netinventory-host/data/environments/museum",
                    },
                    "autostart": True,
                    "status": "active",
                },
                {
                    "id": "devicecontrol",
                    "name": "DeviceControl",
                    "summary": "Museum-side Ansible operations for enrolled devices.",
                    "local_url": "http://127.0.0.1:5031/",
                    "public_path": "/devicecontrol/",
                    "launch_script": "./devicecontrol/run.sh",
                    "launch_env": {
                        "DEVICECONTROL_INSTANCE": "museum",
                        "DEVICECONTROL_ENVIRONMENT": "museum",
                        "DEVICECONTROL_PORT": "5031",
                        "DEVICECONTROL_DATA_DIR": "./devicecontrol/data",
                    },
                    "autostart": True,
                    "status": "active",
                },
                {
                    "id": "quicktrack",
                    "name": "QuickTrack",
                    "summary": "Museum-side timestamped photo observations with optional field notes and GPS.",
                    "local_url": "http://127.0.0.1:5117/",
                    "public_path": "/quicktrack/",
                    "launch_script": "./quicktrack/run.sh",
                    "launch_env": {
                        "QUICKTRACK_PORT": "5117",
                        "QUICKTRACK_DATA_DIR": "./quicktrack/data/environments/museum",
                    },
                    "autostart": False,
                    "status": "experimental",
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
                    "launch_script": "./map3d/run.sh",
                    "launch_env": {
                        "MAP3D_INSTANCE": "lab",
                        "MAP3D_PORT_HTTP": "5012",
                        "MAP3D_PORT_HTTPS": "5455",
                        "MAP3D_DATA_DIR": "./map3d/data/environments/lab",
                    },
                    "autostart": True,
                    "status": "active",
                },
                {
                    "id": "museumcontrol",
                    "name": "Museum Control",
                    "summary": "Lab-side device control and proxy entrypoint.",
                    "local_url": "",
                    "public_path": "/museumcontrol/",
                    "status": "planned",
                },
                {
                    "id": "netinventory",
                    "name": "NetInventory Host",
                    "summary": "Lab-side intake and publishing surface for network observation data.",
                    "local_url": "http://127.0.0.1:8892/",
                    "public_path": "/netinventory/",
                    "launch_script": "./netinventory-host/run.sh",
                    "public_proxy_paths": ["/api/simple-ingest"],
                    "launch_env": {
                        "NETINVENTORY_HOST_INSTANCE": "lab",
                        "NETINVENTORY_HOST_PORT": "8892",
                        "NETINVENTORY_HOST_DATA_DIR": "./netinventory-host/data/environments/lab",
                    },
                    "autostart": False,
                    "status": "active",
                },
                {
                    "id": "devicecontrol",
                    "name": "DeviceControl",
                    "summary": "Lab-side Ansible operations for enrolled devices.",
                    "local_url": "http://127.0.0.1:5032/",
                    "public_path": "/devicecontrol/",
                    "launch_script": "./devicecontrol/run.sh",
                    "launch_env": {
                        "DEVICECONTROL_INSTANCE": "lab",
                        "DEVICECONTROL_ENVIRONMENT": "lab",
                        "DEVICECONTROL_PORT": "5032",
                        "DEVICECONTROL_DATA_DIR": "./devicecontrol/data",
                    },
                    "autostart": False,
                    "status": "active",
                },
                {
                    "id": "quicktrack",
                    "name": "QuickTrack",
                    "summary": "Lab-side timestamped photo observations with optional field notes and GPS.",
                    "local_url": "http://127.0.0.1:5127/",
                    "public_path": "/quicktrack/",
                    "launch_script": "./quicktrack/run.sh",
                    "launch_env": {
                        "QUICKTRACK_PORT": "5127",
                        "QUICKTRACK_DATA_DIR": "./quicktrack/data/environments/lab",
                    },
                    "autostart": False,
                    "status": "experimental",
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


def iter_launch_entries(config: dict[str, object]):
    for env in config.get("environments", []):
        env_id = str(env.get("id", "")).strip()
        for app in env.get("apps", []):
            launch_script = str(app.get("launch_script") or "").strip()
            if not launch_script:
                continue
            launch_env = app.get("launch_env")
            if not isinstance(launch_env, dict):
                launch_env = {}
            autostart = app.get("autostart")
            if autostart is None:
                autostart = True
            yield {
                "name": f"{env_id}:{str(app.get('id', '')).strip()}",
                "environment_id": env_id,
                "app_id": str(app.get("id", "")).strip(),
                "script": launch_script,
                "env": {str(key): str(value) for key, value in launch_env.items()},
                "autostart": bool(autostart),
            }
