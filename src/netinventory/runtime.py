from __future__ import annotations

from netinventory.commands import handle_serve, handle_status

def run_default_mode() -> int:
    """Bare `netinv` should eventually start collection and local service."""
    print("default mode: collection not implemented yet")
    print("starting local service on 127.0.0.1:8080")
    print("api access requires the shared secret from local state")
    print("current rewrite status:")
    handle_status()
    return handle_serve("127.0.0.1:8080")
