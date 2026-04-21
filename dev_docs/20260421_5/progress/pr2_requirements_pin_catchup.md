# PR-2 progress — requirements.txt executor pin catch-up

- Branch: `fix/requirements-geny-executor-029`
- Trigger: Production deploy surfaced `ImportError: cannot import name
  'ReflectionResolver' from 'geny_executor.memory'` in
  `AgentSession._build_pipeline` at runtime.

## Root cause

Cycle 20260421_4 PR #206 bumped the source pin in
`backend/pyproject.toml` to `geny-executor>=0.29.0,<0.30.0` because
`ReflectionResolver` + per-stage model override entered the executor
in PR #45 and first released as **v0.29.0**. The v0.28.0 tag does
not contain `ReflectionResolver`.

The Docker image is installed from `backend/requirements.txt`, not
`pyproject.toml` (`Dockerfile:24` → `pip install -r requirements.txt`).
That file still pinned `>=0.28.0,<0.29.0`, which actively **excludes**
v0.29.0. pip resolved to v0.28.x — missing `ReflectionResolver` — and
the session-build import failed at runtime.

## Fix

One-line bump in `backend/requirements.txt:25`:

```
-geny-executor>=0.28.0,<0.29.0
+geny-executor>=0.29.0,<0.30.0
```

Brings requirements.txt back in sync with pyproject.toml. Next
`docker compose build` will invalidate the `pip install` layer
cache (requirements.txt content changed) and fetch v0.29.0 from
PyPI — published earlier in cycle-5 follow-up via
[CocoRoF/geny-executor#46](https://github.com/CocoRoF/geny-executor/pull/46).

## Why the drift happened

Cycle-4 PR #206 updated one pin but not the other. Dockerfile layer
caching masked the issue until a production rebuild on a clean
cache tried to install against the stale floor. A single-pin
project layout (requirements.txt sourced from pyproject.toml, or
vice versa) would have prevented this — tracked as follow-up, not
addressed here since the fix is deploy-blocking.

## Verification

After redeploy:

```bash
docker compose exec backend python -c \
  "from geny_executor import __version__, memory; \
   print(__version__); print('ReflectionResolver' in memory.__all__)"
# expected: 0.29.0 / True
```
