#!/usr/bin/env python3
"""
One-time script to generate initial fuses.json from existing README.md
Run this locally to create the initial data file.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
README_FILE = REPO_ROOT / "README.md"
DATA_FILE = REPO_ROOT / "fuses.json"


@dataclass(frozen=True)
class FirmwareEntry:
    """A single firmware version entry."""

    version: str
    fuses_production: int | None
    system_title_nca: str
    exfat_title_nca: str

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert to JSON-serializable dict."""
        return {
            "version": self.version,
            "fuses_production": self.fuses_production,
            "system_title_nca": self.system_title_nca,
            "exfat_title_nca": self.exfat_title_nca,
        }


@dataclass(frozen=True)
class FuseNCAData:
    """Complete FuseNCA dataset with metadata."""

    format_version: str = "1.0"
    last_updated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sources: dict[str, str] = field(
        default_factory=lambda: {
            "switchbrew": "https://switchbrew.org/wiki/Fuses",
            "nxnandmanager": "https://raw.githubusercontent.com/impeeza/NxNandManager/master/NxNandManager/NxStorage.cpp",
        }
    )
    entries: list[FirmwareEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "$schema": "https://raw.githubusercontent.com/sthetix/FuseNCA/master/schema.json",
            "format_version": self.format_version,
            "last_updated": self.last_updated,
            "sources": self.sources,
            "data": [entry.to_dict() for entry in self.entries],
        }


def parse_readme() -> list[FirmwareEntry]:
    """Parse README.md table to extract firmware entries."""
    if not README_FILE.exists():
        print(f"Error: {README_FILE} not found")
        sys.exit(1)

    content = README_FILE.read_text()
    entries: list[FirmwareEntry] = []

    # Find the table section
    lines = content.split("\n")
    table_start_idx = -1

    for i, line in enumerate(lines):
        if "| Firmware |" in line or "| System Version |" in line:
            table_start_idx = i
            break

    if table_start_idx == -1:
        print("Error: Could not find table in README")
        sys.exit(1)

    # Skip header and separator, then read rows
    for line in lines[table_start_idx + 2:]:
        # End of table
        if not line.strip().startswith("|"):
            break

        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) >= 4:
            version = parts[0]
            fuse_str = parts[1]
            sys_nca = parts[2]
            exfat_nca = parts[3]

            # Skip header row (in case it wasn't caught)
            if version.lower() in ("firmware", "system version"):
                continue

            # Parse fuse count - handle both numeric and "-" values
            fuses: int | None = None
            if fuse_str and fuse_str != "-":
                try:
                    fuses = int(fuse_str)
                except ValueError:
                    pass

            entries.append(
                FirmwareEntry(
                    version=version,
                    fuses_production=fuses,
                    system_title_nca=sys_nca,
                    exfat_title_nca=exfat_nca,
                )
            )

    return entries


def main() -> int:
    """Generate initial fuses.json from README."""
    print("Parsing README.md...")
    entries = parse_readme()

    if not entries:
        print("Error: No entries found in README")
        return 1

    print(f"Found {len(entries)} firmware entries")

    data = FuseNCAData(entries=entries)

    # Write JSON
    output = json.dumps(
        data.to_dict(),
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
    )

    DATA_FILE.write_text(output + "\n")
    print(f"Created {DATA_FILE}")

    # Pretty print summary
    print("\nEntry summary:")
    for entry in entries[:5]:
        print(f"  {entry.version}: fuses={entry.fuses_production}")
    if len(entries) > 5:
        print(f"  ... and {len(entries) - 5} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
