# D.2 — Framework settings reader map

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/settings/known_sections.py` (new) — `SECTION_READERS` constant + `readers_for(name)` helper.
- `backend/controller/framework_settings_controller.py` — extend `FrameworkSectionSummary` with `readers: List[str]`; populate in `list_sections`.
- `backend/tests/service/settings/test_known_sections.py` (new) — 3 cases (unknown / known non-empty / shared with install map).
- `frontend/src/lib/api.ts` — add `readers: string[]` to `FrameworkSectionSummary`.
- `frontend/src/components/settings/FrameworkSettingsPanel.tsx` — render reader list as small text under each section row + warning color when empty.

## What it changes

The framework settings panel previously edited any registered section without telling the operator who reads it. A misnamed section silently no-oped — JSON sat in `~/.geny/settings.json` and no executor module ever consulted it.

Now each section row shows the list of reader modules (e.g. `service.skills.install` for the `skills` section). When a registered section has no entry in the reader map, the row turns warning-color and reads "no reader" — flagging either a stale registration or an out-of-date map.

## Why

Audit (cycle 20260426_1, analysis/02 §C.2). Combined with C.2's Integration Health card, this closes the "operator can write a setting that does nothing" footgun.

## Tests

3 unit cases in `test_known_sections.py`:
- `test_readers_for_unknown_returns_empty_list` — defensive default.
- `test_readers_for_known_returns_at_least_one` — every entry in `SECTION_READERS` must have a non-empty reader list.
- `test_readers_for_returns_a_copy` — caller can't mutate the module constant.
- Parametrized `test_install_registered_sections_have_readers` — locks the install layer ↔ reader map sync (catches future drift).

Local: skipped (importorskip on pydantic). CI runs them.

## Maintenance

When a new `register_section` call lands, add an entry to `SECTION_READERS`. The parametrized test will fail otherwise.

## Out of scope

- Live verification that the listed reader actually calls `get_section(name)` — that's a static analysis task; the hand-maintained map is the contract.
- Dynamic discovery via grep across the backend — heavier than the maintenance cost of a 10-line dict.
