#!/usr/bin/env python3
"""Decides which parts of the monorepo a change touches, so CI runs only what is needed.

    scripts/ci/changed.py --base <sha> --head <sha>            # prints JSON
    scripts/ci/changed.py --base <sha> --head <sha> --github-output   # also writes to $GITHUB_OUTPUT for later jobs

Outputs (all strings, as GitHub Actions wants):
  services   JSON list of the services whose tests/images must run, e.g. ["fee","student"]
  images     JSON list of the container images to build: [{"name": "fee", "context": "services/fee", "dockerfile": "docker/..."}]
  frontend, terraform, helm, lambdas, tools, workflows   "true" or "false"

Safe by default: if the base is unknown (first push, force push, shallow clone) or git cannot compare, EVERYTHING runs.
A check that is skipped by mistake is far worse than one that runs unnecessarily.
"""

import argparse
import json
import os
import subprocess
import sys

SERVICES = ["auth", "admission", "student", "fee", "attendance", "notification"]

# Files that every service depends on: a change here re-tests and rebuilds all of them.
SHARED_BY_ALL_SERVICES = (
    "docker/python-service.Dockerfile",
    "docker/python-service.Dockerfile.dockerignore",
    ".github/workflows/_service.yml",
    "scripts/ci/",
)
ZERO_SHA = "0" * 40


def classify(paths: list[str]) -> dict[str, object]:
    services: set[str] = set()
    flags = {"frontend": False, "terraform": False, "helm": False, "lambdas": False, "tools": False, "workflows": False}
    for path in paths:
        parts = path.split("/")
        if parts[0] == "services" and len(parts) > 2 and parts[1] in SERVICES:
            services.add(parts[1])
        elif any(path == p or path.startswith(p) for p in SHARED_BY_ALL_SERVICES):
            services.update(SERVICES)
        if parts[0] == "frontend":
            flags["frontend"] = True
        if parts[0] == "terraform" or path.startswith("scripts/tf/"):
            flags["terraform"] = True
        if parts[0] == "helm" or path.startswith("scripts/helm/"):
            flags["helm"] = True
        if parts[0] == "lambdas":
            flags["lambdas"] = True
        if path.startswith("tools/db-bootstrap/") or path == "docker/db-tools.Dockerfile":
            flags["tools"] = True
        if parts[0] == ".github":
            flags["workflows"] = True
        # The Helm chart tests read the services' Terraform and Terraform reads the lambda source: cross-checks.
        if path.startswith("terraform/environments/") and "locals.tf" in path:
            flags["helm"] = True
    ordered = [s for s in SERVICES if s in services]
    return {"services": ordered, "images": images_for(ordered, flags["tools"]), **flags}


def images_for(services: list[str], tools: bool) -> list[dict[str, str]]:
    """What the build workflow must build. Names are the ECR repository names (school/<name>)."""
    images = [{"name": s, "context": f"services/{s}", "dockerfile": "docker/python-service.Dockerfile"} for s in services]
    if tools:
        images.append({"name": "db-tools", "context": "tools/db-bootstrap", "dockerfile": "docker/db-tools.Dockerfile"})
    return images


def everything() -> dict[str, object]:
    return {"services": list(SERVICES), "images": images_for(SERVICES, True), "frontend": True, "terraform": True, "helm": True, "lambdas": True, "tools": True, "workflows": True}


def changed_paths(base: str, head: str) -> list[str] | None:
    if not base or base == ZERO_SHA:
        return None
    result = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True)
    if result.returncode != 0:  # unknown commit, shallow clone, unrelated histories ...
        return None
    return [line for line in result.stdout.splitlines() if line]


def compute(base: str, head: str) -> dict[str, object]:
    paths = changed_paths(base, head)
    return everything() if paths is None else classify(paths)


def write_github_output(result: dict[str, object]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        raise SystemExit("--github-output needs the GITHUB_OUTPUT environment variable (only set inside GitHub Actions)")
    with open(target, "a") as fh:
        for key, value in result.items():
            fh.write(f"{key}={json.dumps(value, separators=(',', ':')) if key in ('services', 'images') else str(value).lower()}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="", help="commit to compare against (empty = run everything)")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--all", action="store_true", help="ignore the diff and run everything (manual runs)")
    args = parser.parse_args(argv)
    result = everything() if args.all else compute(args.base, args.head)
    print(json.dumps(result))
    if args.github_output:
        write_github_output(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
