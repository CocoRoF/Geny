"""Coverage for G10.1 — FileCredentialStore wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("geny_executor.tools.mcp.credentials")

from geny_executor.tools.mcp.credentials import FileCredentialStore  # noqa: E402

from service.credentials import (  # noqa: E402
    credentials_path,
    install_credential_store,
)


@pytest.fixture
def isolated_home(monkeypatch, tmp_path) -> Iterator[Path]:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield tmp_path


class _StubManagerWithSetter:
    def __init__(self) -> None:
        self.store = None

    def set_credential_store(self, store) -> None:
        self.store = store


class _StubManagerWithAttr:
    credential_store = None


class _StubManagerNoHook:
    pass


class _StubPipeline:
    def __init__(self, manager) -> None:
        self._mcp_manager = manager


def test_path_under_home(isolated_home: Path) -> None:
    assert credentials_path() == Path.home() / ".geny" / "credentials.json"


def test_no_op_when_pipeline_has_no_manager(isolated_home: Path) -> None:
    pipeline = _StubPipeline(manager=None)
    assert install_credential_store(pipeline) is None


def test_attaches_via_setter(isolated_home: Path) -> None:
    manager = _StubManagerWithSetter()
    pipeline = _StubPipeline(manager)
    store = install_credential_store(pipeline)
    assert isinstance(store, FileCredentialStore)
    assert manager.store is store


def test_attaches_via_attribute(isolated_home: Path) -> None:
    manager = _StubManagerWithAttr()
    pipeline = _StubPipeline(manager)
    store = install_credential_store(pipeline)
    assert manager.credential_store is store


def test_returns_store_even_when_manager_has_no_hook(isolated_home: Path) -> None:
    """Hosts with an unusual MCPManager subclass still get a store
    constructed — they just have to attach it manually."""
    manager = _StubManagerNoHook()
    pipeline = _StubPipeline(manager)
    store = install_credential_store(pipeline)
    assert isinstance(store, FileCredentialStore)


def test_creates_parent_directory(isolated_home: Path) -> None:
    pipeline = _StubPipeline(_StubManagerWithSetter())
    install_credential_store(pipeline)
    assert credentials_path().parent.exists()
