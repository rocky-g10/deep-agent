"""ANSI-colored event pretty-printer for the demo."""
from __future__ import annotations

import sys

# ANSI escape codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_WHITE = "\033[37m"

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Wrap *text* in an ANSI escape sequence (no-op when not a TTY)."""
    return f"{code}{text}{_RESET}" if _USE_COLOR else text


def print_header(text: str) -> None:
    """Print a section banner."""
    width = 60
    print()
    print(_c(_BOLD + _CYAN, "=" * width))
    print(_c(_BOLD + _CYAN, f"  {text}"))
    print(_c(_BOLD + _CYAN, "=" * width))


def print_divider() -> None:
    """Print a thin separator line."""
    print(_c(_DIM, "-" * 60))


def print_event(data: dict) -> None:  # noqa: C901
    """Pretty-print a single WebSocket event dict."""
    event_type = data.get("type", "unknown")

    if event_type == "session_started":
        session_id = data.get("session_id", "")
        print(_c(_CYAN, f"  SESSION {session_id}"))

    elif event_type == "skill_match":
        skill_id = data.get("skill_id", "")
        confidence = data.get("confidence", 0)
        print(_c(_YELLOW, f"  SKILL MATCH {skill_id} (confidence: {confidence:.2f})"))

    elif event_type == "tool_call":
        tool_name = data.get("tool", "")
        code = data.get("input", {}).get("code", "")
        preview = code.strip()[:200].replace("\n", " | ")
        if len(code.strip()) > 200:
            preview += " ..."
        print(_c(_BLUE, f"  TOOL CALL {tool_name}"))
        print(_c(_DIM, f"    {preview}"))

    elif event_type == "tool_result":
        output = data.get("output", "")
        print(_c(_GREEN, "  TOOL RESULT"))
        for line in output.strip().split("\n"):
            print(_c(_GREEN, f"    {line}"))

    elif event_type == "agent_chunk":
        content = data.get("content", "")
        print(_c(_DIM + _WHITE, f"  {content.rstrip()}"))

    elif event_type == "agent_complete":
        tokens = data.get("tokens_used", 0)
        print(_c(_BOLD + _GREEN, f"  COMPLETE (tokens_used={tokens})"))

    elif event_type == "error":
        code = data.get("code", "")
        message = data.get("message", "")
        print(_c(_RED, f"  ERROR {code}: {message}"))

    else:
        print(_c(_DIM, f"  {event_type}: {data}"))
