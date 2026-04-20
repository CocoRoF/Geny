# Plan 02 — PR #2: Role-default tool rosters

**Branch.** `fix/role-default-tool-rosters`
**Depends on.** PR #1 (`fix/manifest-tool-roster`)

## Goal

VTuber and Worker both get the Geny platform toolset (DM,
inbox, memory, knowledge) by default, while keeping role-
appropriate differences in the custom-tool slice:

| | platform tools | web tools | browser tools |
| --- | --- | --- | --- |
| Worker | ✓ | ✓ | ✓ |
| VTuber | ✓ | ✓ | ✗ |

Rationale for denying `browser_*` to VTuber: the VTuber persona
is conversational and shouldn't spawn a playwright browser on
casual questions. Matches today's `template-vtuber-tools` preset
whitelist (see `backend/tool_presets/template-vtuber-tools.json`).

## Change surface

### `backend/service/environment/templates.py`

Add a shared helper at module level:

```python
def _vtuber_tool_roster(all_tool_names: List[str]) -> List[str]:
    """Platform tools + the three conversational web tools, no
    browser automation."""
    VTUBER_CUSTOM_WHITELIST = {"web_search", "news_search", "web_fetch"}

    platform = [
        name for name in all_tool_names
        if name.startswith(("geny_", "memory_", "knowledge_", "opsidian_"))
    ]
    web_subset = [
        name for name in all_tool_names
        if name in VTUBER_CUSTOM_WHITELIST
    ]
    return platform + web_subset
```

Update `create_vtuber_env` to take the full loader roster and
filter down:

```python
def create_vtuber_env(
    all_tool_names: Optional[List[str]] = None,
) -> EnvironmentManifest:
    roster = _vtuber_tool_roster(all_tool_names or [])
    manifest = build_default_manifest(
        preset="vtuber",
        external_tool_names=roster,
    )
    ...
```

Update `install_environment_templates`:

```python
def install_environment_templates(
    service: EnvironmentService,
    *,
    external_tool_names: Optional[List[str]] = None,
) -> int:
    all_names = list(external_tool_names or [])
    seeds = [
        create_worker_env(external_tool_names=all_names),
        create_vtuber_env(all_tool_names=all_names),
    ]
    ...
```

### Test — `backend/tests/service/environment/test_templates.py`

Extend:

```python
def test_vtuber_env_includes_platform_excludes_browser():
    loader = get_tool_loader()
    manifest = create_vtuber_env(all_tool_names=loader.get_all_names())
    # Platform tools present
    assert "geny_send_direct_message" in manifest.tools.external
    assert "memory_read" in manifest.tools.external
    assert "knowledge_search" in manifest.tools.external
    # Web tools present
    assert "web_search" in manifest.tools.external
    # Browser tools absent
    for name in manifest.tools.external:
        assert not name.startswith("browser_"), name
```

## Why category-prefix filtering (not a hardcoded allowlist)

Hardcoding `["geny_send_direct_message", "geny_read_inbox",
"memory_read", …]` would drift the moment someone adds a new
platform tool. Prefix filtering `geny_` / `memory_` /
`knowledge_` / `opsidian_` is stable: any new tool in
`tools/built_in/` follows the naming convention (enforced
implicitly today) and automatically gets picked up.

If someone later adds a platform tool that should *not* reach
the VTuber (e.g. a destructive admin tool), the right answer is
an explicit exclude list — not a switch to an allowlist. PR #2
leaves room for that; none such exists today.

## Verification before merge

1. `pytest backend/tests/service/environment/test_templates.py`
   passes.
2. Start backend, create a VTuber session, ask it
   "What tools do you have?" — it lists platform + web tools,
   no browser.
3. Create a worker session, ask the same — it lists platform +
   web + browser tools.
4. VTuber → Sub-Worker DM: `geny_send_direct_message` executes
   successfully (no more `ERROR (0ms)`).

## Rollback

Revert the PR. VTuber goes back to 3 web tools only; worker
unaffected (got its roster in PR #1).
