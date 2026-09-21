#!/usr/bin/env python3
"""The Gain Map parity comparison — shared by the CI test
(`test_parity_journey.py`) and the document generator (`make methods-docs`
writes `generated/parity-journey.tex` from the same numbers), so the
chapter's worked-example tables and the test's verdict cannot disagree.

Every case runs the shipped tool (`analysisdump journey-synth`) and the
Python reimplementation (`gain_map.py`) on one synthetic device through one
synthetic loop and compares:

* Swift vs Python — every header quantity (the calibration's chain gain
  and stamp, the residue per column per length, the masks, the presence
  verdict, the peak tile, the cleanup tile and every column's reading, the
  summaries' cleanup) and every cell (THD, every stored order, the three
  masks, the presence reading, the two margin halves, the composed margin,
  the tile's flags) — numerically to a stated tolerance, discrete values
  exactly — and the truth's own read-time half the same way;
* the shipped result vs the closed-form ladder — every content harmonic
  cell and every THD cell, AFTER the analyzer's leakage allowance (below);
  the cleanup crossing against the truth curve's; the presence verdict and
  the peak state against the truth's.

Part B — the read-time layer (the composed floor with its three sources,
the peak tile with its corroboration, the three-state cleanup) — has a
second parity target the oracle cannot make: the kernel test's own
transcribed corpus grids and stamps (`GainMapCorpusFixtures.swift`, records
59 / 428 / 65 / 446 and five bare-loop nulls, read from a store copy on
2026-09-06). Stored records are not the parity target for a CAPTURE — they
hold results, not raw captures — but for the READ-TIME half the stored grid
IS the input, and those fixtures are the store's own figures pinned to the
digit by the kernel's test, so they are the one legitimate exception: the
Python reads the fixture SOURCE by repo path and must reproduce the pinned
tiles.

The tolerances were SET FROM MEASUREMENT on 2026-09-20 (`measure()` below
prints the distributions the #306 chapter-four handoff quotes), never from
hope; each carries its measured value.
"""
from __future__ import annotations

import io
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

import gain_map as gm

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
TOOL_PACKAGE = os.path.join(REPO, "Tools", "analysisdump")
PY = os.path.join(HERE, "gain_map.py")
CORPUS_FIXTURES = os.path.join(REPO, "Packages", "MeasureKit", "Tests", "MeasureKitTests", "GainMapCorpusFixtures.swift")

# --- Tolerances ------------------------------------------------------------

# Swift vs Python on every dB quantity that carries CONTENT — a harmonic
# cell whose truth stands within EMPTY_DEPTH_DB of the truth fundamental,
# every measured cell on a capture with noise in it (the noise is the same
# stream on both sides), a margin, a residue at a column where it is a
# reading and not dust, a stamp point above the dust, the chain gain, the
# cleanup levels, the tile figures. Measured maximum on 2026-09-20 over
# the unfiltered cases: 5.1e−8 dB — the ninth-order TRUTH cell of tanh(2)
# at the loudest level (a quadrature value 130 dB under the fundamental,
# summed in two orders), with every MEASURED cell at or under 3.3e−9 and
# every header quantity at 1.6e−8 (the calibration's chain gain, a median
# of interpolated |H1| reads). Set 1e−6: two orders above the measurement
# and an order below a method change (a one-sample window shortening
# moved chapter one's reads by 1e−5).
T_SWIFT_DB = 1e-6
# The same on a capture rendered through a biquad (a pre- or post-filter):
# the direct-form recursion accumulates rounding differently in scipy's
# C loop and the Swift loop over half a million samples per level.
# Measured 2026-09-20: 1.8e−6 dB (the post-filtered polynomial's H3 at
# the top column) and 1.2e−6 (the pre-filtered tanh's H5). Set 1e−4.
T_SWIFT_DB_FILTERED = 1e-4
# A harmonic cell is DUST — an analytically empty order of a symmetric
# device, the identity's every harmonic — when its TRUTH sits more than
# this far below the truth fundamental; the two FFTs' and the two
# quadratures' dust differ freely (measured: 33 dB on tanh's even orders,
# 50 dB on the identity's), so dust is not compared, only stated.
EMPTY_DEPTH_DB = 140.0
# A residue column is a reading (compared to T_SWIFT_DB) when the Swift
# side reads above this; below it both sides are dust (measured: the
# residue differs by 1.2e−4 dB at −229 dB, 0.0 at every column above
# −150).
RESIDUE_DUST_DB = -150.0
# A stamp point is a reading when the loop's THD there is above this
# (a noiseless identity loop's stamp is the deconvolver's own residue,
# 1e−9 and below — dust on both sides).
STAMP_DUST = 1e-7

