# Error codes

Geny consumes the stable error code taxonomy emitted by geny-executor 2.1.0 and renders human-friendly messages in the UI. This page documents the full code list as Geny sees it, the i18n lookup convention, and how errors propagate from the pipeline to the audience-visible log card.

For the executor-side definition and stability guarantees, see [geny-executor / docs/error_codes.md](https://github.com/CocoRoF/geny-executor/blob/main/docs/error_codes.md).

## Code shape

```
exec.<component>.<reason>
```

- All lower-case, dot-separated
- `component` ∈ `api`, `cli`, `pipeline`, `stage`, `tool`, `mutation`, `mcp`, `unknown`
- Stable across executor patch versions; documented if renamed in a minor bump

Examples:

- `exec.api.auth_invalid_key`
- `exec.cli.auth_failed`
- `exec.tool.invalid_input`
- `exec.mcp.initialize_failed`

## Code list (current as of executor 2.1.0)

### `exec.api.*` — vendor API surface

| Code                            | Meaning                                              |
| ------------------------------- | ---------------------------------------------------- |
| `exec.api.auth_invalid_key`     | API key missing or invalid                           |
| `exec.api.auth_expired`         | Credential expired                                   |
| `exec.api.rate_limited`         | Upstream 429                                         |
| `exec.api.timeout`              | Request timed out                                    |
| `exec.api.network`              | Network error                                        |
| `exec.api.token_limit`          | Prompt exceeded context window                       |
| `exec.api.bad_request`          | Vendor rejected request shape (likely a bug)        |
| `exec.api.server_error`         | Upstream 5xx                                         |
| `exec.api.terminal`             | Vendor refused (policy / content block) — no retry   |
| `exec.api.unknown`              | Unclassified API error                               |
| `exec.api.no_client`            | No LLM client wired into the pipeline                |
| `exec.api.stream_incomplete`    | Stream ended without final response                  |
| `exec.api.retry_exhausted`      | Retry limit hit after recoverable error              |

### `exec.cli.*` — backends that spawn a CLI (`geny_claude_code`)

| Code                            | Meaning                                              |
| ------------------------------- | ---------------------------------------------------- |
| `exec.cli.binary_not_found`     | `claude` binary not on PATH                          |
| `exec.cli.auth_failed`          | CLI not logged in                                    |
| `exec.cli.timeout`              | CLI did not return in time                           |
| `exec.cli.protocol_error`       | CLI emitted malformed stream output                  |
| `exec.cli.permission_denied`    | CLI permission system blocked the call               |
| `exec.cli.exited`               | CLI exited non-zero                                  |

### `exec.pipeline.*` / `exec.stage.*`

| Code                            | Meaning                                              |
| ------------------------------- | ---------------------------------------------------- |
| `exec.pipeline.not_initialized` | Pipeline used before build                           |
| `exec.pipeline.invalid_manifest`| Environment manifest failed schema validation        |
| `exec.stage.failed`             | A stage raised — see chained cause                   |
| `exec.stage.guard_rejected`     | Safety guard refused (budget / cost / iteration)     |

### `exec.tool.*`

| Code                            | Meaning                                              |
| ------------------------------- | ---------------------------------------------------- |
| `exec.tool.unknown`             | LLM called an unregistered tool                      |
| `exec.tool.invalid_input`       | Tool input failed schema validation                  |
| `exec.tool.access_denied`       | Session tool binding disallows this tool             |
| `exec.tool.crashed`             | Tool raised unexpected exception                     |
| `exec.tool.transport`           | MCP / RPC transport failure                          |

### `exec.mutation.*`

| Code                            | Meaning                                              |
| ------------------------------- | ---------------------------------------------------- |
| `exec.mutation.invalid`         | Runtime config mutation rejected                     |
| `exec.mutation.locked`          | Target stage executing; retry after exit             |

### `exec.mcp.*`

| Code                            | Meaning                                              |
| ------------------------------- | ---------------------------------------------------- |
| `exec.mcp.connect_failed`       | MCP server unreachable                               |
| `exec.mcp.initialize_failed`    | `initialize` handshake failed                        |
| `exec.mcp.list_tools_failed`    | `tools/list` errored                                 |
| `exec.mcp.sdk_missing`          | MCP SDK not installed                                |

### Fallback

| Code           | Meaning                                  |
| -------------- | ---------------------------------------- |
| `exec.unknown` | Unclassified error                       |

## End-to-end flow

```
geny-executor                                  Geny backend                     Geny frontend
┌─────────────────────────┐               ┌────────────────────────┐         ┌────────────────────┐
│ GenyExecutorError       │               │ AgentSession           │         │ LogEntryCard       │
│   .code = exec.cli.…    │ ── raise ──▶  │  _extract_executor_    │         │  getEntryDescription│
│   .__cause__ = ...      │               │   error_meta(exc)      │ ──SSE──▶│   t('executor.     │
└─────────────────────────┘               │  → (code, exc_type)    │         │     exec_cli_…')   │
                                          │                        │         └────────────────────┘
                                          │ SessionLogger          │
                                          │  .log_stage_error(     │
                                          │     error_code=…,      │
                                          │     exception_type=…)  │
                                          └────────────────────────┘
```

1. **Pipeline raises** — Any `GenyExecutorError` subclass carries a `code` field. Subclasses like `APIError` resolve from category to code automatically; explicit codes are attached at known failure sites.

2. **Backend extracts** — [backend/service/executor/agent_session.py](../backend/service/executor/agent_session.py) calls `_extract_executor_error_meta(exc)` in both `invoke()` and `astream()` catch blocks. The helper imports `GenyExecutorError` lazily so the backend keeps working even if the executor is downgraded:

   ```python
   def _extract_executor_error_meta(exc: BaseException) -> Tuple[Optional[str], str]:
       exc_type = f"{type(exc).__module__}.{type(exc).__name__}"
       code_str: Optional[str] = None
       try:
           from geny_executor import GenyExecutorError
           if isinstance(exc, GenyExecutorError):
               code_attr = getattr(exc, "code", None)
               if code_attr is not None:
                   code_str = getattr(code_attr, "value", str(code_attr))
       except Exception:
           pass
       return code_str, exc_type
   ```

3. **SessionLogger persists** — [logging/session_logger.py](../backend/service/logging/session_logger.py): `log_stage_error`, `log_graph_error`, and `log_response` accept `error_code` and `exception_type` kwargs and attach them to the SSE event metadata. `SessionInfo.error_code` ([sessions/models.py](../backend/service/sessions/models.py)) persists the code on the session record.

4. **Frontend renders** — [frontend/src/components/execution/LogEntryCard.tsx](../frontend/src/components/execution/LogEntryCard.tsx) reads `entry.metadata.error_code` and looks it up in the `executor` i18n namespace. If a translation exists, it shows the human-friendly message; otherwise it falls back to the raw error string.

## i18n lookup convention

The frontend uses a `getByPath` helper that splits on dots — so a raw code like `exec.cli.auth_failed` would be interpreted as path `executor.exec.cli.auth_failed` and miss. The convention is to **replace dots with underscores** at the lookup site:

```ts
const key = `executor.${code.replace(/\./g, '_')}`;
// exec.cli.auth_failed → executor.exec_cli_auth_failed
const description = t(key);
```

Translations live in:

- [frontend/src/lib/i18n/en.ts](../frontend/src/lib/i18n/en.ts) — `executor` namespace, ~30 entries
- [frontend/src/lib/i18n/ko.ts](../frontend/src/lib/i18n/ko.ts) — Korean mirror

When adding a new code:

1. Upstream the code in executor's `ExecutorErrorCode` enum
2. Add the executor-side documentation entry in executor's `docs/error_codes.md`
3. Add the user-facing translation in Geny's `en.ts` and `ko.ts` under `executor.<code_with_underscores>`
4. Update the table above

## Surfaces that show error codes

- **Execution log cards** — primary surface. One card per stage; failed cards show the translated message plus the raw `error_code` chip for support escalation.
- **Session info panel** — sticky banner if `SessionInfo.error_code` is set; clears on next successful turn.
- **Settings → Providers** — preflight failures (auth, network) bubble up here when you save a provider config.

## Operator playbook

| What you see                                      | Likely cause / fix                                                                  |
| ------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `exec.api.auth_invalid_key`                       | Wrong key — re-paste in Settings → Providers                                        |
| `exec.api.rate_limited` with auto-retry succeeding | Healthy backoff; ignore unless persistent                                          |
| `exec.api.token_limit`                            | Trim the conversation or switch to a larger-context model (Opus 4.7 `[1m]`)         |
| `exec.cli.binary_not_found`                       | Install Claude Code CLI on the backend host; ensure it's on PATH for the user      |
| `exec.cli.auth_failed`                            | Run `claude /login` on the backend host                                             |
| `exec.cli.permission_denied`                      | CLI's own permission system refused — extend the `permissions.allow` list           |
| `exec.mcp.connect_failed` during CLI session      | Per-session MCP bridge didn't bind — check backend logs, restart session            |
| `exec.tool.invalid_input`                         | LLM hallucinated wrong tool args — usually self-corrects, escalate if persistent    |
| `exec.stage.guard_rejected`                       | Budget/iteration guard fired — loosen via Settings or shrink the workload           |

## Reporting

For support, capture:

1. Session ID (visible in URL and session info)
2. The error code (the chip on the failed card)
3. The exception type if shown (e.g. `geny_executor.core.errors.APIError`)
4. The first failing log card's full text
