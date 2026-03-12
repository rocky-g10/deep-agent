"""Mock MCP server returning sample market data for the risk example.

Run via: python -m examples.mock_mcp_server
Exposes a single tool: get_market_data(symbols: list[str]) -> dict
"""
from __future__ import annotations

import json
import sys

import numpy as np


def _generate_returns(symbols: list[str], days: int = 252, seed: int = 42) -> dict:
    """Generate synthetic daily returns for the given symbols."""
    rng = np.random.default_rng(seed)
    data = {}
    for sym in symbols:
        data[sym] = (rng.normal(0.0005, 0.02, days)).tolist()
    return data


def main() -> None:
    """Simple stdio JSON-RPC mock — reads requests from stdin, writes responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id", 1)

        if method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "get_market_data",
                            "description": "Get historical daily returns for a list of stock symbols.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "symbols": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "List of ticker symbols",
                                    }
                                },
                                "required": ["symbols"],
                            },
                        }
                    ]
                },
            }
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            if tool_name == "get_market_data":
                symbols = arguments.get("symbols", ["AAPL", "MSFT", "GOOG"])
                returns = _generate_returns(symbols)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(returns),
                            }
                        ]
                    },
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
        elif method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "market-data-mock", "version": "1.0.0"},
                },
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            }

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