# The shipped read against the closed-form ladder, on a NOISELESS capture,
# in dB, AFTER the analyzer's leakage allowance. A synchronized-sweep
# analysis separates orders by windowing the deconvolved impulse response,
# and the separation is finite AND geometry-dependent: on the journey's
# own geometry (a 5 s sweep, a 32 768-point response) the pure phantom [1]
# — whose truth is exactly zero at every order above the first — reads
# the loudest order's leakage into each order's window per column (the
# LEAKAGE MAP: −70 dB into H2's window at the first unmasked column, −96
# into H3's, −124 into H5's; a column up, −104 / −133 / −155). A cell
# whose truth sits c dB above the leakage landing in its window can read
# up to 20·log10(1 + 10^(−c/20)) dB from the truth by the analyzer alone
# (0.27 dB at c = 30, 0.086 at 40); that allowance is subtracted before
# the bar is applied and what remains is the method's own error. MEASURED
# 2026-09-20, the raw error tracks that bound: at 30 dB of clearance the
# worst raw error is 0.18 dB (the polynomial's H3 at the quietest level,
# 45 Hz) and at 40 dB 0.068 (tanh's H5), against bounds of 0.27 and
# 0.086; the residue after the allowance is 0.012 dB on tanh(2), 3.7e−4
# on the polynomial, 5.1e−3 and 4.0e−2 on their phantom twins (the twin's
# H3 at the quietest level, two columns up — 15 dB of clearance, where the
# phantom's fade envelope enters its harmonics once and the device's
# enters cubed), and 0.148 on the tanh behind a 40 Hz high-pass PRE-filter
# — the truth there treats each column's fundamental as a steady tone
# through the filter, and the sweep is not steady. Three classes, set from
# those figures.
T_TRUTH_SMOOTH_DB = 0.05
T_TRUTH_PHANTOM_DB = 0.05
T_TRUTH_FILTERED_DB = 0.3
# The harmonic-cell comparison's clearance bars — the measurement prints
# the worst raw error at each so the chapter can quote the tracking.
RESOLVED_BARS_DB = (20, 30, 40)
RESOLVED_BAR_DB = 30
# The THD cells against the truth THD, after the same allowance built from
# the analyzer's residue at that column for the case's own sweep length
# (the THD of a pure fundamental) scaled by the loudest order over the
# fundamental. Measured 2026-09-20: 4.0e−8 (tanh), 6.4e−5 (the
# polynomial), 1.7e−5 (its twin), 9.0e−2 (the pre-filtered tanh).
T_THD_SMOOTH_DB = 1e-3
T_THD_FILTERED_DB = 0.2
# The cleanup crossing per unmasked column: the measured curve's
# interpolated 1 % crossing against the truth curve's at the same
# column. Measured 2026-09-20: 0.044 dB (tanh), 0.090 (the polynomial),
# 0.197 (its twin) — the worst at the first unmasked column in every
# case, where the residue's −70 dB H2 leak sits inside the summed THD and
# moves the crossing. Set 0.3.
T_CLEANUP_DB = 0.3
# The identity through seeded noise: the residue at the first unmasked
# column must read #291's three numbers (−46.3 / −70.1 / −86.7 dB at
# 2 / 5 / 10 s on the shipped grid) from the Python's own analysis, to
# within this — a comparison against a law's ROUNDED figures (measured
# −46.322 / −70.112 / −86.668).
T_RESIDUE_VS_LAW_DB = 0.05
RESIDUE_LAW_DB = {2: -46.3, 5: -70.1, 10: -86.7}
# The #100 term: the same device and noise through a loop 12 dB louder
# must give every composed margin within this of the loop at unity gain
# — the noise is referred to the input, so the whole capture scales and
# the margins move only if the term is wrong. Measured 2026-09-20:
# 5.0e−11 dB, with H1 moved by 12.000000 dB and the stamp's chain gain
# reading 12.
T_GAIN_INVARIANCE_DB = 1e-6
# A capture 100 samples late through the loop must give every harmonic
# cell identical to the zero-latency capture — the calibrator found the
# latency and the aligned cut is exact. Measured 2026-09-20: 0.0.
T_LATENCY_DB = 1e-9
# Part B on the corpus grids: the Python's tiles against the kernel's own
# figures — the two peaks pinned by the kernel test to 0.1 dB (11.2116 %
# and 6.2191 %), the two divider bounds and the five nulls' bounds as the
# kernel's own tile printed them on 2026-09-20 through the stored-record
# reader (0.9645661324658485 %, 0.7786771870974883 %, and 0.1306 / 0.1061 /
# 0.1193 / 0.1301 / 0.1056 %). Measured 2026-09-20: the Python's tiles
# equal the Swift's to the printed digit, its composed margins within
# 8.3e−12 dB on every cell, its rig-noise margins bit-equal.
T_CORPUS_PEAK_DB = 0.1
T_CORPUS_BOUND_RELATIVE = 1e-9
CORPUS_PINNED = {
    59: ("at_floor", 0.9645661324658485), 428: ("at_floor", 0.7786771870974883),
    65: ("peak", 11.211647654319302), 446: ("peak", 6.219054865333713),
    404: ("at_floor", 0.13062799612523074), 410: ("at_floor", 0.10609583272701727),
    416: ("at_floor", 0.11927297744702982), 422: ("at_floor", 0.13013609074298024),
    464: ("at_floor", 0.10555177760450558),
}


