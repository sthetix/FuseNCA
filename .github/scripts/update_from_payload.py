#!/usr/bin/env python3
"""
Update FuseNCA README with firmware data from AutoFW webhook payload.
Receives version, NCA FAT, and NCA exFAT from repository_dispatch event.
"""

import os
import re
import sys
from pathlib import Path


def fetch_switchbrew_fuses():
    """Fetch and parse fuse data from Switchbrew wiki."""
    try:
        import requests
        response = requests.get("https://switchbrew.org/wiki/Fuses", timeout=10)
        response.raise_for_status()
        content = response.text
    except Exception as e:
        print(f"Error fetching Switchbrew: {e}")
        return None

    # Extract the Anti-downgrade table
    table_match = re.search(
        r'\| System version.*?\n(?:\|[^\n]*\n)*?((?:\|[\s\d.]+?\|[\s\d.]+?\|[\s\d.]+?\|\n)+)',
        content
    )

    if not table_match:
        print("Could not find Anti-downgrade table on Switchbrew")
        return None

    # Build version to fuse count mapping
    fuse_map = {}
    for line in table_match.group(0).split('\n'):
        if '|' not in line or '---' in line or 'System version' in line:
            continue
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if len(parts) >= 2:
            version_range = parts[0]
            prod_fuses = parts[1]
            try:
                fuse_count = int(prod_fuses)
                fuse_map[version_range] = fuse_count
            except ValueError:
                pass

    return fuse_map


def fetch_nxnandmanager_titles():
    """Fetch and parse title data from NxNandManager."""
    try:
        import requests
        url = "https://raw.githubusercontent.com/impeeza/NxNandManager/master/NxNandManager/NxStorage.cpp"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        content = response.text
    except Exception as e:
        print(f"Error fetching NxNandManager: {e}")
        return None, None

    # Parse systemTitlesArr
    system_titles = {}
    pattern = r'\{\s*"([^"]+)",\s*"([^"]+\.nca)"\s*\}'

    sys_arr_match = re.search(r'static NxSystemTitles systemTitlesArr\[\]\s*=\s*\{(.*?)\};', content, re.DOTALL)
    if sys_arr_match:
        arr_content = sys_arr_match.group(1)
        for match in re.finditer(pattern, arr_content):
            version, nca = match.groups()
            system_titles[version] = nca

    # Parse exFatTitlesArr
    exfat_titles = {}
    ex_arr_match = re.search(r'static NxSystemTitles exFatTitlesArr\[\]\s*=\s*\{(.*?)\};', content, re.DOTALL)
    if ex_arr_match:
        arr_content = ex_arr_match.group(1)
        for match in re.finditer(pattern, arr_content):
            version, nca = match.groups()
            exfat_titles[version] = nca

    return system_titles, exfat_titles


def get_fuse_count_for_version(fuse_map, version):
    """Get fuse count for a specific version from the range map."""
    # Direct match
    if version in fuse_map:
        return fuse_map[version]

    # Check ranges
    for range_key, count in fuse_map.items():
        if '-' in range_key:
            start, end = range_key.split('-')
            if version_in_range(version, start, end):
                return count

    return None


def version_in_range(version, start, end):
    """Check if version falls within start-end range."""
    v_parts = [int(x) for x in version.split('.')]
    s_parts = [int(x) for x in start.split('.')]
    e_parts = [int(x) for x in end.split('.')]

    return s_parts <= v_parts <= e_parts


def version_key(v):
    """Sort key for version strings."""
    parts = v.split('.')
    return [int(x) for x in parts]


def read_current_readme():
    """Read current README content."""
    readme_path = Path(__file__).parent.parent.parent / "README.md"
    if readme_path.exists():
        return readme_path.read_text()
    return ""


