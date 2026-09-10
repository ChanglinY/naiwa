from __future__ import annotations

from pathlib import Path

import pytest

from src.paths import is_desktop_path, normalize_path, paths_equal


def test_normalize_is_absolute_and_strips_trailing_separator(tmp_path: Path) -> None:
    folder = tmp_path / "Folder"
    folder.mkdir()
    assert normalize_path(str(folder) + "\\") == normalize_path(folder)


def test_paths_equal_resolves_dot_segments(tmp_path: Path) -> None:
    file = tmp_path / "folder" / "a.txt"
    file.parent.mkdir()
    file.write_text("x", encoding="utf-8")
    alternate = file.parent / ".." / "folder" / file.name
    assert paths_equal(file, alternate)


def test_normalize_rejects_empty_and_nul() -> None:
    with pytest.raises(ValueError):
        normalize_path("")
    with pytest.raises(ValueError):
        normalize_path("bad\0path")


def test_is_desktop_path_accepts_root_and_nested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user = tmp_path / "Desktop"
    public = tmp_path / "PublicDesktop"
    user.mkdir()
    public.mkdir()
    monkeypatch.setattr("src.paths.desktop_roots", lambda: (user, public))

    assert is_desktop_path(user)
    assert is_desktop_path(user / "folder" / "x.txt")
    assert is_desktop_path(public / "shortcut.lnk")


def test_is_desktop_path_rejects_prefix_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user = tmp_path / "Desktop"
    public = tmp_path / "PublicDesktop"
    user.mkdir()
    public.mkdir()
    monkeypatch.setattr("src.paths.desktop_roots", lambda: (user, public))

    assert not is_desktop_path(tmp_path / "Desktop-old" / "x.txt")
    assert not is_desktop_path(tmp_path / "Downloads" / "x.txt")
