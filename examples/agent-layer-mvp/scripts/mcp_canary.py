#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def probe() -> str:
    if not os.environ.get("AGENT_LAYER_CANARY"):
        raise RuntimeError("AGENT_LAYER_CANARY is unavailable")
    return "canary-ok"


def main() -> int:
    if sys.argv[1:] == ["--probe"]:
        try:
            print(probe())
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 1
        return 0

    from mcp.server.fastmcp import FastMCP

    server = FastMCP("agent-layer-canary")
    server.tool(name="probe")(probe)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
