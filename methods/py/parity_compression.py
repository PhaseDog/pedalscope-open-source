#!/usr/bin/env python3
"""The Compression parity comparison — shared by the CI test
(`test_parity_compression.py`) and the document generator (`make
methods-docs` writes `generated/parity-compression.tex` from the same
numbers), so the chapter's worked-example tables and the test's verdict
cannot disagree.

Every case runs the shipped tool (`analysisdump compression-synth`) and the
Python reimplementation (`compression_curve.py`) on one synthetic device through
one synthetic loop and compares:

* Swift vs Python — every header quantity (the noise stamp, the knee with
  its four fields, the cleanup level, the floor source with and without the
  null run, the floor runs, the summaries' four features, the presence
  verdict) and every row (output level, gain, the arriving slope, THD, the
  estimator's amplitude per order, the window rms, the three bounds, the
  composed floor, the class, the presence reading) — numerically to a
  stated tolerance, discrete values exactly — and the truth's own read-time
  half the same way;
* the shipped result vs the closed-form ladder — the fundamental and every
  content harmonic per step, the THD per step, the knee against the truth
  curve's knee (the shipped rule on the closed-form curve — a hinge fit is a
  summary of a curve, not a property of the device), the cleanup crossing
  against the truth curve's, the presence verdict and every discrete
  reading against the truth's.

Part B — the read-time layer ruled from measurement (the hinge fit's four
verdict legs, the three-state cleanup, the three-source floor with its
label, the presence verdict) — is exercised on the oracle's synthetic loops:
the identity through noise with and without a null run, the exact
sub-unity lines, the sub-floor clippers, the fine window, the plugin
window, the operative floor, the device with no fundamental. Its parity
status is GENERATED from the run (`gen_docs.py`), never typed.

Tolerances are set from MEASUREMENT (`python parity_compression.py`
prints the distributions), a little above the measured maximum, never from
hope; each carries its measured value.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import compression_curve as cp

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
TOOL_PACKAGE = os.path.join(REPO, "Tools", "analysisdump")
PY = os.path.join(HERE, "compression_curve.py")

# --- Tolerances ------------------------------------------------------------
# Every figure below was MEASURED on 2026-09-21 by `python
# parity_compression.py` (the Studio, 96 kHz, the shipped grids) and each bar
# sits a little above its measurement, never at it and never from hope.

# Swift vs Python on every MEASURED quantity — the levels, the gain, the
# slopes, the estimator's amplitude per content order, the window rms, the
# three bounds, the composed floor, the knee's four fields, the cleanup
# levels, the features. The two implementations share the noise stream bit
# for bit and the window arithmetic; what differs is summation order.
# Measured maximum over every unfiltered case: 2.6e−10 dB (the phantom
# twin's THD at the quietest step), and 3.1e−8 dB on the dust fundamental
# of the phantom with NO fundamental (a read of the estimator's own leakage,
# −158 dB re the second harmonic, summed in two orders). Set 1e−7.
T_SWIFT_DB = 1e-7
# The same through a biquad (a pre- or post-filter): the direct-form
# recursion accumulates rounding differently in scipy's C loop and the Swift
# loop over 690 000 samples. Measured: 1.5e−8 dB (the post-filtered
# polynomial's H3). Set 1e−6.
T_SWIFT_DB_FILTERED = 1e-6
# Swift vs Python on the TRUTH columns: two quadratures (a one-pass angle
# recurrence in Swift, per-order sums in numpy) over 2^18 points, compared
# in dB down to content 150 dB under the fundamental. Measured: 3.3e−7 dB
# (the loop-cubic identity's truth THD at a quiet step), 1.7e−7 (tanh(2)'s
# at its fourth step). Set 1e−6.
T_SWIFT_TRUTH_DB = 1e-6
# A harmonic is DUST — an analytically empty order of a symmetric device,
# the identity's every harmonic — when its TRUTH sits more than this far
# below the truth fundamental; dust is the estimator reading its own
# leakage (the leakage map) and is not compared.
EMPTY_DEPTH_DB = 140.0

# The shipped read against the closed-form ladder on a NOISELESS capture, in
# dB, per step EXCLUDING THE LAST (the fade, below), AFTER the estimator's
# leakage allowance: the pure phantom [1] read on the tone's own geometry
# gives the symmetric Hann's leakage of a tone into every other harmonic
# bin by bin distance (−158 dB at one bin, −172 at two, −180 at three …,
# level-invariant), and a content order can read up to its truth plus what
# every OTHER present order leaks into its bin; that allowance is
# subtracted before the bar is applied, and what remains is the method's
# own error. Measured: the fundamental reads to 3.0e−8 dB on every device;
# the residue after the allowance is 5.8e−5 dB on tanh(8) (H9 at its
# 29th step, 74 dB clear of the leakage landing in its bin — the read sits
# AT the allowance, to 2 %), 6.9e−5 on tanh(2), 8.2e−5 on the hard
# clipper (H9 at 163 dB of clearance: at 220 Hz and 96 kHz no alias image
# of a per-sample device lands on a harmonic bin — 96 000/220 is not an
# integer — so the kinked device reads like a smooth one here; its phantom
# twin 1.2e−7), and 1.8e−3 through a post-filter (H3 at 32 dB of clearance,
# the bound's own rounding scaled up). Set from those.
T_H1_DB = 1e-6
T_TRUTH_SMOOTH_DB = 2e-4
T_TRUTH_KINKED_DB = 2e-4
T_TRUTH_PHANTOM_DB = 2e-4
T_TRUTH_FILTERED_DB = 5e-3
# The THD per step against the definition on the ladder, after the same
# allowance summed over every bin the analyzer sums (a dust bin holds
# leakage the truth does not): measured 0.0 on the smooth devices and the
# filtered ones, 7.9e−6 dB on the hard clipper. Set 1e−4.
T_THD_DB = 1e-4
# The last step's fundamental against its truth: LOW by the stimulus's
# final fade inside its window, within this band (measured: −0.0057 dB on
# a linear device at 96 kHz, −0.0031 on tanh(8), −0.0017 on the hard
# clipper — a compressing device flattens the fade — and −0.0070 at 48 kHz).
T_FADE_DB = 0.02
# The knee against the truth curve's knee — both the shipped rule, one on
# the measured curve and one on the closed-form ladder, so the gap is what
# the measurement's own error moves the fit by. Measured: 0.0 dB on every
# point knee of the hardware grid (the fitted breakpoint lands on the same
# candidate), 0.0534 on the loop-cubic clipper and 0.0517 at Simulation
# Mode's 24 steps — one candidate step of the sweep in each case. Set 0.1,
# under two candidate steps.
T_KNEE_DB = 0.1
# The cleanup crossing against the truth curve's. Measured: 1.3e−6 dB
# (tanh 8), 4.0e−7 (the hard clipper), 3.4e−4 on the noisy loops (the
# noise's share of the THD at the crossing). Set 1e−3.
T_CLEANUP_DB = 1e-3
# The noise stamp against the injected rms — the pre-roll estimate's own
# scatter over Int(0.2·fs) samples of white noise. Measured: 0.0074 dB at
# 96 kHz (19 200 samples, one seed). Set 0.02.
T_STAMP_DB = 0.02
# The gain invariance: the same device and noise through a loop 12 dB
# louder gives the same knee input level (bit-identical), the same cleanup
# level to 1.0e−13, every floor class equal, and every output level and
# the stamp moved by exactly 12 dB (1.1e−13). Set 1e−9.
T_GAIN_DB = 1e-9
# A capture 100 samples late with the analyzer told the pre-roll plus 100:
# every point IDENTICAL to the undelayed capture (measured 0.0). Set 1e−12
# on 2026-09-21; RAISED to 1e−9 on 2026-09-22 (the drift ruling,
# `machine_floor.py`): a bar under the machine floor claims agreement the
# machine does not reproduce between two runners, and the document's bound
# "≤ floor" beside it would read as a failure; 1e−9 is the gain bar's value
# and a decade above the floor.
T_LATENCY_DB = 1e-9
# The one-sample mis-cut: a stated figure the chapter quotes, not a bar;
# measured on the pure phantom: 3.0e−8 dB on the fundamental over every
# step but the last — the Hann's taper makes a one-sample mis-cut
# invisible at the seventh decimal. Set 1e−6.
MISCUT_SAMPLES = 1
T_MISCUT_DB = 1e-6
# The one-bin estimator's own separation on a phantom with NO fundamental:
# the fundamental's bin reads the second harmonic's leakage, 158.2 dB down
# (the map's one-bin figure), against the borrowed 76 dB bar — quoted, and
# pinned to stand over the bar by a wide margin.
T_SEPARATION_OVER_BAR_DB = 60.0


@dataclass(frozen=True)
class Case:
    name: str
    args: List[str]
    kind: str  # smooth | kinked | filtered | linear | noise | null | absent | line | bound | fine | plugin | gain | latency | miscut | operative | simulation | separation

    @property
    def noisy(self) -> bool:
        return "--noise-db" in self.args

    @property
    def filtered(self) -> bool:
        return "--pre" in self.args or "--post" in self.args

    @property
    def swift_tolerance_db(self) -> float:
        return T_SWIFT_DB_FILTERED if self.filtered else T_SWIFT_DB

    @property
    def compares_truth(self) -> bool:
        return self.kind in ("smooth", "kinked", "filtered")


def _line_ladders(slope: float, break_db: Optional[float], post_slope: float, offset_db: float) -> str:
    """Per-step phantom ladders for an EXACT piecewise line in dB: H1 at
    each step so that outputDB = offset + slope·(x − x_b) below the break
    and offset + post·(x − x_b) above it; a constant H3 of 0.01 so THD is
    defined. The shipped hardware grid."""
    xs = [-70 + 58 * i / 35 for i in range(36)]

    def y(x):
        if break_db is None or x <= break_db:
            return offset_db + slope * (x - (break_db if break_db is not None else -30))
        return offset_db + post_slope * (x - break_db)

    return ";".join("%r,0,0.01" % (10 ** (y(x) / 20) / 10 ** (x / 20)) for x in xs)


_NOISE = ["--noise-db", "-100"]

CASES = [
    # (a) the worked example: a soft clipper with a POINT knee on the hardware grid, noiseless — every step
    #     against the ladder; and the same clipper at gain 2, whose post-knee slope stays over the
    #     threshold at the ceiling: the never-compresses leg (no knee).
    Case("a-tanh8", ["--source", "tanh", "--gain", "8"], "smooth"),
    Case("a-tanh2", ["--source", "tanh", "--gain", "2"], "smooth"),
    # (a0) the pure phantom [1]: the estimator's own error on the snapped window (rounding), and the
    #      last step's fade.
    Case("a-linear", ["--source", "phantom", "--amps", "1"], "linear"),
    # (b) the identity through seeded noise: the stamp against the injected rms, every class against
    #     the √2 bound (the bathtub), the runs; and with a null run — the #129 arithmetic.
    Case("b-identity-noise", ["--source", "identity"] + _NOISE, "noise"),
    Case("b-identity-null", ["--source", "identity", "--null-run"] + _NOISE, "null"),
    #     … and through a loop with its OWN distortion (a cubic on the capture, the converter's), where the
    #     null run's absolute contribution sets the floor on the identity (the label fires) and the clipper's
    #     own products stand over it.
    Case("b-identity-null-loop", ["--source", "identity", "--null-run", "--loop-a3", "0.02"] + _NOISE, "null"),
    Case("b-tanh8-null-loop", ["--source", "tanh", "--gain", "8", "--null-run", "--loop-a3", "0.02"] + _NOISE, "null"),
    # (c) a hard clipper with the knee inside the window: a point, the post slope near 0, the
    #     breakpoint against the clip onset (a measured relation), the phantom twin as the alias-free control.
    Case("c-hardclip", ["--source", "hardclip", "--threshold", "0.1"], "kinked"),
    # (d) the bound legs: an exact sub-unity line with a break (#53's first leg, the unity guard);
    #     an exact sub-unity LINE (#53's second leg — and the fade finding: see the chapter);
    #     a clipper whose threshold sits just above the floor (the floor-bound zone) and one under it.
    Case("d-subunity-break", ["--source", "phantom", "--amps-per-step", _line_ladders(0.85, -30, 0.2, -30)], "bound"),
    Case("d-subunity-line", ["--source", "phantom", "--amps-per-step", _line_ladders(0.85, None, 0.85, -33)], "line"),
    Case("d-hardclip-zone", ["--source", "hardclip", "--threshold", "0.0004"], "bound"),
    Case("d-hardclip-under", ["--source", "hardclip", "--threshold", "0.0002"], "bound"),
    # (e) the #119 fine window over the hard clipper's knee.
    Case("e-fine", ["--source", "hardclip", "--threshold", "0.1", "--fine-min", "-24", "--fine-max", "-16"], "fine"),
    # (f) the plugin window with the hard clipper: the ceiling step at exactly 0 dBFS.
    Case("f-plugin", ["--source", "hardclip", "--threshold", "0.1", "--plugin-window"], "plugin"),
    # (g) the loop 12 dB louder: the input-referred quantities invariant.
    Case("g-gain0", ["--source", "tanh", "--gain", "8"] + _NOISE, "gain"),
    Case("g-gain12", ["--source", "tanh", "--gain", "8", "--chain-gain-db", "12"] + _NOISE, "gain"),
    # (h) the latency cut: exact when told the truth; a one-sample mis-cut measured.
    Case("h-latency", ["--source", "tanh", "--gain", "8", "--latency-samples", "100"], "latency"),
    Case("h-miscut", ["--source", "phantom", "--amps", "1", "--latency-error", str(MISCUT_SAMPLES)], "miscut"),
    # (i) the #122 stated floor governing.
    Case("i-operative", ["--source", "tanh", "--gain", "8", "--operative-floor-rms", "0.0001"] + _NOISE, "operative"),
    # (j) a device with no fundamental (80 dB under its second harmonic): absent everywhere, the knee
    #     and cleanup not stated; and the one-bin estimator's own separation on a phantom with NO fundamental.
    Case("j-absent", ["--source", "phantom", "--amps", "0.0001,1"] + _NOISE, "absent"),
    Case("j-separation", ["--source", "phantom", "--amps", "0,1"], "separation"),
    # (k) Simulation Mode's assembly at interactive quality on the worked example.
    Case("k-simulation", ["--source", "tanh", "--gain", "8", "--assembly", "simulation", "--rate", "48000",
                          "--steps", "24", "--settle", "0.05", "--measure", "0.1"], "simulation"),
    # (l) filters: the soft clipper behind a high-pass, the polynomial through a low-pass.
    Case("l-tanh-prehp", ["--source", "tanh", "--gain", "8", "--pre", "highpass", "--pre-hz", "40"], "filtered"),
    Case("l-poly-postlp", ["--source", "poly", "--a2", "0.2", "--a3", "0.3", "--post", "lowpass", "--post-hz", "1550"], "filtered"),
]

WORKED = "a-tanh8"
TWIN_OF = ("a-tanh8", "c-hardclip")


# --- Running the two implementations --------------------------------------


def build_tool() -> str:
    subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    out = subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE,
                          "--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
    return os.path.join(out, "analysisdump")


def run_swift(tool: str, args: List[str]) -> str:
    return subprocess.run([tool, "compression-synth"] + args, check=True, capture_output=True, text=True).stdout


def run_python(args: List[str], manifest: Optional[str] = None) -> str:
    cmd = [sys.executable, PY] + args
    if manifest:
        cmd += ["--manifest", manifest]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


# --- Parsing ----------------------------------------------------------------

FIELD = re.compile(r"(\w+)=([^\s\[\]]+)")
LIST = re.compile(r"(\w+)=\[([^\]]*)\]")
TEXT_COLUMNS = {"floor_class", "presence", "truth_floor_class", "truth_presence"}
INT_COLUMNS = {"index"}


@dataclass
class Dump:
    header: Dict[str, Dict[str, str]]
    lists: Dict[str, Dict[str, List[str]]]
    rows: List[Dict[str, object]]

    def value(self, line: str, key: str) -> float:
        return _num(self.header[line][key])


def _num(s: str) -> float:
    return float("nan") if s == "nan" else float(s)


def parse(text: str) -> Dump:
    header: Dict[str, Dict[str, str]] = {}
    lists: Dict[str, Dict[str, List[str]]] = {}
    body: List[str] = []
    for line in text.splitlines():
        if not line.startswith("#"):
            body.append(line)
            continue
        content = line[2:]
        key, rest = content.split(": ", 1) if ": " in content else (content, "")
        key = key.strip()
        if key == "null run rungs":
            header[key] = {"n": str(len(rest.split()))}
            lists[key] = {"rungs": rest.split()}
            continue
        if key.endswith("summaries (FeatureExtractor.extract(compression:))"):
            # Duplicate `confidence=` keys: named positionally.
            m = re.match(r"knee_level_dbfs=(\S+) confidence=(\S+) knee_bound=(\S+) sharpness=(\S+) confidence=(\S+) "
                         r"asymptote=(\S+) confidence=(\S+) cleanup state=(\S+) level_dbfs=(\S+) confidence=(\S+) "
                         r"fundamental_absent=(\S+)", rest)
            assert m, rest
            names = ["knee_level_dbfs", "knee_confidence", "knee_bound", "sharpness", "sharpness_confidence",
                     "asymptote", "asymptote_confidence", "cleanup_state", "cleanup_level_dbfs", "cleanup_confidence",
                     "fundamental_absent"]
            header[key] = dict(zip(names, m.groups()))
            continue
        if key.endswith("floor runs"):
            header[key] = {"runs": rest.strip()}
            continue
        if key.endswith("knee"):
            # `label=≤ -70 dBFS` carries a space; keep the label whole.
            label = rest.split("label=")[1] if "label=" in rest else ""
            header[key] = dict(FIELD.findall(rest.split("label=")[0]))
            header[key]["label"] = label.strip()
            if "state=" in rest and "state=fitted" not in rest:
                header[key]["state"] = rest.split("state=")[1].split(" ")[0]
            continue
        header[key] = dict(FIELD.findall(LIST.sub("", rest)))
        lists[key] = {k: [x for x in v.split(",") if x != ""] for k, v in LIST.findall(rest)}
    rows: List[Dict[str, object]] = []
    if len(body) > 1:
        columns = body[0].split("\t")
        for line in body[1:]:
            if not line:
                continue
            row: Dict[str, object] = {}
            for name, value in zip(columns, line.split("\t")):
                if name in TEXT_COLUMNS:
                    row[name] = value
                elif name in INT_COLUMNS:
                    row[name] = int(value)
                else:
                    row[name] = _num(value)
            rows.append(row)
    return Dump(header, lists, rows)


def _diff(a: float, b: float) -> float:
    if math.isnan(a) and math.isnan(b):
        return 0.0
    if math.isnan(a) or math.isnan(b):
        return math.inf
    if math.isinf(a) and math.isinf(b) and a == b:
        return 0.0
    return abs(a - b)


HEADER_NUMERIC_KEYS = {
    "noise stamp": ["measured_rms", "measured_dbfs", "injected_rms", "injected_dbfs", "error_db", "gate_rms"],
    "precheck": ["operative_rms", "operative_dbfs", "absolute_dbfs"],
    "knee": ["input_dbfs", "resolution_db", "pre_knee_slope", "post_knee_slope"],
    "cleanup": ["level_dbfs"],
    "fundamental verdict": ["absent_fraction", "median_depth_db"],
    "summaries (FeatureExtractor.extract(compression:))": ["knee_level_dbfs", "knee_confidence", "sharpness", "sharpness_confidence",
                                                          "asymptote", "asymptote_confidence", "cleanup_level_dbfs", "cleanup_confidence"],
}
HEADER_EXACT_KEYS = {
    "plan": ["steps", "settle_samples", "measure_samples", "ramp_samples", "step_samples", "tone_samples", "assembly",
             "preroll_samples", "tail_samples", "stimulus_samples", "harmonic_count"],
    "grid": ["delivered", "plugin_window"],
    "loop": ["latency_samples", "latency_error_samples", "analyzed_latency_samples", "seed", "capture_seed", "null_run_seed"],
    "noise stamp": ["dropped", "points", "skipped"],
    "null run": ["points", "dropped"],
    "knee": ["state", "bound", "compressed_throughout", "display_decimals", "label"],
    "cleanup": ["state"],
    "floor source": ["without_null_run"],
    "floor runs": ["runs"],
    "fundamental verdict": ["absent", "evaluated"],
    "summaries (FeatureExtractor.extract(compression:))": ["knee_bound", "cleanup_state", "fundamental_absent"],
}
ROW_EXACT_KEYS = ["dropped", "skipped", "floor_class", "presence", "truth_floor_class", "truth_presence"]
ROW_NUMERIC_KEYS = ["output_db", "gain_db", "slope", "thd", "window_rms", "noise_floor_thd", "null_run_floor_thd",
                    "stated_floor_thd", "floor_thd", "truth_output_db", "truth_gain_db", "truth_slope", "truth_thd",
                    "truth_noise_floor_thd", "truth_null_run_floor_thd", "truth_stated_floor_thd", "truth_floor_thd"]


# The estimator's own leakage: the pure phantom [1] read on the tone's
# geometry — every harmonic bin holds what the symmetric Hann leaks of the
# fundamental into it (no harmonic exists), per step and order, in dB re
# the fundamental. A content harmonic c dB above that leakage can read up
# to 20·log10(1 + 10^(−c/20)) from the truth by the estimator alone; that
# allowance is subtracted before a bar is applied (the Gain Map chapter's
# leakage-map discipline).


def leakage_map(linear_text: str) -> Dict[int, Dict[int, float]]:
    """{order: {step: dB re H1}} from the pure phantom's dump."""
    d = parse(linear_text)
    orders = [int(c[1:]) for c in d.rows[0] if re.fullmatch(r"h\d+", c)]
    out: Dict[int, Dict[int, float]] = {k: {} for k in orders if k >= 2}
    last = max(r["index"] for r in d.rows)
    for r in d.rows:
        if math.isnan(r["h1"]) or r["h1"] <= 0:
            continue
        # The last step's window holds the stimulus's final fade, which
        # breaks the integer-cycle geometry: the fundamental's leakage into
        # the second bin rises from −158 dB to −110 dB there (measured
        # 2026-09-21). No truth comparison reads that step; the map is the
        # snapped window's.
        if r["index"] == last:
            continue
        for k in orders:
            if k < 2 or math.isnan(r["h%d" % k]) or r["h%d" % k] <= 0:
                continue
            out[k][r["index"]] = 20 * math.log10(r["h%d" % k] / r["h1"])
    return out


