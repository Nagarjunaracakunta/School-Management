import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bump_image_tag as bump  # noqa: E402

A = "a" * 40
B = "b" * 40


@pytest.fixture
def base(tmp_path):
    copy = tmp_path / "environments"
    shutil.copytree(bump.ENV_DIR, copy)
    return copy


def test_only_the_tag_changes_and_comments_survive(base):
    path = base / "dev" / "fee.yaml"
    before = path.read_text()
    assert bump.apply("dev", {"fee": A}, base) == [f"dev/fee: 0000000 -> {A[:12]}"]
    after = path.read_text()
    assert f'tag: "{A}"' in after
    assert after.replace(A, "0000000") == before


def test_the_same_tag_again_changes_nothing(base):
    bump.apply("dev", {"fee": A}, base)
    assert bump.apply("dev", {"fee": A}, base) == []


def test_db_tools_goes_to_the_platform_values(base):
    bump.apply("dev", {"db-tools": A}, base)
    assert f'tag: "{A}"' in (base / "dev" / "platform.yaml").read_text()


@pytest.mark.parametrize("bad", ["latest", "abc1234", "A" * 40, "g" * 40, ""])
def test_only_full_lowercase_commit_shas_are_accepted(base, bad):
    with pytest.raises(SystemExit):
        bump.apply("dev", {"fee": bad}, base)


def test_unknown_names_are_refused(base):
    with pytest.raises(SystemExit):
        bump.apply("dev", {"payroll": A}, base)
    with pytest.raises(SystemExit):
        bump.apply("qa", {"fee": A}, base)


def test_build_records_are_read_from_nested_artifact_folders(tmp_path):
    for name, tag in [("fee", A), ("auth", B)]:
        folder = tmp_path / f"image-{name}"
        folder.mkdir()
        (folder / f"image-{name}.json").write_text(json.dumps({"name": name, "tag": tag, "digest": "x", "uri": "y"}))
    assert bump.builds_in(tmp_path) == {"fee": A, "auth": B}


def test_promotion_copies_every_tag_and_leaves_other_settings(base):
    for image in bump.SERVICES + ["db-tools"]:
        bump.apply("dev", {image: A}, base)
    changes = bump.promote("dev", "stage", base)
    assert len(changes) == 7
    stage_fee = (base / "stage" / "fee.yaml").read_text()
    assert f'tag: "{A}"' in stage_fee
    assert stage_fee.replace(A, "0000000") == (bump.ENV_DIR / "stage" / "fee.yaml").read_text()


def test_nothing_is_promoted_from_an_environment_that_never_deployed(base):
    with pytest.raises(SystemExit):
        bump.promote("dev", "stage", base)
