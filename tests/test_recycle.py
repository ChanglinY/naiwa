from __future__ import annotations

from pathlib import Path

import pytest

import src.recycle as recycle


def test_rejects_missing_path(tmp_path: Path) -> None:
    ok, error = recycle.send_to_recycle_bin(tmp_path / "missing.txt")
    assert not ok
    assert "unavailable" in error


def test_passes_shortcut_path_unchanged_to_file_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shortcut = tmp_path / "target.lnk"
    shortcut.write_bytes(b"not-a-real-shortcut")
    seen: list[str] = []

    def fake_recycle(path: str) -> tuple[bool, str]:
        seen.append(path)
        return True, ""

    monkeypatch.setattr(recycle, "_file_operation_recycle", fake_recycle)
    assert recycle.send_to_recycle_bin(shortcut) == (True, "")
    assert seen == [str(shortcut.resolve())]


@pytest.mark.skipif(recycle.os.name != "nt", reason="Windows Recycle Bin API")
def test_sends_temp_file_to_recycle_bin(tmp_path: Path) -> None:
    file = tmp_path / "naiwa-recycle-integration.txt"
    file.write_text("recycle me", encoding="utf-8")
    ok, error = recycle.send_to_recycle_bin(file)
    assert ok, error
    assert not file.exists()
