"""Static prompt-file regression tests (cycle 20260422_6 PR4 + PR5).

These tests guard the *content* of `prompts/worker.md` and
`prompts/vtuber.md` for the contract changes introduced in this cycle.
They are deliberately keyword-level (cheap to run, no LLM) so a casual
edit that drops the structured `[SUB_WORKER_RESULT]` protocol or the
PR2 acclimation guidance is caught at CI time before it hits the model.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


@pytest.fixture(scope="module")
def worker_md() -> str:
    return (_PROMPTS_DIR / "worker.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def vtuber_md() -> str:
    return (_PROMPTS_DIR / "vtuber.md").read_text(encoding="utf-8")


# ── PR4 worker.md — Sub-Worker pair info moved out of code ──────────


def test_worker_md_has_paired_sub_worker_section(worker_md: str) -> None:
    assert "## When You Are a Paired Sub-Worker" in worker_md
    # Conditional opener so an unpaired Worker is told to ignore the
    # block (cycle 20260422_6 PR4 §7 risk-mitigation row 4).
    assert "applies **only** when" in worker_md


# ── PR5 worker.md — structured reply protocol ───────────────────────


def test_worker_md_describes_subworker_result_protocol(worker_md: str) -> None:
    assert "[SUB_WORKER_RESULT]" in worker_md
    # All three required fields and their canonical enum.
    assert "status: ok | partial | failed" in worker_md
    assert "summary:" in worker_md
    assert "details:" in worker_md
    assert "artifacts:" in worker_md


def test_worker_md_subworker_protocol_includes_examples(worker_md: str) -> None:
    """Few-shot examples improve smaller-model adherence (PR5 §7)."""
    # Two illustrative cases — at minimum one ok and one failed.
    assert "status: ok" in worker_md
    assert "status: failed" in worker_md


def test_worker_md_forbids_persona_language_in_reply(worker_md: str) -> None:
    """The Sub-Worker owns facts; the VTuber owns tone. Worker must
    NOT add greetings/persona language to its structured reply."""
    assert "no greetings, no persona" in worker_md.lower()


# ── PR5 vtuber.md — trigger uses structured fields ──────────────────


def test_vtuber_md_subworker_trigger_parses_structured_payload(
    vtuber_md: str,
) -> None:
    """The VTuber trigger must instruct the model to *parse* not
    *quote* the payload, and must reference each canonical field."""
    # The trigger section's new instructions.
    assert "parse it" in vtuber_md.lower() or "*parse it" in vtuber_md
    # Each field referenced explicitly so the model knows what each
    # one is for.
    for field in ("status", "summary", "details", "artifacts"):
        assert f"`{field}" in vtuber_md or f"{field}:" in vtuber_md, field
    # Status enum coverage.
    for verdict in ("ok", "partial", "failed"):
        assert f"status: {verdict}" in vtuber_md or f"`status: {verdict}`" in vtuber_md, verdict


def test_vtuber_md_warns_against_dumping_details(vtuber_md: str) -> None:
    """`details` is for the VTuber's reference only — must NOT be
    forwarded verbatim. The trigger has to say so explicitly so the
    persona doesn't paste raw tool output to the user."""
    snippet = vtuber_md.lower()
    assert "do not dump" in snippet or "do not dump it" in snippet


# ── PR2 vtuber.md — acclimation + naming guidance ───────────────────


def test_vtuber_md_has_acclimation_first_encounter_section(
    vtuber_md: str,
) -> None:
    assert "first-encounter" in vtuber_md.lower()
    # The anti-newborn guard from PR2.
    assert "갓 태어난" in vtuber_md or "newborn" in vtuber_md.lower()


def test_vtuber_md_has_on_your_name_section(vtuber_md: str) -> None:
    """PR2 + PR3: the persona file must instruct the model that
    `session_name` is an internal handle and not a name."""
    assert "On Your Name" in vtuber_md
    assert "internal" in vtuber_md.lower()
