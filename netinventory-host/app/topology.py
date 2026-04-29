from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


IPV4_CIDR_RE = re.compile(r"\b(?P<ip>(?:\d{1,3}\.){3}\d{1,3})/(?P<prefix>\d{1,2})\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def build_topology(registrations: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    hosts: dict[str, dict[str, Any]] = {}

    for entry in registrations:
        for observation in _observations_from_entry(entry):
            host = _normalize_host(observation)
            if not host["id"]:
                continue
            _merge_host(hosts, host)
            host_id = f"host:{host['id']}"
            _merge_node(
                nodes,
                host_id,
                {
                    "id": host_id,
                    "type": "host",
                    "label": host["hostname"] or host["id"],
                    "confidence": host["confidence"],
                    "last_seen": host["last_seen"],
                    "facts": {
                        "host_id": host["id"],
                        "hostname": host["hostname"],
                        "kinds": host["kinds"],
                        "client_ips": host["client_ips"],
                    },
                    "sources": host["sources"],
                },
            )

            for iface in host["interfaces"]:
                iface_id = f"interface:{host['id']}:{iface['name']}"
                _merge_node(
                    nodes,
                    iface_id,
                    {
                        "id": iface_id,
                        "type": "interface",
                        "label": f"{host['hostname'] or host['id']} / {iface['name']}",
                        "confidence": host["confidence"],
                        "last_seen": host["last_seen"],
                        "facts": iface,
                        "sources": host["sources"],
                    },
                )
                _merge_edge(
                    edges,
                    host_id,
                    iface_id,
                    "has_interface",
                    host["confidence"],
                    host["last_seen"],
                    host["sources"],
                )
                for address in iface.get("addresses", []):
                    subnet = _subnet_from_address(address)
                    if not subnet:
                        continue
                    subnet_id = f"subnet:{subnet}"
                    _merge_node(
                        nodes,
                        subnet_id,
                        {
                            "id": subnet_id,
                            "type": "subnet",
                            "label": subnet,
                            "confidence": min(host["confidence"], 0.82),
                            "last_seen": host["last_seen"],
                            "facts": {"cidr": subnet},
                            "sources": host["sources"],
                        },
                    )
                    _merge_edge(
                        edges,
                        iface_id,
                        subnet_id,
                        "attached_to_subnet",
                        min(host["confidence"], 0.82),
                        host["last_seen"],
                        host["sources"],
                    )

            gateway = host["network"].get("default_gateway")
            if gateway:
                gateway_id = f"gateway:{gateway}"
                _merge_node(
                    nodes,
                    gateway_id,
                    {
                        "id": gateway_id,
                        "type": "gateway",
                        "label": gateway,
                        "confidence": min(host["confidence"], 0.78),
                        "last_seen": host["last_seen"],
                        "facts": {"ip": gateway},
                        "sources": host["sources"],
                    },
                )
                _merge_edge(
                    edges,
                    host_id,
                    gateway_id,
                    "uses_gateway",
                    min(host["confidence"], 0.78),
                    host["last_seen"],
                    host["sources"],
                )

            for dns in host["network"].get("dns_servers", []):
                dns_id = f"dns:{dns}"
                _merge_node(
                    nodes,
                    dns_id,
                    {
                        "id": dns_id,
                        "type": "dns",
                        "label": dns,
                        "confidence": min(host["confidence"], 0.70),
                        "last_seen": host["last_seen"],
                        "facts": {"ip": dns},
                        "sources": host["sources"],
                    },
                )
                _merge_edge(
                    edges,
                    host_id,
                    dns_id,
                    "uses_dns",
                    min(host["confidence"], 0.70),
                    host["last_seen"],
                    host["sources"],
                )

            external_ip = host["network"].get("external_ip")
            if external_ip:
                ext_id = f"external-ip:{external_ip}"
                _merge_node(
                    nodes,
                    ext_id,
                    {
                        "id": ext_id,
                        "type": "external_ip",
                        "label": external_ip,
                        "confidence": min(host["confidence"], 0.62),
                        "last_seen": host["last_seen"],
                        "facts": {"ip": external_ip},
                        "sources": host["sources"],
                    },
                )
                _merge_edge(
                    edges,
                    host_id,
                    ext_id,
                    "seen_as_external_ip",
                    min(host["confidence"], 0.62),
                    host["last_seen"],
                    host["sources"],
                )

    host_rows = sorted(hosts.values(), key=lambda item: item.get("last_seen") or "", reverse=True)
    node_rows = sorted(nodes.values(), key=lambda item: (item["type"], item["label"]))
    edge_rows = sorted(edges.values(), key=lambda item: (item["relation"], item["source"], item["target"]))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "hosts": len(host_rows),
            "nodes": len(node_rows),
            "edges": len(edge_rows),
            "subnets": sum(1 for node in node_rows if node["type"] == "subnet"),
            "gateways": sum(1 for node in node_rows if node["type"] == "gateway"),
        },
        "hosts": host_rows,
        "nodes": node_rows,
        "edges": edge_rows,
    }


