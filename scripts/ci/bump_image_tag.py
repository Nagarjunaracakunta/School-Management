#!/usr/bin/env python3
"""Changes WHICH image version an environment runs, by editing the Helm values in Git. This is the only thing CI changes
about a deployment; Argo CD sees the commit and does the rest.

    bump_image_tag.py set  --env dev --image fee=<40-hex sha> [--image db-tools=<sha> ...]
    bump_image_tag.py from-builds --env dev --dir <folder with image-<name>.json files written by build-images.yml>
    bump_image_tag.py promote --from dev --to stage        # copy every tag dev runs to stage

Only the `tag:` line is rewritten, so comments and everything else in the file stay as they are. Prints one line per change.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_DIR = ROOT / "helm" / "environments"
SERVICES = ["auth", "admission", "student", "fee", "attendance", "notification"]
SHA = re.compile(r"^[0-9a-f]{40}$")
PLACEHOLDER = "0000000"
TAG_LINE = re.compile(r'^(\s*tag:\s*)"?([0-9a-f]+)"?(\s*(#.*)?)$', re.M)


def values_file(env: str, image: str, base: Path = ENV_DIR) -> Path:
    """db-tools is deployed by the platform chart; every other image is one service's release."""
    if env not in ("dev", "stage", "prod"):
        raise SystemExit(f"unknown environment: {env}")
    if image == "db-tools":
        return base / env / "platform.yaml"
    if image not in SERVICES:
        raise SystemExit(f"unknown image: {image} (expected one of {SERVICES + ['db-tools']})")
    return base / env / f"{image}.yaml"


def read_tag(path: Path) -> str:
    match = TAG_LINE.search(path.read_text())
    if not match:
        raise SystemExit(f"no tag line in {path}")
    return match.group(2)


def write_tag(path: Path, tag: str) -> str | None:
    """Returns the old tag, or None when nothing changed."""
    text = path.read_text()
    match = TAG_LINE.search(text)
    if not match:
        raise SystemExit(f"no tag line in {path}")
    old = match.group(2)
    if old == tag:
        return None
    path.write_text(text[: match.start()] + f'{match.group(1)}"{tag}"{match.group(3)}' + text[match.end():])
    return old


def check_sha(tag: str) -> str:
    if not SHA.match(tag):
        raise SystemExit(f"refusing tag {tag!r}: it must be a full 40-character lower-case git commit SHA")
    return tag


def apply(env: str, tags: dict[str, str], base: Path = ENV_DIR) -> list[str]:
    changes = []
    for image, tag in tags.items():
        path = values_file(env, image, base)
        old = write_tag(path, check_sha(tag))
        if old is not None:
            changes.append(f"{env}/{image}: {old[:12]} -> {tag[:12]}")
    return changes


def builds_in(directory: Path) -> dict[str, str]:
    tags = {}
    for f in sorted(directory.rglob("image-*.json")):
        data = json.loads(f.read_text())
        tags[data["name"]] = data["tag"]
    return tags


def current_tags(env: str, base: Path = ENV_DIR) -> dict[str, str]:
    return {i: read_tag(values_file(env, i, base)) for i in SERVICES + ["db-tools"]}


def promote(source: str, target: str, base: Path = ENV_DIR) -> list[str]:
    tags = current_tags(source, base)
    unbuilt = [i for i, t in tags.items() if t == PLACEHOLDER]
    if unbuilt:
        raise SystemExit(f"{source} still has the placeholder tag for {unbuilt}: nothing real to promote")
    return apply(target, tags, base)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("set")
    s.add_argument("--env", required=True)
    s.add_argument("--image", action="append", required=True, metavar="NAME=SHA")
    b = sub.add_parser("from-builds")
    b.add_argument("--env", required=True)
    b.add_argument("--dir", type=Path, required=True)
    p = sub.add_parser("promote")
    p.add_argument("--from", dest="source", required=True)
    p.add_argument("--to", required=True)
    args = parser.parse_args(argv)

    if args.command == "set":
        tags = dict(item.split("=", 1) for item in args.image)
        changes = apply(args.env, tags)
    elif args.command == "from-builds":
        tags = builds_in(args.dir)
        if not tags:
            raise SystemExit(f"no image-*.json files in {args.dir}")
        changes = apply(args.env, tags)
    else:
        if args.source == args.to:
            raise SystemExit("--from and --to must differ")
        changes = promote(args.source, args.to)
    print("\n".join(changes) if changes else "no change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
