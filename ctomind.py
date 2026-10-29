#!/usr/bin/env python3
"""ctomind: browse a mind map from a YAML file in the terminal, or export it as ASCII, PNG, or SVG."""

import curses
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import svgwrite
import yaml
from PIL import Image, ImageDraw, ImageFont

DEFAULT_DATA = "mindmap.yaml"
DEFAULT_OUTPUT = "mindmap"
SIDES = {"left": -1, "right": 1}
FORMATS = ("interactive", "ascii", "png", "svg")

BG = "#ffffff"
INK = "#111111"
LINE = "#8aa4c4"
FILL = ("#2b6cb0", "#e6eef8", "#f4f7fb")  # root, first level, deeper levels
ROOT_INK = "#ffffff"
FONT_REGULAR = "DejaVuSans.ttf"
FONT_BOLD = "DejaVuSans-Bold.ttf"
FONT_SIZE = 22
FONT_EMOJI = "NotoColorEmoji.ttf"
EMOJI_WIDTH = 1.25  # width of an emoji, in font sizes
PAD_X = 16
PAD_Y = 8
GAP_X = 70
GAP_Y = 18
MARGIN = 40


class DataError(Exception):
    pass


@dataclass(eq=False)
class Node:
    text: str
    children: list["Node"] = field(default_factory=list)
    expanded: bool = True
    side: str | None = None  # "left" or "right", for the children of the root


def parse(data: Any, where: str) -> Node:
    if not isinstance(data, dict):
        raise DataError(f"{where} is not a mapping")
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise DataError(f"{where}: 'text' must be a non-empty string")
    children = data.get("children", [])
    if children is None:
        children = []
    if not isinstance(children, list):
        raise DataError(f"{where}: 'children' must be a list")
    side = data.get("side")
    if side is not None and side not in SIDES:
        raise DataError(f"{where}: 'side' must be 'left' or 'right'")
    node = Node(text.strip(), [parse(c, f"{where}.{i}") for i, c in enumerate(children, start=1)], side=side)
    return node


def load(path: Path | str) -> Node:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse(data, "root")


def walk(node: Node):
    yield node
    for child in node.children:
        yield from walk(child)


# --- text tree -------------------------------------------------------------------------------


def visible(root: Node) -> list[tuple[Node, Node | None, str]]:
    """Rows of the tree as (node, parent, branch prefix), skipping the children of collapsed nodes."""
    rows: list[tuple[Node, Node | None, str]] = [(root, None, "")]

    def descend(node: Node, indent: str) -> None:
        if not node.expanded:
            return
        for i, child in enumerate(node.children):
            last = i == len(node.children) - 1
            rows.append((child, node, indent + ("└── " if last else "├── ")))
            descend(child, indent + ("    " if last else "│   "))

    descend(root, "")
    return rows


def marker(node: Node) -> str:
    if not node.children:
        return "  "
    return "- " if node.expanded else "+ "


def ascii_tree(root: Node) -> list[str]:
    """The whole map as text, with every node expanded."""
    saved = [(n, n.expanded) for n in walk(root)]
    for n, _ in saved:
        n.expanded = True
    try:
        return [prefix + node.text for node, _, prefix in visible(root)]
    finally:
        for n, state in saved:
            n.expanded = state


# --- interactive -----------------------------------------------------------------------------

UP_KEYS = {curses.KEY_UP, ord("k")}
DOWN_KEYS = {curses.KEY_DOWN, ord("j")}
LEFT_KEYS = {curses.KEY_LEFT, ord("h")}
RIGHT_KEYS = {curses.KEY_RIGHT, ord("l")}
EXPAND_KEYS = {ord("+"), ord("=")}
COLLAPSE_KEYS = {ord("-"), ord("_")}
TOGGLE_KEYS = {ord(" "), 10, 13}
ALL_KEYS = {ord("*")}
NONE_KEYS = {ord("/")}
FIRST_KEYS = {curses.KEY_HOME, ord("g")}
LAST_KEYS = {curses.KEY_END, ord("G")}
QUIT_KEYS = {ord("q"), ord("Q"), 27}
HELP = "↑/↓ move · ←/→ parent/child · +/- expand/collapse · * all · / none · q quit"


