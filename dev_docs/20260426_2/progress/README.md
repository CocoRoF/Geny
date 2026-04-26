# Cycle 20260426_2 — Progress

| Sprint | PR | Status | Notes |
|---|---|---|---|
| (docs) | [#422](https://github.com/CocoRoF/Geny/pull/422) | ✅ Merged | Cycle scaffolding (analysis 01 hook bug + 02 coverage matrix; 17-sprint plan) |
| H.1 | [#423](https://github.com/CocoRoF/Geny/pull/423) | ✅ Merged | Hook backend schema rewrite — command:str, args, match dict, env, working_dir; install layer routes through `parse_hook_config`; 11 unit cases. Fixes the silent "hooks never fire" prod bug |
| H.2 | [#424](https://github.com/CocoRoF/Geny/pull/424) | ✅ Merged | HooksTab frontend rewrite — 16-event picker, structured form (command + args + match + env + working_dir), audit_log_path editor |
| H.3 | [#425](https://github.com/CocoRoF/Geny/pull/425) | ✅ Merged | End-to-end parse roundtrip test — 4 cases. Regression guard for the H.1 schema |
| P.1 | [#426](https://github.com/CocoRoF/Geny/pull/426) | ✅ Merged | Manifest pipeline/model PATCH endpoints with shallow-merge + executor-aligned validation; 9 unit cases |
| P.2 | [#427](https://github.com/CocoRoF/Geny/pull/427) | ✅ Merged | Builder Pipeline + Model config editors. 4-view toggle (Stages / Pipeline / Model / Tools); reuses D.3's affected-sessions toast |
| S.1 | [#428](https://github.com/CocoRoF/Geny/pull/428) | ✅ Merged | Per-stage model_override editor (JSON textarea in stage detail) |
| S.2 | [#429](https://github.com/CocoRoF/Geny/pull/429) | ✅ Merged | Per-stage tool_binding editor (s10 emphasis) |
| R.1 | [#430](https://github.com/CocoRoF/Geny/pull/430) | ✅ Merged | Permission mode picker — advisory↔enforce + 6-value executor mode; PATCH /api/permissions/mode |
| T.1+T.2 | [#431](https://github.com/CocoRoF/Geny/pull/431) | ✅ Merged | tools.external checkbox grid (backed by GenyToolProvider catalog) + tools.scope JSON editor |
| T.3 | [#432](https://github.com/CocoRoF/Geny/pull/432) | ✅ Merged | MCP servers structured editor — Structured / JSON mode toggle; per-transport fields (stdio command+args+env, http/sse url+headers) |
| K.1 | [#433](https://github.com/CocoRoF/Geny/pull/433) | ✅ Merged | Skills version + execution_mode + extras fields |
| K.2 | [#434](https://github.com/CocoRoF/Geny/pull/434) | ✅ Merged | PermissionsConfigSection registered in install_geny_settings |
| G.1 | [#435](https://github.com/CocoRoF/Geny/pull/435) | ✅ Merged | Memory provider settings.json-first resolution (provider/scope/root/dsn/dialect/timezone) |
| G.2 | [#436](https://github.com/CocoRoF/Geny/pull/436) | ✅ Merged | Memory tuning knobs (max_inject_chars / recent_turns / enable_vector_search / enable_reflection) editable; 10 unit cases |
| G.3 | [#437](https://github.com/CocoRoF/Geny/pull/437) | ✅ Merged | AffectTagEmitter.max_tags_per_turn editable via settings.json:affect |
| G.4 | [#438](https://github.com/CocoRoF/Geny/pull/438) | ✅ Merged | install_notification_endpoints reads settings.json:notifications.channels first; legacy JSON files + env still work as fallback sources |

**Total:** 17 sprint PRs merged on 2026-04-26 (PR #422–#438), ~30 unit tests added (skip-on-pydantic locally; CI runs them).

## Outcome vs plan

All 17 sprints from `plan/cycle_plan.md` shipped. T.1 + T.2 bundled into one PR (#431) since they share the same `ToolsEditor` body — splitting would have meant two overlapping diffs. No NEEDS_VERIFY items left dangling.

## Coverage scorecard (post-cycle)

| Area | Coverage % |
|---|---|
| Stages structure (active / artifact / config / strategies / model_override / tool_binding) | ~95% |
| Pipeline-level config | ~95% (full PipelineConfig form in P.2) |
| Model config | ~95% (full ModelConfig form in P.2) |
| Permissions (rules + mode + executor_mode) | ~95% |
| Hooks (16-event support, full HookConfigEntry shape, audit_log_path) | ~95% (was 0% — H.1+H.2 fixed the prod bug) |
| Skills (id / name / description / category / effort / model_override / allowed_tools / examples / version / execution_mode / extras) | ~95% |
| MCP servers (transport-aware structured form) | ~85% (Structured + JSON fallback) |
| Tools (built_in + adhoc + mcp_servers + external + scope + lists) | ~95% |
| Memory layer (provider + tuning knobs) | ~95% |
| Notifications endpoints | ~85% (settings.json+legacy+env) |
| Affect emitter | ~85% |
| Geny-side extensions (persona / sub-worker) | ~30% (persona block ordering still code-only — separate cycle) |

## Future cycle candidates

- Persona block ordering / templates UI (deferred Tier 6).
- `send_message_channels` registry settings.json read (mirror of G.4).
- Per-session memory provider + tuning override.
- Live re-attach for non-hook/permission sections (memory provider, affect knob etc.) — covers what E.1 does for hooks/permissions.
- Bundled-skill version + extras read-only display.