def leakage_allowance_db(leak_re_content_db: float) -> float:
    return 20 * math.log10(1 + 10 ** (-leak_re_content_db / 20))


def leakage_into(k: int, r: dict, orders: List[int], leakage: Dict[int, Dict[int, float]]) -> Optional[float]:
    """The amplitude every OTHER present order leaks into order k's bin at
    this step: Σ_{j≠k} t_j·10^(L(|k−j|)/20), L(d) the phantom's leakage at
    bin distance d (the window's spectrum is symmetric, so the distance is
    what matters); None where the map does not reach a distance."""
    total = 0.0
    step = r["index"]
    for j in orders:
        if j == k:
            continue
        tj = r["truth_h%d" % j]
        if math.isnan(tj) or tj <= 0:
            continue
        d = abs(k - j)
        row = leakage.get(1 + d)
        if row is None or step not in row:
            return None
        total += tj * 10 ** (row[step] / 20)
    return total


def _has_content(r: dict, orders: List[int]) -> bool:
    """A step whose truth has at least one harmonic within EMPTY_DEPTH_DB of
    its fundamental; elsewhere the THD on both sides is dust."""
    t1 = r["truth_h1"]
    if math.isnan(t1) or t1 <= 0:
        return False
    for k in orders:
        if k < 2:
            continue
        tk = r["truth_h%d" % k]
        if not math.isnan(tk) and tk > 0 and 20 * math.log10(t1 / tk) <= EMPTY_DEPTH_DB:
            return True
    return False


