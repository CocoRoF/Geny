#!/usr/bin/env python3
"""Geny hook example — redact API keys / tokens in tool result payloads.

Wire from ~/.geny/hooks.yaml:

    enabled: true
    entries:
      post_tool_use:
        - command: ["python3", "/path/to/redact_secrets.py"]
          timeout_ms: 1000

The hook reads the post-tool-use payload from stdin (JSON), looks for
API key / bearer / private-key patterns in the result, and returns a
modified payload that strips them. Returning ``{}`` leaves the
payload untouched.
"""

import json
import re
import sys

PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
     r"\1=<redacted>"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "<redacted-anthropic-key>"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "<redacted-github-token>"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}"),
     "Bearer <redacted>"),
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----",
                re.DOTALL),
     "<redacted-private-key>"),
]


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        print("{}")
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("{}")
        return

    result = payload.get("result", "")
    if not isinstance(result, str):
        print("{}")
        return

    redacted = result
    changed = False
    for pattern, replacement in PATTERNS:
        new = pattern.sub(replacement, redacted)
        if new != redacted:
            changed = True
            redacted = new

    if not changed:
        print("{}")
        return

    print(json.dumps({
        "modified_payload": {**payload, "result": redacted},
        "reason": "redact_secrets: stripped sensitive token(s)",
    }))


if __name__ == "__main__":
    main()
