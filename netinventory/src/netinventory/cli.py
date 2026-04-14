from __future__ import annotations

import argparse

from netinventory.commands import (
    handle_annotate,
    handle_collect_once,
    handle_context,
    handle_current,
    handle_export,
    handle_import,
    handle_networks,
    handle_recent,
    handle_serve,
    handle_status,
)
from netinventory.runtime import run_default_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netinv",
        description="CLI-first network inventory and topology mapping tool",
    )
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser("collect", help="Run collector only")
    collect_parser.add_argument(
        "--once",
        action="store_true",
        help="Run one collection cycle and exit",
    )

    serve_parser = subparsers.add_parser("serve", help="Run service/UI only")
    serve_parser.add_argument(
        "--bind",
        default="127.0.0.1:8080",
        help="Bind address for the local service",
    )

    subparsers.add_parser("status", help="Show collector/service status")
    subparsers.add_parser("current", help="Show current inferred network")
    subparsers.add_parser("recent", help="Show recent transitions")
    subparsers.add_parser("networks", help="List known network summaries")
    annotate_parser = subparsers.add_parser("annotate", help="Attach user context to a network, port, switch, or device")
    annotate_parser.add_argument("entity_kind", help="Entity kind such as network, location, device, port, or switch")
    annotate_parser.add_argument("entity_id", help="Entity identifier")
    annotate_parser.add_argument("field", help="Field name such as room, note, cabinet, or wall_port")
    annotate_parser.add_argument("value", help="Field value")
    context_parser = subparsers.add_parser("context", help="Show stored user context")
    context_parser.add_argument("--entity-kind", help="Optional entity kind filter")
    context_parser.add_argument("--entity-id", help="Optional entity ID filter")
    export_parser = subparsers.add_parser("export", help="Write an export bundle for import on another machine")
    export_parser.add_argument(
        "--output",
        help="Optional output path for the generated export bundle",
    )
    import_parser = subparsers.add_parser("import", help="Import a replication bundle from another machine")
    import_parser.add_argument("input_path", help="Path to an export bundle")
    subparsers.add_parser("sync", help="Sync with a central node")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        return run_default_mode()

    if args.command == "collect":
        if args.once:
            return handle_collect_once()
        print("collection: daemon mode not implemented yet")
        return 0

    if args.command == "serve":
        return handle_serve(args.bind)

    if args.command == "status":
        return handle_status()

    if args.command == "current":
        return handle_current()

    if args.command == "recent":
        return handle_recent()

    if args.command == "networks":
        return handle_networks()

    if args.command == "annotate":
        return handle_annotate(args.entity_kind, args.entity_id, args.field, args.value)

    if args.command == "context":
        return handle_context(args.entity_kind, args.entity_id)

    if args.command == "export":
        return handle_export(args.output)

    if args.command == "import":
        return handle_import(args.input_path)

    if args.command == "sync":
        print("sync: not implemented yet")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
