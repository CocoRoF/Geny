# 02 — Swap install.py callsites to settings.json loader

**Phase:** 4 (last — highest regression risk)
**PRs:** 3
**Risk:** high — touches the existing yaml flow.

---

## Why deferred from cycles A+B

PR-B.3.3 ships a YAML→settings.json migrator. PR-B.3.5 ships
section schemas + the loader cascade. But the actual install
sites (`service/permission/install.py`, `service/hooks/install.py`,
the skills install) still read yaml directly. Until those switch
to the loader, the cutover isn't complete — operators using the
new settings.json are running parallel paths.

This was deferred because:

1. The yaml flow is the proven path serving prod today.
2. Each install site has its own validation quirks; rewriting all
   three at once would batch the regression risk.
3. Operators need a deprecation window where both paths still work
   (so a faulty settings.json falls back to yaml instead of bricking
   the boot).

---

## Strategy

**Dual-read, settings.json wins.** Each install site:

1. Read settings.json section first (via `loader.get_section(name)`).
2. If present + valid → use it.
3. Else → fall back to the old yaml flow (existing code unchanged).
4. Log a warning when both are present (operator probably forgot
   to delete the yaml after migration).
5. Log info when only yaml is present (deprecation hint).

Yaml fallback can be removed in a follow-on minor (no PR planned
in this folder — leave it living for one cycle of operator
adoption).

---

## PR-D.2.1 — refactor(permission): dual-read install.py

### Files

- `backend/service/permission/install.py` (modify)
- `backend/tests/service/permission/test_install_settings.py` (new)

### Current shape (relevant excerpt)

```python
def install_permission_runner() -> Optional[PermissionRunner]:
    yaml_path = permissions_yaml_path()
    if not yaml_path.exists():
        return None
    rules = load_permission_rules(yaml_path)
    return PermissionRunner(rules=rules, mode=PermissionMode.DEFAULT)
```

### New shape

```python
def install_permission_runner() -> Optional[PermissionRunner]:
    section = _load_from_settings()
    if section is not None:
        if (yaml_path := permissions_yaml_path()).exists():
            logger.warning(
                "permissions duplicated in settings.json AND %s — "
                "settings.json wins; consider deleting the yaml",
                yaml_path,
            )
        return _build_runner_from_section(section)

    # fallback — existing yaml path unchanged
    yaml_path = permissions_yaml_path()
    if not yaml_path.exists():
        return None
    logger.info(
        "permissions loading from yaml (%s) — migrate to settings.json "
        "via service.settings.migrator", yaml_path,
    )
    rules = load_permission_rules(yaml_path)
    return PermissionRunner(rules=rules, mode=PermissionMode.DEFAULT)


def _load_from_settings() -> Optional[Dict[str, Any]]:
    try:
        from geny_executor.settings import get_default_loader
    except ImportError:
        return None
    return get_default_loader().get_section("permissions")


def _build_runner_from_section(section: Dict[str, Any]) -> PermissionRunner:
    # Translate the section dict into PermissionRule list.
    # Schema mirrors the existing yaml format so the migrator's
    # 1:1 yaml→json translation works.
    raw_rules = section.get("rules", [])
    rules = [...]   # parse raw_rules into PermissionRule
    mode = PermissionMode(section.get("mode", "default"))
    return PermissionRunner(rules=rules, mode=mode)
```

### Tests

- settings.json section present → uses it
- yaml only → uses yaml + logs deprecation
- both present → uses settings.json + logs duplication warning
- neither → returns None
- malformed settings.json section → falls back to yaml + logs error

### Risk + mitigation

| Risk | Mitigation |
|---|---|
| Section schema differs from yaml shape → silent rule drift | `PermissionRule` has a single canonical from-dict path; both flows use it |
| settings.json present but parse fails | _load_from_settings returns None on validator failure; yaml fallback covers |
| Operator deletes yaml expecting settings to handle, but settings.json absent | Nothing breaks (returns None, no permissions installed) — same shape as a fresh install |

---

## PR-D.2.2 — refactor(hooks): dual-read install.py

### Files

- `backend/service/hooks/install.py` (modify)
- `backend/tests/service/hooks/test_install_settings.py` (new)

### Same pattern as D.2.1

`install_hook_runner` learns to read `settings.json:hooks` first,
falls back to `~/.geny/hooks.yaml`. Same warning + info log
contract.

### Edge case: env opt-in

`GENY_ALLOW_HOOKS=1` is the env opt-in for any hooks at all (cycle 1
gate). That stays — both paths still gate on it. If
`enabled: true` lives in settings.json but env is unset, no runner
is built. Same as the yaml flow.

### Tests
mirror D.2.1 structure (5 tests).

---

## PR-D.2.3 — refactor(skills): dual-read user_skills_enabled

### Files

- `backend/service/skills/install.py` (modify)
- `backend/tests/service/skills/test_install_settings.py` (new)

### Current

`GENY_ALLOW_USER_SKILLS=1` env var alone gates user skill
discovery. Cycle B's settings.json loader added a `skills` section
schema with `user_skills_enabled: bool`.

### New shape

```python
def _user_skills_enabled() -> bool:
    # 1. settings.json wins
    try:
        from geny_executor.settings import get_default_loader
        section = get_default_loader().get_section("skills")
        if section is not None and "user_skills_enabled" in section:
            return bool(section["user_skills_enabled"])
    except ImportError:
        pass
    # 2. legacy env var
    return os.getenv("GENY_ALLOW_USER_SKILLS") == "1"
```

### Tests

- settings.json `user_skills_enabled: true` enables, env absent
- settings.json absent, env=1 enables (legacy path)
- settings.json `false`, env=1 → settings wins (false)
- both absent → disabled

### Risk + mitigation

| Risk | Mitigation |
|---|---|
| Env-set environments suddenly disabled by a settings.json that didn't exist before | Migrator (PR-B.3.3) doesn't touch the skills section, so existing env-set deployments are unaffected unless an operator hand-edits settings.json |
| Boolean coercion ambiguity | strict `bool()` cast with explicit "true"/"false" string handling in the section schema, not the install site |

---

## Combined acceptance criteria (all 3 PRs)

- [ ] every install site reads settings.json first, yaml second
- [ ] every install site logs warning on both-present
- [ ] every install site logs info on yaml-only ("deprecation hint")
- [ ] tests cover all four scenarios per site (15 tests total)
- [ ] full Geny CI suite passes (no regression on yaml-only operators)
- [ ] `06_cycle_ab_completion_report.md` "What did NOT ship" section
      gets B.3.4 moved to "Closed in cycle D"

---

## Operator migration path

After this cycle merges:

1. Operators on yaml-only: see deprecation log on every boot;
   no behaviour change.
2. Operators who ran the migrator: see settings.json win + a
   warning if they didn't delete the yaml.
3. Operators who hand-edit settings.json: settings.json wins.

A follow-on cycle (not in this folder) removes the yaml fallback
paths entirely after one operator-adoption cycle.