@dataclass(frozen=True)
class Case:
    name: str
    args: List[str]
    kind: str  # smooth | noise | absent | never | plugin | gain | operative | latency | filtered

    @property
    def noisy(self) -> bool:
        return "--noise-db" in self.args

    @property
    def filtered(self) -> bool:
        return "--pre" in self.args or "--post" in self.args

    @property
    def swift_tolerance_db(self) -> float:
        return T_SWIFT_DB_FILTERED if self.filtered else T_SWIFT_DB


_NOISE = ["--noise-db", "-100"]

CASES = [
    # (a0) a pure fundamental (the phantom [1]) — the analyzer's own leakage into every order's
    #      window on the journey's geometry, per column: the allowance every truth comparison uses.
    Case("a-linear", ["--source", "phantom", "--amps", "1"], "linear"),
    # (a) the soft clipper on the hardware lattice, noiseless — every cell against the ladder.
    Case("a-tanh", ["--source", "tanh", "--gain", "2"], "smooth"),
    Case("a-poly", ["--source", "poly", "--a2", "0.2", "--a3", "0.3"], "smooth"),
    # (b) the identity through seeded noise at the three offered lengths — the residue, the margins, the bound.
    Case("b-identity-2s", ["--source", "identity", "--duration", "2"] + _NOISE, "noise"),
    Case("b-identity-5s", ["--source", "identity"] + _NOISE, "noise"),
    Case("b-identity-10s", ["--source", "identity", "--duration", "10"] + _NOISE, "noise"),
    # (c) a device with no fundamental: a phantom whose fundamental sits 80 dB under its second harmonic.
    Case("c-absent", ["--source", "phantom", "--amps", "0.0001,1"] + _NOISE, "absent"),
    # (d) the three cleanup states: (a) cleans up; the identity is always clean; a hard clipper whose
    #     threshold sits under the lattice's floor is never clean.
    Case("d-never-clean", ["--source", "hardclip", "--threshold", "0.002"] + _NOISE, "never"),
    # (e) the #100 term: (a) through noise at unity gain, and the same loop 12 dB louder.
    Case("e-tanh-gain0", ["--source", "tanh", "--gain", "2"] + _NOISE, "gain"),
    Case("e-tanh-gain12", ["--source", "tanh", "--gain", "2", "--chain-gain-db", "12"] + _NOISE, "gain"),
    # (f) the #150 path: a silent stamp, the operative floor governing.
    Case("f-operative", ["--source", "tanh", "--gain", "2", "--operative-floor-rms", "0.0001"] + _NOISE, "operative"),
    # (g) the plugin window with the hard clipper: the knee inside the window, the ceiling row at 0 dBFS.
    Case("g-plugin-hardclip", ["--source", "hardclip", "--threshold", "0.1", "--plugin-window"] + _NOISE, "plugin"),
    # (j) the worked example captured 100 samples late — the aligned cut is exact.
    Case("j-latency", ["--source", "tanh", "--gain", "2", "--latency-samples", "100"], "latency"),
    # (k) filters: the soft clipper behind a pre-filter, the polynomial through a post-filter.
    Case("k-tanh-prehp", ["--source", "tanh", "--gain", "2", "--pre", "highpass", "--pre-hz", "40"], "filtered"),
    Case("k-poly-postlp", ["--source", "poly", "--a2", "0.2", "--a3", "0.3", "--post", "lowpass", "--post-hz", "1550"], "filtered"),
]

WORKED = "a-tanh"
TWIN_OF = ("a-tanh", "a-poly")


# --- Running the two implementations --------------------------------------


def build_tool() -> str:
    subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    out = subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE,
                          "--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
    return os.path.join(out, "analysisdump")


def run_swift(tool: str, args: List[str]) -> str:
    return subprocess.run([tool, "journey-synth"] + args, check=True, capture_output=True, text=True).stdout


def run_python(args: List[str], manifest: Optional[str] = None) -> str:
    cmd = [sys.executable, PY] + args
    if manifest:
        cmd += ["--manifest", manifest]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


# --- Parsing ----------------------------------------------------------------

NUMBER = re.compile(r"-?(?:\d+\.\d+(?:e[-+]?\d+)?|\d+e[-+]?\d+|\d+|inf|nan)")
LIST = re.compile(r"(\w+)=\[([^\]]*)\]")
FIELD = re.compile(r"(\w+)=([^\s\[\]]+)")
TEXT_COLUMNS = {"presence", "truth_presence"}
INT_COLUMNS = {"level_index", "freq_index"}


@dataclass
class Dump:
    header: Dict[str, Dict[str, str]]
    lists: Dict[str, Dict[str, List[str]]]
    series: Dict[str, Dict[int, str]]     # "residue length_s=2.0" → column → value; "stamp" → index → "f:thd"
    rows: List[Dict[str, object]]

    def value(self, line: str, key: str) -> float:
        return _num(self.header[line][key])

    def field(self, line: str, key: str) -> str:
        return self.header[line][key]

    @property
    def orders(self) -> List[int]:
        return [int(o) for o in self.lists["grid"]["orders"]]