@dataclass
class CaseReport:
    case: Case
    swift: Dump
    python: Dump
    swift_header_db: float
    swift_row_db: float                # over the MEASURED columns
    swift_row_at: str
    swift_truth_db: float              # over the truth columns (two quadratures)
    swift_truth_at: str
    header_field_mismatches: List[str]
    discrete_mismatches: List[str]
    # measured vs truth (noiseless device cases)
    content_count: int
    h1_error_db: float                 # worst |output_db − truth_output_db| over steps but the last
    harmonic_error_db: float           # worst content-harmonic error (dB) over steps but the last
    harmonic_error_at: str
    thd_error_db: float                # worst |20·log10(thd/truth_thd)| over content steps but the last
    harmonic_residue_db: float         # the worst content-harmonic error AFTER the leakage allowance
    harmonic_residue_at: str
    thd_residue_db: float              # the THD error after the allowance at the loudest content order
    fade_error_db: float               # the LAST step's fundamental error (signed, dB)
    knee_error_db: float               # |measured knee − truth knee| (both fitted), or nan
    cleanup_error_db: float
    orders: List[int] = field(default_factory=list)


def _floor_source_line(d: Dump, label: str) -> str:
    return d.header[label + "floor source"].get("without_null_run", "")


def compare(case: Case, swift_text: str, python_text: str, m: dict,
            leakage: Optional[Dict[int, Dict[int, float]]] = None) -> CaseReport:
    sw, py = parse(swift_text), parse(python_text)
    assert set(sw.header) == set(py.header), f"{case.name}: header lines differ: {set(sw.header) ^ set(py.header)}"
    header_db = 0.0
    fields: List[str] = []
    for prefix in ("", "truth "):
        for line, keys in HEADER_NUMERIC_KEYS.items():
            key = prefix + line
            if key not in sw.header:
                continue
            for k in keys:
                if k in sw.header[key] or k in py.header[key]:
                    header_db = max(header_db, _diff(_num(sw.header[key].get(k, "nan")), _num(py.header[key].get(k, "nan"))))
        for line, keys in HEADER_EXACT_KEYS.items():
            key = prefix + line
            if key not in sw.header:
                continue
            for k in keys:
                a, b = sw.header[key].get(k), py.header[key].get(k)
                if a != b:
                    fields.append(f"{key}.{k}: {a} vs {b}")
    # The floor source itself (the first token of the line) and the null run's rungs.
    for prefix in ("", "truth "):
        a = swift_text.split("# %sfloor source: " % prefix)[1].split(" ")[0]
        b = python_text.split("# %sfloor source: " % prefix)[1].split(" ")[0]
        if a != b:
            fields.append(f"{prefix}floor source: {a} vs {b}")
    if "null run rungs" in sw.lists:
        ra, rb = sw.lists["null run rungs"]["rungs"], py.lists["null run rungs"]["rungs"]
        if len(ra) != len(rb):
            fields.append("null run rungs: %d vs %d" % (len(ra), len(rb)))
        else:
            for x, y in zip(ra, rb):
                for u, v in zip(x.split(":"), y.split(":")):
                    header_db = max(header_db, _diff(_num(u), _num(v)))
    for k in ("level_dbfs",):
        a, b = sw.lists["plan"].get(k, []), py.lists["plan"].get(k, [])
        if len(a) != len(b):
            fields.append(f"plan.{k}: {len(a)} vs {len(b)} entries")
        else:
            header_db = max(header_db, max((_diff(_num(x), _num(y)) for x, y in zip(a, b)), default=0.0))
    # Rows.
    orders = [int(c[1:]) for c in sw.rows[0] if re.fullmatch(r"h\d+", c)] if sw.rows else []
    row_db = 0.0
    row_at = ""
    truth_db = 0.0
    truth_at = ""
    discrete: List[str] = []
    if len(sw.rows) != len(py.rows):
        discrete.append(f"row count {len(sw.rows)} vs {len(py.rows)}")
    for a, b in zip(sw.rows, py.rows):
        for k in ROW_EXACT_KEYS:
            if a[k] != b[k]:
                discrete.append(f"step {a['index']} {k}: {a[k]} vs {b[k]}")
        content = _has_content(a, orders)
        for k in ROW_NUMERIC_KEYS:
            if k in ("thd", "truth_thd"):
                # THD in dB where the step has content; where the truth is
                # dust both sides read rounding, compared absolutely.
                x, y = a[k], b[k]
                no_fundamental = math.isnan(a["truth_h1"]) or a["truth_h1"] <= 0
                if (content or no_fundamental) and isinstance(x, float) and isinstance(y, float) and x > 0 and y > 0:
                    d = abs(20 * math.log10(x / y))
                else:
                    d = _diff(x, y)
            elif k.endswith("_thd"):
                x, y = a[k], b[k]
                d = abs(20 * math.log10(x / y)) if (isinstance(x, float) and isinstance(y, float) and x > 0 and y > 0) else _diff(x, y)
            elif k == "window_rms":
                x, y = a[k], b[k]
                d = abs(20 * math.log10(x / y)) if (isinstance(x, float) and isinstance(y, float) and x > 0 and y > 0) else _diff(x, y)
            else:
                d = _diff(a[k], b[k])
            if k.startswith("truth_"):
                if d > truth_db:
                    truth_db, truth_at = d, f"step {a['index']} {k}"
            elif d > row_db:
                row_db, row_at = d, f"step {a['index']} {k}"
        # Harmonics: content orders only (dust is where the estimator reads the loop).
        t1 = a["truth_h1"]
        for k in orders:
            tk = a["truth_h%d" % k]
            if not (isinstance(t1, float) and isinstance(tk, float)) or math.isnan(tk) or math.isnan(t1) or t1 <= 0 or tk <= 0:
                continue
            if 20 * math.log10(t1 / tk) > EMPTY_DEPTH_DB:
                continue
            x, y = a["h%d" % k], b["h%d" % k]
            if isinstance(x, float) and isinstance(y, float) and x > 0 and y > 0:
                d = abs(20 * math.log10(x / y))
            else:
                d = _diff(x, y)
            if d > row_db:
                row_db, row_at = d, f"step {a['index']} h{k}"
            d = _diff(a["truth_h%d" % k], b["truth_h%d" % k]) / max(abs(tk), 1e-300)
            if d > truth_db:
                truth_db, truth_at = d, f"step {a['index']} truth_h{k}"
    # Measured vs truth, on the Swift side.
    content = 0
    h1_err = 0.0
    harm_err = 0.0
    harm_at = ""
    harm_res = 0.0
    harm_res_at = ""
    thd_err = 0.0
    thd_res = 0.0
    fade = float("nan")
    if case.compares_truth:
        last = max(r["index"] for r in sw.rows)
        for r in sw.rows:
            if r["dropped"] or r["skipped"] or math.isnan(r["output_db"]):
                continue
            if r["index"] == last:
                fade = r["output_db"] - r["truth_output_db"]
                continue
            h1_err = max(h1_err, abs(r["output_db"] - r["truth_output_db"]))
            t1 = r["truth_h1"]
            loudest_clearance = None
            # The THD's allowance: every summed bin — content or dust — can
            # read up to its truth PLUS the leakage landing in it, so the
            # sum can read up to √Σ(t_k + leak_k)² against √Σ t_k².
            summed = cp.harmonic_orders_summed(_num(sw.header["plan"]["frequency_hz"]), _num(sw.header["plan"]["fs"]),
                                               len(orders), (float(m["compression"]["analyzer"]["band"]["lowHz"]),
                                                             float(m["compression"]["analyzer"]["band"]["highHz"])))
            bound_power = 0.0
            truth_power = 0.0
            for k in summed:
                tk = r["truth_h%d" % k]
                tk = 0.0 if math.isnan(tk) else tk
                lk = None if leakage is None else leakage_into(k, r, orders, leakage)
                bound_power += (tk + (lk or 0.0)) ** 2
                truth_power += tk * tk
            thd_allowance = 10 * math.log10(bound_power / truth_power) if truth_power > 0 and bound_power > 0 else 0.0
            for k in orders:
                tk = r["truth_h%d" % k]
                if k < 2 or math.isnan(tk) or tk <= 0 or 20 * math.log10(t1 / tk) > EMPTY_DEPTH_DB:
                    continue
                content += 1
                e = abs(20 * math.log10(r["h%d" % k] / tk))
                if e > harm_err:
                    harm_err, harm_at = e, "step %d h%d" % (r["index"], k)
                # The allowance: what every other present order leaks into
                # this bin at this step, re the content.
                leak = None if leakage is None else leakage_into(k, r, orders, leakage)
                if leak is not None and leak > 0:
                    clearance = 20 * math.log10(tk / leak)
                    if loudest_clearance is None or 20 * math.log10(tk / t1) > loudest_clearance[0]:
                        loudest_clearance = (20 * math.log10(tk / t1), clearance)
                    res = e - leakage_allowance_db(clearance)
                    if res > harm_res:
                        harm_res, harm_res_at = res, "step %d h%d (%.0f dB clear)" % (r["index"], k, clearance)
            if _has_content(r, orders) and r["truth_thd"] > 0 and r["thd"] > 0:
                e = abs(20 * math.log10(r["thd"] / r["truth_thd"]))
                thd_err = max(thd_err, e)
                # The fundamental's own error enters the ratio too.
                thd_res = max(thd_res, e - thd_allowance - abs(r["output_db"] - r["truth_output_db"]))
    knee_err = float("nan")
    if sw.header["knee"].get("state") == "fitted" and sw.header["truth knee"].get("state") == "fitted":
        knee_err = abs(_num(sw.header["knee"]["input_dbfs"]) - _num(sw.header["truth knee"]["input_dbfs"]))
    cleanup_err = float("nan")
    if sw.header["cleanup"].get("state") == "cleans_up" and sw.header["truth cleanup"].get("state") == "cleans_up":
        cleanup_err = abs(_num(sw.header["cleanup"]["level_dbfs"]) - _num(sw.header["truth cleanup"]["level_dbfs"]))
    return CaseReport(case, sw, py, header_db, row_db, row_at, truth_db, truth_at, fields, discrete, content, h1_err, harm_err, harm_at,
                      thd_err, harm_res, harm_res_at, thd_res, fade, knee_err, cleanup_err, orders)


