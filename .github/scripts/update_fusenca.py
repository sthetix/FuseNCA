#!/usr/bin/env python3
"""
FuseNCA Update Script

Updates fuses.json (source of truth) and generates README.md from it.
Data sources:
- AutoFW webhook: New firmware version and NCA hashes (from Nintendo CDN)
- Switchbrew.org: Anti-downgrade fuse counts
- fuses.json: Historical data storage
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Constants
SWITCHBREW_URL = "https://switchbrew.org/wiki/Fuses"
DEFAULT_REPO_OWNER = "sthetix"
DEFAULT_REPO_NAME = "FuseNCA"
DEFAULT_BRANCH = "master"

# File paths
REPO_ROOT = Path(__file__).parent.parent.parent
DATA_FILE = REPO_ROOT / "fuses.json"
README_FILE = REPO_ROOT / "README.md"


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

    @classmethod
    def from_dict(cls, data: dict[str, str | int | None]) -> FirmwareEntry:
        """Create from dict."""
        return cls(
            version=str(data["version"]),
            fuses_production=int(data["fuses_production"]) if data.get("fuses_production") else None,
            system_title_nca=str(data.get("system_title_nca", "")),
            exfat_title_nca=str(data.get("exfat_title_nca", "")),
        )


@dataclass(frozen=True)
class FuseNCAData:
    """Complete FuseNCA dataset with metadata."""

    format_version: str = "1.0"
    last_updated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sources: dict[str, str] = field(
        default_factory=lambda: {
            "switchbrew": SWITCHBREW_URL,
        }
    )
    entries: list[FirmwareEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "$schema": f"https://raw.githubusercontent.com/{DEFAULT_REPO_OWNER}/{DEFAULT_REPO_NAME}/{DEFAULT_BRANCH}/schema.json",
            "format_version": self.format_version,
            "last_updated": self.last_updated,
            "sources": self.sources,
            "data": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FuseNCAData:
        """Create from dict."""
        return cls(
            format_version=str(data.get("format_version", "1.0")),
            last_updated=str(data.get("last_updated", "")),
            sources=dict(data.get("sources", {})),
            entries=[FirmwareEntry.from_dict(e) for e in data.get("data", [])],
        )

    def get_entry(self, version: str) -> FirmwareEntry | None:
        """Get entry by version."""
        for entry in self.entries:
            if entry.version == version:
                return entry
        return None

    def add_or_update_entry(self, entry: FirmwareEntry) -> FuseNCAData:
        """Add new entry or update existing one."""
        new_entries = [e for e in self.entries if e.version != entry.version]
        new_entries.append(entry)
        return dataclasses.replace(self, entries=new_entries)

    def sorted_entries(self) -> list[FirmwareEntry]:
        """Get entries sorted by version (descending)."""
        return sorted(self.entries, key=_version_key, reverse=True)


def _version_key(entry: FirmwareEntry | str) -> tuple[int, int, int, int]:
    """Sort key for version strings."""
    version = entry if isinstance(entry, str) else entry.version
    parts = version.split(".")
    # Handle up to 4 version parts (e.g., "1.0.0.0")
    return tuple(int(p) for p in parts + [0] * (4 - len(parts)))


def fetch_switchbrew_fuses() -> dict[str, int]:
    """Fetch and parse fuse data from Switchbrew wiki.

    Returns:
        Mapping of version range to fuse count.
    """
    try:
        import requests

        response = requests.get(SWITCHBREW_URL, timeout=10)
        response.raise_for_status()
        content = response.text
    except ImportError as e:
        _print_error("requests module not installed")
        sys.exit(1)
    except Exception as e:
        _print_error(f"fetching Switchbrew: {e}")
        return {}

    # Extract the Anti-downgrade table - handle multiple formats
    # Try pattern 1: "System version" header
    table_match = re.search(
        r"\| System version.*?\n(?:\|[^\n]*\n)*?((?:\|[\s\d.\-]+?\|[\s\d.]+?\|[\s\d.]+?\|\n)+)",
        content,
    )

    # Try pattern 2: "System Version" header (capital V)
    if not table_match:
        table_match = re.search(
            r"\| System Version.*?\n(?:\|[^\n]*\n)*?((?:\|[\s\d.\-]+?\|[\s\d.]+?\|[\s\d.]+?\|\n)+)",
            content,
        )

    if not table_match:
        _print_error("finding Anti-downgrade table on Switchbrew")
        return {}

    fuse_map: dict[str, int] = {}

    for line in table_match.group(0).split("\n"):
        if "|" not in line or "---" in line or "System version" in line.lower():
            continue

        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) >= 2:
            version_range = parts[0]
            prod_fuses = parts[1]
            try:
                fuse_count = int(prod_fuses)
                fuse_map[version_range] = fuse_count
            except ValueError:
                pass

    return fuse_map


def get_fuse_count_for_version(
    fuse_map: dict[str, int],
    version: str,
) -> int | None:
    """Get fuse count for a specific version from the range map.

    Args:
        fuse_map: Mapping of version ranges to fuse counts.
        version: Version string to look up.

    Returns:
        Fuse count or None if not found.
    """
    # Direct match
    if version in fuse_map:
        return fuse_map[version]

    # Check ranges
    for range_key, count in fuse_map.items():
        if "-" in range_key:
            start, end = range_key.split("-")
            if _version_in_range(version, start, end):
                return count

    return None


def _version_in_range(version: str, start: str, end: str) -> bool:
    """Check if version falls within start-end range."""
    v_parts = _version_key(version)
    s_parts = _version_key(start)
    e_parts = _version_key(end)
    return s_parts <= v_parts <= e_parts


def read_current_data() -> FuseNCAData:
    """Read current fuses.json data.

    Returns:
        Current data or empty dataset if file doesn't exist.
    """
    if not DATA_FILE.exists():
        return FuseNCAData()

    try:
        content = DATA_FILE.read_text()
        data = json.loads(content)
        return FuseNCAData.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        _print_error(f"parsing fuses.json: {e}")
        return FuseNCAData()


def write_data(data: FuseNCAData) -> None:
    """Write data to fuses.json with formatting.

    Args:
        data: The dataset to write.
    """
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    output = json.dumps(
        data.to_dict(),
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
    )

    DATA_FILE.write_text(output + "\n")


def generate_readme(data: FuseNCAData) -> str:
    """Generate README.md content from FuseNCA data.

    Args:
        data: The dataset to generate from.

    Returns:
        Complete README markdown content.
    """
    lines = [
        "# FuseNCA",
        "",
        "Nintendo Switch system title NCA references and anti-downgrade fuse information.",
        "",
        "## Data Access",
        "",
        "- **JSON API**: `fuses.json` - Machine-readable data (recommended for automation)",
        "- **Raw URL**: https://raw.githubusercontent.com/sthetix/FuseNCA/master/fuses.json",
        "- **README**: Human-readable table (below)",
        "",
        "## System Firmware Reference",
        "",
        f"Combined data from Switchbrew (anti-downgrade fuses) and AutoFW (system title NCAs from Nintendo CDN).",
        "",
        "| Firmware | Fuses (Prod) | System Title NCA | exFAT Title NCA |",
        "| --- | --- | --- | --- |",
    ]

    for entry in data.sorted_entries():
        fuse_str = str(entry.fuses_production) if entry.fuses_production is not None else "-"
        sys_nca = entry.system_title_nca or "-"
        exfat_nca = entry.exfat_title_nca or "-"
        lines.append(f"| {entry.version} | {fuse_str} | {sys_nca} | {exfat_nca} |")

    lines.extend([
        "",
        "## Sources",
        "",
        f"- Anti-downgrade fuses: [Switchbrew - Fuses]({SWITCHBREW_URL})",
        f"- System title NCAs: AutoFW (fetched from Nintendo CDN)",
        "",
        "## Auto-Update",
        "",
        "This repository is automatically updated when new firmware data is detected.",
        "",
        f"Last updated: {data.last_updated}",
    ])

    return "\n".join(lines)


def write_readme(content: str) -> None:
    """Write content to README.md.

    Args:
        content: The README content.
    """
    README_FILE.write_text(content)


def _print_error(message: str) -> None:
    """Print error message to stderr.

    Args:
        message: Error message to print.
    """
    print(f"Error: {message}", file=sys.stderr)


def load_new_firmware_from_env() -> dict[str, str] | None:
    """Load new firmware data from environment variables.

    Environment variables (set by GitHub Action):
        PAYLOAD_VERSION: Firmware version
        PAYLOAD_NCA_FAT: System title NCA (FAT32)
        PAYLOAD_NCA_EXFAT: exFAT title NCA

    Returns:
        Dict with keys: version, nca_fat, nca_exfat or None if no payload.
    """
    version = os.environ.get("PAYLOAD_VERSION", "").strip()
    nca_fat = os.environ.get("PAYLOAD_NCA_FAT", "").strip()
    nca_exfat = os.environ.get("PAYLOAD_NCA_EXFAT", "").strip()

    if not version:
        return None

    return {
        "version": version,
        "nca_fat": nca_fat,
        "nca_exfat": nca_exfat,
    }


def create_marker_file() -> None:
    """Create marker file to signal changes to GitHub Action."""
    marker_path = REPO_ROOT / ".github" / "has_changes"
    marker_path.write_text("changes_detected")


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    # Check for new firmware payload
    new_fw = load_new_firmware_from_env()

    if new_fw:
        print(f"Processing firmware update: {new_fw['version']}")
        print(f"  FAT NCA: {new_fw['nca_fat']}")
        print(f"  exFAT NCA: {new_fw['nca_exfat']}")

    # Fetch data from external sources
    print("Fetching data from Switchbrew...")
    fuse_map = fetch_switchbrew_fuses()

    if not fuse_map:
        print("Warning: Could not fetch Switchbrew data, will preserve existing fuses")

    # Load current data (source of truth for historical NCA data)
    current_data = read_current_data()
    print(f"Current entries in fuses.json: {len(current_data.entries)}")

    # Build updated data
    updated_data = dataclasses.replace(current_data, last_updated=datetime.now(UTC).isoformat())

    # Update all entries with fresh fuse counts from Switchbrew
    for entry in current_data.entries:
        fuse_count = get_fuse_count_for_version(fuse_map, entry.version)

        # If Switchbrew fetch failed, preserve existing fuse count
        if fuse_count is None and entry.fuses_production is not None:
            fuse_count = entry.fuses_production

        updated_entry = FirmwareEntry(
            version=entry.version,
            fuses_production=fuse_count,
            system_title_nca=entry.system_title_nca,
            exfat_title_nca=entry.exfat_title_nca,
        )
        updated_data = updated_data.add_or_update_entry(updated_entry)

    # Add or update new firmware from AutoFW webhook
    if new_fw:
        fuse_count = get_fuse_count_for_version(fuse_map, new_fw["version"])

        new_entry = FirmwareEntry(
            version=new_fw["version"],
            fuses_production=fuse_count,
            system_title_nca=new_fw["nca_fat"],
            exfat_title_nca=new_fw["nca_exfat"],
        )
        updated_data = updated_data.add_or_update_entry(new_entry)
        print(f"Added/updated firmware {new_fw['version']}")

    # Write JSON (source of truth)
    write_data(updated_data)
    print(f"Updated fuses.json with {len(updated_data.entries)} entries")

    # Generate and write README
    readme_content = generate_readme(updated_data)

    # Check if README actually changed (read BEFORE writing)
    if README_FILE.exists():
        current_readme = README_FILE.read_text()
        if readme_content.strip() != current_readme.strip():
            write_readme(readme_content)
            print("Generated README.md from fuses.json")
            create_marker_file()
            print("Changes detected - marker file created")
        else:
            print("No changes to README.md")
    else:
        write_readme(readme_content)
        print("Generated README.md from fuses.json")
        create_marker_file()
        print("Changes detected - marker file created")

    return 0


if __name__ == "__main__":
    sys.exit(main())