def _num(s: str) -> float:
    return float("nan") if s == "nan" else float(s)


def parse(text: str) -> Dump:
    header: Dict[str, Dict[str, str]] = {}
    lists: Dict[str, Dict[str, List[str]]] = {}
    series: Dict[str, Dict[int, str]] = {}
    body: List[str] = []
    for line in text.splitlines():
        if not line.startswith("#"):
            body.append(line)
            continue
        content = line[2:]
        if ": " in content:
            key, rest = content.split(": ", 1)
        else:
            # `# column j f_hz=… state=…` — the stored reader's own shape.
            key, rest = content.split(" state=", 1)
            rest = "state=" + rest
        key = key.strip()
        rest = rest.strip()
        if key in ("stamp",) or key.startswith("residue length_s=") or key.startswith("analyzer residue"):
            entries = {}
            for i, item in enumerate(rest.split()):
                if key == "stamp":
                    entries[i] = item
                else:
                    j, v = item.split(":")
                    entries[int(j)] = v
            series[key] = entries
            header[key] = {}
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
    return Dump(header, lists, series, rows)


def _diff(a: float, b: float) -> float:
    if math.isnan(a) and math.isnan(b):
        return 0.0
    if math.isnan(a) or math.isnan(b):
        return math.inf
    if math.isinf(a) and math.isinf(b) and a == b:
        return 0.0
    return abs(a - b)


# --- The comparison --------------------------------------------------------

# Header fields compared numerically (dB or dB-like), by line.
HEADER_DB_KEYS = {
    "calibration": ["chain_gain_db", "resolved_chain_gain_db", "delivered_dbfs", "level_dbfs"],
    "peak tile": ["peak_pct", "bound_pct", "depth_db"],
    "truth peak tile": ["peak_pct", "bound_pct", "depth_db"],
    "cleanup tile (nearest column to 220.0 Hz)": ["level_dbfs"],
    "truth cleanup tile (nearest column to 220.0 Hz)": ["level_dbfs"],
    "summaries cleanup (FeatureExtractor.extract(journey:))": ["level_dbfs", "confidence"],
    "truth summaries cleanup (FeatureExtractor.extract(journey:))": ["level_dbfs", "confidence"],
    "fundamental verdict": ["absent_fraction", "median_depth_db"],
    "truth fundamental verdict": ["absent_fraction", "median_depth_db"],
}
# Header fields compared exactly.
HEADER_EXACT_KEYS = {
    "plan": ["levels", "preroll_samples", "tail_samples", "sweep_samples", "harmonic_count", "response_fft_length",
             "export_frequency_count"],
    "loop": ["latency_samples", "calibration_seed", "calibration_noisy"],
    "calibration": ["latency_samples", "preroll_samples", "tail_samples", "stamp_points", "usable_stamp_points",
                    "stamp_median_points", "analyzed_sweep_count"],
    "precheck": ["in_signal_governs"],
    "masks": [],
    "fundamental verdict": ["absent", "evaluated"],
    "truth fundamental verdict": ["absent", "evaluated"],
    "peak tile": ["state", "margins_derivable"],
    "truth peak tile": ["state", "margins_derivable"],
    "cleanup tile (nearest column to 220.0 Hz)": ["state", "column"],
    "truth cleanup tile (nearest column to 220.0 Hz)": ["state", "column"],
    "summaries cleanup (FeatureExtractor.extract(journey:))": ["state"],
    "truth summaries cleanup (FeatureExtractor.extract(journey:))": ["state"],
}
HEADER_LIST_KEYS = {"plan": ["level_dbfs"], "grid": ["f_hz", "orders"], "masks": ["bottom_edge", "top_edge", "truncated"],
                    "loop": ["level_seeds"]}
ROW_EXACT_KEYS = ["truncated", "bottom_edge", "top_edge", "presence", "clear", "corroborated",
                  "truth_presence", "truth_clear", "truth_corroborated"]
ROW_DB_KEYS = ["thd", "rig_margin_db", "margin_db", "truth_thd", "truth_rig_margin_db", "truth_margin_db"]


@dataclass
class CaseReport:
    case: Case
    swift_header_db: float
    swift_row_db: float
    swift_row_at: str
    swift_empty_db: float                 # the worst |Swift − Python| on dust (harmonic cells, residues, truth dust)
    header_field_mismatches: List[str]
    discrete_mismatches: List[str]
    content_count: int
    truth_error_db: float                 # worst |Swift − truth| raw, content harmonic cells (the case's band)
    truth_error_label: str
    truth_residue_db: float               # worst (|Swift − truth| − leakage allowance)
    truth_residue_label: str
    thd_error_db: float                   # worst |Swift − truth| on THD cells, raw
    thd_residue_db: float                 # after the allowance
    thd_residue_label: str
    cleanup_error_db: float               # worst |measured crossing − truth crossing| over unmasked columns
    bar_error: Dict[int, Tuple[float, str]]  # worst raw |Swift − truth| where the truth clears the leakage by the bar
    swift: Dump
    python: Dump


