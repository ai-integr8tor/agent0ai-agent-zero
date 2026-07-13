from __future__ import annotations

"""Contention detection and resolution engine for Time Travel.

Provides category-based protection and cross-chat conflict detection
when restoring snapshots in a multi-chat environment.

Design principles:
- Protect by default: system/platform files require explicit confirmation
- Detect, don't prevent: warn about contention but allow override for user data
- Zero overhead on happy path: check only at restore time
- Additive only: new metadata is optional; missing = legacy behavior
"""

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileRiskCategory(Enum):
    SYSTEM = "system"        # CRITICAL: settings.json, secrets, docker configs
    PLATFORM = "platform"    # HIGH: promptincludes, agent profiles, skills
    USER_DATA = "user_data"  # MEDIUM: workdir files, reports
    TEMP = "temp"            # LOW: logs, cache, temp outputs


@dataclass
class FileOwnershipRecord:
    """Tracks when a file was last modified by which chat."""
    workspace_id: str
    context_id: str
    last_modified: float
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileOwnershipRecord:
        return cls(**data)


@dataclass
class ContentionReport:
    """Result of a contention check before restore."""
    is_safe: bool
    conflicts: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    system_files_affected: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "conflicts": self.conflicts,
            "warnings": self.warnings,
            "system_files_affected": self.system_files_affected,
        }


class FileCategoryScanner:
    """Categorizes files by risk level based on path patterns."""

    SYSTEM_PATTERNS = [
        "settings.json",
        "secrets.env",
        "docker-compose.yml",
        "docker-compose",
        "config.json",
        "model_providers.yaml",
        ".env",
        "secrets",
        "credentials",
        ".a0proj/",
    ]

    PLATFORM_PATTERNS = [
        "promptincludes/",
        ".promptinclude.md",
        "agents/",
        "skills/",
        "/prompts/",
        "plugins/_",
        "agent.system.",
    ]

    TEMP_PATTERNS = [
        "/tmp/",
        ".cache/",
        "logs/",
        "__pycache__",
        ".git/",
        "node_modules/",
        ".log",
        ".time_travel/",
    ]

    @classmethod
    def categorize(cls, file_path: str) -> FileRiskCategory:
        """Categorize a file by its path."""
        path_lower = file_path.lower()

        for pat in cls.SYSTEM_PATTERNS:
            if pat.lower() in path_lower:
                return FileRiskCategory.SYSTEM

        for pat in cls.PLATFORM_PATTERNS:
            if pat.lower() in path_lower:
                return FileRiskCategory.PLATFORM

        for pat in cls.TEMP_PATTERNS:
            if pat.lower() in path_lower:
                return FileRiskCategory.TEMP

        return FileRiskCategory.USER_DATA


