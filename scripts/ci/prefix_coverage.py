#!/usr/bin/env python3
"""Makes a service's coverage.xml readable by SonarQube, which runs once at the repository root.

    scripts/ci/prefix_coverage.py services/fee/coverage.xml services/fee/app

coverage.py writes file names relative to the measured source folder (app/), for example
"api/payments.py". SonarQube resolves them against the repository root, where that file does not exist. This
rewrites every name to "services/fee/app/api/payments.py" and removes the machine-specific <source> folders.
"""

import sys
import xml.etree.ElementTree as ET


def prefix(xml_path: str, prefix_dir: str) -> int:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    prefix_dir = prefix_dir.strip("/")
    count = 0
    for element in root.iter("class"):
        name = element.get("filename")
        if name and not name.startswith(prefix_dir + "/"):
            element.set("filename", f"{prefix_dir}/{name}")
            count += 1
    for sources in root.findall("sources"):
        root.remove(sources)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return count


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(f"rewrote {prefix(sys.argv[1], sys.argv[2])} file names in {sys.argv[1]}")