def leakage_map(linear_text: str) -> Dict[int, List[float]]:
    """The analyzer's own leakage into each order's window on this
    geometry, per column, in dB re the fundamental — read off the pure
    phantom [1]'s own harmonic cells (its truth is exactly zero at every
    order above the first, so every read IS leakage), the worst over the
    levels (a ratio, level-invariant to rounding)."""
    d = parse(linear_text)
    out: Dict[int, List[float]] = {}
    n = len(d.lists["grid"]["f_hz"])
    for k in d.orders:
        if k == 1:
            continue
        out[k] = [-math.inf] * n
    for r in d.rows:
        h1 = r["h1_db"]
        for k in out:
            v = r[f"h{k}_db"]
            if not math.isnan(v) and not math.isnan(h1):
                out[k][r["freq_index"]] = max(out[k][r["freq_index"]], v - h1)
    return out


def leakage_allowance_db(leak_re_content_db: float) -> float:
    """The analyzer's own contribution to a read whose content sits
    `−leak_re_content_db` above the leakage landing in its window: a read
    error of up to 20·log10(1 + 10^(leak/20))."""
    return 20 * math.log10(1 + 10 ** (leak_re_content_db / 20))


def _valid_top(f2: float, fs: float, order: int) -> float:
    return min(f2, fs / (2 * order + 1))


