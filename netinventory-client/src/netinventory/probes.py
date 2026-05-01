from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROBE_IDS = (
    "dhcp",
    "exit_ip",
    "traceroute",
    "link_speed",
    "wifi",
    "speed_test",
)


PROBE_LABELS: dict[str, str] = {
    "dhcp": "DHCP lease",
    "exit_ip": "Public IP",
    "traceroute": "Traceroute (internal hops)",
    "link_speed": "Link speed / duplex",
    "wifi": "Wi-Fi scan",
    "speed_test": "Speed test (download)",
}


PROBE_TOOLS: dict[str, list[dict[str, Any]]] = {
    "dhcp": [
        {"name": "nmcli", "kind": "binary", "package": "network-manager",
         "purpose": "DHCP info via NetworkManager", "required_one_of": "dhcp_source"},
        {"name": "/run/systemd/netif/leases", "kind": "dir", "package": "systemd-networkd",
         "purpose": "DHCP info via systemd-networkd", "required_one_of": "dhcp_source"},
        {"name": "/var/lib/dhcp", "kind": "dir", "package": "isc-dhcp-client",
         "purpose": "DHCP info via dhclient leases", "required_one_of": "dhcp_source"},
    ],
    "exit_ip": [],
    "traceroute": [
        {"name": "traceroute", "kind": "binary", "package": "traceroute",
         "purpose": "preferred traceroute", "required_one_of": "traceroute_tool"},
        {"name": "tracepath", "kind": "binary", "package": "iputils-tracepath",
         "purpose": "fallback (no privileges needed)", "required_one_of": "traceroute_tool"},
    ],
    "link_speed": [
        {"name": "ethtool", "kind": "binary", "package": "ethtool",
         "purpose": "richer link info; sysfs fallback always works", "required": False},
    ],
    "wifi": [
        {"name": "iw", "kind": "binary", "package": "iw",
         "purpose": "Wi-Fi link state and scan (note: iw, not iwd)", "required": True},
    ],
    "speed_test": [],
}


PROBE_NOTES: dict[str, str] = {
    "wifi": "Scanning needs root or cached sudo. The launcher pre-caches sudo for you.",
    "dhcp": "Reads whichever source is available. Missing all three usually means a static IP.",
    "speed_test": "Downloads ~10 MB from speed.cloudflare.com. Skip on metered connections.",
    "exit_ip": "Hits ifconfig.me / api.ipify.org / icanhazip.com — first to respond wins.",
    "traceroute": "Stops at the first non-RFC1918 hop so we only map internal topology.",
    "link_speed": "Reads /sys/class/net/<iface>/speed. ethtool adds duplex / autoneg detail.",
}


def tool_is_available(tool: dict[str, Any]) -> bool:
    kind = tool.get("kind", "binary")
    name = tool.get("name", "")
    if kind == "binary":
        return shutil.which(name) is not None
    if kind == "file":
        return Path(name).is_file()
    if kind == "dir":
        return Path(name).is_dir()
    return False


def gather_probe_tooling(enabled_lookup) -> list[dict[str, Any]]:
    """Returns a list of probe descriptions with tool availability + enabled state.

    `enabled_lookup` is a callable taking probe_id and returning bool.
    """
    rows: list[dict[str, Any]] = []
    for probe_id in PROBE_IDS:
        tools = PROBE_TOOLS.get(probe_id, [])
        tool_status = []
        groups: dict[str, list[bool]] = {}
        any_required_missing = False
        for tool in tools:
            found = tool_is_available(tool)
            tool_status.append(
                {
                    "name": tool.get("name"),
                    "kind": tool.get("kind", "binary"),
                    "package": tool.get("package"),
                    "purpose": tool.get("purpose", ""),
                    "found": found,
                    "required": bool(tool.get("required")),
                    "required_one_of": tool.get("required_one_of"),
                }
            )
            if tool.get("required") and not found:
                any_required_missing = True
            group = tool.get("required_one_of")
            if group:
                groups.setdefault(group, []).append(found)
        for group_results in groups.values():
            if not any(group_results):
                any_required_missing = True

        rows.append(
            {
                "id": probe_id,
                "label": PROBE_LABELS.get(probe_id, probe_id),
                "note": PROBE_NOTES.get(probe_id, ""),
                "tools": tool_status,
                "satisfied": not any_required_missing,
                "enabled": bool(enabled_lookup(probe_id)),
            }
        )
    return rows


