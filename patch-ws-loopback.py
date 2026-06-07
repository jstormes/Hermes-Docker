#!/usr/bin/env python3
"""Patch hermes' dashboard WS loopback gate for Docker Desktop bridge NAT.

Why this exists
---------------
The embedded Chat tab (enabled by ``dashboard --tui``) drives the agent over
WebSockets (``/api/pty``, ``/api/ws``, ``/api/pub``, ``/api/events``).  In
``--insecure`` mode ``_ws_client_is_allowed`` only accepts WS peers whose IP is
loopback (127.0.0.1 / ::1).  Under Docker Desktop's bridge networking the
published ``127.0.0.1:9119`` port is reached through NAT, so the container sees
the peer as the docker bridge gateway (e.g. 172.18.0.1) — never loopback.  Every
chat WebSocket is therefore rejected with 403/4403 and the chat tab is broken.

This patch makes ``_ws_client_is_allowed`` also accept any peer when the
dashboard was explicitly bound to all interfaces (0.0.0.0 / ::) with
``--insecure`` — exactly the stomres-docker setup.  The default loopback bind
(no ``--insecure``) keeps its original loopback-only behaviour.

The patch is idempotent (safe to re-run) and fails loudly if the upstream
anchor text changes, so a base-image bump can't silently no-op it.
"""
import sys

TARGET = "/opt/hermes/hermes_cli/web_server.py"

MARKER = "stomres-docker patch"

ANCHOR = (
    '    if getattr(app.state, "auth_required", False):\n'
    "        return True\n"
    '    client_host = ws.client.host if ws.client else ""\n'
    "    if not client_host:\n"
    "        return True\n"
    "    return client_host in _LOOPBACK_HOSTS\n"
)

REPLACEMENT = (
    '    if getattr(app.state, "auth_required", False):\n'
    "        return True\n"
    "    # stomres-docker patch (embedded chat over Docker Desktop bridge NAT):\n"
    "    # a published 0.0.0.0 bind is reached through Docker's NAT, so the WS\n"
    "    # peer is the docker bridge gateway (e.g. 172.18.0.1), never loopback.\n"
    "    # When the operator explicitly opted into an all-interfaces --insecure\n"
    "    # bind, accept any peer so the --tui chat WebSockets work behind NAT.\n"
    '    if getattr(app.state, "bound_host", None) in {"0.0.0.0", "::"}:\n'
    "        return True\n"
    '    client_host = ws.client.host if ws.client else ""\n'
    "    if not client_host:\n"
    "        return True\n"
    "    return client_host in _LOOPBACK_HOSTS\n"
)


def main() -> int:
    with open(TARGET, "r", encoding="utf-8") as fh:
        src = fh.read()

    if MARKER in src:
        print(f"[patch-ws-loopback] already applied to {TARGET}; skipping")
        return 0

    count = src.count(ANCHOR)
    if count != 1:
        sys.stderr.write(
            f"[patch-ws-loopback] ERROR: expected exactly 1 occurrence of the "
            f"_ws_client_is_allowed anchor in {TARGET}, found {count}. The base "
            f"image's web_server.py changed — update patch-ws-loopback.py.\n"
        )
        return 1

    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(src.replace(ANCHOR, REPLACEMENT, 1))

    print(f"[patch-ws-loopback] applied to {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
