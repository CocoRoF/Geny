"""Layer adapters — legacy SessionMemoryManager ↔ MemoryProvider.

Each layer (STM, LTM, Notes, Vector, Curated/Global) lands its adapter
in this package as its Phase 5 PR merges. The adapter encapsulates the
read/write routing for one layer, gated by its ``MEMORY_LEGACY_<LAYER>``
flag from :mod:`service.memory_provider.flags`.

This package is intentionally empty at Phase 5 kickoff — flags are
scaffolded now so per-layer PRs can be reviewed in isolation and
enabled/disabled independently without touching the env surface.
"""

__all__: list[str] = []
