#!/usr/bin/env python3
"""Start the Deep Agent development server.

Usage:
    python scripts/run_dev.py

Requires:
    OPENAI_API_KEY environment variable (or .env file)
"""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    # Ensure project root is on path
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)

    # Check for API key
    if not os.environ.get("OPENAI_API_KEY"):
        env_file = project_root / ".env"
        if env_file.exists():
            print(f"Loading environment from {env_file}")
        else:
            print("WARNING: OPENAI_API_KEY not set and no .env file found.")
            print("The server will start but LLM calls will fail.")
            print("Set OPENAI_API_KEY or create a .env file.")
            print()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    print("Starting Deep Agent dev server...")
    print(f"  Health: http://{host}:{port}/health")
    print(f"  WebSocket: ws://{host}:{port}/ws/chat")
    print(f"  Skills root: {os.environ.get('SKILLS_ROOT', 'skills/')}")
    print()

    import uvicorn

    uvicorn.run(
        "deep_agent.api.app:create_app",
        host=host,
        port=port,
        reload=True,
        factory=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
