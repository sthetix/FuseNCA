#!/usr/bin/env python3
"""
FuseNCA - Auto-update script for anti-downgrade fuse table
Fetches data from https://switchbrew.org/wiki/Fuses
"""

import re
import sys
from pathlib import Path


def fetch_fuses_data():
    """Fetch and parse fuse data from Switchbrew wiki."""
    try:
        import requests
        response = requests.get("https://switchbrew.org/wiki/Fuses", timeout=10)
        response.raise_for_status()
        content = response.text
    except ImportError:
        print("Error: requests module not installed. Run: pip install requests")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching page: {e}")
        sys.exit(1)

    # Extract the Anti-downgrade table
    # Look for the table section after "Anti-downgrade" header
    anti_downgrade_match = re.search(
        r'Anti-downgrade.*?(?:System version.*?\n.*?\n.*?\n)((?:\|.*?\|.*?\|.*?\|\n)+)',
        content,
        re.DOTALL | re.IGNORECASE
    )

    if not anti_downgrade_match:
        print("Error: Could not find Anti-downgrade table")
        sys.exit(1)

    table_text = anti_downgrade_match.group(0)

    # Parse table rows
    fuses = []
    for line in table_text.split('\n'):
        if '|' not in line or line.strip().startswith('|---'):
            continue
        parts = [p.strip() for p in line.split('|')[1:-1]]  # Skip empty start/end
        if len(parts) >= 3 and parts[0] and parts[0] not in ['System version', 'System Version']:
            version = parts[0]
            prod = parts[1]
            dev = parts[2] if len(parts) > 2 else '1'
            fuses.append((version, prod, dev))

    return fuses


def generate_markdown_table(fuses):
    """Generate markdown table from fuse data."""
    lines = [
        "| System Version | Production Fuses | Development Fuses |",
        "| --- | --- | --- |"
    ]
    for version, prod, dev in fuses:
        lines.append(f"| {version} | {prod} | {dev} |")
    return '\n'.join(lines)


def update_readme(new_table):
    """Update the README.md with new table."""
    readme_path = Path(__file__).parent / "README.md"

    if not readme_path.exists():
        print(f"Error: {readme_path} not found")
        sys.exit(1)

    content = readme_path.read_text()

    # Replace existing table (between the table headers and the ## Notes section)
    pattern = r'\| System Version.*?\n(?:\|.*?\|.*?\|.*?\|\n)+'
    new_content = re.sub(pattern, new_table + '\n', content, count=1)

    readme_path.write_text(new_content)
    print(f"Updated {readme_path}")


def main():
    print("Fetching fuse data from Switchbrew...")
    fuses = fetch_fuses_data()

    if not fuses:
        print("Error: No fuse data found")
        sys.exit(1)

    print(f"Found {len(fuses)} firmware versions")

    new_table = generate_markdown_table(fuses)
    update_readme(new_table)

    print("\nCurrent table:")
    print(new_table)
    print("\nDone!")


if __name__ == "__main__":
    main()
