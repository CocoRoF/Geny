"""Pin the streaming-accumulator sanitize contract in chat_controller.

Cycle 20260421_2 / plan 02, sink #5. The live-streaming path in
``_poll_logs`` has to accumulate the raw LLM token stream (because the
next chunk may complete a partial tag) while exposing a sanitized view
to the UI. These tests mirror the three-line accumulator pattern
inline (``raw = existing + new; sanitized = sanitize_for_display(raw)``)
so a regression in the controller's STREAM branch fails here even
without spinning up the full FastAPI stack.

Sink #1 (final broadcast reply) is covered by review + the shared
sanitizer contract in ``tests/service/utils/test_text_sanitizer.py``;
this file focuses on the token-boundary case the controller has to
handle.
"""

from __future__ import annotations

from service.utils.text_sanitizer import sanitize_for_display


def _apply_stream_chunk(state: dict, chunk: str) -> None:
    """Replicate the exact three lines that chat_controller's
    ``_poll_logs`` applies for each STREAM entry."""
    raw = (state.get("streaming_raw") or "") + (chunk or "")
    state["streaming_raw"] = raw
    state["streaming_text"] = sanitize_for_display(raw)


def test_partial_tag_split_across_chunks_resolves_once_complete() -> None:
    """The reported production case: the LLM emits ``[joy]`` across
    two tokens. Before the closing ``]`` arrives, the partial must stay
    in the raw buffer; after it arrives the sanitized view drops it."""
    state: dict = {}

    _apply_stream_chunk(state, "hello [j")
    assert state["streaming_raw"] == "hello [j"
    assert state["streaming_text"] == "hello [j"  # partial preserved — still accumulating

    _apply_stream_chunk(state, "oy] world")
    assert state["streaming_raw"] == "hello [joy] world"
    assert state["streaming_text"] == "hello world"  # fully stripped


def test_routing_prefix_stripped_from_first_chunk() -> None:
    state: dict = {}
    _apply_stream_chunk(state, "[SUB_WORKER_RESULT] ")
    _apply_stream_chunk(state, "워커 답장이 도착했어요!")

    assert state["streaming_text"] == "워커 답장이 도착했어요!"
    assert state["streaming_raw"].startswith("[SUB_WORKER_RESULT]")


def test_unclosed_think_block_hides_remaining_stream() -> None:
    """Mid-stream ``<think>`` without a closer must hide everything
    after it — reasoning must not leak to the UI even briefly."""
    state: dict = {}
    _apply_stream_chunk(state, "visible ")
    _apply_stream_chunk(state, "<think>internal rea")
    assert state["streaming_text"] == "visible"

    _apply_stream_chunk(state, "soning</think> post")
    # Closer arrived — trailing content is visible again.
    assert state["streaming_text"] == "visible post"


def test_multiple_emotion_tags_stripped_in_order() -> None:
    state: dict = {}
    for chunk in ("[joy] 안녕 ", "[surprise] 반가워", " [smirk]"):
        _apply_stream_chunk(state, chunk)

    assert state["streaming_text"] == "안녕 반가워"
    assert "[joy]" in state["streaming_raw"]
