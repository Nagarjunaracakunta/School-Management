#!/usr/bin/env python3
"""Checks the provider lock files (.terraform.lock.hcl) of every Terraform directory.

Rules:
  1. Wherever a provider appears, its entry (version, constraints, hashes) is IDENTICAL to environments/dev's entry,
     so the laptop, CI and every module test use the exact same provider build.
  2. Every entry has hashes for BOTH platforms we use (macOS arm64 laptop, Linux amd64 CI): two `h1:` hashes.

Note: `terraform init` removes providers a directory does not use from its lock, so directories legitimately differ in
WHICH providers they list. They must never differ in what a provider's entry says.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "terraform"
BLOCK = re.compile(r'^provider "([^"]+)" \{\n(.*?)^\}\n', re.S | re.M)


def blocks(path: Path) -> dict[str, str]:
    return {name: body for name, body in BLOCK.findall(path.read_text())}


def main() -> int:
    reference = blocks(ROOT / "environments/dev/.terraform.lock.hcl")
    problems = []
    for lock in sorted(ROOT.rglob(".terraform.lock.hcl")):
        if ".terraform/" in str(lock):
            continue
        rel = lock.parent.relative_to(ROOT)
        for name, body in blocks(lock).items():
            if reference.get(name) != body:
                problems.append(f"{rel}: provider {name.split('/')[-1]} differs from environments/dev")
            if body.count('"h1:') < 2:
                problems.append(f"{rel}: provider {name.split('/')[-1]} has hashes for fewer than 2 platforms")
    for p in problems:
        print("LOCK PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
