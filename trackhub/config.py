from __future__ import annotations

import json
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
            "name": "Testing / Home",
            "description": "Primary development environment and experimental workspace.",
            "badge": "private",
            "apps": [
                {
                    "id": "map3d",
                    "name": "Map3D",
                    "summary": "Capture spatial evidence, reconstruct spaces, and browse 3D results.",
                    "local_url": "http://127.0.0.1:5001/",
                    "public_path": "/map3d/",
                    "start_script": "./map3d/run.sh",
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
            ],
        },
        {
            "id": "museum",
            "name": "Museum",
            "description": "Operational museum environment. Placeholder until deployment targets are wired.",
            "badge": "planned",
            "apps": [
                {
                    "id": "map3d",
                    "name": "Map3D",
                    "summary": "Museum-side capture and reconstruction entrypoint.",
                    "local_url": "",
                    "public_path": "/map3d/",
                    "start_script": "",
                    "status": "planned",
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
                    "local_url": "",
                    "public_path": "/map3d/",
                    "start_script": "",
                    "status": "planned",
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
    return config
