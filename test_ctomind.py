import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

import ctomind

SAMPLE = Path(__file__).with_name("mindmap.yaml")
EXAMPLE = Path(__file__).parent / "examples" / "cto.yaml"


def run(*args):
    return CliRunner().invoke(ctomind.cli, [str(a) for a in args])


def write_map(tmp_path, data):
    path = tmp_path / "map.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def small():
    return ctomind.parse({"text": "r", "children": [{"text": "a", "children": [{"text": "a1"}]}, {"text": "b"}]}, "root")


def test_load_sample_data():
    root = ctomind.load(SAMPLE)
    assert root.text == "🧠 The CTO's Mind Map"
    assert [c.text for c in root.children] == ["🎯 Strategy", "🏗️ Architecture", "🚀 Delivery", "🧩 Business", "🗺️ Mind maps", "👥 People", "🧭 Leadership", "🔄 Career paths"]


@pytest.mark.parametrize(
    "data",
    [[], {"text": ""}, {"children": []}, {"text": "r", "children": "x"}, {"text": "r", "children": [{"text": 1}]}],
)
def test_rejects_malformed_data(tmp_path, data):
    result = run(write_map(tmp_path, data))
    assert result.exit_code != 0
    assert "Error" in result.output


def test_ascii_tree():
    assert ctomind.ascii_tree(small()) == ["r", "├── a", "│   └── a1", "└── b"]


def test_ascii_ignores_collapsed_state():
    root = small()
    root.expanded = False
    assert len(ctomind.ascii_tree(root)) == 4
    assert root.expanded is False


def test_collapse_hides_children_and_expand_shows_them():
    root = small()
    a = root.children[0]
    assert ctomind.step(root, a, ord("-")) is a
    assert [n.text for n, _, _ in ctomind.visible(root)] == ["r", "a", "b"]
    ctomind.step(root, a, ord("+"))
    assert len(ctomind.visible(root)) == 4


def test_move_between_visible_nodes():
    root = small()
    a, a1, b = root.children[0], root.children[0].children[0], root.children[1]
    assert ctomind.step(root, root, ord("j")) is a
    assert ctomind.step(root, a, ord("j")) is a1
    assert ctomind.step(root, b, ord("k")) is a1
    assert ctomind.step(root, root, ord("k")) is root
    assert ctomind.step(root, root, ord("G")) is b


def test_left_collapses_then_goes_to_parent_and_right_expands_then_enters():
    root = small()
    a, a1 = root.children[0], root.children[0].children[0]
    assert ctomind.step(root, a, ord("h")) is a and not a.expanded
    assert ctomind.step(root, a, ord("h")) is root
    assert ctomind.step(root, a, ord("l")) is a and a.expanded
    assert ctomind.step(root, a, ord("l")) is a1
    assert ctomind.step(root, a1, ord("l")) is a1


def test_expand_all_and_collapse_all():
    root = small()
    assert ctomind.step(root, root.children[1], ord("/")) is root
    assert len(ctomind.visible(root)) == 1
    ctomind.step(root, root, ord("*"))
    assert len(ctomind.visible(root)) == 4


def test_cli_ascii_falls_back_without_terminal():
    result = run(EXAMPLE)
    assert result.exit_code == 0
    assert result.output.splitlines()[0] == "CTO Framework"


def test_cli_ascii_to_file(tmp_path):
    out = tmp_path / "m.txt"
    assert run(EXAMPLE, "--format", "ascii", "-o", out).exit_code == 0
    assert out.read_text().startswith("CTO Framework\n")


def test_cli_svg(tmp_path):
    out = tmp_path / "m.svg"
    assert run(EXAMPLE, "--format", "svg", "-o", out).exit_code == 0
    texts = [t.text for t in ET.parse(out).getroot().iter("{http://www.w3.org/2000/svg}text")]
    assert "Org design" in texts and len(texts) == 10


def test_cli_png(tmp_path):
    out = tmp_path / "m.png"
    assert run(EXAMPLE, "--format", "png", "-o", out).exit_code == 0
    assert Image.open(out).width > 200


def test_missing_file():
    assert run("nope.yaml").exit_code != 0


def test_sides_follow_the_data_or_balance_the_leaves():
    root = ctomind.parse({"text": "r", "children": [{"text": "a", "side": "left"}, {"text": "b"}, {"text": "c"}]}, "root")
    assert ctomind.sides(root) == [-1, 1, 1]  # ties go right


def test_rejects_unknown_side():
    with pytest.raises(ctomind.DataError):
        ctomind.parse({"text": "r", "children": [{"text": "a", "side": "up"}]}, "root")


def test_layout_puts_root_between_its_sides():
    root = ctomind.parse({"text": "r", "children": [{"text": "a", "side": "left"}, {"text": "b", "side": "right"}]}, "root")
    boxes, width, height = ctomind.layout(root)
    top, a, b = boxes[0], *(x for x in boxes[1:])
    left, right = (a, b) if a.node.text == "a" else (b, a)
    assert left.x + left.w < top.x and top.x + top.w < right.x
    assert all(0 <= x.y and x.y + x.h <= height and x.x + x.w <= width for x in boxes)