def run_probe(probe_id: str, **kwargs: Any) -> dict[str, Any]:
    fn = _DISPATCH.get(probe_id)
    if fn is None:
        return {"ok": False, "error": f"unknown probe: {probe_id}"}
    started = time.monotonic()
    try:
        data = fn(**kwargs)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "duration_ms": int((time.monotonic() - started) * 1000)}
    data.setdefault("ok", True)
    data["duration_ms"] = int((time.monotonic() - started) * 1000)
    return data


def probe_dhcp(iface: str | None = None) -> dict[str, Any]:
    iface = iface or _default_iface()
    if iface is None:
        return {"ok": False, "error": "no default interface"}

    sources: list[dict[str, Any]] = []

    nmcli_data = _dhcp_via_nmcli(iface)
    if nmcli_data:
        sources.append({"source": "nmcli", **nmcli_data})

    networkd_data = _dhcp_via_networkd(iface)
    if networkd_data:
        sources.append({"source": "networkd", **networkd_data})

    lease_data = _dhcp_via_dhclient_lease(iface)
    if lease_data:
        sources.append({"source": "dhclient", **lease_data})

    if not sources:
        return {"ok": False, "error": "no DHCP source found", "interface": iface}
    primary = sources[0]
    return {"interface": iface, "sources": sources, **primary}


def probe_exit_ip(timeout: float = 4.0) -> dict[str, Any]:
    endpoints = (
        "https://api.ipify.org/?format=text",
        "https://ifconfig.me/ip",
        "https://icanhazip.com/",
    )
    last_error = ""
    attempts: list[str] = []
    for url in endpoints:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "netinv/0.1"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(64).decode("utf-8", errors="ignore").strip()
            attempts.append(f"{url} -> {body!r}")
            if body and _looks_like_ip(body):
                return {"ip": body, "endpoint": url, "raw_output": "\n".join(attempts)}
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            last_error = f"{url}: {exc}"
            attempts.append(last_error)
            continue
    return {"ok": False, "error": last_error or "no endpoint reachable", "raw_output": "\n".join(attempts)}


def probe_traceroute(target: str = "1.1.1.1", max_hops: int = 12, stop_at_public: bool = True) -> dict[str, Any]:
    binary = shutil.which("traceroute")
    if binary is not None:
        cmd = [binary, "-n", "-q", "1", "-w", "1", "-m", str(max_hops), target]
        return _parse_traceroute_output(_run_with_timeout(cmd, max_hops * 1.5 + 4), target, stop_at_public, mode="traceroute")

    tracepath = shutil.which("tracepath")
    if tracepath is not None:
        cmd = [tracepath, "-n", "-m", str(max_hops), target]
        return _parse_traceroute_output(_run_with_timeout(cmd, max_hops * 1.5 + 4), target, stop_at_public, mode="tracepath")

    return {"ok": False, "error": "neither traceroute nor tracepath installed"}


def _run_with_timeout(cmd: list[str], timeout: float) -> tuple[str, str | None]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return ("", f"{cmd[0]} timeout after {exc.timeout}s")
    except FileNotFoundError as exc:
        return ("", f"{cmd[0]} missing: {exc}")
    return (result.stdout, None)