def compare(case: Case, swift_text: str, python_text: str, m: dict, leakage: Optional[Dict[int, List[float]]] = None) -> CaseReport:
    sw, py = parse(swift_text), parse(python_text)
    assert set(sw.header) == set(py.header), f"{case.name}: header lines differ: {set(sw.header) ^ set(py.header)}"
    tol = case.swift_tolerance_db
    header_db = 0.0
    field_mismatches: List[str] = []
    for line, keys in HEADER_DB_KEYS.items():
        for key in keys:
            if key in sw.header[line] or key in py.header[line]:
                header_db = max(header_db, _diff(_num(sw.header[line].get(key, "nan")), _num(py.header[line].get(key, "nan"))))
    for line, keys in HEADER_EXACT_KEYS.items():
        if line not in sw.header:
            continue
        for key in keys:
            a, b = sw.header[line].get(key), py.header[line].get(key)
            if a != b:
                field_mismatches.append(f"{line}.{key}: {a} vs {b}")
    for line, keys in HEADER_LIST_KEYS.items():
        for key in keys:
            a, b = sw.lists[line].get(key, []), py.lists[line].get(key, [])
            if len(a) != len(b):
                field_mismatches.append(f"{line}.{key}: {len(a)} vs {len(b)} entries")
                continue
            if key in ("orders", "bottom_edge", "top_edge", "truncated", "level_seeds"):
                if a != b:
                    field_mismatches.append(f"{line}.{key}: {a} vs {b}")
            else:
                header_db = max(header_db, max((_diff(_num(x), _num(y)) for x, y in zip(a, b)), default=0.0))
    empty_db = 0.0
    # The stamp: 127 (f, thd) pairs, compared in dB.
    for i, item in sw.series["stamp"].items():
        f_a, t_a = item.split(":")
        f_b, t_b = py.series["stamp"][i].split(":")
        header_db = max(header_db, _diff(_num(f_a), _num(f_b)))
        ta, tb = _num(t_a), _num(t_b)
        if ta > 0 and tb > 0:
            if ta > STAMP_DUST:
                header_db = max(header_db, abs(20 * math.log10(ta / tb)))
            else:
                empty_db = max(empty_db, abs(20 * math.log10(ta / tb)))
    # The residues per length and worst: a reading where the Swift side is
    # above the dust level, dust otherwise.
    for key in sw.series:
        if key == "stamp":
            continue
        for j, a in sw.series[key].items():
            b = py.series[key][j]
            d = _diff(_num(a), _num(b))
            if _num(a) > RESIDUE_DUST_DB:
                header_db = max(header_db, d)
            else:
                empty_db = max(empty_db, d)
    # The per-column cleanup lines.
    for key in sw.header:
        if key.startswith("column ") or key.startswith("truth column "):
            if sw.header[key]["state"] != py.header[key]["state"]:
                field_mismatches.append(f"{key}.state: {sw.header[key]['state']} vs {py.header[key]['state']}")
            header_db = max(header_db, _diff(_num(sw.header[key]["level_dbfs"]), _num(py.header[key]["level_dbfs"])))
    # Rows.
    assert len(sw.rows) == len(py.rows), f"{case.name}: row counts differ"
    orders = sw.orders
    fs = _num(sw.header["plan"]["fs"])
    f2 = _num(sw.header["plan"]["f2"])
    row_db = 0.0
    row_at = ""
    margins_are_readings = case.noisy or "--operative-floor-rms" in case.args
    duration = float(case.args[case.args.index("--duration") + 1]) if "--duration" in case.args else 5.0
    residue_key = "residue length_s=%s" % gm.fmt(duration)
    discrete: List[str] = []
    content = 0
    truth_error, truth_label = 0.0, ""
    truth_residue, residue_label = -math.inf, ""
    bar_error: Dict[int, Tuple[float, str]] = {b: (0.0, "") for b in RESOLVED_BARS_DB}
    thd_error = 0.0
    thd_residue, thd_label = -math.inf, ""
    for s, p in zip(sw.rows, py.rows):
        cell = f"({s['level_index']},{s['freq_index']})"
        for k in ROW_EXACT_KEYS:
            if str(s[k]) != str(p[k]):
                discrete.append(f"{cell}.{k}: {s[k]} vs {p[k]}")
        # Dust on the truth side (a truth THD that is numerically zero on
        # one side and 1e−17 on the other) makes the truth margins and
        # flags incomparable at that cell; the measured side is always
        # compared.
        truth_thd_dust = (s["truth_thd"] if not math.isnan(s["truth_thd"]) else 0.0) < 1e-12
        def note(k, d):
            nonlocal row_db, row_at
            if d > row_db:
                row_db, row_at = d, f"{k} {cell}"
        for k in ROW_DB_KEYS:
            if k.startswith("truth_") and truth_thd_dust:
                continue
            if k.endswith("margin_db") and not margins_are_readings:
                continue
            a, b = s[k], p[k]
            if k == "thd" and truth_thd_dust and not case.noisy:
                continue  # the analyzer's own dust, which the two FFTs make differently
            if k in ("thd", "truth_thd"):
                if math.isnan(a) and math.isnan(b):
                    continue
                if a > 0 and b > 0:
                    note(k, abs(20 * math.log10(a / b)))
                elif a != b:
                    discrete.append(f"{cell}.{k}: {a} vs {b}")
            else:
                note(k, _diff(a, b))
        th1 = s["truth_h1_db"]
        loudest = max((s[f"truth_h{k}_db"] for k in orders if not math.isnan(s[f"truth_h{k}_db"])), default=math.nan)
        for k in orders:
            a, b = s[f"h{k}_db"], p[f"h{k}_db"]
            t = s[f"truth_h{k}_db"]
            is_content = (not math.isnan(t)) and (not math.isnan(th1)) and t - th1 > -EMPTY_DEPTH_DB
            if (is_content or case.noisy) and not math.isnan(a) and not math.isnan(b):
                note(f"h{k}_db", _diff(a, b))
            elif not math.isnan(a) and not math.isnan(b):
                empty_db = max(empty_db, _diff(a, b))
            elif math.isnan(a) != math.isnan(b):
                discrete.append(f"{cell}.h{k}_db: {a} vs {b}")
            # The truth's own dust differs freely between the two quadratures.
            ta, tb = s[f"truth_h{k}_db"], p[f"truth_h{k}_db"]
            if is_content:
                note(f"truth_h{k}_db", _diff(ta, tb))
            elif not math.isnan(ta) and not math.isnan(tb):
                empty_db = max(empty_db, _diff(ta, tb))
            # Swift vs truth, on a noiseless capture, in the case's band.
            if case.noisy or not is_content or math.isnan(a) or s["bottom_edge"] == 1 or s["top_edge"] == 1:
                continue
            f0 = s["freq_hz"]
            top = _valid_top(f2, fs, k)
            in_band = (f0 <= top) if case.kind == "phantom" else (f0 <= top / 2)
            if not in_band or f0 < 30:
                continue
            content += 1
            err = abs(a - t)
            if err > truth_error:
                truth_error, truth_label = err, f"H{k} {cell}"
            leak = leakage[k][s["freq_index"]] if leakage and k in leakage else -math.inf
            allowance = leakage_allowance_db(leak + loudest - t)
            if err - allowance > truth_residue:
                truth_residue, residue_label = err - allowance, f"H{k} {cell}"
            clearance = t - (loudest + leak)
            for bar in RESOLVED_BARS_DB:
                if clearance >= bar and err > bar_error[bar][0]:
                    bar_error[bar] = (err, f"H{k} {cell}")
        # THD cells against the truth THD, with the same allowance built
        # from the loudest order's leakage into the summed orders.
        if (not case.noisy) and s["bottom_edge"] == 0 and s["top_edge"] == 0 and s["truncated"] == 0 \
                and not math.isnan(s["thd"]) and not math.isnan(s["truth_thd"]) and s["truth_thd"] > 0 and s["thd"] > 0 \
                and not truth_thd_dust:
            f0 = s["freq_hz"]
            if f0 >= 30 and f0 <= _valid_top(f2, fs, 3) / 2:
                err = abs(20 * math.log10(s["thd"] / s["truth_thd"]))
                # The leakage into THD: the analyzer's residue at this
                # column for the case's own sweep length (the THD of a pure
                # fundamental), scaled by the loudest order over the
                # fundamental, against the truth THD.
                residue = _num(sw.series[residue_key][s["freq_index"]]) if residue_key in sw.series else -math.inf
                allowance = leakage_allowance_db(residue + (loudest - th1) - 20 * math.log10(s["truth_thd"]))
                thd_error = max(thd_error, err)
                if err - allowance > thd_residue:
                    thd_residue, thd_label = err - allowance, f"THD {cell}"
    # The cleanup crossing per column: measured against the truth curve's.
    cleanup_error = 0.0
    if not case.noisy:
        bottom = sw.lists["masks"]["bottom_edge"]
        top = sw.lists["masks"]["top_edge"]
        for key in sw.header:
            if key.startswith("column "):
                j = int(key.split()[1])
                if bottom[j] == "1" or top[j] == "1":
                    continue
                tkey = "truth " + key
                a, b = sw.header[key], sw.header[tkey]
                if a["state"] != b["state"]:
                    discrete.append(f"{key}: cleanup {a['state']} vs truth {b['state']}")
                elif a["state"] == "cleans_up":
                    cleanup_error = max(cleanup_error, abs(_num(a["level_dbfs"]) - _num(b["level_dbfs"])))
    return CaseReport(case, header_db, row_db, row_at, empty_db, field_mismatches, discrete, content,
                      truth_error, truth_label, truth_residue, residue_label, thd_error, thd_residue, thd_label,
                      cleanup_error, bar_error, sw, py)


