#!/usr/bin/env python3
"""The Waveform Matrix parity comparison — shared by the CI test
(`test_parity_matrix.py`) and the document generator (`make methods-docs`
writes `generated/parity-matrix.tex` from the same numbers), so the
chapter's worked-example tables and the test's verdict cannot disagree.

Every case runs the shipped tool (`analysisdump matrix-synth`) and the
Python reimplementation (`waveform_matrix.py`) on one synthetic device
through one synthetic loop over the shipped lattices and compares:

* Swift vs Python — the delivered lattices and every start index EXACTLY
  (the method is exact there: integers, and doubles the same arithmetic
  produces bit for bit), every discrete reading exactly (the note names,
  the badges, the truth kind), and every statistic to a stated tolerance
  (two implementations summing the same Float32 samples in different
  orders);
* the stored tile against its truth — EQUALITY to Float32 rounding on a
  memoryless device (the truth is the device's function of the float64
  tone; the tile is that rounded to Float32, and the measured departure is
  pinned to be exactly the tile's own quantization), and a measured residue
  on a device behind a filter (what the settle window left of the step's
  transient);
* the read-time layer — the stamp against the injected noise, the margins
  and badges, the mirror's two-site expression on both sides.

Part B — the lattice guarantees (nesting, anchor membership, the centre
index, the #372 tie), the two extraction refusals and the two decoder
refusals, the stamp and margin, the badge — is exercised on the oracle's
runs and on the manifest's delivered lattices; its parity status is
GENERATED from the run (`gen_docs.py`), never typed.

Tolerances are set from MEASUREMENT (`python parity_matrix.py` prints the
distributions), a little above the measured maximum, never from hope; each
carries its measured value. Where the method is exact the tolerance is
EQUALITY and the provenance says why.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import waveform_matrix as wmx

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
TOOL_PACKAGE = os.path.join(REPO, "Tools", "analysisdump")
PY = os.path.join(HERE, "waveform_matrix.py")

# --- Tolerances ------------------------------------------------------------
# Every figure below was MEASURED on 2026-09-22 by `python parity_matrix.py`
# (the Studio, 96 kHz, the shipped lattices) and each bar sits a little
# above its measurement, never at it and never from hope.

# EQUALITY, by construction, on every lattice value, every note name and
# cents figure, every start index, every sample count, every badge, the
# truth kind, the dead fractions and the truth stamp: the lattices are
# integer-and-double arithmetic both implementations perform in the same
# order (the delivered lattices at 3/5/7 and at the four volts factors —
# the #372 pair included — read back bit for bit), a start index is an
# integer, a badge is a comparison of two numbers that agree to the bars
# below. Measured: 0 mismatches on every case.
T_EXACT_MISMATCHES = 0
# The encoded payload's byte count: identical on every noiseless
# unfiltered case; on a case with noise or a slow filter the row stamps
# differ in their last bits (below) and their shortest-round-trip spelling
# can differ by a character. Measured: ≤ 5 bytes. Set 8.
T_PAYLOAD_BYTES = 8
# Swift vs Python on the SIGNAL statistics (rms, peak; the truth's too):
# the same Float32 samples summed in different orders (a sequential Double
# loop in Swift, numpy's pairwise sum). Measured maximum relative
# difference: 2.3e−14 on an unfiltered device (the identity 1.7e−15); 7.7e−12
# through a fast biquad; 1.2e−8 through a SLOW one (a 0.5 Hz second-order
# high-pass over a 1.2 M-sample carried stream — the two recursions round
# differently in the last bit and a handful of samples flip a Float32
# ulp). Set 1e−12 unfiltered, 1e−7 filtered.
T_SWIFT_RELATIVE = 1e-12
T_SWIFT_RELATIVE_FILTERED = 1e-7
# The MEANS (a near-zero mean has no relative scale): absolute, measured
# ≤ 6.1e−10. Set 1e−8.
T_SWIFT_MEAN_ABSOLUTE = 1e-8
# The ERROR quantities (the Float32 quantization, the max and rms error
# against the truth — residuals near zero): absolute, measured ≤ 3.7e−9
# (a rectifier behind the slow capacitor), 1.1e−16 on tanh(8) where the
# two libms' tanh differ by an ulp. Set 1e−7.
T_SWIFT_ERROR_ABSOLUTE = 1e-7
# The MARGINS in dB, compared only where the stamp is injected noise:
# measured ≤ 1.8e−7 dB (the rectifier's carried rows, whose stamp is the
# tail), 2e−13 elsewhere. Set 1e−5 dB.
T_SWIFT_MARGIN_DB = 1e-5
# The STAMP: the same noise stream bit for bit on both sides (chapter one's
# SplitMix64 vectorized), so it agrees to summation order — relative with
# noise (measured ≤ 8.3e−9, the rectifier's tail; 3e−15 on plain noise),
# absolute without (the filter's own numerical residue, ≤ 7.3e−10).
T_SWIFT_STAMP_RELATIVE = 1e-7
T_SWIFT_STAMP_ABSOLUTE = 1e-8
# The cross-check's figures (bin-centre reads against a mean over ~115
# cycles): summation order again, measured ≤ 3.6e−16. Set 1e−12.
T_SWIFT_CROSS = 1e-12
# The tile against its truth on a MEMORYLESS UNFILTERED device: EQUALITY to
# Float32 rounding — max |stored − truth| over every tile EQUALS the tile's
# own quantization max |Float32(capture) − capture| (measured 0 on the
# difference in every memoryless case; the quantization itself 5.9e−8
# relative at the identity's loudest tile, ≤ 2^−24 of the sample).
T_MEMORYLESS_EQUALS_QUANTIZATION = 0.0
# Through a FAST filter (a 40 Hz pre high-pass, a 1 kHz post low-pass —
# time constants far under the 0.15 s settle) the residue after the
# quantization is 2.3e−13 (the settle absorbed the transient): the
# relative residue stays 5.8e−8, the quantization's. Set 1e−7 relative,
# and 1e−10 absolute on what is left after the quantization.
T_FAST_FILTER_RELATIVE = 1e-7
T_FAST_FILTER_BEYOND_QUANTIZATION = 1e-10
# Through a SLOW output coupling capacitor (a second-order high-pass at 2 Hz
# and at 0.5 Hz — time constants of the settle's order and longer) the
# residue is what the settle window LEFT of the step's transient: measured
# 8.3e−5 of the truth peak at 2 Hz and 1.3e−3 at 0.5 Hz on the symmetric
# tanh(8). Quoted, and pinned as bounds: above the quantization (the
# transient is real), under the stated ceiling.
T_SLOW_FILTER_CEILING_RELATIVE = 5e-3
# A RECTIFIER behind the same capacitors carries a DC shift at every step
# that decays through the whole tile: measured 4.2e−2 (2 Hz) and 8.9e−2
# (0.5 Hz) of the truth peak on independent rows, and on carried rows 2…N
# 1.3e−1 and 1.02 — the previous row's tail reaches the quiet tiles.
# Quoted; pinned only in ORDER (carried ≥ independent on every later row).
# The stamp EXCESS over the injected noise on those rows: +61.3 dB (2 Hz)
# and +68.4 dB (0.5 Hz) carried, within ±0.13 dB independent — #267's
# mechanism, measured; the excess is pinned to be over 20 dB carried and
# under the scatter bar independent.
T_DC_TAIL_EXCESS_DB = 20.0
# The stamp against the injected noise on the identity: the pre-roll
# estimate's own scatter over 19 200 samples of white noise, measured
# −0.120…+0.062 dB over the five rows (one seed per row). Set 0.3 dB.
T_STAMP_DB = 0.3
# The gain invariance: the same device and noise through a loop 12 dB
# louder — every lattice value, start index and badge equal, every output
# statistic and the stamp moved by 12 dB to 4.0e−8 dB (Float32 rounding of
# the louder tile). Set 1e−6 dB.
T_GAIN_DB = 1e-6
# The latency cut: a capture 100 samples late with the tiles cut at 100 —
# every stored statistic IDENTICAL (measured 0). Equality.
T_LATENCY = 0.0
# The one-sample mis-cut: a stated figure the chapter quotes, not a bar —
# measured on tanh(8): 1.1 % of the truth peak at E2, 2.2 % at E3, 4.5 % at
# E4, 9.0 % at E5, 18 % at E6 (a one-sample phase error grows with the
# note, and on a flattened wave it moves the edges).
MISCUT_SAMPLES = 1
# The cross-check on the identity: the frame's own difference — the
# transfer cycle sits under the tone by its end fade's share of the
# average (an input-cycle deficit of −0.032 dB) — measured 1.19 % of the
# cycle peak (−38.5 dB re peak). Pinned as a ceiling on the identity
# CONTROL; a device case is quoted beside it, never barred.
T_CROSS_CHECK_CONTROL_RE_PEAK = 0.02
# #372: the two factors deliver different quiet-side lattices at 7 (four
# of seven levels differ by more than 0.5 dB) and the same at 5 — both
# implementations, pinned by count.
TIE_DIFFERING_LEVELS_AT_SEVEN = 4


@dataclass(frozen=True)
class Case:
    name: str
    args: List[str]
    kind: str  # memoryless | fast | slow | rectifier | noise | gain | latency | miscut | lattice | plugin | floor | crossover | refusals

    @property
    def compares_truth_exactly(self) -> bool:
        return self.kind in ("memoryless", "crossover", "gain", "latency", "plugin", "floor", "lattice")


_NOISE = ["--noise-db", "-100"]

CASES = [
    # (a) the identity at the default 5×5, 96 kHz, with the cross-check: every output tile equals its input.
    Case("a-identity", ["--source", "identity", "--cross-check"], "memoryless"),
    # (b) memoryless devices: every tile against f, to Float32.
    Case("b-hardclip", ["--source", "hardclip", "--threshold", "0.1", "--cross-check"], "memoryless"),
    Case("b-tanh8", ["--source", "tanh", "--gain", "8", "--cross-check"], "memoryless"),
    # (c) the crossover device at the default 5×5: the dead fraction per tile.
    Case("c-crossover", ["--source", "crossover"], "crossover"),
    # (d) tanh(8) behind filters: fast ones the settle absorbs, slow ones it does not.
    Case("d-tanh8-prehp", ["--source", "tanh", "--gain", "8", "--pre", "highpass", "--pre-hz", "40"], "fast"),
    Case("d-tanh8-postlp", ["--source", "tanh", "--gain", "8", "--post", "lowpass", "--post-hz", "1000"], "fast"),
    Case("d-tanh8-posthp2", ["--source", "tanh", "--gain", "8", "--post", "highpass", "--post-hz", "2"], "slow"),
    Case("d-tanh8-posthp05", ["--source", "tanh", "--gain", "8", "--post", "highpass", "--post-hz", "0.5"], "slow"),
    # (e) the lattices at 3 and 7 on the default span, at the four volts factors (5 is (a)); the tables.
    Case("e-3-none", ["--source", "identity", "--dimension", "3"], "lattice"),
    Case("e-7-none", ["--source", "identity", "--dimension", "7"], "lattice"),
    Case("e-5-335", ["--source", "identity", "--dimension", "5", "--volts-at-full-scale", "3.35"], "lattice"),
    Case("e-7-335", ["--source", "identity", "--dimension", "7", "--volts-at-full-scale", "3.35"], "lattice"),
    Case("e-7-4827", ["--source", "identity", "--dimension", "7", "--volts-at-full-scale", "4.827"], "lattice"),
    Case("e-7-4828", ["--source", "identity", "--dimension", "7", "--volts-at-full-scale", "4.828"], "lattice"),
    Case("e-5-4828", ["--source", "identity", "--dimension", "5", "--volts-at-full-scale", "4.828"], "lattice"),
    # (f) the chain gain: badges and indices unchanged, the statistics moved by 12 dB.
    Case("f-hardclip-noise", ["--source", "hardclip", "--threshold", "0.1"] + _NOISE, "gain"),
    Case("f-hardclip-gain12", ["--source", "hardclip", "--threshold", "0.1", "--chain-gain-db", "12"] + _NOISE, "gain"),
    # (g) the latency cut, exact; a one-sample mis-cut, measured.
    Case("g-latency100", ["--source", "tanh", "--gain", "8", "--latency-samples", "100"], "latency"),
    Case("g-miscut1", ["--source", "tanh", "--gain", "8", "--latency-error", str(MISCUT_SAMPLES)], "miscut"),
    # (h) seeded noise on the identity: the stamp against the injected rms, the quiet tiles' margins.
    Case("h-identity-noise", ["--source", "identity"] + _NOISE, "noise"),
    # (i) #267: a rectifier behind an output coupling capacitor, carried state against independent rows.
    Case("i-asym-hp05", ["--source", "asymmetric", "--gain", "3", "--negative-scale", "0.5", "--post", "highpass", "--post-hz", "0.5"] + _NOISE, "rectifier"),
    Case("i-asym-hp05-indep", ["--source", "asymmetric", "--gain", "3", "--negative-scale", "0.5", "--post", "highpass", "--post-hz", "0.5", "--independent-rows"] + _NOISE, "rectifier"),
    Case("i-asym-hp2", ["--source", "asymmetric", "--gain", "3", "--negative-scale", "0.5", "--post", "highpass", "--post-hz", "2"] + _NOISE, "rectifier"),
    Case("i-asym-hp2-indep", ["--source", "asymmetric", "--gain", "3", "--negative-scale", "0.5", "--post", "highpass", "--post-hz", "2", "--independent-rows"] + _NOISE, "rectifier"),
    # (k) the plugin ceiling (0 dBFS exact) and a user floor honoured as set.
    Case("k-plugin", ["--source", "hardclip", "--threshold", "0.1", "--plugin-ceiling"], "plugin"),
    Case("k-floor40", ["--source", "hardclip", "--threshold", "0.1", "--floor-db", "-40"], "floor"),
]

# (l) the refusals and (j) the cross-check ride flags rather than cases.
REFUSALS = Case("l-refusals", ["--source", "identity", "--refusals"], "refusals")

WORKED = "b-tanh8"
CROSS_CHECK_CONTROL = "a-identity"
TIE_PAIR = ("e-7-4827", "e-7-4828")
TIE_PAIR_FIVE = ("e-5-4828", "e-5-335")


# --- Running the two implementations --------------------------------------


def build_tool() -> str:
    subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    out = subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE,
                          "--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
    return os.path.join(out, "analysisdump")


def run_swift(tool: str, args: List[str]) -> str:
    return subprocess.run([tool, "matrix-synth"] + args, check=True, capture_output=True, text=True).stdout


def run_python(args: List[str], manifest: Optional[str] = None) -> str:
    cmd = [sys.executable, PY] + args
    if manifest:
        cmd += ["--manifest", manifest]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


# --- Parsing ----------------------------------------------------------------

FIELD = re.compile(r"(\w+)=([^\s\[\]]+)")
LIST = re.compile(r"(\w+)=\[([^\]]*)\]")
TEXT_COLUMNS = {"note", "truth_kind"}
INT_COLUMNS = {"freq_index", "amp_index", "input_start", "captured_start", "tile_samples"}


@dataclass
class Dump:
    header: Dict[str, Dict[str, str]]
    lists: Dict[str, Dict[str, List[str]]]
    rows: List[Dict[str, object]]


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
        if key == "mirror":
            header[key] = {"text": rest.strip()}
            continue
        if key == "cross-check bins":
            pairs = rest.split()
            lists[key] = {"tile": [p.split(":")[0] for p in pairs], "cycle": [p.split(":")[1] for p in pairs]}
            header[key] = {"n": str(len(pairs))}
            continue
        if key.startswith("refusal"):
            message = rest.split("message=", 1)[1] if "message=" in rest else ""
            header[key] = dict(FIELD.findall(rest.split("message=")[0]))
            header[key]["message"] = message.strip()
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


def _rel(a: float, b: float) -> float:
    d = _diff(a, b)
    if d == 0.0 or math.isinf(d):
        return d
    return d / max(abs(a), abs(b), 1e-300)


EXACT_LISTS = {"grid": ["f_hz", "note_names", "amp_dbfs"], "plan": ["settle_samples", "measure_samples", "ramp_samples", "row_samples", "tile_samples"],
               "loop": ["row_seeds"]}
EXACT_FIELDS = {"source": ["carried_state", "pre", "post", "inverted"],
                "grid": ["dimension", "low_hz", "high_hz", "floor_db", "ceiling_db", "volts_at_full_scale", "anchor_dbfs",
                         "default_floor_dbfs", "note_anchor_hz", "fs", "period_count", "notes", "levels", "tiles"],
                "plan": ["preroll_s", "tail_s", "settle_s", "measure_s", "preroll_samples", "tail_samples"],
                "loop": ["latency_samples", "latency_error_samples", "analyzed_latency_samples", "chain_gain_db", "chain_gain",
                         "noise_rms_dbfs", "seed"],
                "stamps": ["truth_stamp", "noise_clear_margin_db"],
                "mirror": ["text"],
                "cross-check": ["freq_index", "amp_index", "tile_amplitude", "transfer_amplitude", "bins", "bins_filled"]}
RELATIVE_FIELDS = {"cross-check": ["cycle_peak", "cycle_input_peak", "max_difference", "rms_difference"]}
DB_FIELDS = {"cross-check": ["amplitude_ratio_db", "input_deficit_db", "max_difference_re_peak_db"]}
ROW_EXACT = ["freq_index", "amp_index", "freq_hz", "note", "cents", "amp_dbfs", "amp_mv_pk", "input_start", "captured_start",
             "tile_samples", "noise_badge", "truth_kind", "truth_badge", "dead_fraction", "truth_dead_fraction", "truth_stamp"]
# Signal statistics: a ratio; means: absolute (a near-zero mean has no
# scale); error quantities (a residual near zero): absolute; margins in dB:
# absolute, and compared only where the stamp is INJECTED noise — without
# noise a memoryless device's pre-roll is exactly 0 (margin nil on both
# sides) and a filtered device's is its own numerical tail (a ratio of two
# residues, which no bar describes).
ROW_RELATIVE = ["input_peak", "input_rms", "output_peak", "output_rms", "truth_peak", "truth_rms"]
ROW_MEAN = ["input_mean", "output_mean", "truth_mean"]
ROW_ERROR = ["float32_error", "truth_max_error", "truth_rms_error"]
ROW_DB = ["noise_margin_db", "truth_margin_db"]


@dataclass
class CaseReport:
    case: Case
    swift: Dump
    python: Dump
    exact_mismatches: List[str]
    worst_relative: float
    worst_relative_at: str
    worst_mean_absolute: float
    worst_error_absolute: float
    worst_error_at: str
    worst_margin_db: float
    worst_stamp: float                   # relative with noise, absolute without
    worst_cross: float
    payload_bytes_difference: int
    # the tile against its truth (Swift side)
    quantization_max: float              # max float32_error over tiles
    truth_max_error: float               # max truth_max_error over tiles
    truth_minus_quantization: float      # max (truth_max_error − float32_error), the exactness pin
    truth_relative_max: float            # max truth_max_error / truth_peak
    truth_relative_at: str
    truth_relative_per_row: List[float]
    dead_fraction_rows: List[List[float]]
    stamp_excess_db: List[float]


def compare(case: Case, swift_text: str, python_text: str) -> CaseReport:
    sw, py = parse(swift_text), parse(python_text)
    noisy = "--noise-db" in case.args
    exact: List[str] = []
    if set(sw.header) != set(py.header):
        exact.append(f"header lines differ: {set(sw.header) ^ set(py.header)}")
    for line, keys in EXACT_FIELDS.items():
        if line not in sw.header:
            continue
        for k in keys:
            a, b = sw.header[line].get(k), py.header.get(line, {}).get(k)
            if a != b:
                exact.append(f"{line}.{k}: {a} vs {b}")
    for line, keys in EXACT_LISTS.items():
        for k in keys:
            a, b = sw.lists.get(line, {}).get(k, []), py.lists.get(line, {}).get(k, [])
            if a != b:
                exact.append(f"{line}.{k}: {a} vs {b}")
    payload = abs(int(sw.header["stamps"]["payload_bytes"]) - int(py.header["stamps"]["payload_bytes"])) if "stamps" in sw.header else 0
    worst_rel, worst_at = 0.0, ""
    worst_mean = 0.0
    worst_err, worst_err_at = 0.0, ""
    worst_margin = 0.0
    worst_stamp = 0.0
    worst_cross = 0.0
    if "stamps" in sw.header:
        a = [_num(x) for x in sw.lists["stamps"]["row_noise_rms"]]
        b = [_num(x) for x in py.lists["stamps"]["row_noise_rms"]]
        if len(a) != len(b):
            exact.append("stamps.row_noise_rms: %d vs %d rows" % (len(a), len(b)))
        for x, y in zip(a, b):
            worst_stamp = max(worst_stamp, _rel(x, y) if noisy else _diff(x, y))
        if noisy:
            for x, y in zip(sw.lists["stamps"]["excess_db"], py.lists["stamps"]["excess_db"]):
                worst_margin = max(worst_margin, _diff(_num(x), _num(y)))
    for line, keys in RELATIVE_FIELDS.items():
        if line in sw.header:
            for k in keys:
                worst_cross = max(worst_cross, _rel(_num(sw.header[line][k]), _num(py.header[line][k])))
    for line, keys in DB_FIELDS.items():
        if line in sw.header:
            for k in keys:
                worst_cross = max(worst_cross, _diff(_num(sw.header[line][k]), _num(py.header[line][k])))
    if "cross-check bins" in sw.lists:
        for k in ("tile", "cycle"):
            for x, y in zip(sw.lists["cross-check bins"][k], py.lists["cross-check bins"][k]):
                worst_cross = max(worst_cross, _rel(_num(x), _num(y)))
    if len(sw.rows) != len(py.rows):
        exact.append(f"row count {len(sw.rows)} vs {len(py.rows)}")
    for a, b in zip(sw.rows, py.rows):
        for k in ROW_EXACT:
            if a[k] != b[k] and not (isinstance(a[k], float) and _diff(a[k], b[k]) == 0.0):
                exact.append(f"tile f{a['freq_index']} a{a['amp_index']} {k}: {a[k]} vs {b[k]}")
        for k in ROW_RELATIVE:
            r = _rel(a[k], b[k])
            if r > worst_rel:
                worst_rel, worst_at = r, f"f{a['freq_index']} a{a['amp_index']} {k}"
        for k in ROW_MEAN:
            worst_mean = max(worst_mean, _diff(a[k], b[k]))
        for k in ROW_ERROR:
            d = _diff(a[k], b[k])
            if d > worst_err:
                worst_err, worst_err_at = d, f"f{a['freq_index']} a{a['amp_index']} {k}"
        if noisy:
            for k in ROW_DB:
                worst_margin = max(worst_margin, _diff(a[k], b[k]))
    # The tile against its truth, on the Swift side.
    q = max(r["float32_error"] for r in sw.rows)
    tme = max(r["truth_max_error"] for r in sw.rows)
    tmq = max(r["truth_max_error"] - r["float32_error"] for r in sw.rows)
    rel_rows = []
    rel_max, rel_at = 0.0, ""
    rows_by_f: Dict[int, List[dict]] = {}
    for r in sw.rows:
        rows_by_f.setdefault(r["freq_index"], []).append(r)
    for f in sorted(rows_by_f):
        worst = max(rows_by_f[f], key=lambda r: r["truth_max_error"] / max(r["truth_peak"], 1e-300))
        rel_rows.append(worst["truth_max_error"] / max(worst["truth_peak"], 1e-300))
        if rel_rows[-1] > rel_max:
            rel_max, rel_at = rel_rows[-1], f"f{f} a{worst['amp_index']}"
    dead = [[r["dead_fraction"] for r in rows_by_f[f]] for f in sorted(rows_by_f)]
    excess = [_num(x) for x in sw.lists.get("stamps", {}).get("excess_db", [])]
    return CaseReport(case, sw, py, exact, worst_rel, worst_at, worst_mean, worst_err, worst_err_at, worst_margin, worst_stamp,
                      worst_cross, payload, q, tme, tmq, rel_max, rel_at, rel_rows, dead, excess)


def run_all(tool: str, manifest_path: Optional[str] = None, dump_dir: Optional[str] = None
            ) -> Dict[str, Tuple[Case, str, str]]:
    results: Dict[str, Tuple[Case, str, str]] = {}
    for case in CASES + [REFUSALS]:
        swift = run_swift(tool, case.args)
        results[case.name] = (case, swift, run_python(case.args, manifest_path))
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for name, (case, swift, python) in results.items():
            with open(os.path.join(dump_dir, name + ".swift.tsv"), "w", encoding="utf-8") as f:
                f.write(swift)
            with open(os.path.join(dump_dir, name + ".py.tsv"), "w", encoding="utf-8") as f:
                f.write(python)
    return results


def lattice_of(dump: Dump) -> Tuple[List[float], List[str], List[float]]:
    g = dump.lists["grid"]
    return [_num(x) for x in g["f_hz"]], g["note_names"], [_num(x) for x in g["amp_dbfs"]]


def measure(argv=None) -> int:
    """Print the measured distributions the tolerances are set from."""
    manifest_path = argv[0] if argv else None
    tool = build_tool()
    results = run_all(tool, manifest_path, os.environ.get("MATRIX_DUMP_DIR"))
    print("%-20s %-10s %5s %9s %-16s %9s %9s %-22s %9s %9s %9s %5s | %9s %9s %9s %9s %-8s" % (
        "case", "kind", "exact", "rel", "at", "mean", "error", "at", "margin", "stamp", "cross", "bytes", "quant", "truth", "t-q", "rel-t", "at"))
    for name, (case, swift, python) in results.items():
        if case.kind == "refusals":
            continue
        r = compare(case, swift, python)
        print("%-20s %-10s %5d %9.2e %-16s %9.2e %9.2e %-22s %9.2e %9.2e %9.2e %5d | %9.2e %9.2e %9.2e %9.2e %-8s" % (
            name, case.kind, len(r.exact_mismatches), r.worst_relative, r.worst_relative_at, r.worst_mean_absolute,
            r.worst_error_absolute, r.worst_error_at, r.worst_margin_db, r.worst_stamp, r.worst_cross, r.payload_bytes_difference,
            r.quantization_max, r.truth_max_error, r.truth_minus_quantization, r.truth_relative_max, r.truth_relative_at))
        for issue in r.exact_mismatches[:6]:
            print("    ", issue[:200])
        if case.kind in ("slow", "rectifier", "miscut"):
            print("     truth residue per row (re truth peak):", ["%.2e" % x for x in r.truth_relative_per_row])
        if case.kind in ("rectifier", "noise"):
            print("     stamp excess dB per row:", ["%+.3f" % x for x in r.stamp_excess_db])
        if case.kind == "crossover":
            for f, row in enumerate(r.dead_fraction_rows):
                print("     dead fraction row %d:" % f, ["%.4f" % x for x in row])
    for name in ("a-identity", "b-tanh8"):
        d = parse(results[name][1])
        print("cross-check %s:" % name, {k: d.header["cross-check"][k] for k in ("amplitude_ratio_db", "input_deficit_db", "max_difference_re_peak_db", "bins_filled")})
    for name in ("e-7-4827", "e-7-4828", "e-5-4828", "e-5-335"):
        print("lattice %s:" % name, lattice_of(parse(results[name][1]))[2])
    d = parse(results["l-refusals"][1]); p = parse(results["l-refusals"][2])
    for k in d.header:
        print("refusal", k, "swift", d.header[k], "python", p.header[k])
    g0, g12 = parse(results["f-hardclip-noise"][1]), parse(results["f-hardclip-gain12"][1])
    print("gain12: worst |rms shift − 12| = %.2e dB; badges equal %s; starts equal %s" % (
        max(abs(20 * math.log10(b["output_rms"] / a["output_rms"]) - 12) for a, b in zip(g0.rows, g12.rows)),
        all(a["noise_badge"] == b["noise_badge"] for a, b in zip(g0.rows, g12.rows)),
        all(a["input_start"] == b["input_start"] for a, b in zip(g0.rows, g12.rows))))
    z, l = parse(results["b-tanh8"][1]), parse(results["g-latency100"][1])
    print("latency100: worst |output_rms diff| %.2e, captured_start shift %s" % (
        max(_diff(a["output_rms"], b["output_rms"]) for a, b in zip(z.rows, l.rows)), {b["captured_start"] - a["captured_start"] for a, b in zip(z.rows, l.rows)}))
    print("7x7 payload bytes:", parse(results["e-7-none"][1]).header["stamps"]["payload_bytes"])
    return 0


if __name__ == "__main__":
    sys.exit(measure(sys.argv[1:]))