def parent_of(root: Node, node: Node) -> Node | None:
    for n in walk(root):
        if node in n.children:
            return n
    return None


def step(root: Node, current: Node, key: int) -> Node:
    """Apply `key` to the map (expanding or collapsing nodes) and return the node that is current afterwards."""
    rows = visible(root)
    nodes = [n for n, _, _ in rows]
    index = nodes.index(current)
    if key in UP_KEYS:
        return nodes[max(index - 1, 0)]
    if key in DOWN_KEYS:
        return nodes[min(index + 1, len(nodes) - 1)]
    if key in FIRST_KEYS:
        return nodes[0]
    if key in LAST_KEYS:
        return nodes[-1]
    if key in EXPAND_KEYS:
        current.expanded = True
    elif key in COLLAPSE_KEYS:
        current.expanded = False
    elif key in TOGGLE_KEYS and current.children:
        current.expanded = not current.expanded
    elif key in ALL_KEYS:
        for n in walk(current):
            n.expanded = True
    elif key in NONE_KEYS:
        for n in walk(root):
            n.expanded = False
        return root
    elif key in RIGHT_KEYS:
        if current.children and not current.expanded:
            current.expanded = True
        elif current.children:
            return current.children[0]
    elif key in LEFT_KEYS:
        if current.children and current.expanded:
            current.expanded = False
        else:
            return parent_of(root, current) or current
    return current


def cells(char: str) -> int:
    """Columns a character takes on a terminal."""
    if unicodedata.combining(char) or ord(char) in (0x200D, 0xFE0F):
        return 0
    return 2 if unicodedata.east_asian_width(char) in "WF" else 1


def clip(text: str, columns: int) -> str:
    out = ""
    for char in text:
        columns -= cells(char)
        if columns < 0:
            break
        out += char
    return out


def put(screen: "curses.window", y: int, x: int, text: str, attr: int = 0) -> None:
    height, width = screen.getmaxyx()
    if 0 <= y < height and 0 <= x < width:
        try:
            screen.addstr(y, x, clip(text, width - x), attr)
        except curses.error:  # writing the bottom-right cell raises after drawing
            pass


def browse(screen: "curses.window", root: Node) -> None:
    curses.curs_set(0)
    current = root
    top = 0
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        rows = visible(root)
        body = max(height - 1, 1)
        at = [n for n, _, _ in rows].index(current)
        top = min(max(top, at - body + 1), at)
        for offset, (node, _, prefix) in enumerate(rows[top : top + body]):
            attr = curses.A_REVERSE if node is current else (curses.A_BOLD if node is root else 0)
            put(screen, offset, 0, prefix, curses.A_DIM)
            put(screen, offset, sum(cells(c) for c in prefix), marker(node) + node.text, attr)
        put(screen, height - 1, 0, HELP, curses.A_DIM)
        screen.refresh()
        key = screen.getch()
        if key in QUIT_KEYS:
            return
        current = step(root, current, key)


# --- graphic ---------------------------------------------------------------------------------

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


def load_font(name: str, size: int) -> Font:
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size)


def is_emoji(char: str) -> bool:
    code = ord(char)
    return code >= 0x1F000 or 0x2600 <= code <= 0x27BF or 0x2B00 <= code <= 0x2BFF or code in (0x200D, 0xFE0F)


def runs(text: str) -> list[tuple[bool, str]]:
    """Split text into (is_emoji, run) pieces, so each can be drawn with its own font."""
    pieces: list[tuple[bool, str]] = []
    for char in text:
        kind = is_emoji(char)
        if pieces and pieces[-1][0] == kind:
            pieces[-1] = (kind, pieces[-1][1] + char)
        else:
            pieces.append((kind, char))
    return pieces


def emoji_count(run: str) -> int:
    return sum(1 for c in run if ord(c) not in (0x200D, 0xFE0F))


def text_width(text: str, bold: bool) -> float:
    font = load_font(FONT_BOLD if bold else FONT_REGULAR, FONT_SIZE)
    return sum(emoji_count(run) * FONT_SIZE * EMOJI_WIDTH if emoji else font.getlength(run) for emoji, run in runs(text))