def truth_tolerance(case: Case) -> float:
    if case.kind == "phantom":
        return T_TRUTH_PHANTOM_DB
    return T_TRUTH_FILTERED_DB if case.filtered else T_TRUTH_SMOOTH_DB


def thd_tolerance(case: Case) -> float:
    return T_THD_FILTERED_DB if case.filtered else T_THD_SMOOTH_DB


# --- The twins ---------------------------------------------------------------


def phantom_twin(case: Case, swift_text: str) -> Case:
    """The alias-free control: the case's own truth ladder per level (read
    at the column whose validity admits every order, the grid's own first
    unmasked column) as a phantom on the same lattice, with no filter (a
    phantom carries no filter: it IS the response)."""
    d = parse(swift_text)
    orders = d.orders
    levels = len(d.lists["plan"]["level_dbfs"])
    g = _num(d.header["loop"]["chain_gain"])
    ladders = []
    for i in range(levels):
        row = next(r for r in d.rows if r["level_index"] == i and r["freq_index"] == 1)
        ladder = []
        for k in orders:
            t = row[f"truth_h{k}_db"]
            ladder.append(0.0 if math.isnan(t) else 10 ** (t / 20) / g)
        ladders.append(",".join(gm.fmt(x) for x in ladder))
    extra: List[str] = []
    for key in ("--floor-db", "--ceiling-db", "--levels", "--duration", "--rate", "--start", "--end", "--chain-gain-db"):
        if key in case.args:
            extra += [key, case.args[case.args.index(key) + 1]]
    if "--plugin-window" in case.args:
        extra.append("--plugin-window")
    return Case(case.name + "-twin", ["--source", "phantom", "--amps-per-level", ";".join(ladders)] + extra, "phantom")


# --- Part B on the corpus grids ----------------------------------------------


@dataclass
class CorpusRecord:
    pk: int
    title: str
    sample_rate: float
    frequencies: List[float]
    levels_db: List[float]
    thd: List[List[Optional[float]]]
    h1_db: List[List[Optional[float]]]
    stamp: List[Tuple[float, float]]
    stamp_amplitude: float
    stamp_chain_gain_db: float


def _swift_number_list(text: str) -> List[Optional[float]]:
    out = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        out.append(None if item == "nil" else float(item))
    return out


def corpus_records(path: str = CORPUS_FIXTURES) -> List[CorpusRecord]:
    """The kernel test's transcribed grids and stamps, read from the fixture
    SOURCE by repo path — the read-time half's one stored-input exception."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stamps: Dict[str, Tuple[float, float, List[Tuple[float, float]]]] = {}
    for m in re.finditer(r"static let (stamp\w+) = Stamp\(createdAt: \"[^\"]+\", sweepAmplitude: ([0-9.e-]+), chainGainDB: ([0-9.e-]+), points: \[(.*?)\]\)", text, re.S):
        points = [(float(a), float(b)) for a, b in re.findall(r"\(([0-9.e-]+), ([0-9.e-]+)\)", m.group(4))]
        stamps[m.group(1)] = (float(m.group(2)), float(m.group(3)), points)
    records = []
    for m in re.finditer(r"static let record(\d+) = Record\((.*?stamp: stamp\w+)\)", text, re.S):
        body = m.group(2)
        title = re.search(r'title: "([^"]+)"', body).group(1)
        fs = float(re.search(r"sampleRate: ([0-9.]+)", body).group(1))
        frequencies = _swift_number_list(re.search(r"frequencies: \[(.*?)\]", body, re.S).group(1))
        levels = _swift_number_list(re.search(r"levelDB: \[(.*?)\]", body, re.S).group(1))
        grids = {}
        for name in ("thd", "h1DB"):
            block = re.search(name + r": \[\n(.*?)\]\],", body, re.S).group(1) + "]"
            grids[name] = [_swift_number_list(row) for row in re.findall(r"\[([^\[\]]*)\]", block)]
        stamp_name = re.search(r"stamp: (stamp\w+)", body).group(1)
        amp, gain, points = stamps[stamp_name]
        records.append(CorpusRecord(int(m.group(1)), title, fs, [float(f) for f in frequencies],
                                    [float(l) for l in levels], grids["thd"], grids["h1DB"], points, amp, gain))
    assert records, "no records parsed from the fixture source"
    return records


def corpus_reading(record: CorpusRecord, m: dict) -> gm.Reading:
    """The Python's read-time half on one transcribed record: the kernel
    test's own calibration shape (a 20 Hz–43.2 kHz 10 s sweep at the stamp's
    amplitude, the stamp's chain gain) and the stored grid."""
    band = (float(m["gainMap"]["summary"]["band"]["lowHz"]), float(m["gainMap"]["summary"]["band"]["highHz"]))
    s = gm.Summary(record.frequencies, record.levels_db, [1], record.thd, {1: record.h1_db}, record.sample_rate, band)
    hdm = gm.calibration_manifest(m, 20.0)
    sweep = gm.hd.Sweep.from_manifest(hdm, f1=20.0, f2=43_200.0, requested_duration=10.0, fs=96_000.0,
                                      amplitude=record.stamp_amplitude)
    cal = gm.Calibration(sweep, 20 * math.log10(record.stamp_amplitude), 0, record.stamp_chain_gain_db,
                         [p for p in record.stamp if p[1] > 0], record.stamp, None)
    return gm.read(s, cal, None, m)