def write_topology(topology: dict[str, Any], topology_dir: Path) -> None:
    topology_dir.mkdir(parents=True, exist_ok=True)
    (topology_dir / "summary.json").write_text(
        json.dumps(topology, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (topology_dir / "nodes.json").write_text(
        json.dumps(topology.get("nodes", []), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (topology_dir / "edges.json").write_text(
        json.dumps(topology.get("edges", []), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _observations_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return []

    if payload.get("kind") == "sync-bundle" and isinstance(payload.get("payload"), dict):
        rows = []
        bundle = payload["payload"]
        for record in bundle.get("records", []):
            if not isinstance(record, dict) or record.get("record_type") != "observation":
                continue
            item = record.get("payload")
            if not isinstance(item, dict):
                continue
            facts = _loads_json_object(item.get("facts_json"))
            if not facts:
                continue
            rows.append(
                {
                    "entry": entry,
                    "payload": {
                        "kind": "netinventory-client-observation",
                        "host": {
                            "hostname": facts.get("hostname"),
                            "fqdn": facts.get("fqdn"),
                            "machine_id": item.get("device_id") or record.get("source_device_id"),
                        },
                        "network": {
                            "default_gateway": facts.get("default_gateway"),
                            "default_route_interface": facts.get("default_route_interface"),
                            "dns_servers": facts.get("dns_servers", []),
                            "primary_ip": facts.get("primary_ip"),
                            "interfaces": facts.get("interfaces", []),
                        },
                    },
                    "timestamp": item.get("observed_at") or record.get("observed_at") or entry.get("timestamp"),
                    "client_id": entry.get("client_id") or record.get("source_device_id"),
                }
            )
        return rows

    return [
        {
            "entry": entry,
            "payload": payload,
            "timestamp": entry.get("timestamp"),
            "client_id": entry.get("client_id"),
        }
    ]


def _normalize_host(observation: dict[str, Any]) -> dict[str, Any]:
    payload = observation["payload"]
    entry = observation["entry"]
    host_info = payload.get("host") if isinstance(payload.get("host"), dict) else {}
    network = payload.get("network") if isinstance(payload.get("network"), dict) else {}

    identity = (
        str(observation.get("client_id") or "").strip()
        or str(host_info.get("machine_id") or "").strip()
        or str(host_info.get("hostname") or "").strip()
        or str(entry.get("client", {}).get("remote_addr") or "").strip()
    )
    timestamp = str(observation.get("timestamp") or entry.get("timestamp") or "")
    kind = str(payload.get("kind") or entry.get("kind") or "unknown")
    confidence = _source_confidence(payload, entry)
    interfaces = _interfaces_from_network(network)
    default_gateway = _default_gateway(network)
    dns_servers = _string_list(network.get("nameservers")) or _string_list(network.get("dns_servers"))

    return {
        "id": _safe_identifier(identity),
        "raw_id": identity,
        "hostname": str(host_info.get("hostname") or "").strip(),
        "fqdn": str(host_info.get("fqdn") or "").strip(),
        "first_seen": timestamp,
        "last_seen": timestamp,
        "kinds": [kind],
        "confidence": confidence,
        "submission_count": 1,
        "client_ips": _string_list(entry.get("client", {}).get("remote_addr")),
        "interfaces": interfaces,
        "network": {
            "default_gateway": default_gateway,
            "default_route_interface": str(network.get("default_route_interface") or "").strip(),
            "dns_servers": dns_servers,
            "external_ip": _first_ipv4(str(network.get("external_ip") or "")),
        },
        "sources": [
            {
                "kind": kind,
                "timestamp": timestamp,
                "entry_id": _entry_id(entry),
            }
        ],
    }


def _merge_host(hosts: dict[str, dict[str, Any]], incoming: dict[str, Any]) -> None:
    current = hosts.get(incoming["id"])
    if current is None:
        hosts[incoming["id"]] = incoming
        return
    current["first_seen"] = min(filter(None, [current.get("first_seen"), incoming.get("first_seen")]), default="")
    if str(incoming.get("last_seen") or "") > str(current.get("last_seen") or ""):
        current["last_seen"] = incoming["last_seen"]
        current["hostname"] = incoming["hostname"] or current["hostname"]
        current["fqdn"] = incoming["fqdn"] or current["fqdn"]
        current["network"].update({k: v for k, v in incoming["network"].items() if v})
    current["kinds"] = sorted(set(current["kinds"]) | set(incoming["kinds"]))
    current["confidence"] = max(float(current["confidence"]), float(incoming["confidence"]))
    current["submission_count"] = int(current["submission_count"]) + 1
    current["client_ips"] = sorted(set(current["client_ips"]) | set(incoming["client_ips"]))
    current["interfaces"] = _merge_interfaces(current["interfaces"], incoming["interfaces"])
    current["sources"] = (current["sources"] + incoming["sources"])[-12:]


def _merge_node(nodes: dict[str, dict[str, Any]], node_id: str, incoming: dict[str, Any]) -> None:
    current = nodes.get(node_id)
    if current is None:
        nodes[node_id] = incoming
        return
    current["confidence"] = max(float(current.get("confidence", 0)), float(incoming.get("confidence", 0)))
    if str(incoming.get("last_seen") or "") > str(current.get("last_seen") or ""):
        current["last_seen"] = incoming.get("last_seen")
        current["facts"] = incoming.get("facts", current.get("facts", {}))
    current["sources"] = _merge_sources(current.get("sources", []), incoming.get("sources", []))


def _merge_edge(
    edges: dict[str, dict[str, Any]],
    source: str,
    target: str,
    relation: str,
    confidence: float,
    last_seen: str,
    sources: list[dict[str, Any]],
) -> None:
    edge_id = f"{source}|{relation}|{target}"
    current = edges.get(edge_id)
    if current is None:
        edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "relation": relation,
            "confidence": confidence,
            "last_seen": last_seen,
            "sources": sources[-12:],
        }
        return
    current["confidence"] = max(float(current["confidence"]), confidence)
    if str(last_seen or "") > str(current.get("last_seen") or ""):
        current["last_seen"] = last_seen
    current["sources"] = _merge_sources(current.get("sources", []), sources)


def _interfaces_from_network(network: dict[str, Any]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}

    for item in _string_list(network.get("interface_addresses")):
        parts = item.split()
        name = parts[0] if parts else "unknown"
        addresses = [match.group(0) for match in IPV4_CIDR_RE.finditer(item)]
        by_name[name] = {
            "name": name,
            "state": parts[1] if len(parts) > 1 else "",
            "addresses": addresses,
            "raw": item,
        }

    raw_interfaces = network.get("interfaces")
    if isinstance(raw_interfaces, list):
        for item in raw_interfaces:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "unknown").strip() or "unknown"
            current = by_name.setdefault(name, {"name": name, "state": "", "addresses": [], "raw": ""})
            current.update(
                {
                    "state": str(item.get("operstate") or current.get("state") or ""),
                    "mac_address": str(item.get("mac_address") or "").strip(),
                    "is_wireless": bool(item.get("is_wireless", False)),
                    "mtu": item.get("mtu"),
                }
            )

    primary_ip = _first_ipv4(str(network.get("primary_ip") or ""))
    default_iface = str(network.get("default_route_interface") or "").strip()
    if primary_ip:
        name = default_iface or "primary"
        current = by_name.setdefault(name, {"name": name, "state": "", "addresses": [], "raw": ""})
        if primary_ip not in current["addresses"]:
            current["addresses"].append(primary_ip)

    return sorted(by_name.values(), key=lambda item: item["name"])


def _merge_interfaces(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): dict(item) for item in current if item.get("name")}
    for item in incoming:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        row = by_name.setdefault(name, {"name": name, "addresses": []})
        row.update({key: value for key, value in item.items() if value not in {"", None, []}})
        row["addresses"] = sorted(set(_string_list(row.get("addresses")) + _string_list(item.get("addresses"))))
    return sorted(by_name.values(), key=lambda item: item["name"])


def _default_gateway(network: dict[str, Any]) -> str:
    for key in ["default_gateway", "default_route"]:
        value = str(network.get(key) or "")
        if not value:
            continue
        if key == "default_route":
            match = re.search(r"\bvia\s+((?:\d{1,3}\.){3}\d{1,3})\b", value)
            if match:
                return match.group(1)
        first = _first_ipv4(value)
        if first:
            return first
    for route in _string_list(network.get("routes")):
        if route.startswith("default ") or " default " in route:
            match = re.search(r"\bvia\s+((?:\d{1,3}\.){3}\d{1,3})\b", route)
            if match:
                return match.group(1)
    return ""


def _subnet_from_address(address: str) -> str:
    try:
        if "/" not in address:
            return ""
        return str(ipaddress.ip_interface(address).network)
    except ValueError:
        return ""


def _source_confidence(payload: dict[str, Any], entry: dict[str, Any]) -> float:
    kind = str(payload.get("kind") or entry.get("kind") or "")
    if "admin" in kind:
        return 0.90
    if kind == "netinventory-client-observation" or kind == "sync-bundle":
        return 0.84
    if "user" in kind or "script" in kind:
        return 0.70
    if "browser" in kind:
        return 0.35
    return 0.50


def _entry_id(entry: dict[str, Any]) -> str:
    material = json.dumps(entry, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _safe_identifier(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    if cleaned:
        return cleaned[:96]
    return ""


def _first_ipv4(value: str) -> str:
    match = IPV4_RE.search(value)
    if not match:
        return ""
    candidate = match.group(0)
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _loads_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _merge_sources(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = current + incoming
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("entry_id") or row)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged[-12:]
