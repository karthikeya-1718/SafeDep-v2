"""Unit tests for safedep.snapshot."""

import pytest
from pathlib import Path

from safedep.snapshot import create_snapshot, restore_snapshot, list_snapshots


def test_snapshot_modify_restore_byte_identical(tmp_path: Path):
    """Snapshot then modify then restore gives byte-identical files."""
    file1 = tmp_path / "app.py"
    file2 = tmp_path / "sub" / "config.txt"
    file2.parent.mkdir(parents=True, exist_ok=True)

    file1.write_text("print('version 1')\n", encoding="utf-8")
    file2.write_text("DEBUG=True\nPORT=8080\n", encoding="utf-8")

    orig1 = file1.read_bytes()
    orig2 = file2.read_bytes()

    # Create snapshot
    snap = create_snapshot(tmp_path, [file1, file2], label="test_initial")
    assert snap.snapshot_id
    assert snap.label == "test_initial"

    # Modify both files
    file1.write_text("print('version 2 modified')\n", encoding="utf-8")
    file2.write_text("DEBUG=False\nPORT=9000\nEXTRA=1\n", encoding="utf-8")

    assert file1.read_bytes() != orig1
    assert file2.read_bytes() != orig2

    # Restore snapshot
    restored = restore_snapshot(tmp_path, snap.snapshot_id)
    assert len(restored) == 2

    # Verify byte-identical
    assert file1.read_bytes() == orig1
    assert file2.read_bytes() == orig2


def test_file_not_existing_before_is_deleted_on_restore(tmp_path: Path):
    """A file that did not exist when the snapshot was taken is deleted on restore."""
    existing_file = tmp_path / "main.py"
    existing_file.write_text("initial code\n", encoding="utf-8")

    non_existing_file = tmp_path / "generated.py"
    # Ensure it doesn't exist yet

    snap = create_snapshot(tmp_path, [existing_file, non_existing_file], label="before_gen")

    # Now create the file
    non_existing_file.write_text("generated dynamically\n", encoding="utf-8")
    assert non_existing_file.exists()

    # Also modify existing
    existing_file.write_text("mutated code\n", encoding="utf-8")

    # Restore
    restore_snapshot(tmp_path, snap.snapshot_id)

    assert existing_file.read_text(encoding="utf-8") == "initial code\n"
    assert not non_existing_file.exists()


def test_restore_raises_when_stored_copy_edited(tmp_path: Path):
    """Restore raises when a stored snapshot copy was tampered with (hash mismatch)."""
    target = tmp_path / "service.py"
    target.write_text("original content\n", encoding="utf-8")

    snap = create_snapshot(tmp_path, [target], label="tamper_test")

    # Tamper with the snapshot storage directly
    snap_dir = tmp_path / ".safedep" / "snapshots" / snap.snapshot_id
    stored_copy = snap_dir / "files" / "service.py"
    assert stored_copy.exists()
    stored_copy.write_text("tampered content\n", encoding="utf-8")

    # Target modified
    target.write_text("new content\n", encoding="utf-8")

    # Attempt restore -> must raise ValueError / RuntimeError
    with pytest.raises((ValueError, RuntimeError), match="[Hh]ash mismatch|tamper"):
        restore_snapshot(tmp_path, snap.snapshot_id)


def test_list_snapshots(tmp_path: Path):
    """list_snapshots returns all recorded snapshots in order."""
    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")

    snap1 = create_snapshot(tmp_path, [f], label="first")
    snap2 = create_snapshot(tmp_path, [f], label="second")

    snapshots = list_snapshots(tmp_path)
    snap_ids = [s.snapshot_id for s in snapshots]
    assert snap1.snapshot_id in snap_ids
    assert snap2.snapshot_id in snap_ids
