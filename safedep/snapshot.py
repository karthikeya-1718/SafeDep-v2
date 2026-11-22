"""SafeDep Snapshot Module.

Provides immutable, hash-verified directory snapshots and atomic restorations
under `<project_root>/.safedep/snapshots/`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Union


@dataclass
class SnapshotManifestEntry:
    """Entry in snapshot manifest for a single tracked file."""

    relative_path: str
    existed: bool
    sha256: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "existed": self.existed,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotManifestEntry:
        return cls(
            relative_path=data["relative_path"],
            existed=data["existed"],
            sha256=data.get("sha256"),
        )


@dataclass
class Snapshot:
    """Represents a recorded snapshot."""

    snapshot_id: str
    label: str
    created_at: str
    project_root: Path
    snapshot_dir: Path
    entries: list[SnapshotManifestEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "label": self.label,
            "created_at": self.created_at,
            "entries": [e.to_dict() for e in self.entries],
        }


def _compute_sha256(data: bytes) -> str:
    """Compute hex sha256 checksum of bytes."""
    return hashlib.sha256(data).hexdigest()


def _sanitize_label(label: str) -> str:
    """Sanitize label for use in folder names."""
    clean = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in label)
    return clean.strip("_") or "snapshot"


def create_snapshot(
    project_root: Union[str, Path],
    files: Iterable[Union[str, Path]],
    label: str = "default",
) -> Snapshot:
    """Save copies of files under <project_root>/.safedep/snapshots/<UTC timestamp>-<label>/.

    Args:
        project_root: Root path of the project.
        files: List or iterable of file paths (absolute or relative to project_root).
        label: Semantic label for this snapshot.

    Returns:
        Snapshot object with snapshot_id, label, timestamp, and manifest.
    """
    root = Path(project_root).resolve()
    clean_label = _sanitize_label(label)
    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = f"{ts_str}-{clean_label}"

    snap_dir = root / ".safedep" / "snapshots" / snapshot_id
    files_storage_dir = snap_dir / "files"
    files_storage_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[SnapshotManifestEntry] = []

    for item in files:
        fpath = Path(item)
        if not fpath.is_absolute():
            fpath = (root / fpath).resolve()
        else:
            fpath = fpath.resolve()

        try:
            rel_path = fpath.relative_to(root).as_posix()
        except ValueError:
            rel_path = fpath.name

        if fpath.is_file():
            content = fpath.read_bytes()
            csum = _compute_sha256(content)
            dest = files_storage_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

            manifest_entries.append(
                SnapshotManifestEntry(
                    relative_path=rel_path,
                    existed=True,
                    sha256=csum,
                )
            )
        else:
            manifest_entries.append(
                SnapshotManifestEntry(
                    relative_path=rel_path,
                    existed=False,
                    sha256=None,
                )
            )

    manifest_data = {
        "snapshot_id": snapshot_id,
        "label": label,
        "created_at": now_utc.isoformat(),
        "entries": [e.to_dict() for e in manifest_entries],
    }

    manifest_path = snap_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    return Snapshot(
        snapshot_id=snapshot_id,
        label=label,
        created_at=now_utc.isoformat(),
        project_root=root,
        snapshot_dir=snap_dir,
        entries=manifest_entries,
    )


def restore_snapshot(
    project_root: Union[str, Path],
    snapshot_id: str,
) -> list[str]:
    """Restore files from a snapshot back into the project.

    Restores exact bytes, deletes files that did not exist when the snapshot
    was taken, verifies sha256 checksums, and raises ValueError if any stored
    copy has been tampered with.

    Args:
        project_root: Project root path.
        snapshot_id: Identifier of the snapshot to restore.

    Returns:
        List of restored file paths.

    Raises:
        FileNotFoundError: If snapshot or manifest does not exist.
        ValueError: If stored file checksum does not match manifest.
    """
    root = Path(project_root).resolve()
    snap_dir = root / ".safedep" / "snapshots" / snapshot_id
    if not snap_dir.is_dir():
        raise FileNotFoundError(f"Snapshot directory not found: {snap_dir}")

    manifest_path = snap_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found in snapshot: {manifest_path}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [SnapshotManifestEntry.from_dict(d) for d in manifest_data.get("entries", [])]
    files_storage_dir = snap_dir / "files"

    restored_paths: list[str] = []

    # First verify all stored copies for integrity (fail before making any partial changes)
    for entry in entries:
        if entry.existed:
            stored_file = files_storage_dir / entry.relative_path
            if not stored_file.is_file():
                raise ValueError(
                    f"Stored snapshot copy missing for '{entry.relative_path}' in snapshot {snapshot_id}"
                )
            data = stored_file.read_bytes()
            actual_hash = _compute_sha256(data)
            if actual_hash != entry.sha256:
                raise ValueError(
                    f"Hash mismatch / tamper detected for '{entry.relative_path}' in snapshot {snapshot_id}: "
                    f"expected {entry.sha256}, got {actual_hash}"
                )

    # Now apply restorations
    for entry in entries:
        target_path = (root / entry.relative_path).resolve()
        if entry.existed:
            stored_file = files_storage_dir / entry.relative_path
            data = stored_file.read_bytes()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(data)
            restored_paths.append(str(target_path))
        else:
            # File did not exist when snapshot was taken -> delete if present
            if target_path.exists():
                if target_path.is_file() or target_path.is_symlink():
                    target_path.unlink()
                elif target_path.is_dir():
                    shutil.rmtree(target_path)
            restored_paths.append(str(target_path))

    return restored_paths


def list_snapshots(project_root: Union[str, Path]) -> list[Snapshot]:
    """List all recorded snapshots for a project in chronological order.

    Args:
        project_root: Project root path.

    Returns:
        List of Snapshot objects.
    """
    root = Path(project_root).resolve()
    base_dir = root / ".safedep" / "snapshots"
    if not base_dir.is_dir():
        return []

    results: list[Snapshot] = []
    for snap_dir in sorted(base_dir.iterdir()):
        if not snap_dir.is_dir():
            continue
        manifest_path = snap_dir / "manifest.json"
        if not manifest_path.is_file():
            continue

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = [SnapshotManifestEntry.from_dict(d) for d in data.get("entries", [])]
            results.append(
                Snapshot(
                    snapshot_id=data.get("snapshot_id", snap_dir.name),
                    label=data.get("label", ""),
                    created_at=data.get("created_at", ""),
                    project_root=root,
                    snapshot_dir=snap_dir,
                    entries=entries,
                )
            )
        except Exception:
            continue

    return results
