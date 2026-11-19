#!/usr/bin/env python3
"""Generate the architecture diagrams in docs/architecture/diagrams/.

    python scripts/gen_diagrams.py

Every diagram is drawn twice, light and dark, from the same coordinates. The README
embeds both through <picture> + prefers-color-scheme. Stdlib only.

Colour is semantic and identical in every diagram (ROLES below):

    simulated    stand-ins for real meters and the utility (meter-producer, reference-dropper)
    provisional  the speed layer and what it writes
    final        the batch layer and what it writes
    failure      rejected records, failed runs, critical alerts
    control      orchestration and monitoring (Airflow, Prometheus, Alertmanager, Grafana)
    neutral      shared infrastructure (Kafka, MinIO, Postgres, the API)
    unused       written but never read, or the end of a path (dashed)

Diagram 0 is the plain-language overview; 1-5 are the detail; 6-9 follow the scenario
scripts (demo.sh, smoke_test.sh kill-speed-layer, backfill.sh, inject_faults.sh) step by
step, with ✓ for each of the script's own PASS checks.

Step numbers in the day sequence (diagram 2) are reused by the state machines (3) and the
alerting map (5); fault numbers F1–F6 and T in diagram 4 are reused by 1 and 5.

Every label is a real identifier from src/, airflow/, config/ or docker/. When the code
changes, change the label here and re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture" / "diagrams"

SANS = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, 'SFMono-Regular', 'Cascadia Mono', Consolas, Menlo, monospace"

# Neutrals lean slightly blue, toward the `final` accent.
THEMES = {
    "light": {
        "bg": "#f6f8fb",
        "panel": "#ebeff6",
        "ink": "#172033",
        "muted": "#4e5a71",
        "faint": "#8a94a8",
        "line": "#b8c2d3",
        "tint": 0.11,
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
        "faint": "#6b7890",
        "line": "#38465e",
        "tint": 0.17,
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

ROLE_LABELS = {
    "simulated": "simulated source",
    "provisional": "speed · provisional",
    "final": "batch · final",
    "failure": "rejected / failed",
    "control": "orchestration, monitoring",
    "neutral": "infrastructure",
    "unused": "never read / end of path",
}

WARNINGS: list[str] = []


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _mix(a: str, b: str, t: float) -> str:
    (r1, g1, b1), (r2, g2, b2) = _hex(a), _hex(b)
    return "#{:02x}{:02x}{:02x}".format(
        round(r1 * t + r2 * (1 - t)), round(g1 * t + g2 * (1 - t)), round(b1 * t + b2 * (1 - t))
    )


def text_width(s: str, size: float, mono: bool) -> float:
    return len(s) * size * (0.6 if mono else 0.54)


class Svg:
    def __init__(self, name: str, w: int, h: int, theme: str, title: str, desc: str):
        self.name, self.w, self.h = name, w, h
        self.t = THEMES[theme]
        self.title, self.desc = title, desc
        self.body: list[str] = []
        self.markers: set[tuple[str, bool]] = set()

    # -- colours ------------------------------------------------------------------------
    def col(self, key: str) -> str:
        return self.t["roles"].get(key) or self.t[key]

    def tint(self, role: str) -> str:
        if role == "neutral":
            return self.t["panel"]
        return _mix(self.t["roles"][role], self.t["bg"], self.t["tint"])

    # -- primitives ---------------------------------------------------------------------
    def fit(self, s: str, size: float, mono: bool, maxw: float) -> None:
        if text_width(s, size, mono) > maxw:
            WARNINGS.append(f"{self.name}: '{s}' ~{text_width(s, size, mono):.0f}px > {maxw:.0f}px")

    def text(
        self,
        x: float,
        y: float,
        s: str,
        size: float = 13,
        color: str = "ink",
        weight: int = 400,
        anchor: str = "start",
        mono: bool = False,
        maxw: float | None = None,
        italic: bool = False,
    ) -> None:
        if maxw is not None:
            self.fit(s, size, mono, maxw)
        style = ' font-style="italic"' if italic else ""
        self.body.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO if mono else SANS}" '
            f'font-size="{size}" font-weight="{weight}" fill="{self.col(color)}" '
            f'text-anchor="{anchor}"{style}>{escape(s)}</text>'
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str,
        stroke: str | None,
        r: float = 8,
        dash: bool = False,
        sw: float = 1.3,
    ) -> None:
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        if dash:
            st += ' stroke-dasharray="5 4"'
        self.body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" '
            f'fill="{fill}"{st}/>'
        )

    def box(self, x, y, w, h, role="neutral", dash=False, r=8, sw=1.3):  # noqa: ANN001
        stroke = self.t["line"] if role == "neutral" else self.col(role)
        fill = "none" if role == "unused" else self.tint(role)
        self.rect(x, y, w, h, fill, stroke, r=r, dash=dash or role == "unused", sw=sw)

    def group(self, x, y, w, h, label):  # noqa: ANN001
        """A real boundary: one service or container."""
        self.rect(x, y, w, h, "none", self.t["line"], r=10, sw=1.2)
        self.text(x + 12, y + 20, label, 12, "muted", 600, mono=True, maxw=w - 20)

    def marker(self, color_key: str, open_head: bool) -> str:
        self.markers.add((color_key, open_head))
        return f"ah-{color_key}-{'o' if open_head else 'f'}"

    def edge(
        self,
        pts: list[tuple[float, float]],
        role: str = "neutral",
        dash: bool = False,
        head: bool = True,
        open_head: bool = False,
        sw: float = 1.6,
        dotted: bool = False,
    ) -> None:
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        color = self.col("muted") if role == "neutral" else self.col(role)
        key = "muted" if role == "neutral" else role
        # Halo first, so a later edge that crosses this one shows a clean gap.
        self.body.append(
            f'<path d="{d}" fill="none" stroke="{self.t["bg"]}" stroke-width="{sw + 5}" '
            f'stroke-linejoin="round"/>'
        )
        attrs = f'fill="none" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round"'
        if dash:
            attrs += ' stroke-dasharray="6 4"'
        if dotted:  # "defines", not a flow: distinct from the dashed "never read"
            attrs += ' stroke-dasharray="1 4" stroke-linecap="round"'
        if head:
            attrs += f' marker-end="url(#{self.marker(key, open_head)})"'
        self.body.append(f'<path d="{d}" {attrs}/>')

    def label(  # noqa: ANN001
        self, x, y, s, size=11.5, color="muted", anchor="start", mono=False, weight=400
    ):
        """Text on a background plate, for labels that sit on top of lines.

        The plate is sized on the narrow side: a plate wider than its text paints a
        visible sliver over whatever box is next to it.
        """
        w = len(s) * size * (0.58 if mono else 0.49)
        x0 = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
        self.rect(x0 - 3, y - size, w + 6, size + 5, self.t["bg"], None, r=3)
        self.text(x, y, s, size, color, weight, anchor, mono)

    def badge(self, cx, cy, s, role="ink"):  # noqa: ANN001
        fill = self.col(role) if role != "ink" else self.t["ink"]
        if len(s) <= 2 and s.isdigit():
            self.body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="9" fill="{fill}"/>')
        else:
            w = text_width(s, 10.5, False) + 10
            self.rect(cx - w / 2, cy - 9, w, 18, fill, None, r=9)
        self.text(cx, cy + 3.8, s, 10.5, "bg", 700, "middle")

    def header(self, title: str, subtitle: str) -> None:
        self.text(24, 38, title, 20, "ink", 650)
        self.text(24, 61, subtitle, 13, "muted", maxw=self.w - 48)

    def legend(self, y: float, roles: list[str]) -> None:
        x = 24.0
        for role in roles:
            if role == "unused":
                self.rect(x, y - 11, 24, 14, "none", self.col("unused"), r=3, dash=True)
            else:
                self.box(x, y - 11, 24, 14, role, r=3)
            label = ROLE_LABELS[role]
            self.text(x + 31, y, label, 11.5, "muted")
            x += 31 + text_width(label, 11.5, False) + 20
        if x > self.w:
            WARNINGS.append(f"{self.name}: legend overflows ({x:.0f} > {self.w})")

    # -- output -------------------------------------------------------------------------
    def render(self) -> str:
        defs = []
        for key, open_head in sorted(self.markers):
            color = self.col(key)
            mid = f"ah-{key}-{'o' if open_head else 'f'}"
            shape = (
                f'<path d="M1,1 L9,5 L1,9" fill="none" stroke="{color}" stroke-width="1.6"/>'
                if open_head
                else f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/>'
            )
            defs.append(
                f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" '
                f'markerHeight="6.5" orient="auto-start-reverse">{shape}</marker>'
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
# 1. Where a meter reading goes
# =========================================================================================

DATA_FLOW_DESC = (
    "Data flow of the Voltstream Lambda pipeline. meter-producer publishes readings to the "
    "Kafka topic meter.readings (3 partitions, keyed by household_id). Two consumers read it "
    "independently: raw-archiver appends every record unchanged to Parquet in MinIO bucket "
    "voltstream-raw, and speed-layer runs three Spark Structured Streaming queries that upsert "
    "zone_metrics_rt and household_running_rt in Postgres and send rejected records to "
    "rejected_records and the meter.readings.dlq topic, which nothing consumes. "
    "reference-dropper writes tariff_D.csv to voltstream-landing when day D closes; the speed "
    "layer prices day D with the previous day's tariff, and the file's arrival triggers the "
    "Airflow daily_billing DAG, whose containers rescan the day from voltstream-raw and write "
    "pipeline_runs, household_bill_daily, household_bill_history, zone_metrics_daily and "
    "reconciliation_daily, plus an archived tariff and report in voltstream-archive. The "
    "weather file is written but never read. voltstream-api reads Postgres and merges: the "
    "batch bill if the day is finalised, otherwise the speed estimate; the dashboard polls it "
    "every 5 seconds."
)


def data_flow(s: Svg) -> None:
    s.header(
        "1 · Where a meter reading goes",
        "Every arrow is a read or a write in the code. Colour says which layer owns the data; "
        "F1–F6 are the injected faults in diagram 4.",
    )

    # -- A: simulated sources --------------------------------------------------------------
    s.box(20, 150, 190, 136, "simulated")
    s.text(34, 174, "meter-producer", 14, "ink", 650, mono=True)
    s.text(34, 196, "50 households · 5 zones", 12, "muted", maxw=170)
    s.text(34, 215, "one tick every 2 s real", 12, "muted", maxw=170)
    s.text(34, 234, "= 9.6 simulated minutes", 12, "muted", maxw=170)
    s.text(34, 262, "FaultInjector: F1–F6", 12, "simulated", 600, maxw=170)

    s.box(20, 380, 190, 92, "simulated")
    s.text(34, 404, "reference-dropper", 14, "ink", 650, mono=True)
    s.text(34, 426, "tariff_D when D closes", 12, "muted", maxw=170)
    s.text(34, 445, "weather_D when D starts", 12, "muted", maxw=170)

    # -- B: Kafka and MinIO ----------------------------------------------------------------
    s.group(240, 100, 240, 234, "kafka:9092")
    s.box(252, 130, 216, 58, "failure")
    s.text(264, 152, "meter.readings.dlq", 13, "ink", 600, mono=True, maxw=196)
    s.text(264, 172, "3 partitions · no consumer", 11.5, "muted", maxw=196)

    s.box(252, 200, 216, 122, "neutral")
    s.text(264, 222, "meter.readings", 13, "ink", 600, mono=True)
    s.text(264, 240, "keyed by household_id · 7 days", 11.5, "muted", maxw=196)
    # The topic is an ordered log: three partitions, offsets increasing to the right.
    base = [4182, 4227, 4163]
    for i, start in enumerate(base):
        y = 254 + i * 21
        s.text(264, y + 13, f"P{i}", 10.5, "muted", 600, mono=True)
        for j in range(5):
            s.rect(284 + j * 31, y, 29, 17, s.t["bg"], s.t["line"], r=2, sw=1)
            s.text(
                284 + j * 31 + 14.5, y + 12.5, str(start + j), 9, "muted", "middle", mono=True
            )
        s.text(441, y + 13, "→", 12, "muted")

    s.group(240, 372, 240, 330, "minio:9000 (S3)")
    s.box(252, 402, 216, 94, "neutral")
    s.text(264, 424, "voltstream-landing", 13, "ink", 600, mono=True)
    s.text(264, 444, "tariff/tariff_D.csv", 11.5, "ink", mono=True)
    s.box(260, 456, 200, 30, "unused", r=5)
    s.text(270, 475, "weather_D.csv · never read", 10.5, "faint", mono=True, maxw=186)

    s.box(252, 508, 216, 68, "final")
    s.text(264, 530, "voltstream-raw", 13, "ink", 600, mono=True)
    s.text(264, 549, "meter_readings/sim_date=D/", 11, "muted", mono=True, maxw=196)
    s.text(264, 566, "hour=H/*.parquet", 11, "muted", mono=True, maxw=196)

    s.box(252, 590, 216, 98, "final")
    s.text(264, 612, "voltstream-archive", 13, "ink", 600, mono=True)
    s.text(264, 632, "tariff/sim_date=D/run_id=R/", 11, "muted", mono=True, maxw=196)
    s.text(264, 650, "  (tariff billed with, Parquet)", 11, "muted", maxw=196)
    s.text(264, 672, "reports/report_D.md", 11, "muted", mono=True, maxw=196)

    # -- C: processing ---------------------------------------------------------------------
    s.box(512, 100, 236, 232, "provisional")
    s.text(526, 124, "speed-layer", 14, "ink", 650, mono=True)
    s.text(526, 143, "Spark Structured Streaming", 11.5, "muted", maxw=210)
    s.text(526, 159, "3 queries · trigger 10 s real", 11.5, "muted", maxw=210)
    rows = [
        (170, "speed_layer_validation", "split_valid_invalid() → rejects"),
        (222, "speed_layer_zone", "15 min windows, 30 min watermark"),
        (274, "speed_layer_household", "per day · priced with tariff D−1"),
    ]
    for y, name, sub in rows:
        s.rect(524, y, 212, 46, s.t["bg"], s.col("provisional"), r=6, sw=1)
        s.text(534, y + 19, name, 12, "ink", 600, mono=True, maxw=196)
        s.text(534, y + 36, sub, 10.5, "muted", maxw=196)

    s.box(512, 508, 236, 68, "final")
    s.text(526, 530, "raw-archiver", 14, "ink", 650, mono=True)
    s.text(526, 549, "no validation, dedup or filtering", 11, "muted", maxw=210)
    s.text(526, 566, "appends Parquet by sim_date/hour", 11, "muted", maxw=210)

    s.box(512, 606, 236, 222, "control")
    s.text(526, 630, "airflow", 14, "ink", 650, mono=True)
    s.text(526, 649, "tariff_watcher: every 1 min", 11, "muted", maxw=210)
    s.text(526, 664, "→ daily_billing, one run per day", 11, "muted", maxw=210)
    jobs = [
        (674, "daily_billing.py", "Spark"),
        (712, "daily_zone_rollup.py", "Spark"),
        (750, "voltstream-reconcile", "app"),
        (788, "generate_report.py", "app"),
    ]
    for y, name, kind in jobs:
        s.box(524, y, 212, 32, "final", r=5, sw=1)
        s.text(534, y + 21, name, 11.5, "ink", 600, mono=True, maxw=150)
        s.text(726, y + 21, kind, 10.5, "muted", anchor="end")

    # -- D: Postgres ---------------------------------------------------------------------------
    s.group(780, 100, 230, 728, "postgres:5432 / voltstream")
    tables = [
        (178, "rejected_records", "failure", "speed + billing"),
        (230, "zone_metrics_rt", "provisional", "speed"),
        (282, "household_running_rt", "provisional", "speed"),
        (420, "households", "neutral", "seed SQL"),
        (640, "pipeline_runs", "final", "billing, rollup"),
        (674, "household_bill_daily", "final", "billing"),
        (708, "household_bill_history", "final", "billing"),
        (742, "zone_metrics_daily", "final", "rollup"),
        (776, "reconciliation_daily", "final", "reconcile"),
    ]
    for y, name, role, writer in tables:
        s.box(792, y, 206, 30, role, r=5, sw=1)
        s.text(802, y + 19, name, 11, "ink", 600, mono=True, maxw=150)
        s.text(990, y + 19, writer, 9.5, "muted", anchor="end")
    s.text(792, 628, "daily_billing: one transaction", 9.5, "muted", maxw=210)

    # -- E: serving ----------------------------------------------------------------------------
    s.box(1042, 330, 218, 210, "neutral")
    s.text(1056, 354, "voltstream-api", 14, "ink", 650, mono=True)
    s.text(1056, 372, "FastAPI :8000", 11.5, "muted")
    s.text(1056, 400, "GET …/households/{id}/bill", 11, "ink", 600, mono=True, maxw=196)
    s.text(1056, 422, "merge, per request:", 11.5, "muted")
    s.text(1056, 444, "pipeline_runs success for D?", 11.5, "ink", maxw=196)
    s.text(1066, 466, "yes → household_bill_daily", 11.5, "final", 600, maxw=186)
    s.text(1066, 486, "no  → household_running_rt", 11.5, "provisional", 600, maxw=186)
    s.text(1066, 504, "(provisional=true)", 11, "muted", maxw=186)
    s.text(1056, 526, "neither → 404", 11.5, "muted", maxw=186)

    s.box(1042, 600, 218, 92, "neutral")
    s.text(1056, 624, "dashboard/", 14, "ink", 650, mono=True)
    s.text(1056, 644, "static files served by the API", 11.5, "muted", maxw=196)
    s.text(1056, 663, "polls the API every 5 s", 11.5, "muted", maxw=196)

    # -- edges ---------------------------------------------------------------------------------
    s.edge([(210, 232), (252, 232)], "simulated")  # produce
    s.label(214, 222, "produce", 10.5)
    s.edge([(210, 416), (252, 416)], "simulated")  # dropper writes landing
    s.edge([(468, 256), (512, 256)], "provisional")  # three queries read the topic
    s.edge([(468, 306), (490, 306), (490, 530), (512, 530)], "final")  # archiver reads topic
    s.edge([(512, 176), (468, 176)], "failure")  # rejects to DLQ
    s.edge([(512, 542), (468, 542)], "final")  # archiver writes raw
    # The speed layer reads the previous day's tariff from the landing zone.
    s.edge([(468, 444), (500, 444), (500, 300), (524, 300)], "provisional")
    # The tariff's arrival triggers billing, which also reads it: routed round the left.
    s.edge([(252, 444), (226, 444), (226, 850), (600, 850), (600, 828)], "control")
    s.label(236, 868, "tariff_D.csv arrives = day D is closed → triggers daily_billing, "
            "which prices D with it", 11, "control", weight=600)
    s.edge([(468, 562), (498, 562), (498, 620), (512, 620)], "final")  # billing rescans raw
    s.edge([(524, 690), (476, 690), (476, 640), (468, 640)], "final")  # tariff to archive
    s.edge([(524, 804), (482, 804), (482, 676), (468, 676)], "final")  # report to archive
    for y in (193, 245, 297):  # speed queries upsert
        s.edge([(736, y), (792, y)], "provisional" if y != 193 else "failure")
    s.edge([(748, 718), (784, 718)], "final")
    s.rect(784, 640, 3, 166, s.col("final"), None, r=1)  # bracket over the batch tables
    s.edge([(1010, 436), (1042, 436)], "neutral")
    s.label(1012, 428, "SQL", 10)
    s.edge([(1151, 600), (1151, 540)], "neutral")
    s.label(1157, 576, "GET", 10)

    s.legend(906, ["simulated", "provisional", "final", "failure", "control", "neutral", "unused"])


# =========================================================================================
# 2. One simulated day, as a sequence
# =========================================================================================

DAY_DESC = (
    "Sequence diagram of one simulated day D, which lasts 300 real seconds. In a loop every 2 "
    "real seconds meter-producer publishes 50 readings to Kafka. raw-archiver appends them to "
    "Parquet in MinIO and speed-layer upserts provisional figures into Postgres every 10 "
    "seconds, priced with the previous day's tariff, so the API answers a bill request with the "
    "speed row marked provisional. At T+5:00, simulated midnight, reference-dropper writes "
    "tariff_D.csv. Within a minute Airflow's tariff_watcher triggers daily_billing, which "
    "waits for the file, waits 90 seconds for late readings, then marks pipeline_runs running, "
    "rescans the day, and in one transaction replaces the bills and marks the run success. On "
    "an exception the run is marked failed and retried twice. Verification, zone rollup, "
    "reconciliation and the report follow. From the success commit on, the API serves the "
    "batch row as final."
)

# Lifelines, left to right: (key, label, sublabel, role).
LIFELINES = [
    ("producer", "meter-producer", "", "simulated"),
    ("kafka", "kafka", "meter.readings", "neutral"),
    ("archiver", "raw-archiver", "", "final"),
    ("speed", "speed-layer", "3 queries", "provisional"),
    ("pg", "postgres", "", "neutral"),
    ("api", "voltstream-api", "", "neutral"),
    ("dropper", "reference-dropper", "", "simulated"),
    ("minio", "minio", "3 buckets", "neutral"),
    ("airflow", "airflow", "DAG + task containers", "control"),
]


def day_sequence(s: Svg) -> None:
    s.header(
        "2 · One simulated day: when a bill becomes final",
        "T is real time since day D began; one simulated day = 300 s real (time_scale 288). "
        "Numbered steps are referenced by diagrams 3 and 5.",
    )
    x0, step = 205, 128
    X = {key: x0 + i * step for i, (key, *_rest) in enumerate(LIFELINES)}
    top, bottom = 90, s.h - 70

    for key, name, sub, role in LIFELINES:
        x = X[key]
        s.body.append(
            f'<line x1="{x}" y1="{top + 46}" x2="{x}" y2="{bottom}" stroke="{s.t["line"]}" '
            f'stroke-width="1.2" stroke-dasharray="4 4"/>'
        )
        s.box(x - 61, top, 122, 46, role)
        s.text(x, top + (20 if sub else 28), name, 11.5, "ink", 650, "middle", mono=True, maxw=118)
        if sub:
            s.text(x, top + 36, sub, 10, "muted", anchor="middle", maxw=118)

    n = 0
    y = 162

    def gutter(label: str, at: float) -> None:
        s.text(22, at + 4, label, 11, "muted", 600, mono=True)

    def divider(label: str, at: float) -> None:
        s.body.append(
            f'<line x1="150" y1="{at}" x2="{s.w - 20}" y2="{at}" stroke="{s.t["muted"]}" '
            f'stroke-width="1.2" stroke-dasharray="10 5"/>'
        )
        s.label((150 + s.w - 20) / 2, at + 4, label, 12, "ink", "middle", weight=600)

    def frame(kind: str, guard: str, x1: float, y1: float, x2: float, y2: float) -> None:
        s.rect(x1, y1, x2 - x1, y2 - y1, "none", s.t["muted"], r=4, sw=1.1)
        tw = text_width(kind, 11, False) + 16
        s.body.append(
            f'<path d="M{x1},{y1} h{tw} v12 l-7,7 H{x1} z" fill="{s.t["panel"]}" '
            f'stroke="{s.t["muted"]}" stroke-width="1.1"/>'
        )
        s.text(x1 + 6, y1 + 14, kind, 11, "ink", 700)
        s.text(x1 + tw + 8, y1 + 14, guard, 11, "muted", 600)

    def msg(a: str, b: str, label: str, role: str, at: float, ret: bool = False,
            numbered: bool = True) -> None:
        nonlocal n
        xa, xb = X[a], X[b]
        s.edge([(xa, at), (xb + (-4 if xb > xa else 4), at)], role, dash=ret, open_head=ret)
        color = role if role != "neutral" else "muted"
        right = xb > xa
        if numbered:
            n += 1
            bx = xa + 15 if right else xa - 15
            s.badge(bx, at - 11, str(n), role if role != "neutral" else "muted")
            if right:
                s.label(xa + 30, at - 6, label, 11.5, color)
            else:
                s.label(xa - 30, at - 6, label, 11.5, color, anchor="end")
        else:
            if right:
                s.label(xa + 8, at - 6, label, 11.5, color)
            else:
                s.label(xa - 8, at - 6, label, 11.5, color, anchor="end")

    def self_call(a: str, label: str, role: str, at: float) -> None:
        nonlocal n
        x = X[a]
        s.edge([(x, at - 8), (x + 26, at - 8), (x + 26, at + 8), (x + 4, at + 8)], role)
        n += 1
        s.badge(x - 15, at - 3, str(n), role)
        s.label(x - 30, at + 1, label, 11.5, role, anchor="end")

    def found(a: str, label: str, at: float) -> None:
        x = X[a]
        s.body.append(f'<circle cx="{x + 70}" cy="{at}" r="4" fill="{s.t["muted"]}"/>')
        s.edge([(x + 70, at), (x + 4, at)], "neutral")
        s.label(x + 8, at - 6, label, 11.5, "muted")

    # -- day D running ---------------------------------------------------------------------------
    divider("day D begins · simulated 00:00", y)
    gutter("T+0:00", y)
    y += 26
    frame("loop", "[every 2 s real · 150 ticks per simulated day]", 150, y, 420, y + 58)
    msg("producer", "kafka", "produce 50 readings (+ F1–F6)", "simulated", y + 42)
    y += 74
    guard = "[continuous · each query resumes from its own checkpoint]"
    frame("loop", guard, 270, y, 1150, y + 150)
    msg("kafka", "archiver", "records", "final", y + 42)
    msg("archiver", "minio", "append Parquet to voltstream-raw sim_date=D/hour=H", "final", y + 72)
    msg("kafka", "speed", "micro-batch every 10 s", "provisional", y + 104)
    upsert = "upsert zone_metrics_rt, household_running_rt (tariff D−1)"
    msg("speed", "pg", upsert, "provisional", y + 134)
    y += 184
    found("api", "dashboard: GET /bill?date=D", y)
    msg("api", "pg", "success row for D? no → household_running_rt", "provisional", y + 30)
    msg("pg", "api", "speed row", "neutral", y + 54, ret=True, numbered=False)
    s.edge([(X["api"], y + 80), (X["api"] + 66, y + 80)], "provisional", dash=True, open_head=True)
    s.label(X["api"] + 8, y + 74, "200 · source=speed · provisional=true", 11.5, "provisional",
            weight=600)
    y += 118

    # -- day D closes ----------------------------------------------------------------------------
    divider("T+5:00 · simulated midnight: D closes, D+1 begins (both loops carry on for D+1)", y)
    gutter("T+5:00", y)
    y += 38
    msg("dropper", "minio", "put tariff_D.csv (.tmp, then copy)", "simulated", y)
    gutter("≤ T+5:01", y)
    y += 36
    msg("airflow", "minio", "tariff_watcher: list tariff/ (every 1 min)", "control", y)
    y += 34
    self_call("airflow", "trigger daily_billing, run_id billing__D", "control", y)
    gutter("≤ T+6:01", y)
    y += 36
    msg("airflow", "minio", "wait_for_tariff: S3KeySensor, poke 15 s", "control", y)
    y += 34
    self_call("airflow", "wait_late_data_grace: until LastModified + 90 s", "control", y)
    msg("archiver", "minio", "meanwhile: F6 backfill for sim_date=D still landing (≤ 30 s)",
        "final", y + 30, ret=True, numbered=False)
    y += 70

    frame("alt", "[billing job succeeds]", 650, y, s.w - 22, y + 196)
    gutter("≥ T+6:31", y + 34)
    msg("airflow", "pg", "run_daily_billing: pipeline_runs ← running", "final", y + 34)
    msg("airflow", "minio", "rescan voltstream-raw sim_date=D, read tariff_D.csv", "final", y + 66)
    msg("airflow", "pg", "one transaction: demote old success · replace household_bill_daily",
        "final", y + 98)
    s.label(X["airflow"] - 30, y + 114, "append household_bill_history · pipeline_runs ← success",
            11.5, "final", anchor="end")
    s.body.append(
        f'<line x1="650" y1="{y + 132}" x2="{s.w - 22}" y2="{y + 132}" stroke="{s.t["muted"]}" '
        f'stroke-width="1.1" stroke-dasharray="6 4"/>'
    )
    s.text(658, y + 148, "[any exception]", 11, "muted", 600)
    msg("airflow", "pg", "pipeline_runs ← failed · DockerOperator retries 2 (30 s, exponential)",
        "failure", y + 178)
    y += 228

    msg("airflow", "pg", "verify_row_count = 50 · verify_bill_sanity", "final", y)
    y += 32
    msg("airflow", "pg", "run_zone_rollup → zone_metrics_daily", "final", y)
    y += 32
    msg("airflow", "pg", "run_reconciliation → reconciliation_daily (S − B split)", "final", y)
    y += 32
    msg("airflow", "minio", "generate_report → voltstream-archive/reports/report_D.md", "final", y)
    y += 50

    found("api", "dashboard: GET /bill?date=D", y)
    s.label(X["api"] + 8, y + 16, "any time after step 14 commits", 10.5, "muted")
    msg("api", "pg", "success row for D? yes → household_bill_daily", "final", y + 42)
    msg("pg", "api", "batch row", "neutral", y + 66, ret=True, numbered=False)
    s.edge([(X["api"], y + 92), (X["api"] + 66, y + 92)], "final", dash=True, open_head=True)
    s.label(X["api"] + 8, y + 86, "200 · source=batch · provisional=false", 11.5, "final",
            weight=600)

    # Diagrams 3 and 5 cite steps 5, 12, 14 and 15 by number.
    if n != 20:
        WARNINGS.append(f"{s.name}: expected 20 numbered steps, drew {n}; fix the references")
    s.legend(s.h - 26, ["simulated", "provisional", "final", "failure", "control", "neutral"])


# =========================================================================================
# 3. Which bill GET /bill returns
# =========================================================================================

STATES_DESC = (
    "Two state machines. Left: a pipeline_runs row for one billing attempt (layer batch_billing) "
    "starts running, then becomes success when finalise commits, or failed on an exception or "
    "when the next attempt finds it abandoned; a success becomes superseded when a later "
    "restatement commits, in the same transaction, and a partial unique index allows at most "
    "one success per day. Right: what GET /api/v1/households/{id}/bill returns for a day. It "
    "starts at 404, becomes provisional (the speed row, priced with the previous day's tariff) "
    "after the first household micro-batch, and becomes final (the batch row) once a success "
    "row exists. A restatement keeps it final with new figures. No transition leaves final."
)


def state(s: Svg, x, y, w, h, role, title, lines):  # noqa: ANN001
    s.box(x, y, w, h, role, r=14, sw=1.8)
    s.text(x + w / 2, y + 24, title, 14, "ink", 700, "middle", mono=True)
    for i, line in enumerate(lines):
        s.text(x + w / 2, y + 44 + i * 17, line, 11.5, "muted", anchor="middle", maxw=w - 16)


def start_dot(s: Svg, x, y):  # noqa: ANN001
    s.body.append(f'<circle cx="{x}" cy="{y}" r="7" fill="{s.t["ink"]}"/>')


def end_dot(s: Svg, x, y):  # noqa: ANN001
    s.body.append(
        f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="{s.t["ink"]}" stroke-width="1.6"/>'
        f'<circle cx="{x}" cy="{y}" r="5" fill="{s.t["ink"]}"/>'
    )


def bill_states(s: Svg) -> None:
    s.header(
        "3 · Which bill GET /bill returns, and why it never goes back",
        "Left: the run ledger that decides it. Right: what the API serves. (n) = step n in "
        "diagram 2.",
    )
    # -- left: pipeline_runs ---------------------------------------------------------------------
    s.group(20, 92, 600, 470, "pipeline_runs · one row per attempt · layer = 'batch_billing'")
    start_dot(s, 56, 186)
    state(s, 96, 158, 170, 58, "control", "running", [])
    state(s, 410, 158, 170, 74, "final", "success", ["is_day_finalised(D)", "is true"])
    state(s, 96, 388, 170, 58, "failure", "failed", [])
    state(s, 410, 388, 170, 74, "neutral", "superseded", ["kept for lineage"])
    s.edge([(63, 186), (96, 186)], "control")
    s.label(40, 150, "ledger.start_run (12)", 11.5, "control", weight=600)
    s.edge([(266, 186), (410, 186)], "final")
    s.label(276, 178, "finalise() commits (14)", 11.5, "final", weight=600)
    s.edge([(181, 216), (181, 388)], "failure")
    s.label(190, 270, "exception → fail_run (15)", 11.5, "failure", weight=600)
    s.label(190, 290, "or the attempt was killed: the", 11, "muted")
    s.label(190, 306, "next start_run marks it failed", 11, "muted")
    s.edge([(495, 232), (495, 388)], "neutral")
    s.label(486, 272, "a later run's finalise", 11.5, "ink", anchor="end", weight=600)
    s.label(486, 290, "demotes it, in the same", 11, "muted", anchor="end")
    s.label(486, 306, "transaction (restatement)", 11, "muted", anchor="end")
    end_dot(s, 181, 486)
    s.edge([(181, 446), (181, 474)], "neutral", head=False)
    end_dot(s, 495, 500)
    s.edge([(495, 462), (495, 488)], "neutral", head=False)
    s.text(36, 536, "idx_runs_date_layer_success (partial unique index): at most one 'success' "
           "per (sim_date, layer).", 10.5, "muted", maxw=570)
    s.text(36, 552, "So 'a success row exists' is exact, even after a restatement.", 11,
           "muted", maxw=570)

    # -- right: the API ------------------------------------------------------------------------
    s.group(660, 92, 600, 470, "GET /api/v1/households/{id}/bill?date=D")
    start_dot(s, 692, 186)
    state(s, 724, 158, 160, 58, "neutral", "404", ["no row in either view"])
    state(s, 1050, 150, 190, 90, "provisional", "provisional",
          ["source = speed", "tariff_date = D−1", "household_running_rt"])
    state(s, 1050, 372, 190, 90, "final", "final",
          ["source = batch", "tariff_date = D", "household_bill_daily"])
    s.edge([(699, 186), (724, 186)], "neutral")
    s.edge([(884, 186), (1050, 186)], "provisional")
    s.label(892, 168, "first household upsert (5);", 11.5, "provisional", weight=600)
    s.label(892, 206, "needs tariff D−1 in landing", 11, "muted")
    # Self-loop on provisional: re-upserted every trigger.
    s.edge([(1110, 150), (1110, 122), (1180, 122), (1180, 150)], "provisional")
    s.label(1086, 114, "re-upserted every 10 s (5)", 11, "provisional", weight=600)
    s.edge([(1145, 240), (1145, 372)], "final")
    s.label(1154, 292, "success row", 11.5, "final", weight=600)
    s.label(1154, 310, "exists (14)", 11.5, "final", weight=600)
    s.edge([(799, 216), (799, 417), (1050, 417)], "final")
    s.label(810, 408, "success row, no speed row (14)", 11, "final", weight=600)
    # Self-loop on final: a restatement replaces the figures.
    s.edge([(1110, 462), (1110, 490), (1180, 490), (1180, 462)], "final")
    s.label(1040, 508, "restatement commits: new figures (14)", 11, "final", weight=600)
    s.text(676, 536, "No transition leaves final: a success row is only demoted inside the "
           "transaction", 11, "muted", maxw=570)
    s.text(676, 552, "that commits its replacement, so there is no instant with no success row.",
           11, "muted", maxw=570)

    # The bridge between the two machines.
    s.edge([(580, 196), (640, 196), (640, 440), (1050, 440)], "final", head=False, dotted=True)
    s.label(648, 470, "is_day_finalised(D) = SELECT 1 … status = 'success'", 11, "final",
            mono=True)

    s.legend(s.h - 26, ["provisional", "final", "failure", "control", "neutral"])


# =========================================================================================
# 4. What happens to a bad or late reading
# =========================================================================================

FAULTS_DESC = (
    "Matrix of the six faults FaultInjector injects and one deliberate design choice, and how "
    "each layer handles them. raw-archiver writes every record unchanged. F1 null_field, F2 "
    "negative_kwh and F3 unknown_household are rejected by both layers: the speed layer writes "
    "them to rejected_records and meter.readings.dlq, the billing job to rejected_records only; "
    "they drive the HighRejectRate alert. F4 out-of-order readings within 30 simulated minutes "
    "are counted by both. F5 duplicates are removed by both on (meter_id, event_ts). F6 dropout "
    "backfill older than the 30-minute watermark is dropped by the speed layer but counted by "
    "the batch rescan, which is the data effect. T: the speed layer prices day D with the "
    "previous day's tariff, the batch layer with D's, which is the tariff effect. "
    "Reconciliation splits speed minus batch exactly into the two effects and pushes the mean "
    "percentage to voltstream_lambda_divergence, which drives LambdaDivergenceHigh."
)


def faults(s: Svg) -> None:
    s.header(
        "4 · What happens to a bad, repeated or late reading",
        "Rows are what FaultInjector does (rates from config/base.yaml) plus one deliberate "
        "staleness, T. Columns follow the reading through the pipeline.",
    )
    cols = [(20, 270), (302, 170), (484, 256), (752, 256), (1020, 240)]
    heads = [
        "injected by FaultInjector",
        "raw-archiver",
        "speed-layer (seconds)",
        "daily_billing (after D + 90 s)",
        "where it shows up",
    ]
    for (x, w), h in zip(cols, heads, strict=True):
        s.text(x + 4, 104, h, 12, "muted", 700, maxw=w)
    s.body.append(
        f'<line x1="20" y1="114" x2="{s.w - 20}" y2="114" stroke="{s.t["line"]}" stroke-width="1"/>'
    )

    rows = [
        ("F1", "null_field", '1 % · household_id = ""'),
        ("F2", "negative_kwh", "0.5 % · kWh = −(|kWh| + 1)"),
        ("F3", "unknown_household", "0.5 % · household_id = HH-9999"),
        ("F4", "out_of_order", "3 % · event_ts set 1–30 sim min back"),
        ("F5", "duplicate", "2 %, on top of any other fault"),
        ("F6", "dropout", "0.2 %/meter-tick · offline 30 s real,"),
        ("T", "stale tariff (by design)", "speed prices D with tariff D−1;"),
    ]
    extra = {
        "F6": "then backfills, event_ts unchanged",
        "T": "block_1_rate +0.50 on even days",
    }
    top, rh = 124, 66
    ys = {tag: top + i * rh for i, (tag, *_r) in enumerate(rows)}
    for tag, name, sub in rows:
        y = ys[tag]
        s.badge(38, y + 20, tag, "simulated" if tag != "T" else "provisional")
        s.text(60, y + 25, name, 13, "ink", 650, mono=tag != "T", maxw=226)
        s.text(60, y + 43, sub, 11, "muted", maxw=226)
        if tag in extra:
            s.text(60, y + 58, extra[tag], 11, "muted", maxw=226)
        if tag != "F1":
            s.body.append(
                f'<line x1="20" y1="{y}" x2="{s.w - 20}" y2="{y}" stroke="{s.t["line"]}" '
                f'stroke-width="0.8" stroke-dasharray="2 4"/>'
            )

    def cell(col: int, y0: float, nrows: int, role: str, lines: list[tuple[str, bool]]) -> None:
        x, w = cols[col]
        h = nrows * rh - 10
        s.box(x, y0 + 5, w, h, role, r=7, sw=1.2)
        block = len(lines) * 17
        ty = y0 + 5 + h / 2 - block / 2 + 12
        for i, (line, mono) in enumerate(lines):
            s.text(x + 10, ty + i * 17, line, 11.5 if not mono else 11, "ink", mono=mono,
                   maxw=w - 18)

    # raw-archiver: one cell for every injected fault, because it treats them all alike.
    cell(1, ys["F1"], 6, "final", [("every record kept,", False), ("byte for byte:", False),
                                   ("no validation,", False), ("no dedup.", False),
                                   ("Lands in its sim_date", False), ("by event_ts.", False)])
    cell(1, ys["T"], 1, "neutral", [("—", False)])

    # F1–F3: identical handling, so one merged cell per layer.
    cell(2, ys["F1"], 3, "failure", [
        ("rejected: first matching rule wins", False),
        ("→ rejected_records stage=speed", True),
        ("→ meter.readings.dlq", True),
    ])
    cell(3, ys["F1"], 3, "failure", [
        ("rejected by the same rules", False),
        ("→ rejected_records stage=batch", True),
        ("day's batch rejects replaced per run;", False),
        ("never sent to the DLQ", False),
    ])
    cell(4, ys["F1"], 3, "failure", [
        ("voltstream_records_", True),
        ("  rejected_total{reason}", True),
        ("→ HighRejectRate", True),
        ("  (> 5 % of consumed, 1 m)", False),
    ])

    cell(2, ys["F4"], 1, "neutral", [("counted: inside the 30-min watermark;", False),
                                     ("window re-upserted (update mode)", False)])
    cell(3, ys["F4"], 1, "neutral", [("counted", False)])
    cell(4, ys["F4"], 1, "neutral", [("no gap expected", False)])

    cell(2, ys["F5"], 1, "neutral", [("removed: dropDuplicates(", True),
                                     ("  meter_id, event_ts)", True)])
    cell(3, ys["F5"], 1, "neutral", [("removed: row_number() on the same", False),
                                     ("key, earliest ingest_ts wins", False)])
    cell(4, ys["F5"], 1, "neutral", [("household_bill_daily.", True),
                                     ("  duplicates_removed", True)])

    cell(2, ys["F6"], 1, "provisional", [("partly lost: backfill older than", False),
                                         ("the watermark is dropped → kWh low", False)])
    cell(3, ys["F6"], 1, "final", [("counted: the closed day is", False),
                                   ("rescanned from voltstream-raw", False)])
    cell(4, ys["F6"], 1, "final", [("data_effect = C − B", True)])

    cell(2, ys["T"], 1, "provisional", [("priced with tariff D−1", False)])
    cell(3, ys["T"], 1, "final", [("priced with tariff_D.csv", False)])
    cell(4, ys["T"], 1, "provisional", [("tariff_effect = S − C", True)])

    # The reconciliation identity, under the matrix.
    y = top + len(rows) * rh + 12
    s.box(20, y, s.w - 40, 74, "control", r=8)
    s.text(36, y + 24, "voltstream-reconcile, per household, in Decimal:", 12, "ink", 650)
    s.text(372, y + 24, "S − B = tariff_effect + data_effect   (exactly)", 13, "ink", 700,
           mono=True)
    s.text(36, y + 46, "S = speed estimate (tariff D−1) · B = batch final (tariff D) · C = "
           "speed kWh priced with tariff D, by core/tariff.py", 11.5, "muted", maxw=s.w - 72)
    s.text(36, y + 64, "mean % → voltstream_lambda_divergence (pushgateway) → "
           "LambdaDivergenceHigh when > 5", 11.5, "muted", mono=False, maxw=s.w - 72)

    s.legend(s.h - 26, ["simulated", "provisional", "final", "failure", "control", "neutral"])


# =========================================================================================
# 5. How a problem reaches someone
# =========================================================================================

ALERTS_DESC = (
    "Alerting path. Prometheus scrapes every 15 seconds from three kinds of source: the "
    "services' own metrics on port 8001, a Pushgateway that the short-lived batch containers "
    "push to as they exit, and sql-exporter, which turns two Postgres queries into gauges. "
    "Five rules: LowRenewableContribution and HighRejectRate from the speed layer's metrics, "
    "MeterDataStale and BatchSLAMiss from sql-exporter, and LambdaDivergenceHigh from the "
    "reconciliation gauge. Alertmanager routes critical and warning alerts to two receivers, "
    "and suppresses LowRenewableContribution while MeterDataStale fires for the same zone. "
    "Both receivers post to the API's webhook, which writes one log line per alert. No email, "
    "chat or pager receiver is configured. Grafana reads Prometheus and Postgres for its "
    "dashboards but plays no part in alerting."
)


def alerting(s: Svg) -> None:
    s.header(
        "5 · How a problem reaches someone",
        "config/prometheus/alert_rules.yml and config/alertmanager/alertmanager.yml. "
        "F1–F6 and T are from diagram 4; (14) is the step in diagram 2.",
    )

    # -- sources ---------------------------------------------------------------------------------
    srcs = [
        (130, 150, "scrape :8001 (and api:8000)", [
            ("meter-producer, speed-layer, raw-archiver", False),
            ("voltstream_zone_renewable_ratio", True),
            ("voltstream_records_rejected_total", True),
            ("voltstream_events_consumed_total", True),
            ("voltstream_consumer_lag, …_e2e_latency", True),
        ]),
        (298, 150, "sql-exporter:9399", [
            ("queries postgres as voltstream_reader", False),
            ("voltstream_pg_zone_data_age_seconds", True),
            ("  ← zone_metrics_rt.updated_at", True),
            ("voltstream_pg_billing_last_success_", True),
            ("  timestamp_seconds ← pipeline_runs", True),
        ]),
        (466, 110, "pushgateway:9091", [
            ("pushed by batch containers as they exit", False),
            ("voltstream_lambda_divergence", True),
            ("voltstream_batch_duration_seconds", True),
        ]),
    ]
    for y, h, name, lines in srcs:
        s.box(20, y, 340, h, "neutral")
        s.text(34, y + 22, name, 13, "ink", 650, mono=True)
        for i, (line, mono) in enumerate(lines):
            s.text(34, y + 44 + i * 19, line, 11 if mono else 11.5, "muted", mono=mono, maxw=316)

    # -- prometheus rules ------------------------------------------------------------------
    s.group(390, 96, 460, 504, "prometheus:9090 · scrape 15 s · evaluate 15 s")
    rules = [
        (136, "LowRenewableContribution", "voltstream_zone_renewable_ratio < 0.15", None,
         "for 10s", "warning", "latest window's solar / consumption"),
        (206, "HighRejectRate", "rejected / consumed {layer=\"speed\"} [5m]", "> 0.05",
         "for 1m", "warning", "← F1–F3"),
        (306, "MeterDataStale", "voltstream_pg_zone_data_age_seconds > 120", None,
         "for 30s", "critical", "zone_metrics_rt silent for 2 min"),
        (376, "BatchSLAMiss", "time() − voltstream_pg_billing_last_",
         "success_timestamp_seconds > 900", "", "critical", "no billing success (14) for 15 min"),
        (476, "LambdaDivergenceHigh", "voltstream_lambda_divergence",
         "{job=\"reconciliation\"} > 5", "", "warning", "← F6 + T"),
    ]
    rule_mid = {}
    for y, name, expr1, expr2, for_, sev, cause in rules:
        s.box(402, y, 436, 62, "control", r=6, sw=1)
        s.text(414, y + 19, name, 12.5, "ink", 700, mono=True)
        s.text(414, y + 36, expr1 if not expr2 else expr1, 10.5, "muted", mono=True, maxw=300)
        if expr2:
            s.text(414, y + 51, expr2, 10.5, "muted", mono=True, maxw=300)
        s.text(826, y + 54, cause, 10.5, "ink", 600, anchor="end", maxw=200)
        # severity: critical filled, warning outlined, both in the failure colour
        cw = text_width(sev, 10.5, False) + 14
        if sev == "critical":
            s.rect(826 - cw, y + 8, cw, 17, s.col("failure"), None, r=8)
            s.text(826 - cw / 2, y + 20.5, sev, 10.5, "bg", 700, "middle")
        else:
            s.rect(826 - cw, y + 8, cw, 17, "none", s.col("failure"), r=8, sw=1.2)
            s.text(826 - cw / 2, y + 20.5, sev, 10.5, "failure", 700, "middle")
        if for_:
            s.text(826 - cw - 8, y + 20.5, for_, 10.5, "muted", anchor="end", mono=True)
        rule_mid[name] = y + 31

    for src_y, h, targets in ((130, 150, ("LowRenewableContribution", "HighRejectRate")),
                              (298, 150, ("MeterDataStale", "BatchSLAMiss")),
                              (466, 110, ("LambdaDivergenceHigh",))):
        for t in targets:
            yy = rule_mid[t]
            s.edge([(360, yy), (402, yy)], "control")

    # -- alertmanager ----------------------------------------------------------------------------
    s.box(882, 136, 200, 402, "control")
    s.text(896, 160, "alertmanager:9093", 13, "ink", 650, mono=True)
    s.text(896, 180, "routes by severity", 11.5, "muted")
    s.rect(894, 196, 176, 64, s.t["bg"], s.col("failure"), r=6, sw=2.2)
    s.text(904, 216, "critical-log", 12, "ink", 700, mono=True)
    s.text(904, 234, "group_wait 10s", 11, "muted", mono=True)
    s.text(904, 250, "repeat_interval 30m", 11, "muted", mono=True)
    s.rect(894, 272, 176, 64, s.t["bg"], s.col("failure"), r=6, sw=1)
    s.text(904, 292, "warning-log", 12, "ink", 700, mono=True)
    s.text(904, 310, "group_wait 30s", 11, "muted", mono=True)
    s.text(904, 326, "repeat_interval 1h", 11, "muted", mono=True)
    s.text(896, 370, "inhibit_rules:", 11.5, "ink", 700)
    for i, line in enumerate(["MeterDataStale", "silences", "LowRenewableContribution",
                              "in the same grid_zone", "(no data ≠ low renewables)"]):
        s.text(896, 390 + i * 17, line, 11, "muted", mono=i in (0, 2), maxw=176)

    # rules → alertmanager over one bus
    for name, yy in rule_mid.items():
        s.edge([(838, yy), (860, yy)], "control", head=False)
    s.edge([(860, rule_mid["LowRenewableContribution"]), (860, rule_mid["LambdaDivergenceHigh"])],
           "control", head=False)
    s.edge([(860, 330), (882, 330)], "control")

    # -- webhook ---------------------------------------------------------------------------------
    s.box(1112, 136, 148, 252, "neutral")
    s.text(1124, 160, "voltstream-api", 13, "ink", 650, mono=True)
    s.text(1124, 182, "POST /api/v1/", 11, "ink", 600, mono=True)
    s.text(1124, 198, "alerts/webhook", 11, "ink", 600, mono=True)
    s.text(1124, 224, "one JSON log line", 11.5, "muted")
    s.text(1124, 240, "per alert:", 11.5, "muted")
    s.text(1124, 264, "WARNING", 11, "failure", 700, mono=True)
    s.text(1124, 280, "  \"alert firing\"", 11, "muted", mono=True)
    s.text(1124, 304, "INFO", 11, "ink", 700, mono=True)
    s.text(1124, 320, "  \"alert resolved\"", 11, "muted", mono=True)
    s.text(1124, 346, "send_resolved: true", 10.5, "muted", mono=True)
    s.edge([(1070, 228), (1112, 228)], "failure")
    s.edge([(1070, 304), (1112, 304)], "failure")

    s.box(1112, 410, 148, 128, "unused")
    for i, line in enumerate(["end of the path:", "no email, chat or", "pager receiver is",
                              "configured. Someone", "has to read the log."]):
        s.text(1124, 434 + i * 19, line, 11.5, "muted", 600 if i == 0 else 400, maxw=128)
    s.edge([(1186, 388), (1186, 410)], "unused", dash=True)

    # -- grafana: a reader, not part of the path ---------------------------------------------------
    s.box(390, 624, 460, 58, "control")
    s.text(404, 646, "grafana:3000", 13, "ink", 650, mono=True)
    grafana = "3 dashboards · reads Prometheus + postgres · not on the alert path"
    s.text(404, 666, grafana, 11, "muted", maxw=436)
    s.edge([(620, 600), (620, 624)], "control")

    s.legend(s.h - 26, ["control", "failure", "neutral", "unused"])


# =========================================================================================
# 0. The idea in one picture
# =========================================================================================

OVERVIEW_DESC = (
    "Overview. Fifty simulated smart meters send a reading every 2 seconds into one Kafka "
    "stream. A fast path, the speed layer, adds the readings up within seconds but uses "
    "yesterday's prices and skips readings that arrive very late, so its bill is an estimate. "
    "Every reading is also kept unchanged in a raw copy. Once a day ends and that day's price "
    "list arrives, a slow path, the batch layer, re-reads every reading of the day with the "
    "right prices and produces the exact bill. The API gives one answer: the exact bill if it "
    "is ready, otherwise the estimate, and the dashboard shows a Provisional or Final badge."
)


def overview(s: Svg) -> None:
    s.header(
        "The idea in one picture",
        "One stream of meter readings, two ways of adding it up, one answer. "
        "Grey text is the name in the code; diagrams 1–5 have the detail.",
    )

    def node(x, y, w, h, role, title, lines, code):  # noqa: ANN001
        s.box(x, y, w, h, role, r=12, sw=1.6)
        s.text(x + 16, y + 28, title, 16, "ink", 700, maxw=w - 28)
        for i, (line, color) in enumerate(lines):
            s.text(x + 16, y + 52 + i * 20, line, 13, color, 600 if color != "ink" else 400,
                   maxw=w - 28)
        s.text(x + 16, y + h - 14, code, 11, "faint", mono=True, maxw=w - 28)

    node(24, 190, 190, 128, "simulated", "Smart meters",
         [("50 homes, 5 zones", "ink"), ("a reading every 2 s", "ink")], "meter-producer")
    node(24, 400, 190, 128, "simulated", "Price list",
         [("one file per day,", "ink"), ("sent when the day ends", "ink")], "reference-dropper")
    node(256, 190, 176, 128, "neutral", "One stream",
         [("every reading,", "ink"), ("kept in order", "ink")], "Kafka")

    node(480, 96, 316, 148, "provisional", "Fast path · seconds",
         [("Adds readings up as they arrive.", "ink"),
          ("Uses yesterday's prices and skips", "ink"),
          ("very late readings: an estimate.", "ink")], "speed-layer · Spark Streaming")
    node(480, 268, 316, 92, "final", "Raw copy, never changed",
         [("every reading, kept for re-reading", "ink")], "raw-archiver → Parquet in MinIO")
    node(480, 384, 316, 148, "final", "Slow path · once a day",
         [("When the day is over, re-reads every", "ink"),
          ("reading with that day's prices.", "ink"),
          ("The exact bill.", "ink")], "Airflow + Spark · daily_billing")

    node(846, 214, 196, 214, "neutral", "One answer",
         [("Is the exact bill", "ink"), ("for this day ready?", "ink"),
          ("yes → Final", "final"), ("no  → Provisional", "provisional")], "voltstream-api")
    node(1080, 214, 176, 214, "neutral", "Dashboard",
         [("refreshes every 5 s;", "ink"), ("the bill badge", "ink"),
          ("flips from", "ink"), ("Provisional to Final", "ink")], "localhost:8000")

    s.edge([(214, 254), (256, 254)], "simulated")
    s.edge([(432, 230), (456, 230), (456, 170), (480, 170)], "provisional")
    s.edge([(432, 290), (480, 290)], "final")
    s.edge([(638, 360), (638, 384)], "final")
    s.edge([(214, 464), (480, 464)], "simulated")
    s.label(232, 456, "triggers + prices the slow path", 12, "simulated", weight=600)
    s.edge([(796, 170), (820, 170), (820, 270), (846, 270)], "provisional")
    s.label(800, 160, "estimate", 12, "provisional", weight=600)
    s.edge([(796, 458), (820, 458), (820, 370), (846, 370)], "final")
    s.label(800, 478, "exact bill", 12, "final", weight=600)
    s.edge([(1042, 320), (1080, 320)], "neutral")

    s.box(24, 556, s.w - 48, 48, "control", r=8)
    s.text(40, 586, "Time runs 288× fast: one simulated day = 5 real minutes. Prometheus, "
           "Alertmanager and Grafana watch every box above (diagram 5).", 13, "ink",
           maxw=s.w - 80)
    s.legend(s.h - 22, ["simulated", "provisional", "final", "control", "neutral"])


# =========================================================================================
# Scenario diagrams: what each script in scripts/ does, step by step, and what it checks
# =========================================================================================


def lane_grid(s: Svg, cols, lanes, bottom):  # noqa: ANN001
    """Column headers (the script's own steps) over swimlanes (the parts that react)."""
    for x0, x1, num, title, sub in cols:
        if num:
            s.badge(x0 + 12, 106, num, "ink")
        s.text(x0 + (28 if num else 4), 111, title, 13, "ink", 700, maxw=x1 - x0 - 30)
        s.text(x0 + 4, 130, sub, 11, "muted", maxw=x1 - x0 - 8)
        s.body.append(
            f'<line x1="{x0 - 5}" y1="96" x2="{x0 - 5}" y2="{bottom}" stroke="{s.t["line"]}" '
            f'stroke-width="1" stroke-dasharray="2 4"/>'
        )
    for y0, y1, title, sub in lanes:
        s.rect(20, y0, s.w - 40, y1 - y0, s.t["panel"], None, r=6)
        s.text(32, y0 + (y1 - y0) / 2 - (2 if sub else -4), title, 12.5, "ink", 650, maxw=180)
        if sub:
            s.text(32, y0 + (y1 - y0) / 2 + 14, sub, 10.5, "faint", mono=True, maxw=180)


def bar(s: Svg, x0, x1, y0, y1, role, text, sub=None, dash=False):  # noqa: ANN001
    s.box(x0, y0 + 6, x1 - x0, y1 - y0 - 12, role, r=6, sw=1.2, dash=dash)
    mid = (y0 + y1) / 2
    s.text(x0 + 10, mid + (-3 if sub else 4.5), text, 12, "ink", 600, maxw=x1 - x0 - 16)
    if sub:
        s.text(x0 + 10, mid + 13, sub, 10.5, "muted", maxw=x1 - x0 - 16)


def check(s: Svg, x, y, text):  # noqa: ANN001
    """One of the script's own PASS assertions."""
    s.text(x, y, "✓ " + text, 11.5, "ink", 700)


DEMO_DESC = (
    "Scenario diagram for scripts/demo.sh. While day D is open, a bill request for HH-0001 is "
    "answered by the speed layer: source speed, provisional true, priced with day D−1's "
    "tariff, and the dashboard badge reads Provisional. At simulated midnight D closes; within "
    "about two minutes the batch layer waits out the 90-second grace, rescans the day and "
    "commits the bills. The same request is then answered by the batch layer: source batch, "
    "provisional false, tariff of day D, badge Final. The bill/delta endpoint then shows the "
    "estimate, the final bill and the gap split into tariff effect and data effect."
)


def scenario_demo(s: Svg) -> None:
    s.header(
        "Scenario · Provisional → final   (voltstream.ps1 demo · make demo)",
        "scripts/demo.sh asks for the same household's bill for the same day twice: before and "
        "after the day is billed. Numbers are the script's own steps.",
    )
    cols = [
        (230, 420, "1", "Start the stack", "waits for every health check"),
        (430, 720, "2", "Day D is open", "until simulated midnight (≤ 5 min real)"),
        (730, 980, "3", "D closes, is billed", "about 2 min: 90 s grace, then the job"),
        (990, 1260, "4", "Same request again", "then GET …/bill/delta"),
    ]
    lanes = [
        (146, 198, "Simulated clock", "simclock"),
        (206, 270, "Speed layer", "speed-layer"),
        (278, 342, "Batch layer", "airflow daily_billing"),
        (350, 444, "GET …/HH-0001/bill", "?date=D"),
        (452, 504, "Dashboard badge", ""),
    ]
    lane_grid(s, cols, lanes, 600)

    bar(s, 430, 728, 146, 198, "neutral", "day D")
    bar(s, 732, 1260, 146, 198, "neutral", "day D+1 (the stack keeps running)")
    s.body.append(f'<line x1="730" y1="140" x2="730" y2="600" stroke="{s.col("ink")}" '
                  f'stroke-width="2"/>')
    s.label(736, 594, "simulated midnight", 11, "ink", weight=700)

    bar(s, 430, 720, 206, 270, "provisional", "re-totals D every 10 s",
        "priced with tariff D−1 (D's does not exist yet)")
    bar(s, 732, 1260, 206, 270, "provisional", "now estimating D+1", "D's estimate is kept")
    s.text(440, 314, "idle: D is not over, so there is nothing exact to compute", 11.5, "muted",
           italic=True)
    bar(s, 740, 980, 278, 342, "final", "rescans D from the raw copy",
        "tariff_D.csv · bills + success row")
    bar(s, 990, 1260, 278, 342, "final", "reconciles D", "estimate − final, split in two")

    bar(s, 440, 720, 350, 444, "provisional", "source: speed · provisional: true",
        "tariff_date: D−1 · total grows during the day")
    check(s, 450, 436, "served by the speed layer while D is open")
    bar(s, 1000, 1260, 350, 444, "final", "source: batch · provisional: false",
        "tariff_date: D · the exact bill")
    check(s, 1010, 436, "merge now serves the batch bill")

    bar(s, 440, 600, 452, 504, "provisional", "Provisional")
    bar(s, 1000, 1120, 452, 504, "final", "Final")

    s.box(990, 520, 270, 72, "control", r=8)
    s.text(1004, 542, "GET …/bill/delta?date=D", 11.5, "ink", 700, mono=True)
    s.text(1004, 562, "estimate − final =", 11.5, "ink")
    s.text(1004, 580, "tariff_effect + data_effect", 11.5, "ink", 600, mono=True)
    s.text(232, 540, "Nothing is faked: the script only waits and asks. The flip is the merge "
           "function", 12, "muted", maxw=740)
    s.text(232, 558, "(diagram 3) seeing a success row in pipeline_runs for D.", 12, "muted",
           maxw=740)
    s.legend(s.h - 22, ["provisional", "final", "control", "neutral"])


KILL_DESC = (
    "Scenario diagram for the kill test, scripts/smoke_test.sh kill-speed-layer. The speed "
    "layer is killed with SIGKILL for 60 seconds. Meanwhile the raw archiver keeps consuming "
    "into the raw copy, the live zone view goes stale, and the final bill of an already billed "
    "day is served unchanged. After a restart the speed layer resumes from its checkpoint and "
    "catches up until the view is under 30 seconds old with zero consumer lag. When the day of "
    "the kill closes it is billed in full from the raw copy: 50 bills, and readings at least "
    "95 percent of the day before. Losing the speed layer costs freshness, never correctness."
)


def scenario_kill(s: Svg) -> None:
    s.header(
        "Scenario · Crash the speed layer   (voltstream.ps1 killtest · make kill-test)",
        "scripts/smoke_test.sh kill-speed-layer, on the running stack. ✓ marks the script's own "
        "PASS checks.",
    )
    cols = [
        (230, 400, "", "Before", "a day already billed"),
        (410, 650, "1", "Kill: down 60 s", "docker kill (SIGKILL), no clean stop"),
        (660, 910, "2", "Restart, catch up", "waits up to 300 s"),
        (920, 1260, "3", "The kill day closes", "billed like any other day"),
    ]
    lanes = [
        (146, 214, "Speed layer", "speed-layer"),
        (222, 290, "Raw copy", "raw-archiver → MinIO"),
        (298, 366, "Live zone view", "zone_metrics_rt"),
        (374, 442, "Final bill, earlier day", "household_bill_daily"),
        (450, 518, "Bills for the kill day", "household_bill_daily"),
    ]
    lane_grid(s, cols, lanes, 530)

    bar(s, 230, 404, 146, 214, "provisional", "running")
    bar(s, 410, 654, 146, 214, "failure", "killed", "nothing reads the stream for it")
    bar(s, 660, 914, 146, 214, "provisional", "re-reads from its checkpoint",
        "the missed minute first, then live")
    bar(s, 920, 1260, 146, 214, "provisional", "running")

    bar(s, 230, 1260, 222, 290, "final", "keeps consuming every reading, untouched by the crash",
        " ")
    check(s, 420, 270, "kept consuming while speed was down")

    bar(s, 230, 404, 298, 366, "neutral", "seconds old")
    bar(s, 410, 654, 298, 366, "failure", "stale: data age grows", "the dashboard freezes")
    bar(s, 660, 914, 298, 366, "neutral", "fresh again", " ")
    check(s, 670, 346, "age < 30 s, consumer lag 0")
    bar(s, 920, 1260, 298, 366, "neutral", "seconds old")

    bar(s, 230, 914, 374, 442, "final", "same total, served by the API throughout", " ")
    check(s, 420, 422, "unchanged during")
    check(s, 670, 422, "identical before, during, after")

    s.text(240, 490, "not billed yet: the kill day is still open", 11.5, "muted", italic=True)
    bar(s, 920, 1260, 450, 518, "final", "billed from the raw copy, not the speed view", " ")
    check(s, 930, 498, "50 bills · readings ≥ 95 % of the day before")

    s.box(20, 540, s.w - 40, 46, "control", r=8)
    s.text(36, 569, "The point: losing the speed layer costs freshness, never correctness. "
           "Bills come from the raw copy (diagram 1).", 13, "ink", 600, maxw=s.w - 72)
    s.legend(s.h - 22, ["provisional", "final", "failure", "control", "neutral"])


RESTATE_DESC = (
    "Scenario diagram for scripts/backfill.sh, restating an already billed day D. The script "
    "corrupts block_1_rate by 45.00 in every row of tariff_D.csv and runs billing again as "
    "billing__D__r1: all 50 bills change, the original run becomes superseded and r1 becomes "
    "success. It then restores the original file and runs billing__D__r2: all 50 wrong bills "
    "are replaced, r1 becomes superseded and r2 success. household_bill_daily, which the API "
    "serves, holds only the latest bills, while household_bill_history keeps all three sets. "
    "The original tariff file is restored on any exit."
)


def scenario_restate(s: Svg) -> None:
    s.header(
        "Scenario · Restate a day   (voltstream.ps1 backfill -Date D · make backfill d=D)",
        "scripts/backfill.sh: a wrong price list is fixed by re-running the day, not by editing "
        "bills. Each run is a new Airflow run of the same DAG.",
    )
    cols = [
        (230, 450, "", "Before", "D billed once, normally"),
        (460, 850, "1", "Corrupt the price list, re-run", "the wrong bills, on purpose"),
        (860, 1260, "2", "Restore it, re-run", "the corrected bills"),
    ]
    lanes = [
        (146, 210, "Price list for D", "landing tariff_D.csv"),
        (218, 282, "Billing run", "airflow daily_billing"),
        (290, 410, "Run ledger", "pipeline_runs"),
        (418, 482, "What the API serves", "household_bill_daily"),
        (490, 610, "Every run's bills", "household_bill_history"),
    ]
    lane_grid(s, cols, lanes, 620)

    bar(s, 230, 454, 146, 210, "neutral", "original")
    bar(s, 460, 854, 146, 210, "failure", "block_1_rate + 45.00 in every row")
    bar(s, 860, 1260, 146, 210, "neutral", "original, put back",
        "also restored on any exit, Ctrl+C included")

    bar(s, 230, 454, 218, 282, "control", "billing__D")
    bar(s, 460, 854, 218, 282, "control", "billing__D__r1", "waits 90 s grace, rescans D")
    bar(s, 860, 1260, 218, 282, "control", "billing__D__r2", "waits 90 s grace, rescans D")

    def ledger(x, rows, w=300):  # noqa: ANN001
        for i, (run, status, role) in enumerate(rows):
            y = 298 + i * 36
            s.box(x, y, w, 30, role, r=5, sw=1)
            s.text(x + 10, y + 20, run, 11, "ink", 600, mono=True)
            s.text(x + w - 10, y + 20, status, 11, "ink", 700, anchor="end", mono=True)

    ledger(240, [("billing__D", "success", "final")], w=204)
    ledger(470, [("billing__D", "superseded", "neutral"), ("billing__D__r1", "success", "final")])
    ledger(870, [("billing__D", "superseded", "neutral"),
                 ("billing__D__r1", "superseded", "neutral"),
                 ("billing__D__r2", "success", "final")])
    check(s, 1178, 330, "3 runs,")
    s.text(1192, 346, "this order", 11.5, "ink", 700)

    bar(s, 230, 454, 418, 482, "final", "original bills")
    bar(s, 460, 854, 418, 482, "failure", "wrong bills")
    check(s, 680, 460, "all 50 changed")
    bar(s, 860, 1260, 418, 482, "final", "corrected bills")
    check(s, 1050, 460, "all 50 wrong bills replaced")

    def history(x, sets):  # noqa: ANN001
        for i, (label, role) in enumerate(sets):
            y = 496 + i * 36
            s.box(x, y, 220, 30, role, r=5, sw=1)
            s.text(x + 10, y + 20, label, 11.5, "ink", 600)

    history(240, [("original (50)", "final")])
    history(470, [("original (50)", "final"), ("wrong, from r1 (50)", "failure")])
    history(870, [("original (50)", "final"), ("wrong, from r1 (50)", "failure"),
                  ("corrected, from r2 (50)", "final")])
    check(s, 1100, 586, "all 3 runs kept")

    s.text(24, s.h - 52, "Corrected bills equal the originals to the cent unless late readings "
           "reached the raw copy after the first run; a restatement bills those too.", 11.5,
           "muted", maxw=s.w - 48)
    s.legend(s.h - 22, ["final", "failure", "control", "neutral"])


DRILLS_DESC = (
    "Timeline of the five alert drills in scripts/inject_faults.sh, in real minutes. stale "
    "stops meter-producer; MeterDataStale fires for all five zones after about 3 minutes and "
    "the drill takes about 4. rejects restarts the producer with 15 percent null fields; "
    "HighRejectRate fires after about 2 minutes, about 3 in total. renewable changes nothing "
    "and waits for simulated dusk, when LowRenewableContribution fires for all five zones, up "
    "to 7 minutes. sla pauses the daily_billing DAG; BatchSLAMiss fires 15 minutes after the "
    "last billing, 15 to 17 minutes in total. divergence makes 60 percent of readings 3 to 5 "
    "simulated hours late; LambdaDivergenceHigh fires after 8 to 13 minutes. Every drill "
    "undoes its change on any exit; running all of them overlaps the SLA wait with the first "
    "three, about 30 minutes."
)


def scenario_drills(s: Svg) -> None:
    s.header(
        "Scenario · The five alert drills   (voltstream.ps1 faults · make faults s=<name>)",
        "scripts/inject_faults.sh breaks one thing, waits until Alertmanager shows the alert, "
        "then undoes it. Real minutes; ranges vary by run.",
    )
    x0, ppm = 400, 38.0  # minutes → pixels

    def mx(minutes: float) -> float:
        return x0 + minutes * ppm

    top, rh = 150, 74
    for m in range(0, 18):
        x = mx(m)
        dash = "" if m % 5 == 0 else ' stroke-dasharray="2 4"'
        s.body.append(f'<line x1="{x}" y1="{top - 8}" x2="{x}" y2="{top + 5 * rh}" '
                      f'stroke="{s.t["line"]}" stroke-width="{1 if m % 5 else 1.4}"{dash}/>')
        if m % 2 == 0:
            s.text(x, top - 14, f"{m} min", 11, "muted", anchor="middle")
    s.text(24, top - 14, "drill · what it breaks", 12, "muted", 700)

    # (name, break, alert, severity, fires_from, fires_to, done_from, done_to)
    drills = [
        ("stale", "docker stop meter-producer", "MeterDataStale ×5 zones", "critical",
         3, 3, 4, 4),
        ("rejects", "producer: null_field_rate 0.15", "HighRejectRate", "warning", 2, 2, 3, 3),
        ("renewable", "nothing: waits for dusk", "LowRenewable… ×5 zones", "warning",
         0, 7, 0, 7),
        ("sla", "airflow dags pause daily_billing", "BatchSLAMiss", "critical", 15, 15, 15, 17),
        ("divergence", "producer: 60 % of readings", "LambdaDivergenceHigh", "warning",
         8, 13, 8, 13),
    ]
    for i, (name, brk, alert, sev, f0, f1, d0, d1) in enumerate(drills):
        y = top + i * rh
        s.rect(20, y + 4, s.w - 40, rh - 8, s.t["panel"], None, r=6)
        s.text(34, y + 28, name, 14, "ink", 700, mono=True)
        s.text(34, y + 48, brk, 11, "muted", mono=True, maxw=370)
        if name == "divergence":
            s.text(34, y + 63, "3–5 simulated hours late", 11, "muted", mono=True)
        # fault in place, from the break until it is undone
        s.box(mx(0), y + 16, mx(d1) - mx(0), 26, "failure", r=5, sw=1)
        if f1 > f0:  # the alert fires somewhere in this window
            s.rect(mx(f0), y + 16, mx(f1) - mx(f0), 26, s.col("failure"), None, r=5)
            s.text(mx(f0) + 8, y + 33.5, "fires in this window", 11, "bg", 700)
        else:
            s.body.append(f'<circle cx="{mx(f0)}" cy="{y + 29}" r="7" fill="{s.col("failure")}"/>')
        s.text(1066, y + 28, alert, 12, "ink", 700, mono=True, maxw=190)
        after = "clears at dawn" if name == "renewable" else "undone, then clears"
        s.text(1066, y + 45, f"{sev} · {after}", 11, "muted", maxw=190)
        if d1 > d0 and f1 == f0:
            s.text(mx(f0) - 10, y + 60, "fires at 15 min · undo 0–2 min more", 10.5, "muted",
                   anchor="end")

    s.box(20, top + 5 * rh + 14, s.w - 40, 52, "control", r=8)
    s.text(36, top + 5 * rh + 36, "make faults (all) runs the sla wait alongside stale, rejects "
           "and renewable, then divergence: about 30 minutes. Each change is undone on any "
           "exit,", 12, "ink", maxw=s.w - 72)
    s.text(36, top + 5 * rh + 54, "Ctrl+C included. Which signal feeds which alert: diagram 5.",
           12, "ink", maxw=s.w - 72)
    s.legend(s.h - 22, ["failure", "control"])


# =========================================================================================

DIAGRAMS = [
    ("00-overview", 1280, 660, "Voltstream: the idea in one picture", OVERVIEW_DESC, overview),
    ("01-data-flow", 1280, 940, "Voltstream data flow: where a meter reading goes", DATA_FLOW_DESC,
     data_flow),
    ("02-day-sequence", 1300, 1350, "Voltstream: one simulated day, from reading to final bill",
     DAY_DESC, day_sequence),
    ("03-bill-states", 1280, 630, "Voltstream: which bill GET /bill returns", STATES_DESC,
     bill_states),
    ("04-fault-handling", 1280, 740, "Voltstream: how each injected fault is handled",
     FAULTS_DESC, faults),
    ("05-alerting", 1280, 740, "Voltstream: how a problem reaches someone", ALERTS_DESC, alerting),
    ("06-scenario-demo", 1280, 640, "Voltstream scenario: provisional to final", DEMO_DESC,
     scenario_demo),
    ("07-scenario-kill", 1280, 640, "Voltstream scenario: crash the speed layer", KILL_DESC,
     scenario_kill),
    ("08-scenario-restate", 1280, 700, "Voltstream scenario: restate a day", RESTATE_DESC,
     scenario_restate),
    ("09-scenario-drills", 1280, 660, "Voltstream scenario: the five alert drills", DRILLS_DESC,
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