def _parse_traceroute_output(produced: tuple[str, str | None], target: str, stop_at_public: bool, mode: str) -> dict[str, Any]:
    output, err = produced
    if err:
        return {"ok": False, "error": err, "raw_output": output or ""}
    hops: list[dict[str, Any]] = []
    stopped_at_public = False
    seen_hop_numbers: set[int] = set()
    for line in output.splitlines():
        line = line.strip()
        match = re.match(r"(\d+)[:\s]?\s+(.+)", line)
        if not match:
            continue
        hop_no = int(match.group(1))
        rest = match.group(2).strip()
        if hop_no in seen_hop_numbers:
            continue
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", rest)
        rtt_match = re.search(r"(\d+(?:\.\d+)?)\s*ms", rest)
        ip_addr = ip_match.group(1) if ip_match else None
        if ip_addr is None and "no reply" not in rest.lower() and "*" not in rest:
            continue
        seen_hop_numbers.add(hop_no)
        is_private = ip_addr is not None and _is_private(ip_addr)
        hop = {
            "hop": hop_no,
            "ip": ip_addr,
            "rtt_ms": float(rtt_match.group(1)) if rtt_match else None,
            "private": bool(is_private),
            "raw": rest,
        }
        hops.append(hop)
        if stop_at_public and ip_addr and not is_private:
            stopped_at_public = True
            break
    return {
        "target": target,
        "tool": mode,
        "hops": hops,
        "stopped_at_public": stopped_at_public,
        "internal_hop_count": sum(1 for h in hops if h.get("private")),
        "raw_output": output,
    }


def probe_link_speed(iface: str | None = None) -> dict[str, Any]:
    iface = iface or _default_iface()
    if iface is None:
        return {"ok": False, "error": "no default interface"}

    base = Path("/sys/class/net") / iface
    if not base.exists():
        return {"ok": False, "error": f"interface {iface} not found"}

    speed_path = base / "speed"
    duplex_path = base / "duplex"
    operstate = _read_text(base / "operstate")
    carrier = _read_int(base / "carrier")

    speed: int | None = None
    duplex: str | None = None
    if speed_path.exists():
        try:
            speed = int(speed_path.read_text().strip())
        except (OSError, ValueError):
            speed = None
    if duplex_path.exists():
        duplex = _read_text(duplex_path)

    result: dict[str, Any] = {
        "interface": iface,
        "operstate": operstate,
        "carrier": carrier,
        "speed_mbit": speed if speed and speed > 0 else None,
        "duplex": duplex,
    }

    ethtool = shutil.which("ethtool")
    if ethtool is not None:
        ethtool_out = _capture([ethtool, iface])
        if ethtool_out:
            result["ethtool"] = _parse_ethtool(ethtool_out)
            result["raw_output"] = ethtool_out
    if "raw_output" not in result:
        sysfs_lines = [
            f"interface  : {iface}",
            f"operstate  : {operstate or '-'}",
            f"carrier    : {carrier if carrier is not None else '-'}",
            f"speed_mbit : {speed if speed and speed > 0 else '-'}",
            f"duplex     : {duplex or '-'}",
        ]
        result["raw_output"] = "\n".join(sysfs_lines)
    return result


def probe_wifi(iface: str | None = None) -> dict[str, Any]:
    from netinventory.realtime import gather_wifi
    data = gather_wifi()
    return data


def probe_speed_test(timeout: float = 8.0, bytes_to_fetch: int = 10_000_000) -> dict[str, Any]:
    url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_fetch}"
    request = urllib.request.Request(url, headers={"User-Agent": "netinv/0.1"})
    started = time.monotonic()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                received += len(chunk)
                if time.monotonic() - started > timeout:
                    break
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return {"ok": False, "error": f"download failed: {exc}"}

    elapsed = max(time.monotonic() - started, 0.001)
    bits = received * 8
    mbps = (bits / elapsed) / 1_000_000
    return {
        "endpoint": url,
        "bytes": received,
        "elapsed_s": round(elapsed, 3),
        "down_mbit": round(mbps, 2),
        "complete": received >= bytes_to_fetch,
    }


_DISPATCH: dict[str, Any] = {
    "dhcp": probe_dhcp,
    "exit_ip": probe_exit_ip,
    "traceroute": probe_traceroute,
    "link_speed": probe_link_speed,
    "wifi": probe_wifi,
    "speed_test": probe_speed_test,
}