def truth_tolerance(case: Case) -> float:
    return {"smooth": T_TRUTH_SMOOTH_DB, "kinked": T_TRUTH_KINKED_DB, "filtered": T_TRUTH_FILTERED_DB}.get(case.kind, T_TRUTH_PHANTOM_DB)


def phantom_twin(case: Case, swift_text: str) -> Case:
    """The device case's alias-free twin: the truth ladder per step as a
    phantom (input-normalized: the truth output amplitude over the drive),
    every order under Nyquist, the same grid."""
    d = parse(swift_text)
    orders = [int(c[1:]) for c in d.rows[0] if re.fullmatch(r"h\d+", c)]
    gain = _num(d.header["loop"]["chain_gain"])
    ladders = []
    for r in sorted(d.rows, key=lambda r: r["index"]):
        a = r["input_amplitude"] * gain
        ladders.append(",".join(repr(0.0 if math.isnan(r["truth_h%d" % k]) else r["truth_h%d" % k] / a) for k in orders))
    args = ["--source", "phantom", "--amps-per-step", ";".join(ladders)]
    for flag in ("--floor-db", "--ceiling-db", "--steps", "--plugin-window", "--rate", "--frequency"):
        if flag in case.args:
            i = case.args.index(flag)
            args += [flag] if flag == "--plugin-window" else [flag, case.args[i + 1]]
    return Case(case.name + "-twin", args, "smooth")


