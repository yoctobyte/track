from __future__ import annotations

import hashlib
import json
import platform
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CollectedObservation:
    observation_id: str
    observed_at: str
    network_id: str
    kind: str
    facts: dict[str, object]
    material_fingerprint: str
    summary: str
    display_name: str
    confidence: float


def collect_once() -> CollectedObservation:
    observed_at = datetime.now(UTC).isoformat()
    hostname = socket.gethostname()
    fqdn = socket.getfqdn()
    primary_ip = _detect_primary_ip()
    mac_address = _format_mac(uuid.getnode())
    default_gateway = _detect_default_gateway()
    default_route_interface = _detect_default_route_interface()
    dns_servers = _read_dns_servers()
    search_domains = _read_dns_search_domains()
    interfaces = _read_interfaces()
    active_interfaces = [item["name"] for item in interfaces if item.get("operstate") == "up"]

    facts = {
        "hostname": hostname,
        "fqdn": fqdn,
        "primary_ip": primary_ip,
        "mac_address": mac_address,
        "default_gateway": default_gateway,
        "default_route_interface": default_route_interface,
        "dns_servers": dns_servers,
        "search_domains": search_domains,
        "active_interfaces": active_interfaces,
        "interfaces": interfaces,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }

    network_id = _derive_network_id(primary_ip, mac_address)
    observation_id = str(uuid.uuid4())
    material_fingerprint = _build_material_fingerprint(
        hostname=hostname,
        fqdn=fqdn,
        primary_ip=primary_ip,
        mac_address=mac_address,
        default_gateway=default_gateway,
        default_route_interface=default_route_interface,
        dns_servers=dns_servers,
        search_domains=search_domains,
        active_interfaces=active_interfaces,
    )
    summary = json.dumps(facts, sort_keys=True)
    display_name = primary_ip or hostname or network_id

    return CollectedObservation(
        observation_id=observation_id,
        observed_at=observed_at,
        network_id=network_id,
        kind="local_probe",
        facts=facts,
        material_fingerprint=material_fingerprint,
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


def _build_material_fingerprint(
    *,
    hostname: str,
    fqdn: str,
    primary_ip: str | None,
    mac_address: str,
    default_gateway: str | None,
    default_route_interface: str | None,
    dns_servers: list[str],
    search_domains: list[str],
    active_interfaces: list[str],
) -> str:
    material = {
        "hostname": hostname,
        "fqdn": fqdn,
        "primary_ip": primary_ip,
        "mac_address": mac_address,
        "default_gateway": default_gateway,
        "default_route_interface": default_route_interface,
        "dns_servers": dns_servers,
        "search_domains": search_domains,
        "active_interfaces": active_interfaces,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def _detect_default_gateway() -> str | None:
    route_file = Path("/proc/net/route")
    if not route_file.exists():
        return None

    try:
        with route_file.open("r", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                fields = line.split()
                if len(fields) < 3:
                    continue
                if fields[1] != "00000000":
                    continue
                return socket.inet_ntoa(bytes.fromhex(fields[2])[::-1])
    except OSError:
        return None
    return None


def _detect_default_route_interface() -> str | None:
    route_file = Path("/proc/net/route")
    if not route_file.exists():
        return None

    try:
        with route_file.open("r", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                fields = line.split()
                if len(fields) < 2:
                    continue
                if fields[1] == "00000000":
                    return fields[0]
    except OSError:
        return None
    return None


def _read_dns_servers() -> list[str]:
    values: list[str] = []
    resolv_file = Path("/etc/resolv.conf")
    if not resolv_file.exists():
        return values

    try:
        with resolv_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    values.append(parts[1])
    except OSError:
        return []
    return values


def _read_dns_search_domains() -> list[str]:
    values: list[str] = []
    resolv_file = Path("/etc/resolv.conf")
    if not resolv_file.exists():
        return values

    try:
        with resolv_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] in {"search", "domain"}:
                    values.extend(parts[1:])
    except OSError:
        return []
    return values


def _read_interfaces() -> list[dict[str, object]]:
    root = Path("/sys/class/net")
    if not root.exists():
        return []

    interfaces: list[dict[str, object]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_dir():
            continue
        interfaces.append(
            {
                "name": path.name,
                "mac_address": _read_text(path / "address"),
                "operstate": _read_text(path / "operstate"),
                "mtu": _read_int(path / "mtu"),
                "carrier": _read_int(path / "carrier"),
                "is_wireless": (path / "wireless").exists(),
            }
        )
    return interfaces


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _read_int(path: Path) -> int | None:
    value = _read_text(path)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
