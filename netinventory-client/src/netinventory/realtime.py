from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SYS_NET = Path("/sys/class/net")
PROC_NET_ROUTE = Path("/proc/net/route")
PROC_NET_ARP = Path("/proc/net/arp")
PROC_NET_DEV = Path("/proc/net/dev")


def gather_realtime() -> dict[str, Any]:
    interfaces = list_interfaces()
    primary_ip = detect_primary_ip()
    gateway, gateway_iface = detect_default_gateway()
    arp = read_arp_table()
    dns_servers, search_domains = read_resolv_conf()
    return {
        "now": datetime.now(UTC).isoformat(),
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "primary_ip": primary_ip,
        "default_gateway": gateway,
        "default_route_interface": gateway_iface,
        "interfaces": interfaces,
        "arp": {
            "count": len(arp),
            "entries": arp,
        },
        "dns_servers": dns_servers,
        "search_domains": search_domains,
        "privileged": os.geteuid() == 0,
        "sudo_available": _sudo_cached(),
        "wifi": gather_wifi(),
        "gps": gather_gps(),
    }


def list_interfaces() -> list[dict[str, Any]]:
    if not SYS_NET.exists():
        return []
    interfaces: list[dict[str, Any]] = []
    for entry in sorted(SYS_NET.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        name = entry.name
        info = {
            "name": name,
            "mac_address": _read_text(entry / "address"),
            "operstate": _read_text(entry / "operstate"),
            "carrier": _read_int(entry / "carrier"),
            "mtu": _read_int(entry / "mtu"),
            "is_wireless": (entry / "wireless").exists(),
            "is_loopback": name == "lo" or _read_int(entry / "type") == 772,
            "rx_bytes": _read_int(entry / "statistics" / "rx_bytes"),
            "tx_bytes": _read_int(entry / "statistics" / "tx_bytes"),
            "rx_packets": _read_int(entry / "statistics" / "rx_packets"),
            "tx_packets": _read_int(entry / "statistics" / "tx_packets"),
            "rx_errors": _read_int(entry / "statistics" / "rx_errors"),
            "tx_errors": _read_int(entry / "statistics" / "tx_errors"),
            "addresses": list_addresses(name),
        }
        interfaces.append(info)
    return interfaces


def list_addresses(iface: str) -> list[dict[str, str]]:
    out = _capture(["ip", "-json", "addr", "show", "dev", iface])
    if not out:
        return _list_addresses_fallback(iface)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return _list_addresses_fallback(iface)
    addrs: list[dict[str, str]] = []
    for entry in data:
        for info in entry.get("addr_info", []) or []:
            addrs.append(
                {
                    "family": info.get("family", ""),
                    "address": info.get("local", ""),
                    "prefixlen": str(info.get("prefixlen", "")),
                    "scope": info.get("scope", ""),
                }
            )
    return addrs


def _list_addresses_fallback(iface: str) -> list[dict[str, str]]:
    out = _capture(["ip", "addr", "show", "dev", iface])
    if not out:
        return []
    addrs: list[dict[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            parts = line.split()
            if len(parts) >= 2 and "/" in parts[1]:
                addr, prefix = parts[1].split("/", 1)
                addrs.append({"family": "inet", "address": addr, "prefixlen": prefix, "scope": ""})
        elif line.startswith("inet6 "):
            parts = line.split()
            if len(parts) >= 2 and "/" in parts[1]:
                addr, prefix = parts[1].split("/", 1)
                addrs.append({"family": "inet6", "address": addr, "prefixlen": prefix, "scope": ""})
    return addrs


def detect_primary_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def detect_default_gateway() -> tuple[str | None, str | None]:
    if not PROC_NET_ROUTE.exists():
        return (None, None)
    try:
        with PROC_NET_ROUTE.open("r", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                fields = line.split()
                if len(fields) < 3:
                    continue
                if fields[1] != "00000000":
                    continue
                gw = socket.inet_ntoa(bytes.fromhex(fields[2])[::-1])
                return (gw, fields[0])
    except OSError:
        return (None, None)
    return (None, None)


def read_arp_table() -> list[dict[str, str]]:
    entries = _read_arp_via_ip()
    if entries:
        return entries
    return _read_arp_via_proc()


def _read_arp_via_ip() -> list[dict[str, str]]:
    out = _capture(["ip", "-json", "neigh", "show"])
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    entries: list[dict[str, str]] = []
    for item in data:
        addr = item.get("dst", "")
        mac = item.get("lladdr", "")
        state = ",".join(item.get("state", []) if isinstance(item.get("state"), list) else [str(item.get("state", ""))])
        if not addr:
            continue
        entries.append(
            {
                "ip": addr,
                "mac": mac,
                "device": item.get("dev", ""),
                "state": state,
            }
        )
    return entries


def _read_arp_via_proc() -> list[dict[str, str]]:
    if not PROC_NET_ARP.exists():
        return []
    entries: list[dict[str, str]] = []
    try:
        with PROC_NET_ARP.open("r", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                fields = line.split()
                if len(fields) < 6:
                    continue
                ip, _hwtype, flags, mac, _mask, dev = fields[:6]
                if mac == "00:00:00:00:00:00":
                    continue
                entries.append({"ip": ip, "mac": mac, "device": dev, "state": flags})
    except OSError:
        return []
    return entries


def read_resolv_conf() -> tuple[list[str], list[str]]:
    servers: list[str] = []
    domains: list[str] = []
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        return (servers, domains)
    try:
        with resolv.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    servers.append(parts[1])
                elif len(parts) >= 2 and parts[0] in {"search", "domain"}:
                    domains.extend(parts[1:])
    except OSError:
        return ([], [])
    return (servers, domains)


def gather_wifi() -> dict[str, Any]:
    iw = shutil.which("iw")
    if not iw:
        return {"available": False, "reason": "iw not installed"}

    wireless: list[str] = []
    if SYS_NET.exists():
        for entry in SYS_NET.iterdir():
            if (entry / "wireless").exists():
                wireless.append(entry.name)
    if not wireless:
        return {"available": False, "reason": "no wireless interface"}

    info: dict[str, Any] = {"available": True, "interfaces": []}
    for iface in wireless:
        link = _capture([iw, "dev", iface, "link"])
        link_data = _parse_iw_link(link or "")
        scan_data: list[dict[str, Any]] = []
        scan_out = _capture_privileged([iw, "dev", iface, "scan"])
        if scan_out:
            scan_data = _parse_iw_scan(scan_out)
        info["interfaces"].append(
            {
                "name": iface,
                "link": link_data,
                "scan_count": len(scan_data),
                "scan": scan_data[:30],
                "scan_privileged": bool(scan_out),
            }
        )
    return info


def _parse_iw_link(text: str) -> dict[str, Any]:
    if not text or "Not connected" in text:
        return {"connected": False}
    data: dict[str, Any] = {"connected": True}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Connected to "):
            parts = line.split()
            if len(parts) >= 3:
                data["bssid"] = parts[2]
        elif line.startswith("SSID:"):
            data["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("freq:"):
            data["freq"] = line.split(":", 1)[1].strip()
        elif line.startswith("signal:"):
            data["signal"] = line.split(":", 1)[1].strip()
        elif line.startswith("tx bitrate:"):
            data["tx_bitrate"] = line.split(":", 1)[1].strip()
        elif line.startswith("rx bitrate:"):
            data["rx_bitrate"] = line.split(":", 1)[1].strip()
    return data


def _parse_iw_scan(text: str) -> list[dict[str, Any]]:
    networks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        if raw.startswith("BSS "):
            if current is not None:
                networks.append(current)
            match = re.match(r"BSS ([0-9a-f:]+)", raw, re.IGNORECASE)
            current = {"bssid": match.group(1) if match else raw[4:].split("(")[0].strip()}
            continue
        if current is None:
            continue
        line = raw.strip()
        if line.startswith("SSID:"):
            current["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("signal:"):
            current["signal"] = line.split(":", 1)[1].strip()
        elif line.startswith("freq:"):
            current["freq"] = line.split(":", 1)[1].strip()
        elif line.startswith("DS Parameter set:"):
            current["channel"] = line.split(":", 1)[1].strip()
    if current is not None:
        networks.append(current)
    networks.sort(key=lambda item: _signal_value(item.get("signal", "")))
    return networks


def _signal_value(text: str) -> float:
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return 0.0


def gather_gps() -> dict[str, Any]:
    host = os.environ.get("NETINV_GPSD_HOST", "127.0.0.1")
    port = int(os.environ.get("NETINV_GPSD_PORT", "2947"))
    try:
        sock = socket.create_connection((host, port), timeout=0.6)
    except OSError as exc:
        return {"available": False, "reason": f"gpsd not reachable: {exc.strerror or exc}"}

    try:
        sock.settimeout(0.8)
        sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
        buffer = b""
        deadline_chunks = 12
        while deadline_chunks > 0:
            try:
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            if b"TPV" in buffer:
                break
            deadline_chunks -= 1
    finally:
        try:
            sock.close()
        except OSError:
            pass

    fix: dict[str, Any] | None = None
    for line in buffer.splitlines():
        try:
            obj = json.loads(line.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            continue
        if obj.get("class") == "TPV":
            fix = obj
            break

    if fix is None:
        return {"available": True, "fix": False, "reason": "no fix yet"}

    return {
        "available": True,
        "fix": True,
        "lat": fix.get("lat"),
        "lon": fix.get("lon"),
        "alt": fix.get("alt"),
        "speed": fix.get("speed"),
        "track": fix.get("track"),
        "time": fix.get("time"),
        "mode": fix.get("mode"),
        "epx": fix.get("epx"),
        "epy": fix.get("epy"),
    }


def _capture(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _capture_privileged(cmd: list[str]) -> str | None:
    if os.geteuid() == 0:
        return _capture(cmd)
    if not _sudo_cached():
        return None
    sudo = shutil.which("sudo")
    if not sudo:
        return None
    return _capture([sudo, "-n", *cmd])


def _sudo_cached() -> bool:
    if os.geteuid() == 0:
        return True
    sudo = shutil.which("sudo")
    if not sudo:
        return False
    try:
        result = subprocess.run([sudo, "-n", "-v"], capture_output=True, timeout=2)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


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