def _default_iface() -> str | None:
    route = Path("/proc/net/route")
    if not route.exists():
        return None
    try:
        with route.open("r", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                fields = line.split()
                if len(fields) >= 2 and fields[1] == "00000000":
                    return fields[0]
    except OSError:
        return None
    return None


def _dhcp_via_nmcli(iface: str) -> dict[str, Any] | None:
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return None
    out = _capture([nmcli, "-t", "device", "show", iface])
    if not out:
        return None
    fields: dict[str, str] = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if value:
            fields[key.strip()] = value.strip()
    dhcp_data: dict[str, Any] = {}
    for key, value in fields.items():
        if key.startswith("DHCP4.OPTION["):
            if "=" in value:
                opt_name, _, opt_value = value.partition("=")
                dhcp_data[opt_name.strip()] = opt_value.strip()
    ip = fields.get("IP4.ADDRESS[1]", "").split("/")[0] or None
    gateway = fields.get("IP4.GATEWAY") or None
    dns = [v for k, v in fields.items() if k.startswith("IP4.DNS")]
    if not (ip or gateway or dns or dhcp_data):
        return None
    return {
        "ip": ip,
        "gateway": gateway,
        "dns": dns,
        "lease": dhcp_data,
        "connection": fields.get("GENERAL.CONNECTION"),
        "raw_output": out,
    }


def _dhcp_via_networkd(iface: str) -> dict[str, Any] | None:
    leases_dir = Path("/run/systemd/netif/leases")
    if not leases_dir.exists():
        return None
    candidates: list[Path] = []
    iface_link_dir = Path("/sys/class/net") / iface
    ifindex_path = iface_link_dir / "ifindex"
    target_idx: str | None = None
    if ifindex_path.exists():
        target_idx = _read_text(ifindex_path)
    if target_idx and (leases_dir / target_idx).exists():
        candidates.append(leases_dir / target_idx)
    if not candidates:
        candidates = sorted(leases_dir.iterdir())
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        data: dict[str, str] = {}
        for line in text.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                data[key.strip()] = value.strip()
        if not data:
            continue
        return {
            "ip": data.get("ADDRESS"),
            "gateway": data.get("ROUTER"),
            "dns": data.get("DNS", "").split() if data.get("DNS") else [],
            "lease": data,
            "raw_output": text,
        }
    return None


def _dhcp_via_dhclient_lease(iface: str) -> dict[str, Any] | None:
    candidates = [
        Path(f"/var/lib/dhcp/dhclient.{iface}.leases"),
        Path("/var/lib/dhcp/dhclient.leases"),
        Path(f"/var/lib/dhclient/dhclient.{iface}.leases"),
        Path("/var/lib/dhclient/dhclient.leases"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        leases = _parse_dhclient_leases(text)
        if not leases:
            continue
        latest = leases[-1]
        return {
            "ip": latest.get("fixed-address"),
            "gateway": latest.get("option routers"),
            "dns": (latest.get("option domain-name-servers", "") or "").split(","),
            "lease": latest,
            "raw_output": text,
        }
    return None


def _parse_dhclient_leases(text: str) -> list[dict[str, str]]:
    leases: list[dict[str, str]] = []
    current: dict[str, str] = {}
    in_lease = False
    for raw in text.splitlines():
        line = raw.strip().rstrip(";")
        if line.startswith("lease"):
            in_lease = True
            current = {}
            continue
        if line == "}":
            if in_lease and current:
                leases.append(current)
            in_lease = False
            current = {}
            continue
        if not in_lease or not line:
            continue
        if " " in line:
            key, _, value = line.partition(" ")
            if key == "option":
                opt_key, _, opt_value = value.partition(" ")
                current[f"option {opt_key}"] = opt_value.strip().rstrip('"').lstrip('"')
            else:
                current[key] = value.strip().rstrip('"').lstrip('"')
    return leases


def _capture(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _looks_like_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _is_private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _parse_ethtool(text: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Speed:"):
            info["speed"] = line.split(":", 1)[1].strip()
        elif line.startswith("Duplex:"):
            info["duplex"] = line.split(":", 1)[1].strip()
        elif line.startswith("Port:"):
            info["port"] = line.split(":", 1)[1].strip()
        elif line.startswith("Link detected:"):
            info["link_detected"] = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("Auto-negotiation:"):
            info["autoneg"] = line.split(":", 1)[1].strip().lower() == "on"
    return info


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
