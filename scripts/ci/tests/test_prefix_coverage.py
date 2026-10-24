import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prefix_coverage import prefix  # noqa: E402

SAMPLE = """<?xml version="1.0" ?>
<coverage><sources><source>/home/runner/work/x/services/fee/app</source></sources>
<packages><package name="."><classes>
<class name="a.py" filename="app/a.py"/><class name="b.py" filename="services/fee/app/b.py"/>
</classes></package></packages></coverage>"""


def test_names_get_the_service_prefix_and_sources_are_removed(tmp_path):
    f = tmp_path / "coverage.xml"
    f.write_text(SAMPLE)
    assert prefix(str(f), "services/fee") == 1
    root = ET.parse(f).getroot()
    assert [c.get("filename") for c in root.iter("class")] == ["services/fee/app/a.py", "services/fee/app/b.py"]
    assert root.find("sources") is None


def test_running_twice_changes_nothing_more(tmp_path):
    f = tmp_path / "coverage.xml"
    f.write_text(SAMPLE)
    prefix(str(f), "services/fee/")
    assert prefix(str(f), "services/fee") == 0
