#!/usr/bin/env python3
"""PreToolUse hook: block edits to secret and credential files.

Reads the tool call JSON on stdin. Exit 2 blocks the call and sends the
message on stderr back to Claude. Exit 0 allows it.
"""
import json
import os
import re
import sys

BLOCKED = [
    r"(^|/)\.env(\.(?!example$|sample$|template$)[^/]+)?$",
    r"\.pem$",
    r"\.key$",
    r"(^|/)id_(rsa|ed25519)(\.pub)?$",
    r"(^|/)credentials(\.json)?$",
    r"(^|/)\.aws/",
    r"(^|/)secrets?\.(json|ya?ml|toml)$",
]

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

path = (data.get("tool_input") or {}).get("file_path", "")
norm = os.path.normpath(path).replace("\\", "/") if path else ""

for pattern in BLOCKED:
    if norm and re.search(pattern, norm):
        print(
            f"Blocked: {path} looks like a secret or credential file. "
            "Ask the user to edit it themselves.",
            file=sys.stderr,
        )
        sys.exit(2)

sys.exit(0)
