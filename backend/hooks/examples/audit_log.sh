#!/usr/bin/env bash
# Geny hook example — append every hook event to /var/log/geny-hooks.log
#
# Wire from ~/.geny/hooks.yaml:
#
#   enabled: true
#   entries:
#     pre_tool_use:
#       - command: ["bash", "/path/to/audit_log.sh"]
#         timeout_ms: 500
#
# The hook runner sends the event payload as JSON on stdin and waits
# for a JSON response on stdout. Returning {} (the empty default
# below) leaves the call unchanged.

cat > /tmp/geny-last-hook-payload.json
date >> /var/log/geny-hooks.log 2>/dev/null || true
cat /tmp/geny-last-hook-payload.json >> /var/log/geny-hooks.log 2>/dev/null || true
echo "" >> /var/log/geny-hooks.log 2>/dev/null || true
echo "{}"