def draw_text(image: Image.Image, x: float, y: float, text: str, bold: bool, fill: str) -> None:
    draw = ImageDraw.Draw(image)
    font = load_font(FONT_BOLD if bold else FONT_REGULAR, FONT_SIZE)
    for emoji, run in runs(text):
        if not emoji:
            draw.text((x, y), run, fill=fill, font=font)
            x += font.getlength(run)
            continue
        for char in run:
            if ord(char) in (0x200D, 0xFE0F):
                continue
            try:  # the color emoji font only exists at one size: draw it there, then scale down
                glyph = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
                ImageDraw.Draw(glyph).text((0, 0), char, font=ImageFont.truetype(FONT_EMOJI, 109), embedded_color=True)
                size = round(FONT_SIZE * EMOJI_WIDTH)
                small = glyph.resize((size, round(size * 128 / 136)), Image.LANCZOS)
                image.paste(small, (round(x), round(y)), small)
            except OSError:
                pass
            x += FONT_SIZE * EMOJI_WIDTH


@dataclass(eq=False)
class Box:
    node: Node
    depth: int
    side: int  # -1 left of the root, 1 right, 0 the root itself
    kids: list["Box"] = field(default_factory=list)
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0


def sides(root: Node) -> list[int]:
    """The side of each child of the root: as declared, else balanced by the number of leaves."""
    load = {-1: 0, 1: 0}
    result: list[int] = []
    for child in root.children:
        side = SIDES[child.side] if child.side else (1 if load[1] <= load[-1] else -1)
        load[side] += sum(1 for n in walk(child) if not n.children)
        result.append(side)
    return result


def layout(root: Node) -> tuple[list[Box], float, float]:
    """Place the root in the centre, its branches to the left and right, one column per depth.

    Leaves are stacked, parents are centred on their children, and each side is centred on the root.
    """
    height = FONT_SIZE + 2 * PAD_Y
    boxes: list[Box] = []

    def build(node: Node, depth: int, side: int) -> Box:
        box = Box(node, depth, side, w=text_width(node.text, depth == 0) + 2 * PAD_X, h=height)
        boxes.append(box)
        box.kids = [build(c, depth + 1, side) for c in node.children]
        return box

    top = Box(root, 0, 0, w=text_width(root.text, True) + 2 * PAD_X, h=height)
    boxes.append(top)
    top.kids = [build(c, 1, side) for c, side in zip(root.children, sides(root))]

    def stack(box: Box, cursor: float) -> float:
        """Give `box` and its descendants a y from `cursor` down; return the next free y."""
        if not box.kids:
            box.y = cursor
            return cursor + height + GAP_Y
        end = cursor
        for kid in box.kids:
            end = stack(kid, end)
        box.y = (box.kids[0].y + box.kids[-1].y) / 2
        return end

    extent: dict[int, float] = {}
    for side in (-1, 1):
        cursor = 0.0
        for kid in (k for k in top.kids if k.side == side):
            cursor = stack(kid, cursor)
        extent[side] = max(cursor - GAP_Y, 0)
    total = max(*extent.values(), height)
    for side in (-1, 1):
        shift = (total - extent[side]) / 2
        for b in boxes:
            if b.side == side:
                b.y += shift
    top.y = (total - height) / 2
    for b in boxes:
        b.y += MARGIN

    columns: dict[int, dict[int, float]] = {-1: {}, 1: {}}
    for b in boxes:
        if b.side:
            columns[b.side][b.depth] = max(columns[b.side].get(b.depth, 0), b.w)
    span = {s: sum(w + GAP_X for w in columns[s].values()) for s in columns}
    top.x = MARGIN + span[-1]
    for side in (-1, 1):
        edge = top.x + top.w + GAP_X if side == 1 else top.x - GAP_X  # near edge of the column
        for depth in sorted(columns[side]):
            for b in boxes:
                if b.side == side and b.depth == depth:
                    b.x = edge if side == 1 else edge - b.w
            edge += side * (columns[side][depth] + GAP_X)
    width = top.x + top.w + span[1] + MARGIN
    return boxes, width, total + 2 * MARGIN