def generate_readme_table(fuse_map, system_titles, exfat_titles, new_firmware_data):
    """
    Generate the README markdown table.
    new_firmware_data is a dict with keys: version, nca_fat, nca_exfat
    """
    lines = [
        "# FuseNCA",
        "",
        "Nintendo Switch system title NCA references and anti-downgrade fuse information.",
        "",
        "## System Firmware Reference",
        "",
        "Combined data from Switchbrew (anti-downgrade fuses) and NxNandManager (system title NCAs).",
        "",
        "| Firmware | Fuses (Prod) | System Title NCA | exFAT Title NCA |",
        "| --- | --- | --- | --- |"
    ]

    # Get all unique versions from both sources, sorted in descending order
    all_versions = set(system_titles.keys()) | set(exfat_titles.keys())

    # Add new firmware from AutoFW if not already present
    if new_firmware_data.get('version'):
        all_versions.add(new_firmware_data['version'])

    sorted_versions = sorted(all_versions, key=version_key, reverse=True)

    for version in sorted_versions:
        fuse_count = get_fuse_count_for_version(fuse_map, version)

        # Use AutoFW data if available for this version, otherwise use NxNandManager
        if version == new_firmware_data.get('version'):
            sys_nca = new_firmware_data.get('nca_fat', '')
            exfat_nca = new_firmware_data.get('nca_exfat', '')
        else:
            sys_nca = system_titles.get(version, "")
            exfat_nca = exfat_titles.get(version, "")

        fuse_str = str(fuse_count) if fuse_count is not None else "-"
        lines.append(f"| {version} | {fuse_str} | {sys_nca} | {exfat_nca} |")

    lines.extend([
        "",
        "## Sources",
        "",
        "- Anti-downgrade fuses: [Switchbrew - Fuses](https://switchbrew.org/wiki/Fuses)",
        "- System title NCAs: [NxNandManager - NxStorage.cpp](https://github.com/impeeza/NxNandManager/blob/master/NxNandManager/NxStorage.cpp)",
        "",
        "## Auto-Update",
        "",
        "This repository is automatically updated when new firmware data is detected.",
    ])

    return '\n'.join(lines)


def main():
    # Get firmware data from environment (set by GitHub Action)
    version = os.environ.get('PAYLOAD_VERSION', '')
    nca_fat = os.environ.get('PAYLOAD_NCA_FAT', '')
    nca_exfat = os.environ.get('PAYLOAD_NCA_EXFAT', '')

    if not version:
        print("No version payload found")
        sys.exit(0)

    print(f"Processing firmware update: {version}")
    print(f"  FAT NCA: {nca_fat}")
    print(f"  exFAT NCA: {nca_exfat}")

    new_firmware_data = {
        'version': version,
        'nca_fat': nca_fat,
        'nca_exfat': nca_exfat
    }

    # Fetch data from sources
    fuse_map = fetch_switchbrew_fuses()
    system_titles, exfat_titles = fetch_nxnandmanager_titles()

    if fuse_map is None:
        print("Warning: Could not fetch Switchbrew data")
        fuse_map = {}

    if system_titles is None or exfat_titles is None:
        print("Warning: Could not fetch NxNandManager data")
        system_titles = {}
        exfat_titles = {}

    # Generate new README content
    new_readme = generate_readme_table(fuse_map, system_titles, exfat_titles, new_firmware_data)

    # Compare with current README
    current_readme = read_current_readme()

    if new_readme.strip() != current_readme.strip():
        print("Changes detected! Updating README.md...")

        readme_path = Path(__file__).parent.parent.parent / "README.md"
        readme_path.write_text(new_readme)

        # Create marker file for GitHub Action
        marker_path = Path(__file__).parent.parent / "has_changes"
        marker_path.write_text("changes_detected")

        print("README.md updated successfully!")
        print(f"Total versions in table: {len(set(system_titles.keys()) | set(exfat_titles.keys()) | {version})}")
    else:
        print("No changes detected. README is up to date.")


if __name__ == "__main__":
    main()