# --- The measurement ---------------------------------------------------------


def run_all(tool: str, m: dict, manifest_path: Optional[str] = None,
            dump_dir: Optional[str] = None) -> Dict[str, Tuple[Case, str, str]]:
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


def leakage_from(results: Dict[str, Tuple[Case, str, str]]) -> Dict[int, List[float]]:
    return leakage_map(results["a-linear"][1])


def measure(argv=None) -> int:
    """Print the measured distributions the tolerances are set from."""
    manifest_path = argv[0] if argv else None
    m = gm.load_manifest(manifest_path or gm.DEFAULT_MANIFEST)
    tool = build_tool()
    results = run_all(tool, m, manifest_path, os.environ.get("JOURNEY_DUMP_DIR"))
    leakage = leakage_from(results)
    print("leakage map (dB re H1, worst over levels) at columns 1..4 per order:",
          {k: [round(v[j], 1) for j in (1, 2, 3, 4)] for k, v in leakage.items()})
    print("%-22s %10s %10s %-22s %10s %8s %10s %10s %-14s %10s %10s %-12s %10s %s" % (
        "case", "hdr dB", "row dB", "at", "dust dB", "content", "vs truth", "residue", "at", "thd err", "thd res", "at", "cleanup", "issues"))
    for name, (case, swift, python) in results.items():
        r = compare(case, swift, python, m, leakage)
        issues = r.header_field_mismatches + r.discrete_mismatches
        print("%-22s %10.2e %10.2e %-22s %10.2e %8d %10.2e %10.2e %-14s %10.2e %10.2e %-12s %10.2e %d" % (
            name, r.swift_header_db, r.swift_row_db, r.swift_row_at, r.swift_empty_db, r.content_count, r.truth_error_db,
            r.truth_residue_db, r.truth_error_label, r.thd_error_db, r.thd_residue_db, r.thd_residue_label,
            r.cleanup_error_db, len(issues)))
        if r.content_count:
            print("    bars:", "  ".join("%d dB: %.2e at %s" % (b, e, at) for b, (e, at) in r.bar_error.items()))
        for issue in issues[:6]:
            print("    ", issue[:220])
    # The #100 invariance and the latency identity, from the runs above.
    g0, g12 = parse(results["e-tanh-gain0"][1]), parse(results["e-tanh-gain12"][1])
    worst = max(_diff(a["margin_db"], b["margin_db"]) for a, b in zip(g0.rows, g12.rows))
    print("gain invariance: worst |margin(12 dB) − margin(0 dB)| = %.2e dB; H1 shift %.6f dB" % (
        worst, g12.rows[0]["h1_db"] - g0.rows[0]["h1_db"]))
    z, l = parse(results["a-tanh"][1]), parse(results["j-latency"][1])
    worst = max(max(_diff(a[f"h{k}_db"], b[f"h{k}_db"]) for k in z.orders) for a, b in zip(z.rows, l.rows))
    print("latency: measured latency %s, worst cell difference %.2e dB" % (l.header["calibration"]["latency_samples"], worst))
    for name in ("b-identity-2s", "b-identity-5s", "b-identity-10s"):
        d = parse(results[name][2])
        print("%s: Python residue at column 1 — %s" % (name, {k: round(_num(v[1]), 3) for k, v in d.series.items() if k.startswith("residue")}))
    # Part B: the corpus grids.
    for r in corpus_records():
        reading = corpus_reading(r, m)
        print("corpus %d %s: peak %s" % (r.pk, r.title[:40], reading.peak))
    return 0


if __name__ == "__main__":
    sys.exit(measure(sys.argv[1:]))
