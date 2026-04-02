from __future__ import annotations

import hashlib
import json
import platform
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class CollectedObservation:
    observation_id: str
    observed_at: str
    network_id: str
    kind: str
    summary: str
    display_name: str
    confidence: float


def collect_once() -> CollectedObservation:
    observed_at = datetime.now(UTC).isoformat()
    hostname = socket.gethostname()
    fqdn = socket.getfqdn()
    primary_ip = _detect_primary_ip()
    mac_address = _format_mac(uuid.getnode())

    fingerprint = {
        "hostname": hostname,
        "fqdn": fqdn,
        "primary_ip": primary_ip,
        "mac_address": mac_address,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }

    network_id = _derive_network_id(primary_ip, mac_address)
    observation_id = str(uuid.uuid4())
    summary = json.dumps(fingerprint, sort_keys=True)
    display_name = primary_ip or hostname or network_id

    return CollectedObservation(
        observation_id=observation_id,
        observed_at=observed_at,
        network_id=network_id,
        kind="local_probe",
        summary=summary,
        display_name=display_name,
        confidence=0.20,
    )


def _detect_primary_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        ip = sock.getsockname()[0]
        return ip
    except OSError:
        return None
    finally:
        sock.close()


def _format_mac(node: int) -> str:
    hex_value = f"{node:012x}"
    return ":".join(hex_value[index : index + 2] for index in range(0, 12, 2))


def _derive_network_id(primary_ip: str | None, mac_address: str) -> str:
    network_hint = primary_ip or "unknown"
    material = f"{network_hint}|{mac_address}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return digest[:16]
