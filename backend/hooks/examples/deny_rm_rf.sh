#!/usr/bin/env bash
# Geny hook example — block any Bash invocation containing "rm -rf"
#
# Wire from ~/.geny/hooks.yaml:
#
#   enabled: true
#   entries:
#     pre_tool_use:
#       - command: ["bash", "/path/to/deny_rm_rf.sh"]
#         tool_filter: ["bash"]
#         timeout_ms: 200
#
# When the LLM tries to call `bash` with "rm -rf" in the input,
# this returns {"continue": false, "reason": "..."} and the runner
# blocks the tool call. Other bash calls return {} (empty) so they
# proceed unchanged.

payload="$(cat)"
if echo "$payload" | grep -qE 'rm[[:space:]]+-rf'; then
  cat <<'JSON'
{"continue": false, "reason": "Bash 'rm -rf' blocked by deny_rm_rf hook"}
JSON
else
  echo "{}"
fi
