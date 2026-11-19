#!/usr/bin/env python3
"""Generate the architecture diagrams in docs/architecture/diagrams/.

    python scripts/gen_diagrams.py

Each diagram is written twice, light and dark, from the same coordinates; the README
embeds both through <picture> + prefers-color-scheme. Stdlib only.

Conventions, the same in every diagram:

- Shape is the kind of thing: rounded box = service, cylinder = data store,
  pipe = Kafka topic.
- Colour is the layer: amber = speed (provisional), blue = batch (final),
  red = rejected / failed, violet = simulated source, teal = orchestration and
  monitoring, grey = shared infrastructure. Dashed = written but never read.
- Boxes carry a name and a [technology]; edges carry a verb. Explanation belongs in the
  README next to the diagram, not inside it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture" / "diagrams"

SANS = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, 'SFMono-Regular', 'Cascadia Mono', Consolas, Menlo, monospace"

# Neutrals lean slightly blue, toward the batch accent.
THEMES = {
    "light": {
        "bg": "#f6f8fb",
        "panel": "#edf1f7",
        "ink": "#172033",
        "muted": "#55617a",
        "line": "#b8c2d3",
        "tint": 0.12,
        "roles": {
            "simulated": "#7150b3",
            "provisional": "#a3620a",
            "final": "#2a5ea8",
            "failure": "#bb2f2f",
            "control": "#0d7366",
            "neutral": "#56627a",
            "unused": "#8a94a8",
        },
    },
    "dark": {
        "bg": "#0e131b",
        "panel": "#172030",
        "ink": "#e3e9f2",
        "muted": "#9aa6bc",
        "line": "#38465e",
        "tint": 0.18,
        "roles": {
            "simulated": "#ad8eec",
            "provisional": "#e6a743",
            "final": "#72a2ec",
            "failure": "#f17878",
            "control": "#4cc4b2",
            "neutral": "#9aa6bc",
            "unused": "#6b7890",
        },
    },
}

LEGEND = {
    "simulated": "simulated source",
    "provisional": "speed · provisional",
    "final": "batch · final",
    "failure": "rejected / failed",
    "control": "orchestration · monitoring",
    "neutral": "infrastructure",
    "unused": "never read",
}

WARNINGS: list[str] = []


def _mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(ca, cb, strict=True))


def text_width(s: str, size: float, mono: bool = False) -> float:
    return len(s) * size * (0.6 if mono else 0.54)


class Svg:
    def __init__(self, name: str, w: int, h: int, theme: str, title: str, desc: str):
        self.name, self.w, self.h, self.t = name, w, h, THEMES[theme]
        self.title, self.desc = title, desc
        self.body: list[str] = []
        self.markers: set[tuple[str, bool]] = set()

    # -- colour -------------------------------------------------------------------------
    def col(self, key: str) -> str:
        return self.t["roles"].get(key) or self.t[key]

    def fill(self, role: str) -> str:
        if role in ("neutral", "unused"):
            return self.t["panel"] if role == "neutral" else self.t["bg"]
        return _mix(self.t["roles"][role], self.t["bg"], self.t["tint"])

    def stroke(self, role: str) -> str:
        return self.t["line"] if role == "neutral" else self.col(role)

    # -- primitives -----------------------------------------------------------------------
    def text(self, x, y, s, size=13.0, color="ink", weight=400, anchor="start",  # noqa: ANN001
             mono=False, maxw=None):
        if maxw is not None and text_width(s, size, mono) > maxw:
            WARNINGS.append(f"{self.name}: '{s}' does not fit {maxw:.0f}px")
        self.body.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO if mono else SANS}" '
            f'font-size="{size}" font-weight="{weight}" fill="{self.col(color)}" '
            f'text-anchor="{anchor}">{escape(s)}</text>'
        )

    def raw(self, svg: str) -> None:
        self.body.append(svg)

    def rect(self, x, y, w, h, fill, stroke=None, r=8, dash=False, sw=1.4):  # noqa: ANN001
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        st += ' stroke-dasharray="5 4"' if dash else ""
        self.raw(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" '
                 f'fill="{fill}"{st}/>')

    def _labels(self, cx, cy, name, tech):  # noqa: ANN001
        if tech:
            self.text(cx, cy - 2, name, 14, "ink", 650, "middle")
            self.text(cx, cy + 15, f"[{tech}]", 11, "muted", anchor="middle")
        else:
            self.text(cx, cy + 5, name, 14, "ink", 650, "middle")

    def service(self, x, y, w, h, role, name, tech=None):  # noqa: ANN001
        self.rect(x, y, w, h, self.fill(role), self.stroke(role), r=10,
                  dash=role == "unused", sw=1.6)
        self._labels(x + w / 2, y + h / 2, name, tech)
        self._fit(name, tech, w)

    def store(self, x, y, w, h, role, name, tech=None):  # noqa: ANN001
        """Cylinder: a data store."""
        ry = 7
        fill, stroke = self.fill(role), self.stroke(role)
        dash = ' stroke-dasharray="5 4"' if role == "unused" else ""
        self.raw(
            f'<path d="M{x},{y + ry} V{y + h - ry} A{w / 2},{ry} 0 0 0 {x + w},{y + h - ry} '
            f'V{y + ry} A{w / 2},{ry} 0 0 0 {x},{y + ry} Z" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.6"{dash}/>'
            f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.6"{dash}/>'
        )
        self._labels(x + w / 2, y + h / 2 + ry / 2, name, tech)
        self._fit(name, tech, w)

    def topic(self, x, y, w, h, role, name, tech=None):  # noqa: ANN001
        """Horizontal pipe: a Kafka topic."""
        rx = 9
        fill, stroke = self.fill(role), self.stroke(role)
        dash = ' stroke-dasharray="5 4"' if role == "unused" else ""
        self.raw(
            f'<path d="M{x + rx},{y} H{x + w - rx} A{rx},{h / 2} 0 0 1 {x + w - rx},{y + h} '
            f'H{x + rx} A{rx},{h / 2} 0 0 1 {x + rx},{y} Z" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.6"{dash}/>'
            f'<ellipse cx="{x + w - rx}" cy="{y + h / 2}" rx="{rx}" ry="{h / 2}" fill="none" '
            f'stroke="{stroke}" stroke-width="1.6"{dash}/>'
        )
        self._labels(x + w / 2 - rx / 2, y + h / 2, name, tech)
        self._fit(name, tech, w - 2 * rx)

    def _fit(self, name, tech, w):  # noqa: ANN001
        if text_width(name, 14) > w - 12 or (tech and text_width(f"[{tech}]", 11) > w - 12):
            WARNINGS.append(f"{self.name}: '{name}' / '{tech}' too wide for {w}px")

    def group(self, x, y, w, h, label):  # noqa: ANN001
        """A real boundary: one server or one system."""
        self.rect(x, y, w, h, "none", self.t["line"], r=12, sw=1.2)
        self.text(x + 12, y + 18, label, 11.5, "muted", 650)

    def chip(self, cx, cy, s, role, w=None, solid=False):  # noqa: ANN001
        w = w or text_width(s, 12) + 22
        fill = self.col(role) if solid else self.fill(role)
        self.rect(cx - w / 2, cy - 13, w, 26, fill, self.stroke(role), r=13, sw=1.3,
                  dash=role == "unused")
        self.text(cx, cy + 4.5, s, 12, "bg" if solid else "ink", 600, "middle")

    def marker(self, key: str, open_head: bool) -> str:
        self.markers.add((key, open_head))
        return f"ah-{key}-{'o' if open_head else 'f'}"

    def edge(self, pts, role="neutral", label=None, at=None, dash=False,  # noqa: ANN001
             dotted=False, head=True, open_head=False, sw=1.6, anchor="middle"):
        key = "muted" if role == "neutral" else role
        color = self.col(key)
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.raw(f'<path d="{d}" fill="none" stroke="{self.t["bg"]}" stroke-width="{sw + 5}" '
                 f'stroke-linejoin="round"/>')
        attrs = f'fill="none" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round"'
        if dash:
            attrs += ' stroke-dasharray="6 4"'
        if dotted:
            attrs += ' stroke-dasharray="1 4" stroke-linecap="round"'
        if head:
            attrs += f' marker-end="url(#{self.marker(key, open_head)})"'
        self.raw(f'<path d="{d}" {attrs}/>')
        if label:
            if at is None:  # midpoint of the longest segment, just above it
                segs = list(zip(pts, pts[1:], strict=False))
                (x1, y1), (x2, y2) = max(segs, key=lambda s: abs(s[1][0] - s[0][0])
                                         + abs(s[1][1] - s[0][1]))
                at = ((x1 + x2) / 2, (y1 + y2) / 2 - 7)
            self.label(at[0], at[1], label, color=key, anchor=anchor)

    def label(self, x, y, s, size=11.5, color="muted", anchor="middle"):  # noqa: ANN001
        w = len(s) * size * 0.5
        x0 = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
        self.rect(x0 - 3, y - size + 1, w + 6, size + 4, self.t["bg"], r=3)
        self.text(x, y, s, size, color, 600, anchor)

    def num(self, cx, cy, n, role):  # noqa: ANN001
        key = "muted" if role == "neutral" else role
        self.raw(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8.5" fill="{self.col(key)}"/>')
        self.text(cx, cy + 3.8, str(n), 10, "bg", 700, "middle")

    def title_(self, s: str) -> None:
        self.text(24, 36, s, 19, "ink", 650)

    def legend(self, roles: list[str]) -> None:
        x, y = 24.0, self.h - 20
        for role in roles:
            if role == "unused":
                self.rect(x, y - 11, 22, 14, "none", self.col("unused"), r=3, dash=True)
            else:
                self.rect(x, y - 11, 22, 14, self.fill(role), self.stroke(role), r=3, sw=1.2)
            self.text(x + 29, y, LEGEND[role], 11.5, "muted")
            x += 29 + text_width(LEGEND[role], 11.5) + 20
        if x > self.w:
            WARNINGS.append(f"{self.name}: legend overflows")

    def render(self) -> str:
        defs = []
        for key, open_head in sorted(self.markers):
            c = self.col(key)
            shape = (f'<path d="M1,1 L9,5 L1,9" fill="none" stroke="{c}" stroke-width="1.6"/>'
                     if open_head else f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/>')
            defs.append(
                f'<marker id="ah-{key}-{"o" if open_head else "f"}" viewBox="0 0 10 10" '
                f'refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" '
                f'orient="auto-start-reverse">{shape}</marker>'
            )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="title desc">\n'
            f'<title id="title">{escape(self.title)}</title>\n'
            f'<desc id="desc">{escape(self.desc)}</desc>\n'
            f"<defs>{''.join(defs)}</defs>\n"
            f'<rect width="{self.w}" height="{self.h}" fill="{self.t["bg"]}"/>\n'
            + "\n".join(self.body)
            + "\n</svg>\n"
        )


# =========================================================================================
# 00 · System overview
# =========================================================================================


def overview(s: Svg) -> None:
    s.title_("System overview")
    s.service(30, 190, 160, 64, "simulated", "Smart meters", "simulated · every 2 s")
    s.service(30, 352, 160, 64, "simulated", "Tariff feed", "simulated · daily")
    s.topic(230, 190, 170, 64, "neutral", "Event stream", "Kafka · 3 partitions")
    s.service(450, 88, 200, 64, "provisional", "Speed layer", "Spark Streaming · seconds")
    s.store(450, 278, 200, 80, "final", "Raw archive", "Parquet · append-only")
    s.service(705, 286, 180, 64, "final", "Batch layer", "Airflow · Spark · daily")
    s.store(935, 176, 140, 92, "neutral", "Serving DB", "PostgreSQL")
    s.service(1115, 190, 130, 64, "neutral", "API", "FastAPI · merge")
    s.service(1115, 330, 130, 64, "neutral", "Dashboard", "web")

    s.edge([(190, 222), (230, 222)], "simulated")
    s.edge([(400, 210), (425, 210), (425, 120), (450, 120)], "provisional")
    s.edge([(400, 236), (425, 236), (425, 318), (450, 318)], "final")
    s.edge([(650, 318), (705, 318)], "final", "replay")
    s.edge([(190, 384), (795, 384), (795, 350)], "simulated", "daily tariff", at=(480, 377))
    s.edge([(650, 120), (1005, 120), (1005, 176)], "provisional", "estimates", at=(830, 113))
    s.edge([(885, 318), (1005, 318), (1005, 268)], "final", "exact bills", at=(945, 311))
    s.edge([(1075, 222), (1115, 222)], "neutral")
    s.edge([(1180, 330), (1180, 254)], "neutral")
    s.legend(["simulated", "provisional", "final", "neutral"])


# =========================================================================================
# 01 · Containers and data flow
# =========================================================================================


def kafka_topic(s: Svg, x, y, w, h, name, tech, partitions=3):  # noqa: ANN001
    """A topic drawn as what it is: an ordered log, one lane per partition."""
    s.topic(x, y, w, h, "neutral", "", None)
    s.text(x + w / 2 - 4, y + 21, name, 14, "ink", 650, "middle")
    s.text(x + w / 2 - 4, y + 36, f"[{tech}]", 11, "muted", anchor="middle")
    for p in range(partitions):
        ly = y + 46 + p * 18
        s.text(x + 18, ly + 11, f"P{p}", 10, "muted", 700, mono=True)
        for j in range(5):
            s.rect(x + 40 + j * 27, ly, 24, 14, s.t["bg"], s.t["line"], r=2, sw=1)
        s.text(x + 40 + 5 * 27 + 2, ly + 11, "→", 11, "muted")


def data_flow(s: Svg) -> None:
    s.title_("Containers and data flow")
    s.service(30, 150, 150, 64, "simulated", "Meters", "simulated · every 2 s")
    s.service(30, 470, 150, 64, "simulated", "Tariff feed", "simulated · daily")

    kafka_topic(s, 210, 136, 210, 108, "meter.readings", "Kafka · key household_id")
    s.service(210, 336, 210, 64, "final", "Raw archiver", "Spark Streaming · append-only")
    s.store(210, 462, 210, 80, "neutral", "Landing", "MinIO · tariff_D.csv")

    s.rect(490, 112, 230, 208, s.fill("provisional"), s.stroke("provisional"), r=12, sw=1.6)
    s.text(605, 136, "Speed layer", 14, "ink", 650, "middle")
    s.text(605, 152, "[Spark Structured Streaming]", 11, "muted", anchor="middle")
    s.text(605, 166, "trigger 10 s · watermark 30 min", 11, "muted", anchor="middle")
    for y, name, tag in ((176, "Validation", "reject rules"),
                         (222, "Zone windows", "15 min"),
                         (268, "Household totals", "daily · tariff D−1")):
        s.rect(502, y, 206, 40, s.t["bg"], s.stroke("provisional"), r=6, sw=1)
        s.text(514, y + 25, name, 12.5, "ink", 650)
        s.text(698, y + 25, tag, 10.5, "muted", anchor="end")

    s.topic(770, 70, 170, 46, "unused", "readings.dlq", "Kafka · unread")
    s.store(490, 334, 230, 80, "final", "Master dataset", "Parquet · sim_date / hour")
    s.service(770, 342, 170, 64, "final", "Batch layer", "Airflow · Spark")

    s.group(990, 112, 180, 370, "PostgreSQL")
    s.store(1005, 150, 150, 58, "failure", "Rejects")
    s.store(1005, 222, 150, 58, "provisional", "Speed views")
    s.store(1005, 334, 150, 58, "final", "Batch views")
    s.store(1005, 410, 150, 58, "final", "Run ledger")

    s.service(1200, 262, 124, 64, "neutral", "API", "FastAPI · merge")
    s.service(1200, 400, 124, 64, "neutral", "Dashboard", "web")

    s.edge([(180, 182), (210, 182)], "simulated")
    s.edge([(180, 502), (210, 502)], "simulated")
    s.edge([(420, 196), (490, 196)], "provisional", "consume ×3", at=(455, 188))
    s.edge([(315, 244), (315, 336)], "final", "consume", at=(323, 294), anchor="start")
    s.edge([(420, 368), (490, 368)], "final", "append", at=(440, 361))
    s.edge([(420, 484), (465, 484), (465, 296), (502, 296)], "provisional", "tariff D−1",
           at=(470, 432), anchor="start")
    s.edge([(420, 522), (855, 522), (855, 406)], "final", "tariff D", at=(640, 515))
    s.edge([(720, 374), (770, 374)], "final", "rescan")
    s.edge([(708, 186), (745, 186), (745, 93), (770, 93)], "failure", "dead letters",
           at=(752, 140), anchor="start")
    s.edge([(708, 198), (1005, 198)], "failure", "invalid", at=(860, 191))
    s.edge([(708, 242), (1005, 242)], "provisional", "upsert", at=(860, 235))
    s.edge([(708, 288), (975, 288), (975, 262), (1005, 262)], "provisional", "upsert",
           at=(860, 281))
    s.edge([(940, 362), (1005, 362)], "final", "write", at=(972, 354))
    s.edge([(940, 388), (965, 388), (965, 440), (1005, 440)], "final", "commit",
           at=(958, 420), anchor="end")
    s.edge([(1170, 294), (1200, 294)], "neutral")
    s.edge([(1262, 400), (1262, 326)], "neutral", "poll 5 s", at=(1270, 368),
           anchor="start")
    s.legend(["simulated", "provisional", "final", "failure", "neutral", "unused"])


# =========================================================================================
# 02a–d · Sequence diagrams
# =========================================================================================


class Seq:
    """Lifelines and the usual grammar: numbered messages, replies, frames, dividers."""

    def __init__(self, s: Svg, lifelines, x0: float, step: float, top: float = 62):  # noqa: ANN001
        self.s, self.n = s, 0
        self.X = {k: x0 + i * step for i, (k, *_r) in enumerate(lifelines)}
        for key, name, tag, role in lifelines:
            x = self.X[key]
            s.raw(f'<line x1="{x}" y1="{top + 46}" x2="{x}" y2="{s.h - 50}" '
                  f'stroke="{s.t["line"]}" stroke-width="1.2" stroke-dasharray="4 4"/>')
            s.rect(x - step / 2 + 8, top, step - 16, 46, s.fill(role), s.stroke(role), r=8,
                   sw=1.4)
            s.text(x, top + 20, name, 13, "ink", 650, "middle", maxw=step - 24)
            s.text(x, top + 36, tag, 10.5, "muted", anchor="middle", maxw=step - 24)

    def msg(self, a: str, b: str, label: str, role: str, y: float, reply: bool = False) -> None:
        s, xa, xb = self.s, self.X[a], self.X[b]
        right = xb > xa
        tip = xb - 3 if right else xb + 3
        if reply:
            at, anchor = ((xa + xb) / 2, y - 7), "middle"
        else:
            at, anchor = (xa + (28 if right else -28), y - 7), ("start" if right else "end")
        s.edge([(xa, y), (tip, y)], role, label, at=at, anchor=anchor, dash=reply,
               open_head=reply)
        if not reply:
            self.n += 1
            s.num(xa + (14 if right else -14), y, self.n, role)

    def self_call(self, a: str, label: str, role: str, y: float) -> None:
        s, x = self.s, self.X[a]
        s.edge([(x, y - 7), (x + 24, y - 7), (x + 24, y + 9), (x + 3, y + 9)], role)
        self.n += 1
        s.num(x - 14, y, self.n, role)
        s.label(x - 28, y + 4, label, color="muted" if role == "neutral" else role,
                anchor="end")

    def frame(  # noqa: ANN001
        self, kind: str, guard: str, x1, y1, x2, y2, alt_y=None, alt_guard=None
    ):
        s = self.s
        s.rect(x1, y1, x2 - x1, y2 - y1, "none", s.t["muted"], r=4, sw=1)
        tw = text_width(kind, 11) + 14
        s.raw(f'<path d="M{x1},{y1} h{tw} v11 l-6,6 H{x1} z" fill="{s.t["panel"]}" '
              f'stroke="{s.t["muted"]}" stroke-width="1"/>')
        s.text(x1 + 6, y1 + 13, kind, 11, "ink", 700)
        s.text(x1 + tw + 8, y1 + 13, guard, 11, "muted", 600)
        if alt_y is not None:
            s.raw(f'<line x1="{x1}" y1="{alt_y}" x2="{x2}" y2="{alt_y}" '
                  f'stroke="{s.t["muted"]}" stroke-width="1" stroke-dasharray="6 4"/>')
            s.text(x1 + 8, alt_y + 15, alt_guard or "", 11, "muted", 600)

    def divider(self, label: str, y: float) -> None:
        s = self.s
        s.raw(f'<line x1="24" y1="{y}" x2="{s.w - 24}" y2="{y}" stroke="{s.t["ink"]}" '
              f'stroke-width="1.2" stroke-dasharray="10 5"/>')
        s.label(s.w / 2, y + 4, label, 12, "ink")


def seq_live(s: Svg) -> None:
    s.title_("Live path · during the day")
    q = Seq(s, [
        ("meters", "Meters", "simulated", "simulated"),
        ("kafka", "Kafka", "meter.readings", "neutral"),
        ("archiver", "Raw archiver", "Spark", "final"),
        ("minio", "MinIO", "S3", "neutral"),
        ("speed", "Speed layer", "Spark", "provisional"),
        ("pg", "PostgreSQL", "serving DB", "neutral"),
        ("api", "API", "FastAPI", "neutral"),
        ("dash", "Dashboard", "web", "neutral"),
    ], 95, 150)
    q.frame("loop", "[every 2 s · 50 meters]", 40, 122, 380, 176)
    q.msg("meters", "kafka", "publish · key household_id", "simulated", 160)

    q.frame("loop", "[continuous]", 170, 192, 690, 262)
    q.msg("kafka", "archiver", "consume", "final", 226)
    q.msg("archiver", "minio", "append Parquet", "final", 252)

    q.frame("loop", "[trigger every 10 s · 3 queries]", 170, 278, 940, 456)
    q.msg("kafka", "speed", "micro-batch", "provisional", 312)
    q.msg("speed", "minio", "tariff D−1 (cached)", "provisional", 340)
    q.self_call("speed", "validate · dedup · window", "provisional", 370)
    q.msg("speed", "pg", "upsert estimates", "provisional", 402)
    q.msg("speed", "pg", "rejects", "failure", 428)
    q.msg("speed", "kafka", "dead letters → readings.dlq", "failure", 448)

    q.frame("loop", "[every 5 s]", 620, 472, s.w - 22, 580)
    q.msg("dash", "api", "GET zones · bill", "neutral", 506)
    q.msg("api", "pg", "read speed views", "neutral", 532)
    q.msg("pg", "api", "rows", "neutral", 552, reply=True)
    q.msg("api", "dash", "provisional", "provisional", 572, reply=True)
    s.legend(["simulated", "provisional", "final", "failure", "neutral"])


def seq_billing(s: Svg) -> None:
    s.title_("Daily billing · after midnight")
    q = Seq(s, [
        ("tariff", "Tariff feed", "simulated", "simulated"),
        ("minio", "MinIO", "landing · raw", "neutral"),
        ("airflow", "Airflow", "daily_billing DAG", "control"),
        ("jobs", "Batch jobs", "Spark · Python", "final"),
        ("pg", "PostgreSQL", "serving DB", "neutral"),
        ("api", "API", "FastAPI", "neutral"),
    ], 110, 190)
    q.divider("simulated midnight · day D closes", 132)
    q.msg("tariff", "minio", "put tariff_D.csv", "simulated", 168)
    q.frame("loop", "[every 1 min]", 210, 186, 520, 230)
    q.msg("airflow", "minio", "list tariffs", "control", 216)
    q.self_call("airflow", "trigger billing__D", "control", 256)
    q.msg("airflow", "minio", "sensor: tariff_D ready", "control", 290)
    q.self_call("airflow", "grace 90 s", "control", 322)
    q.msg("airflow", "jobs", "run billing", "control", 356)
    q.msg("jobs", "pg", "ledger: running", "final", 384)
    q.msg("jobs", "minio", "read day D + tariff D", "final", 412)
    q.self_call("jobs", "dedup · validate · bill", "final", 444)
    q.msg("jobs", "pg", "bills + success · 1 txn", "final", 476)
    q.msg("airflow", "pg", "verify 50 bills", "control", 508)
    q.msg("airflow", "jobs", "rollup · reconcile · report", "control", 540)
    q.msg("jobs", "pg", "zone totals · reconciliation", "final", 568)
    q.msg("jobs", "minio", "report_D.md", "final", 596)
    q.msg("api", "pg", "get bill (D)", "neutral", 632)
    q.msg("pg", "api", "final", "final", 656, reply=True)
    s.legend(["simulated", "final", "control", "neutral"])


def seq_failure(s: Svg) -> None:
    s.title_("Billing failure and retry")
    q = Seq(s, [
        ("airflow", "Airflow", "daily_billing DAG", "control"),
        ("job", "Billing job", "Spark", "final"),
        ("pg", "PostgreSQL", "run ledger", "neutral"),
        ("api", "API", "FastAPI", "neutral"),
        ("prom", "Prometheus", "via SQL exporter", "control"),
    ], 120, 210)
    q.msg("airflow", "job", "run (attempt 1)", "control", 140)
    q.msg("job", "pg", "ledger: running", "final", 168)
    q.self_call("job", "error", "failure", 198)
    q.msg("job", "pg", "ledger: failed", "failure", 228)
    q.msg("job", "airflow", "exit 1", "failure", 252, reply=True)

    q.frame("loop", "[≤ 2 retries · 30 s backoff]", 40, 272, 700, 440)
    q.msg("airflow", "job", "run (retry)", "control", 304)
    q.frame("alt", "[succeeds]", 240, 320, 690, 430, 372, "[fails again]")
    q.msg("job", "pg", "bills + success", "final", 354)
    q.msg("job", "pg", "ledger: failed", "failure", 412)

    q.msg("api", "pg", "get bill (D)", "neutral", 466)
    q.msg("pg", "api", "no success → estimate", "provisional", 492, reply=True)
    q.msg("prom", "pg", "last success age", "control", 530)
    q.self_call("prom", "> 15 min → BatchSLAMiss", "failure", 562)
    s.legend(["provisional", "final", "failure", "control", "neutral"])


def seq_request(s: Svg) -> None:
    s.title_("Bill request · the merge function")
    q = Seq(s, [
        ("dash", "Dashboard", "web", "neutral"),
        ("api", "API", "FastAPI", "neutral"),
        ("ledger", "Run ledger", "PostgreSQL", "neutral"),
        ("batch", "Batch views", "PostgreSQL", "final"),
        ("speed", "Speed views", "PostgreSQL", "provisional"),
    ], 110, 200)
    q.msg("dash", "api", "GET bill (household, D)", "neutral", 140)
    q.msg("api", "ledger", "success run for D?", "neutral", 172)
    q.frame("alt", "[yes]", 40, 192, s.w - 22, 410, 272, "[no]")
    q.msg("api", "batch", "bill row", "final", 226)
    q.msg("api", "dash", "Final · source = batch", "final", 254, reply=True)
    q.msg("api", "speed", "estimate row", "provisional", 306)
    q.frame("alt", "[found]", 50, 322, s.w - 32, 400, 362, "[none]")
    q.msg("api", "dash", "Provisional · source = speed", "provisional", 352, reply=True)
    q.msg("api", "dash", "404", "neutral", 390, reply=True)
    s.legend(["provisional", "final", "neutral"])


# =========================================================================================
# 03 · Bill lifecycle (state machines)
# =========================================================================================


def _state(s: Svg, x, y, w, role, name):  # noqa: ANN001
    s.rect(x, y, w, 48, s.fill(role), s.stroke(role), r=24, sw=1.8)
    s.text(x + w / 2, y + 29, name, 14, "ink", 650, "middle")


def _start(s: Svg, x, y):  # noqa: ANN001
    s.raw(f'<circle cx="{x}" cy="{y}" r="7" fill="{s.t["ink"]}"/>')


def _end(s: Svg, x, y):  # noqa: ANN001
    s.raw(f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="{s.t["ink"]}" '
          f'stroke-width="1.6"/><circle cx="{x}" cy="{y}" r="5" fill="{s.t["ink"]}"/>')


def bill_states(s: Svg) -> None:
    s.title_("Bill lifecycle")
    s.group(24, 64, 540, 330, "Billing run")
    _start(s, 58, 150)
    _state(s, 96, 126, 150, "control", "Running")
    _state(s, 370, 126, 160, "final", "Succeeded")
    _state(s, 96, 276, 150, "failure", "Failed")
    _state(s, 370, 276, 160, "neutral", "Superseded")
    s.edge([(65, 150), (96, 150)], "control")
    s.edge([(246, 150), (370, 150)], "final", "commit")
    s.edge([(171, 174), (171, 276)], "failure", "error", at=(180, 230), anchor="start")
    s.edge([(450, 174), (450, 276)], "neutral", "restated", at=(459, 230), anchor="start")
    s.edge([(171, 324), (171, 352)], "neutral", head=False)
    _end(s, 171, 361)
    s.edge([(450, 324), (450, 352)], "neutral", head=False)
    _end(s, 450, 361)

    s.group(620, 64, 556, 330, "Bill served for day D")
    _start(s, 652, 150)
    _state(s, 690, 126, 150, "neutral", "Not found")
    _state(s, 970, 126, 170, "provisional", "Provisional")
    _state(s, 970, 276, 170, "final", "Final")
    s.edge([(659, 150), (690, 150)], "neutral")
    s.edge([(840, 150), (970, 150)], "provisional", "first estimate")
    s.edge([(1055, 174), (1055, 276)], "final", "day billed", at=(1064, 230), anchor="start")
    s.edge([(765, 174), (765, 300), (970, 300)], "final", "day billed", at=(868, 293))
    s.edge([(1030, 126), (1030, 100), (1090, 100), (1090, 126)], "provisional", "update",
           at=(1060, 93))
    s.edge([(1140, 290), (1162, 290), (1162, 312), (1140, 312)], "final")
    s.label(1100, 343, "restate", color="final")

    # The run ledger is what the API reads: Succeeded selects Final.
    s.edge([(530, 150), (590, 150), (590, 372), (1055, 372), (1055, 324)], "final",
           dotted=True)
    s.label(822, 366, "selects", color="final")
    s.legend(["provisional", "final", "failure", "control", "neutral"])


# =========================================================================================
# 04 · Fault handling
# =========================================================================================


def faults(s: Svg) -> None:
    s.title_("Fault handling")
    cols = [("Archive", 360), ("Speed layer", 560), ("Batch layer", 760), ("Effect", 960)]
    for name, cx in cols:
        s.text(cx, 84, name, 13, "muted", 700, "middle")
    s.raw(f'<line x1="24" y1="96" x2="{s.w - 24}" y2="96" stroke="{s.t["line"]}"/>')

    kept, rejected = ("Kept", "neutral"), ("Rejected", "failure")
    counted, removed = ("Counted", "neutral"), ("Removed", "neutral")
    reject_rate = ("Reject rate", "failure")
    # (fault, injected rate from config/base.yaml, outcome per column)
    rows = [
        ("Null field", "1 %", [kept, rejected, rejected, reject_rate]),
        ("Negative kWh", "0.5 %", [kept, rejected, rejected, reject_rate]),
        ("Unknown household", "0.5 %", [kept, rejected, rejected, reject_rate]),
        ("Out of order", "3 % · ≤ 30 min", [kept, counted, counted, None]),
        ("Duplicate", "2 %", [kept, removed, removed, None]),
        ("Late reading", "dropout · 0.2 %", [kept, ("Dropped", "provisional"),
                                            ("Counted", "final"), ("Data effect", "control")]),
        ("Stale tariff", "by design", [None, ("Priced D−1", "provisional"),
                                       ("Priced D", "final"), ("Tariff effect", "control")]),
    ]
    for i, (name, rate, cells) in enumerate(rows):
        y = 124 + i * 46
        if i % 2 == 0:
            s.rect(24, y - 21, s.w - 48, 42, s.t["panel"], r=6)
        s.text(40, y - 1, name, 14, "ink", 650)
        s.text(40, y + 14, rate, 11, "muted")
        for (_c, cx), cell in zip(cols, cells, strict=True):
            if cell is None:
                s.text(cx, y + 5, "—", 13, "muted", anchor="middle")
            else:
                s.chip(cx, y, cell[0], cell[1], w=130)

    y = 124 + len(rows) * 46 + 14
    s.rect(24, y, s.w - 48, 48, s.fill("control"), s.stroke("control"), r=8)
    s.text(s.w / 2, y + 30, "Estimate − Final  =  Tariff effect  +  Data effect", 15, "ink",
           700, "middle")
    s.legend(["provisional", "final", "failure", "control", "neutral"])


# =========================================================================================
# 05 · Monitoring and alerting
# =========================================================================================

# (rule, condition from config/prometheus/alert_rules.yml, severity)
RULES = [
    ("LowRenewableContribution", "< 0.15", "warning"),
    ("HighRejectRate", "> 5 %", "warning"),
    ("MeterDataStale", "> 2 min", "critical"),
    ("BatchSLAMiss", "> 15 min", "critical"),
    ("LambdaDivergenceHigh", "> 5 %", "warning"),
]


def alerting(s: Svg) -> None:
    s.title_("Monitoring and alerting")
    s.service(30, 110, 190, 64, "neutral", "Services", "metrics endpoints")
    s.service(30, 220, 190, 64, "neutral", "Pushgateway", "batch jobs")
    s.service(30, 330, 190, 64, "neutral", "SQL exporter", "PostgreSQL")

    s.rect(290, 80, 330, 330, s.fill("control"), s.stroke("control"), r=12, sw=1.6)
    s.text(455, 108, "Prometheus", 14, "ink", 650, "middle")
    s.text(455, 125, "[5 alert rules]", 11, "muted", anchor="middle")
    for i, (rule, cond, sev) in enumerate(RULES):
        y = 160 + i * 50
        s.rect(310, y - 18, 290, 36, s.t["bg"], s.stroke("control"), r=6, sw=1)
        s.text(320, y + 5, rule, 11.5, "ink", 600, mono=True)
        s.text(568, y + 5, cond, 11.5, "muted", 600, anchor="end")
        red = s.col("failure")
        s.raw(f'<circle cx="582" cy="{y}" r="6" fill="{red}"/>' if sev == "critical"
              else f'<circle cx="582" cy="{y}" r="5.5" fill="none" stroke="{red}" '
                   f'stroke-width="1.6"/>')

    s.service(690, 180, 180, 64, "control", "Alertmanager", "route · inhibit")
    s.service(950, 180, 160, 64, "neutral", "API webhook", "FastAPI")
    s.store(950, 300, 160, 74, "neutral", "Logs", "JSON")
    s.service(950, 80, 160, 56, "unused", "Pager / email", "not configured")
    s.service(290, 440, 330, 56, "control", "Grafana", "3 dashboards")

    for y in (142, 252, 362):
        s.edge([(220, y), (290, y)], "control", "scrape" if y == 142 else None, at=(255, 132))
    s.edge([(620, 212), (690, 212)], "failure", "fire", at=(655, 204))
    s.edge([(870, 212), (950, 212)], "failure", "notify", at=(910, 204))
    s.edge([(1030, 244), (1030, 300)], "neutral", "log", at=(1038, 276), anchor="start")
    s.edge([(780, 180), (780, 108), (950, 108)], "unused", dash=True)  # no such receiver
    s.edge([(455, 410), (455, 440)], "control", "query", at=(463, 430), anchor="start")

    # Severity key for the rule dots.
    red = s.col("failure")
    s.raw(f'<circle cx="702" cy="330" r="6" fill="{red}"/>')
    s.text(714, 334, "critical", 12, "muted")
    s.raw(f'<circle cx="702" cy="356" r="5.5" fill="none" stroke="{red}" stroke-width="1.6"/>')
    s.text(714, 360, "warning", 12, "muted")
    s.legend(["control", "failure", "neutral", "unused"])


# =========================================================================================
# Scenarios: swimlane timelines
# =========================================================================================

LANE_H = 58


def lanes(s: Svg, cols, rows) -> None:  # noqa: ANN001
    """cols: (x0, x1, header). rows: (y0, label)."""
    for x0, x1, header in cols:
        s.text((x0 + x1) / 2, 82, header, 13, "muted", 700, "middle")
    for y0, label in rows:
        s.rect(24, y0, s.w - 48, LANE_H, s.t["panel"], r=8)
        s.text(40, y0 + LANE_H / 2 + 5, label, 14, "ink", 650)
    for x0, _x1, _h in cols[1:]:
        s.raw(f'<line x1="{x0 - 4}" y1="66" x2="{x0 - 4}" y2="{rows[-1][0] + LANE_H + 6}" '
              f'stroke="{s.t["line"]}" stroke-dasharray="2 4"/>')


def seg(s: Svg, x0, x1, y0, role, text, tick=False):  # noqa: ANN001
    s.rect(x0, y0 + 10, x1 - x0, LANE_H - 20, s.fill(role), s.stroke(role), r=6, sw=1.3,
           dash=role == "unused")
    s.text((x0 + x1) / 2, y0 + LANE_H / 2 + 5, ("✓ " if tick else "") + text, 13, "ink", 600,
           "middle", maxw=x1 - x0 - 10)


def scenario_demo(s: Svg) -> None:
    s.title_("Scenario · provisional → final")
    cols = [(230, 560, "Day D open"), (568, 820, "Day D closes"), (828, 1176, "Next day")]
    lanes(s, cols, [(100, "Speed layer"), (170, "Batch layer"), (240, "GET bill (D)")])
    seg(s, 230, 556, 100, "provisional", "estimating D")
    seg(s, 568, 1176, 100, "provisional", "estimating D+1")
    seg(s, 230, 556, 170, "unused", "idle")
    seg(s, 576, 812, 170, "final", "rescan · bill D")
    seg(s, 836, 1000, 170, "final", "reconcile")
    seg(s, 230, 556, 240, "provisional", "Provisional")
    seg(s, 836, 1176, 240, "final", "Final")
    s.raw(f'<line x1="564" y1="66" x2="564" y2="310" stroke="{s.t["ink"]}" stroke-width="2"/>')
    s.label(564, 330, "midnight", 11.5, "ink")
    s.legend(["provisional", "final", "neutral"])


def scenario_kill(s: Svg) -> None:
    s.title_("Scenario · speed layer crash")
    cols = [(230, 420, "Before"), (428, 640, "Killed · 60 s"), (648, 880, "Restarted"),
            (888, 1176, "Day closes")]
    lanes(s, cols, [(100, "Speed layer"), (170, "Raw archive"), (240, "Live view"),
                    (310, "Bills")])
    seg(s, 230, 420, 100, "provisional", "running")
    seg(s, 428, 640, 100, "failure", "down")
    seg(s, 648, 880, 100, "provisional", "catch up")
    seg(s, 888, 1176, 100, "provisional", "running")
    seg(s, 230, 1176, 170, "final", "ingesting", tick=True)
    seg(s, 230, 420, 240, "neutral", "fresh")
    seg(s, 428, 640, 240, "failure", "stale")
    seg(s, 648, 1176, 240, "neutral", "fresh", tick=True)
    seg(s, 230, 880, 310, "final", "unchanged", tick=True)
    seg(s, 888, 1176, 310, "final", "billed in full", tick=True)
    s.legend(["provisional", "final", "failure", "neutral"])


def scenario_restate(s: Svg) -> None:
    s.title_("Scenario · restate a day")
    cols = [(230, 520, "Original run"), (528, 850, "Re-run 1"), (858, 1176, "Re-run 2")]
    lanes(s, cols, [(100, "Tariff D"), (170, "Served bills")])
    for y0, label in ((240, "Run ledger"), (330, "History")):  # taller lanes: they hold stacks
        s.rect(24, y0, s.w - 48, 82, s.t["panel"], r=8)
        s.text(40, y0 + 46, label, 14, "ink", 650)
    for x0, _x1, _h in cols[1:]:
        s.raw(f'<line x1="{x0 - 4}" y1="236" x2="{x0 - 4}" y2="418" '
              f'stroke="{s.t["line"]}" stroke-dasharray="2 4"/>')

    seg(s, 230, 520, 100, "neutral", "correct")
    seg(s, 528, 850, 100, "failure", "corrupted")
    seg(s, 858, 1176, 100, "neutral", "correct")
    seg(s, 230, 520, 170, "final", "original")
    seg(s, 528, 850, 170, "failure", "wrong")
    seg(s, 858, 1176, 170, "final", "corrected", tick=True)

    ledgers = [
        (375, [("success", "final")]),
        (689, [("superseded", "neutral"), ("success", "final")]),
        (1017, [("superseded", "neutral"), ("superseded", "neutral"), ("success", "final")]),
    ]
    for cx, items in ledgers:
        for i, (status, role) in enumerate(items):
            s.chip(cx + (i - (len(items) - 1) / 2) * 104, 281, status, role, w=98)
    history = [(375, ["original"]), (689, ["original", "wrong"]),
               (1017, ["original", "wrong", "corrected"])]
    for cx, items in history:
        for i, name in enumerate(items):
            role = "failure" if name == "wrong" else "final"
            s.chip(cx + (i - (len(items) - 1) / 2) * 104, 371, name, role, w=98)
    s.legend(["final", "failure", "neutral"])


# (drill, what it breaks, alert, fires from, fires by, drill ends) — real minutes.
DRILLS = [
    ("Stale data", "producer stopped", "MeterDataStale", 3, 3, 4),
    ("Rejects", "15 % invalid", "HighRejectRate", 2, 2, 3),
    ("Night", "no change", "LowRenewableContribution", 0, 7, 7),
    ("Billing SLA", "billing paused", "BatchSLAMiss", 15, 15, 17),
    ("Divergence", "60 % late", "LambdaDivergenceHigh", 8, 13, 13),
]


def scenario_drills(s: Svg) -> None:
    s.title_("Scenario · alert drills")
    x0, ppm = 230, 34.0

    def mx(m: float) -> float:
        return x0 + m * ppm

    top, rh = 96, 56
    for m in range(0, 18, 2):
        s.text(mx(m), top - 12, f"{m} min", 11, "muted", anchor="middle")
        s.raw(f'<line x1="{mx(m)}" y1="{top - 4}" x2="{mx(m)}" y2="{top + 5 * rh}" '
              f'stroke="{s.t["line"]}" stroke-dasharray="2 4"/>')
    s.text(850, top - 12, "alert", 11, "muted", 700)
    for i, (name, brk, alert, f0, f1, end) in enumerate(DRILLS):
        y = top + i * rh
        s.rect(24, y + 4, s.w - 48, rh - 8, s.t["panel"], r=8)
        s.text(40, y + 26, name, 14, "ink", 650)
        s.text(40, y + 43, brk, 11.5, "muted")
        s.rect(mx(0), y + 16, mx(end) - mx(0), 24, s.fill("failure"), s.stroke("failure"),
               r=5, sw=1)
        if f1 > f0:
            s.rect(mx(f0), y + 16, mx(f1) - mx(f0), 24, s.col("failure"), r=5)
        else:
            s.raw(f'<circle cx="{mx(f0)}" cy="{y + 28}" r="7" fill="{s.col("failure")}"/>')
        s.text(850, y + 33, alert, 12.5, "ink", 600, mono=True)

    y = s.h - 20
    red = s.col("failure")
    s.rect(24, y - 11, 22, 14, s.fill("failure"), red, r=3, sw=1)
    s.text(53, y, "fault active", 11.5, "muted")
    s.raw(f'<circle cx="160" cy="{y - 4}" r="6" fill="{red}"/>')
    s.text(172, y, "alert fires", 11.5, "muted")
    s.rect(262, y - 11, 22, 14, red, r=3)
    s.text(291, y, "fires within this window", 11.5, "muted")


# =========================================================================================


def _desc(*parts: str) -> str:
    return " ".join(parts)


DIAGRAMS = [
    ("00-overview", 1260, 470, "Voltstream system overview", _desc(
        "Simulated smart meters publish readings to a Kafka event stream. The speed layer",
        "turns them into estimates within seconds; a raw archive keeps every reading, which",
        "the batch layer replays once a day with that day's tariff to produce exact bills.",
        "Both write to a PostgreSQL serving database, read by the API and dashboard."),
     overview),
    ("01-data-flow", 1350, 600, "Voltstream containers and data flow", _desc(
        "Meters publish to the meter.readings topic. The speed layer consumes it, upserts",
        "speed views in PostgreSQL and sends invalid records to the rejects table and to a",
        "dead-letter topic nothing reads. The raw archiver appends every record to the",
        "master dataset. The batch layer rescans it with the day's tariff from the landing",
        "bucket, writes batch views and commits the run ledger; the speed layer prices with",
        "the previous day's tariff. The API reads PostgreSQL and the dashboard polls the API."),
     data_flow),
    ("02a-live-path", 1260, 640, "Voltstream sequence: live path during the day", _desc(
        "Every 2 s fifty meters publish to meter.readings, keyed by household_id. The raw",
        "archiver appends each record to Parquet in MinIO. Every 10 s the speed layer reads",
        "a micro-batch, loads the previous day's tariff, validates, deduplicates and windows",
        "it, upserts estimates into PostgreSQL, and sends rejects to PostgreSQL and the",
        "dead-letter topic. Every 5 s the dashboard reads them through the API."),
     seq_live),
    ("02b-daily-billing", 1240, 720, "Voltstream sequence: daily billing", _desc(
        "At simulated midnight the tariff feed writes tariff_D.csv. Airflow, polling every",
        "minute, triggers billing for D, waits for the file and a 90 s grace, then runs the",
        "billing job: ledger running, read day D and its tariff, bill, and commit the bills",
        "with a success row in one transaction. Airflow verifies 50 bills, then runs the",
        "rollup, reconciliation and report. The API now returns the final bill."),
     seq_billing),
    ("02c-billing-failure", 1180, 640, "Voltstream sequence: billing failure and retry", _desc(
        "A billing attempt marks the ledger running, fails, marks it failed and exits 1.",
        "Airflow retries up to twice with backoff; a successful retry commits bills and a",
        "success row. Until then the API keeps returning the speed estimate, and if no run",
        "succeeds for 15 minutes Prometheus fires BatchSLAMiss."),
     seq_failure),
    ("02d-bill-request", 1080, 480, "Voltstream sequence: bill request and merge", _desc(
        "The dashboard asks the API for a household's bill for day D. The API checks the run",
        "ledger for a successful run. If there is one it returns the batch row as final;",
        "otherwise it returns the speed estimate as provisional, or 404 if there is none."),
     seq_request),
    ("03-bill-states", 1200, 440, "Voltstream bill lifecycle", _desc(
        "Two state machines. A billing run goes from running to succeeded on commit or to",
        "failed on error; a succeeded run becomes superseded when the day is restated. The",
        "bill served for a day goes from not found to provisional on the first estimate,",
        "and to final once a run has succeeded; restating keeps it final."),
     bill_states),
    ("04-fault-handling", 1100, 560, "Voltstream fault handling", _desc(
        "How each layer treats bad data. The archive keeps everything. Null fields, negative",
        "kWh and unknown households are rejected by both layers. Out-of-order readings are",
        "counted and duplicates removed by both. Late readings are dropped by the speed layer",
        "but counted by the batch layer: the data effect. The speed layer prices with the",
        "previous day's tariff: the tariff effect. Estimate minus final equals the two."),
     faults),
    ("05-alerting", 1140, 540, "Voltstream monitoring and alerting", _desc(
        "Prometheus scrapes service metrics, a Pushgateway for batch jobs and an SQL",
        "exporter for PostgreSQL, and evaluates five alert rules. Alertmanager routes them",
        "to the API webhook, which writes logs; no pager or email is configured. Grafana",
        "queries Prometheus for three dashboards."),
     alerting),
    ("06-scenario-demo", 1200, 370, "Voltstream scenario: provisional to final", _desc(
        "While day D is open the speed layer estimates it and the bill is provisional.",
        "After midnight the batch layer bills and reconciles D, and the bill is final."),
     scenario_demo),
    ("07-scenario-kill", 1200, 420, "Voltstream scenario: speed layer crash", _desc(
        "The speed layer is down for 60 seconds: the live view goes stale while the raw",
        "archive keeps ingesting and bills are unchanged. After a restart it catches up,",
        "and the day of the crash is billed in full."),
     scenario_kill),
    ("08-scenario-restate", 1200, 460, "Voltstream scenario: restate a day", _desc(
        "A billed day is re-run with a corrupted tariff, giving wrong bills, then re-run",
        "with the correct tariff, giving corrected bills. Each re-run supersedes the last",
        "in the run ledger, and the history keeps every run's bills."),
     scenario_restate),
    ("09-scenario-drills", 1140, 430, "Voltstream scenario: alert drills", _desc(
        "Five drills on a timeline in minutes: stopping the producer fires MeterDataStale",
        "at about 3, invalid readings fire HighRejectRate at about 2, night fires",
        "LowRenewableContribution within 7, pausing billing fires BatchSLAMiss at 15, and",
        "late readings fire LambdaDivergenceHigh between 8 and 13."),
     scenario_drills),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, w, h, title, desc, draw in DIAGRAMS:
        for theme in THEMES:
            svg = Svg(f"{name}-{theme}", w, h, theme, title, desc)
            draw(svg)
            (OUT / f"{name}-{theme}.svg").write_text(svg.render(), encoding="utf-8")
    for warning in sorted(set(WARNINGS)):
        print("warning:", warning, file=sys.stderr)
    print(f"wrote {len(DIAGRAMS) * len(THEMES)} SVGs to {OUT}")
    return 1 if WARNINGS else 0


if __name__ == "__main__":
    raise SystemExit(main())