def run_all(tool: str, m: dict, manifest_path: Optional[str] = None, dump_dir: Optional[str] = None
            ) -> Dict[str, Tuple[Case, str, str]]:
    results: Dict[str, Tuple[Case, str, str]] = {}
    for case in CASES:
        swift = run_swift(tool, case.args)
        results[case.name] = (case, swift, run_python(case.args, manifest_path))
        if case.name in TWIN_OF:
            twin = phantom_twin(case, swift)
            results[twin.name] = (twin, run_swift(tool, twin.args), run_python(twin.args, manifest_path))
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for name, (case, swift, python) in results.items():
            with open(os.path.join(dump_dir, name + ".swift.tsv"), "w", encoding="utf-8") as f:
                f.write(swift)
            with open(os.path.join(dump_dir, name + ".py.tsv"), "w", encoding="utf-8") as f:
                f.write(python)
    return results


def leakage_from(results: Dict[str, Tuple[Case, str, str]]) -> Dict[int, Dict[int, float]]:
    return leakage_map(results["a-linear"][1])


def measure(argv=None) -> int:
    """Print the measured distributions the tolerances are set from."""
    manifest_path = argv[0] if argv else None
    m = cp.load_manifest(manifest_path or cp.DEFAULT_MANIFEST)
    tool = build_tool()
    results = run_all(tool, m, manifest_path, os.environ.get("COMPRESSION_DUMP_DIR"))
    leakage = leakage_from(results)
    print("estimator leakage (dB re H1) at steps 0 / 17 / 34 per order:",
          {k: [round(v.get(j, float("nan")), 1) for j in (0, 17, 34)] for k, v in leakage.items()})
    print("%-22s %9s %9s %-22s %9s %7s %9s %9s %-12s %9s %-26s %9s %9s %8s %8s %9s %s" % (
        "case", "hdr", "row", "at", "truth", "content", "H1 err", "harm err", "at", "residue", "at", "thd err", "thd res", "fade", "knee", "cleanup", "issues"))
    for name, (case, swift, python) in results.items():
        r = compare(case, swift, python, m, leakage)
        issues = r.header_field_mismatches + r.discrete_mismatches
        print("%-22s %9.2e %9.2e %-22s %9.2e %7d %9.2e %9.2e %-12s %9.2e %-26s %9.2e %9.2e %8.4f %8.4f %9.2e %d" % (
            name, r.swift_header_db, r.swift_row_db, r.swift_row_at, r.swift_truth_db, r.content_count, r.h1_error_db, r.harmonic_error_db,
            r.harmonic_error_at, r.harmonic_residue_db, r.harmonic_residue_at, r.thd_error_db, r.thd_residue_db,
            r.fade_error_db, r.knee_error_db, r.cleanup_error_db, len(issues)))
        for issue in issues[:6]:
            print("    ", issue[:200])
    # The read-time verdicts, one line per case.
    for name, (case, swift, python) in results.items():
        d = parse(swift)
        print("%-20s knee %s | cleanup %s | source %s | runs %s" % (
            name, d.header["knee"].get("label") or d.header["knee"].get("state"), cp.cleanup_fields((d.header["cleanup"]["state"], _num(d.header["cleanup"]["level_dbfs"]))),
            swift.split("# floor source: ")[1].split("\n")[0], d.header["floor runs"]["runs"]))
    g0, g12 = parse(results["g-gain0"][1]), parse(results["g-gain12"][1])
    worst = max(abs((b["output_db"] - a["output_db"]) - 12) for a, b in zip(g0.rows, g12.rows))
    print("gain: knee %s vs %s; worst |out(12) − out(0) − 12| = %.2e dB; classes equal: %s" % (
        g0.header["knee"]["input_dbfs"], g12.header["knee"]["input_dbfs"], worst,
        all(a["floor_class"] == b["floor_class"] for a, b in zip(g0.rows, g12.rows))))
    z, l = parse(results["a-tanh8"][1]), parse(results["h-latency"][1])
    worst = max(max(_diff(a["h%d" % k], b["h%d" % k]) for k in range(1, 10)) for a, b in zip(z.rows, l.rows))
    print("latency: analyzed %s, worst cell difference %.2e" % (l.header["loop"]["analyzed_latency_samples"], worst))
    mc = parse(results["h-miscut"][1])
    print("mis-cut by %d sample(s): worst |H1 err| %.2e dB over steps but the last" % (
        MISCUT_SAMPLES, max(abs(r["output_db"] - r["truth_output_db"]) for r in mc.rows if r["index"] < max(x["index"] for x in mc.rows))))
    sep = parse(results["j-separation"][1])
    print("one-bin separation on a phantom with no fundamental: median depth %s dB (the borrowed bar is 76)" % sep.header["fundamental verdict"]["median_depth_db"])
    ks = parse(results["k-simulation"][1])
    print("simulation assembly: knee %s vs the app assembly's %s" % (ks.header["knee"].get("input_dbfs"), z.header["knee"]["input_dbfs"]))
    return 0


if __name__ == "__main__":
    sys.exit(measure(sys.argv[1:]))
