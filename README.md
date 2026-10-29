# CTOMind

Browse a mind map from a YAML file in the terminal, expanding and collapsing branches, or export it as ASCII, PNG, or SVG.

## Install

    pip install -r requirements.txt

Requires Python 3 with `click`, `Pillow`, `PyYAML` and `svgwrite`. `pytest` is only needed to run the tests.

## Data

The data is a tree of nodes. Each node has a `text` and optional `children`:

```yaml
text: 🧠 The CTO's Mind Map
children:
  # ---- right side: the work of a CTO ----
  - text: 🎯 Strategy
    side: right
    children:
      - text: 🔭 Vision
        children:
          - text: 3-year technology horizon
          - text: Build vs. buy vs. partner
          - text: 🌱 Emerging tech radar
            children:
              - text: 🤖 AI and agents
              - text: ☁️ Platform shifts
              - text: 🔐 Post-quantum security
      - text: 🗺️ Roadmap
        children:
          - text: Now / Next / Later
          - text: Outcomes over outputs
          - text: ⚖️ Trade-offs
            children:
              - text: Speed vs. quality
              - text: Features vs. tech debt
      - text: 💰 Budget
        children:
          - text: Cloud costs (FinOps)
          - text: Headcount planning
          - text: 📈 ROI of engineering
```

The root sits in the centre of the PNG and SVG, with its branches to the left and right. Give a child of the root `side: left` or `side: right` to choose; children without one are balanced by number of leaves (ties go right). `side` on deeper nodes is ignored.

Text can contain emoji. The terminal and SVG output show them as is; PNG export draws them with `NotoColorEmoji.ttf` if it is installed.

The loader rejects a `side` that is not `left` or `right`, nodes without a non-empty `text` and `children` that is not a list. `mindmap.yaml` is a full example (see `examples/mindmap.png`); `examples/cto.yaml` is a smaller one.

## Usage

    python ctomind.py [mindmap.yaml] [--format {interactive,ascii,png,svg}] [-o OUTPUT]

| Format        | Result                                                           |
|---------------|------------------------------------------------------------------|
| `interactive` | Full-screen ncurses browser (default).                           |
| `ascii`       | The whole map printed as a tree.                                 |
| `png`         | One image, `mindmap/<name>.png`, centred on the root.            |
| `svg`         | One vector image, `mindmap/<name>.svg`.                          |

Keys in interactive mode:

| Key                | Action                                                         |
|--------------------|----------------------------------------------------------------|
| `↑` `k` / `↓` `j`  | Previous / next visible node.                                  |
| `←` `h`            | Collapse the node; if already collapsed, go to its parent.     |
| `→` `l`            | Expand the node; if already expanded, go to its first child.   |
| `+` `=` / `-`      | Expand / collapse the current node.                            |
| `Space` `Enter`    | Toggle the current node.                                       |
| `*` / `/`          | Expand the whole subtree / collapse everything.                |
| `g` `Home` / `G` `End` | First / last visible node.                                 |
| `q` `Esc`          | Quit.                                                          |

Nodes with children show `-` when expanded and `+` when collapsed.

When stdin or stdout is not a terminal, or `-o` is given, `interactive` falls back to the `ascii` output. `-o` sets the output file for every format.

    $ python ctomind.py --format ascii
    🧠 The CTO's Mind Map
    ├── 🎯 Strategy
    │   ├── 🔭 Vision
    │   │   ├── 3-year technology horizon
    │   …

## Tests

    python -m pytest
