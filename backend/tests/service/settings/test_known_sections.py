"""D.2 (cycle 20260426_1) — known section reader map tests.

The map is the single-file source of truth for "which modules read
section X at runtime". The list is hand-maintained; this test locks in
the contract that every section ``install_geny_settings`` registers
also has at least one reader entry. A failure here means either a
new register_section call landed without updating the reader map, or
the reader map kept a stale entry for a removed section.
"""

from __future__ import annotations

import pytest

# service.settings.__init__ pulls in pydantic via install.py's section
# imports; skip cleanly when the bare test venv lacks pydantic. CI
# installs the full backend requirements.
pytest.importorskip("pydantic")

from service.settings.known_sections import SECTION_READERS, readers_for  # noqa: E402


def test_readers_for_unknown_returns_empty_list() -> None:
    assert readers_for("definitely-not-a-section") == []


def test_readers_for_known_returns_at_least_one() -> None:
    """Every entry in SECTION_READERS must have a non-empty reader list
    (the whole point of the map). This guards against accidental
    ``"foo": []`` rows."""
    for name, readers in SECTION_READERS.items():
        assert readers, f"empty reader list for section {name!r}"
        assert all(isinstance(r, str) and r for r in readers), (
            f"section {name!r} has a non-string or empty reader entry"
        )


def test_readers_for_returns_a_copy() -> None:
    """``readers_for`` must return a list-copy so the caller can't
    accidentally mutate the module-level constant."""
    a = readers_for("permissions")
    b = readers_for("permissions")
    assert a == b
    a.append("__mutation_attempt__")
    assert "__mutation_attempt__" not in readers_for("permissions")


@pytest.mark.parametrize(
    "name",
    [
        # Sections registered by ``install_geny_settings`` (one per
        # ``register_section`` call). Locking these in this test
        # ensures the install layer + the reader map stay in sync.
        "preset",
        "vtuber",
        "hooks",
        "skills",
        "model",
        "telemetry",
        "notifications",
        "permissions",  # K.2 (cycle 20260426_2)
        "memory",       # G.1 (cycle 20260426_2)
        "affect",       # G.3 (cycle 20260426_2)
        "channels",     # L.1 (cycle 20260426_3)
    ],
)
def test_install_registered_sections_have_readers(name: str) -> None:
    assert readers_for(name), (
        f"section {name!r} is registered by install_geny_settings but "
        "missing from known_sections.SECTION_READERS — add a reader "
        "entry or remove the registration."
    )