def links(boxes: list[Box]):
    """Each parent-child connection as ((x1, y1), (x2, y2)), from the parent's near edge to the child's."""
    for parent in boxes:
        for kid in parent.kids:
            side = kid.side
            x1 = parent.x + parent.w if side == 1 else parent.x
            x2 = kid.x if side == 1 else kid.x + kid.w
            yield (x1, parent.y + parent.h / 2), (x2, kid.y + kid.h / 2)


def fill_of(depth: int) -> str:
    return FILL[min(depth, 2)]


def render_png(root: Node, path: Path | str) -> None:
    boxes, width, height = layout(root)
    image = Image.new("RGB", (int(width), int(height)), BG)
    draw = ImageDraw.Draw(image)
    for (x1, y1), (x2, y2) in links(boxes):
        mid = (x1 + x2) / 2
        draw.line([(x1, y1), (mid, y1), (mid, y2), (x2, y2)], fill=LINE, width=2)
    for b in boxes:
        draw.rounded_rectangle([b.x, b.y, b.x + b.w, b.y + b.h], radius=10, fill=fill_of(b.depth), outline=FILL[0], width=2)
        draw_text(image, b.x + PAD_X, b.y + PAD_Y, b.node.text, b.depth == 0, ROOT_INK if b.depth == 0 else INK)
    image.save(path)


def render_svg(root: Node, path: Path | str) -> None:
    boxes, width, height = layout(root)
    drawing = svgwrite.Drawing(size=(width, height), profile="full")
    drawing.viewbox(0, 0, width, height)
    drawing["font-family"] = "DejaVu Sans, Verdana, Noto Color Emoji, sans-serif"
    drawing.add(drawing.rect(insert=(0, 0), size=(width, height), fill=BG))
    for (x1, y1), (x2, y2) in links(boxes):
        mid = (x1 + x2) / 2
        drawing.add(drawing.path(d=f"M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}", fill="none", stroke=LINE, stroke_width=2))
    for b in boxes:
        bold = b.depth == 0
        y = b.y
        drawing.add(drawing.rect(insert=(b.x, y), size=(b.w, b.h), rx=10, ry=10, fill=fill_of(b.depth), stroke=FILL[0], stroke_width=2))
        drawing.add(
            drawing.text(
                b.node.text,
                insert=(b.x + PAD_X, y + PAD_Y + FONT_SIZE * 0.85),
                font_size=FONT_SIZE,
                font_weight="bold" if bold else "normal",
                fill=ROOT_INK if bold else INK,
            )
        )
    drawing.saveas(path, pretty=True)


# --- cli -------------------------------------------------------------------------------------


def load_map(path: str) -> Node:
    try:
        return load(path)
    except (OSError, yaml.YAMLError, DataError) as err:
        raise click.ClickException(str(err)) from None


@click.command()
@click.argument("data", default=DEFAULT_DATA)
@click.option("--format", "fmt", type=click.Choice(FORMATS), default="interactive", show_default=True, help="interactive browses the map in the terminal; ascii prints it; png and svg export it.")
@click.option("-o", "--output", help="Output file (default for png and svg: mindmap/<name>.<format>; with ascii, writes the text to this file instead of printing).")
def cli(data: str, fmt: str, output: str | None) -> None:
    """Browse a mind map from a YAML file."""
    root = load_map(data)

    # Without a terminal to drive (pipes, -o FILE), the interactive mode falls back to plain text.
    if fmt == "interactive" and sys.stdin.isatty() and sys.stdout.isatty() and output is None:
        curses.wrapper(browse, root)
        return

    if fmt in ("interactive", "ascii"):
        text = "\n".join(ascii_tree(root))
        if output is None:
            click.echo(text)
        else:
            Path(output).write_text(text + "\n", encoding="utf-8")
            click.echo(f"Wrote {output}")
        return

    target = Path(output) if output else Path(DEFAULT_OUTPUT) / f"{Path(data).stem}.{fmt}"
    target.parent.mkdir(parents=True, exist_ok=True)
    (render_png if fmt == "png" else render_svg)(root, target)
    click.echo(f"Wrote {target}")


if __name__ == "__main__":
    cli()
