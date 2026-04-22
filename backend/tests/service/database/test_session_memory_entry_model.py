"""Schema-level tests for :class:`SessionMemoryEntryModel` affect fields.

Cycle 20260422_2 PR-X6-1 adds nullable ``emotion_vec`` /
``emotion_intensity`` columns. These tests pin the shape without
requiring a live DB connection — they inspect the model's
``get_schema()`` output and ``__init__`` defaults so that regressions
to the column declarations show up in CI instead of at container
startup.
"""

from __future__ import annotations

from service.database.models.session_memory_entry import SessionMemoryEntryModel


def test_default_init_leaves_affect_fields_null() -> None:
    m = SessionMemoryEntryModel()
    assert m.emotion_vec is None
    assert m.emotion_intensity is None


def test_affect_fields_round_trip_through_init() -> None:
    m = SessionMemoryEntryModel(
        emotion_vec='[0.1, 0.2, 0.3]',
        emotion_intensity=0.75,
    )
    assert m.emotion_vec == '[0.1, 0.2, 0.3]'
    assert m.emotion_intensity == 0.75


def test_schema_declares_affect_columns_as_nullable_text_and_real() -> None:
    schema = SessionMemoryEntryModel().get_schema()
    assert "emotion_vec" in schema
    assert "emotion_intensity" in schema
    assert "TEXT" in schema["emotion_vec"].upper()
    assert "NULL" in schema["emotion_vec"].upper()
    assert "REAL" in schema["emotion_intensity"].upper()
    assert "NULL" in schema["emotion_intensity"].upper()


def test_schema_preserves_all_pre_existing_columns() -> None:
    """Guard against accidentally clobbering the schema when adding
    new fields. If this test fails, a column was removed or renamed."""
    schema = SessionMemoryEntryModel().get_schema()
    required = {
        "entry_id", "session_id", "source", "entry_type", "content",
        "filename", "heading", "topic", "role", "event_name",
        "metadata_json", "entry_timestamp", "category", "tags_json",
        "importance", "links_to_json", "linked_from_json", "source_type",
        "summary", "is_global",
    }
    assert required.issubset(set(schema.keys()))


def test_create_table_query_includes_affect_columns() -> None:
    """Pin that the generated DDL mentions the new columns — catches
    a regression where the schema method was updated but the DDL
    generator skipped them."""
    for db_type in ("postgresql", "sqlite"):
        ddl = SessionMemoryEntryModel.get_create_table_query(db_type)
        assert "emotion_vec" in ddl
        assert "emotion_intensity" in ddl


def test_affect_columns_cross_backend_types() -> None:
    """Both TEXT and REAL render identically in PostgreSQL and SQLite
    — this pins that the schema entries don't use backend-specific
    types like ``FLOAT8[]`` or ``pgvector`` that would break SQLite."""
    schema = SessionMemoryEntryModel().get_schema()
    for col in ("emotion_vec", "emotion_intensity"):
        t = schema[col].upper()
        forbidden = ("FLOAT8[]", "VECTOR", "ARRAY", "DOUBLE PRECISION")
        for f in forbidden:
            assert f not in t, f"{col} uses backend-specific type {f}"
