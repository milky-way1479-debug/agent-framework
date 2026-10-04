"""Metadata-only intake. No import, install, script, build hook, or outbound read."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .policy import GovernanceError, canonical


@dataclass(frozen=True)
class SkillInventory:
    status: str
    tree_digest: str
    files: tuple[str, ...]
    required_review: tuple[str, ...]


def inspect_quarantined_skill(
    directory: Path, *, max_files: int = 100, max_bytes: int = 1_000_000
) -> SkillInventory:
    """Hash a local quarantined tree. Inventory does not mean approved or safe."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise GovernanceError("A real isolated directory is required")
    root = directory.resolve()
    entries, total = [], 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GovernanceError("Symlinks are not accepted during quarantine intake")
        if path.is_file():
            if not path.resolve().is_relative_to(root) or len(entries) >= max_files:
                raise GovernanceError("Quarantine boundary or file count exceeded")
            size = path.stat().st_size
            total += size
            if total > max_bytes:
                raise GovernanceError("Quarantine size bound exceeded")
            entries.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return SkillInventory(
        "UNREVIEWED",
        hashlib.sha256(canonical(entries).encode()).hexdigest(),
        tuple(name for name, _ in entries),
        (
            "owner decision",
            "source and license",
            "dependencies and install hooks",
            "code and outbound destinations",
            "data handling",
            "required permissions",
            "isolated tests",
            "version pinning",
        ),
    )
