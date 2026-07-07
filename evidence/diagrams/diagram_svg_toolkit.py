"""A small, deliberate SVG toolkit for Omni's monochrome flow diagrams.

Why hand-authored SVG (not graphviz): the brief demands genuinely-designed,
strictly black-and-white diagrams — ink (#0A0A0A) on paper — not default
graphviz output. This toolkit gives pixel control over nodes, ports, orthogonal
edges, and dashed trust boundaries, with a consistent type scale and spacing so
every diagram reads as one system. Each diagram is emitted as a PNG (cairosvg
rasterisation) and a self-contained HTML page embedding the same SVG.

Strict B&W: differentiation is by stroke weight, fill tint (greys), and dashing —
never colour. Analysis-only; never imported by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cairosvg

DIAGRAM_DIR = Path(__file__).resolve().parent
INK = "#0A0A0A"
GREY = "#6E6E6E"
GREY_FILL = "#F0F0F0"
GREY_TINT = "#E4E4E4"
PAPER = "#FFFFFF"
FONT = "Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Node:
    """A placed box with named anchor ports on each side."""

    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def port(self, side: str) -> tuple[float, float]:
        return {
            "left": (self.x, self.cy),
            "right": (self.x + self.w, self.cy),
            "top": (self.cx, self.y),
            "bottom": (self.cx, self.y + self.h),
        }[side]


class Diagram:
    """Accumulates SVG primitives, then renders to SVG / PNG / HTML."""

    def __init__(self, width: int, height: int, title: str) -> None:
        self.width = width
        self.height = height
        self.title = title
        self._body: list[str] = []

    # -- primitives ---------------------------------------------------------
    def node(
        self, x: float, y: float, w: float, h: float, label: str,
        sub: str = "", *, emphasis: bool = False, dashed: bool = False,
    ) -> Node:
        fill = GREY_FILL if emphasis else PAPER
        stroke_w = 2.4 if emphasis else 1.6
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self._body.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill}" '
            f'stroke="{INK}" stroke-width="{stroke_w}"{dash}/>'
        )
        ty = y + h / 2 + (0 if not sub else -7)
        self._body.append(
            f'<text x="{x + w / 2}" y="{ty + 5}" font-family="{FONT}" font-size="15" '
            f'font-weight="700" text-anchor="middle" fill="{INK}">{_esc(label)}</text>'
        )
        if sub:
            self._body.append(
                f'<text x="{x + w / 2}" y="{ty + 22}" font-family="{FONT}" font-size="11.5" '
                f'text-anchor="middle" fill="{GREY}">{_esc(sub)}</text>'
            )
        return Node(x, y, w, h)

    def boundary(self, x: float, y: float, w: float, h: float, label: str) -> None:
        self._body.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="none" '
            f'stroke="{GREY}" stroke-width="1.3" stroke-dasharray="2 5"/>'
        )
        self._body.append(
            f'<rect x="{x + 14}" y="{y - 11}" width="{10 + len(label) * 7.2}" height="22" '
            f'rx="5" fill="{PAPER}" stroke="{GREY}" stroke-width="1"/>'
        )
        self._body.append(
            f'<text x="{x + 20}" y="{y + 4}" font-family="{FONT}" font-size="11.5" '
            f'font-weight="600" fill="{GREY}">{_esc(label)}</text>'
        )

    def edge(
        self, a: tuple[float, float], b: tuple[float, float], label: str = "",
        *, elbow: bool = False, dashed: bool = False,
    ) -> None:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        if elbow:
            midx = (a[0] + b[0]) / 2
            path = f"M {a[0]} {a[1]} L {midx} {a[1]} L {midx} {b[1]} L {b[0]} {b[1]}"
        else:
            path = f"M {a[0]} {a[1]} L {b[0]} {b[1]}"
        self._body.append(
            f'<path d="{path}" fill="none" stroke="{INK}" stroke-width="1.5"{dash} '
            f'marker-end="url(#arrow)"/>'
        )
        if label:
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            wpx = 8 + len(label) * 6.4
            self._body.append(
                f'<rect x="{mx - wpx / 2}" y="{my - 11}" width="{wpx}" height="18" rx="4" '
                f'fill="{PAPER}" opacity="0.92"/>'
            )
            self._body.append(
                f'<text x="{mx}" y="{my + 2}" font-family="{FONT}" font-size="11" '
                f'text-anchor="middle" fill="{GREY}">{_esc(label)}</text>'
            )

    def caption(self, text: str) -> None:
        self._body.append(
            f'<text x="{self.width / 2}" y="{self.height - 16}" font-family="{FONT}" '
            f'font-size="12" text-anchor="middle" fill="{GREY}">{_esc(text)}</text>'
        )

    # -- rendering ----------------------------------------------------------
    def _svg(self) -> str:
        header = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}">'
            f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{INK}"/></marker></defs>'
            f'<rect width="{self.width}" height="{self.height}" fill="{PAPER}"/>'
            f'<text x="{self.width / 2}" y="38" font-family="{FONT}" font-size="20" '
            f'font-weight="800" text-anchor="middle" fill="{INK}">{_esc(self.title)}</text>'
        )
        return header + "".join(self._body) + "</svg>"

    def save(self, stem: str) -> None:
        svg = self._svg()
        cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            write_to=str(DIAGRAM_DIR / f"{stem}.png"),
            output_width=self.width * 2,
            output_height=self.height * 2,
        )
        html = (
            f"<!doctype html><meta charset='utf-8'><title>{_esc(self.title)}</title>"
            f"<style>body{{margin:0;background:{PAPER};display:flex;justify-content:center;"
            f"padding:24px;font-family:{FONT}}}svg{{max-width:100%;height:auto}}</style>"
            f"{svg}"
        )
        (DIAGRAM_DIR / f"{stem}.html").write_text(html, encoding="utf-8")


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