class ContentionEngine:
    """Detects and handles file contention across chat workspaces.

    Tracks which chat last modified each file and warns when a restore
    would overwrite changes made by another chat.
    """

    def __init__(self, workspace_real_path: Path):
        self.workspace_path = workspace_real_path
        self.meta_dir = workspace_real_path / ".agent-zero" / "time-travel-meta"
        self.ownership_file = self.meta_dir / "file-ownership.json"
        self._ownership_cache: Optional[Dict[str, FileOwnershipRecord]] = None

    def _ensure_meta_dir(self) -> None:
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def _load_ownership(self) -> Dict[str, FileOwnershipRecord]:
        if self._ownership_cache is not None:
            return self._ownership_cache

        if not self.ownership_file.exists():
            return {}

        try:
            with open(self.ownership_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._ownership_cache = {
                path: FileOwnershipRecord.from_dict(record)
                for path, record in data.items()
            }
            return self._ownership_cache
        except (json.JSONDecodeError, KeyError, TypeError):
            return {}

    def _save_ownership(self, ownership: Dict[str, FileOwnershipRecord]) -> None:
        self._ensure_meta_dir()
        temp_file = self.ownership_file.with_suffix(".tmp")

        data = {path: record.to_dict() for path, record in ownership.items()}

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        os.replace(temp_file, self.ownership_file)
        self._ownership_cache = ownership.copy()

    def _get_content_hash(self, file_path: str) -> str:
        full_path = self.workspace_path / file_path
        try:
            with open(full_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        except (IOError, OSError):
            return "MISSING"

    def update_ownership(
        self,
        workspace_id: str,
        context_id: str,
        files_changed: list[str],
    ) -> None:
        """Record that this chat now owns these files. Called after snapshot or restore."""
        ownership = self._load_ownership()
        timestamp = time.time()

        for file_path in files_changed:
            ownership[file_path] = FileOwnershipRecord(
                workspace_id=workspace_id,
                context_id=context_id,
                last_modified=timestamp,
                content_hash=self._get_content_hash(file_path),
            )

        self._save_ownership(ownership)

    def check_contention(
        self,
        workspace_id: str,
        files_to_restore: list[str],
        source_snapshot_timestamp: str,
    ) -> ContentionReport:
        """Check if restoring these files would create conflicts.

        Conflict rules:
        1. Another chat modified a file AFTER this snapshot → CONFLICT
        2. System/platform files in restore set → WARNING (requires confirmation)
        3. Current file hash differs from recorded → CONFLICT
        """
        ownership = self._load_ownership()

        try:
            source_time = float(source_snapshot_timestamp.rstrip("Z+").split("+")[0].replace("T", " ").split(".")[0])
        except (ValueError, AttributeError):
            source_time = 0.0

        conflicts: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        system_files: list[str] = []

        for file_path in files_to_restore:
            category = FileCategoryScanner.categorize(file_path)

            if category in (FileRiskCategory.SYSTEM, FileRiskCategory.PLATFORM):
                system_files.append(file_path)
                warnings.append({
                    "file": file_path,
                    "category": category.value,
                    "reason": f"{category.value.upper()} file requires confirmation",
                })

            if file_path in ownership:
                record = ownership[file_path]

                if record.workspace_id == workspace_id:
                    continue

                if record.last_modified > source_time:
                    current_hash = self._get_content_hash(file_path)
                    conflicts.append({
                        "file": file_path,
                        "other_workspace": record.workspace_id,
                        "other_context_id": record.context_id,
                        "their_timestamp": record.last_modified,
                        "snapshot_timestamp": source_time,
                        "current_hash": current_hash,
                        "their_hash": record.content_hash,
                        "category": category.value,
                        "resolution": (
                            "modified_by_other_chat"
                            if current_hash != record.content_hash
                            else "touched_by_other_chat"
                        ),
                    })

        is_safe = len(conflicts) == 0 and len(system_files) == 0

        return ContentionReport(
            is_safe=is_safe,
            conflicts=conflicts,
            warnings=warnings,
            system_files_affected=system_files,
        )

    def generate_restore_summary(
        self,
        report: ContentionReport,
        files_to_restore: list[str],
    ) -> str:
        """Generate human-readable summary of the contention check."""
        lines = ["=== Time Travel Contention Report ===\n"]
        lines.append(f"Files to restore: {len(files_to_restore)}\n")

        if report.system_files_affected:
            lines.append("\n** SYSTEM/PLATFORM FILES IN RESTORE SET **\n")
            for f in report.system_files_affected:
                lines.append(f"  - {f}\n")

        if report.conflicts:
            lines.append(f"\n** DETECTED CONFLICTS ({len(report.conflicts)}) **\n")
            for c in report.conflicts:
                lines.append(f"  File: {c['file']}\n")
                lines.append(f"  Modified by: {c['other_context_id']}\n")
                lines.append(f"  Category: {c['category']}\n")

        if report.warnings:
            lines.append(f"\n** WARNINGS ({len(report.warnings)}) **\n")
            for w in report.warnings:
                lines.append(f"  [{w['category'].upper()}] {w['file']}\n")

        if report.is_safe:
            lines.append("\nNo conflicts detected. Safe to restore.\n")
        else:
            lines.append("\nRestoration requires explicit confirmation.\n")

        return "".join(lines)
