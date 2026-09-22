#!/usr/bin/env python3
"""The Chord IMD parity comparison — shared by the CI test
(`test_parity_imd.py`) and the document generator (`make methods-docs`
writes `generated/parity-imd.tex` from the same numbers), so the chapter's
worked-example tables and the test's verdict cannot disagree.

Every case runs the shipped tool (`analysisdump imd-synth`) and the Python
reimplementation (`chord_imd.py`) on one synthetic input and compares:

* Swift vs Python — every header quantity (the lattice search's choice
  and counts, the tones, the window, the floor and its sentence, the
  verdict counts, the three tiles, the harmonic-role sums, the coherence
  reading's every field and BOTH registers' sentences, the loudest-skirt
  and neighbour lines, the summary features) and every row (bin, level,
  gate, reading and its evidence, grid index, role, contest, partner
  check, truth) — numerically to a stated tolerance, text exactly;
* the shipped result vs the truth — every content product against the
  torus quadrature (and the polynomial's closed form), the phantom read
  back exactly, the noise floor against its analytic median, the
  coherence excess against its clean-noise reference.

The tolerances were SET FROM MEASUREMENT on 2026-09-20 (`measure()` below
prints the distributions the #306 chapter-three handoff quotes), never
from hope; each carries its measured value.
"""
from __future__ import annotations

import io
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

import chord_imd as ci

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
TOOL_PACKAGE = os.path.join(REPO, "Tools", "analysisdump")
PY = os.path.join(HERE, "chord_imd.py")

# --- Tolerances ------------------------------------------------------------

# Swift vs Python on every dB quantity — product levels, floors, margins,
# bounds, the coherence reading's excesses, the role sums, the tile
# percentages and the truth — on a capture with NO biquad in it. Measured
# maximum 2.3e−9 dB over the unfiltered cases (the asymmetric clipper: the
# two libraries' tanh differ by an ulp per sample, and a product 140 dB
# below the tone carries that as 1e−9 dB; the two FFTs — Accelerate's and
# numpy's — differ at the last few bits, 1e−11 dB on a bin at the noise).
# The squarer driven forty times harder (products above the tones) reads
# 1.9e−8. Set 1e−7: a one-bin change in any read moves a level by whole
# decibels, so the bar is far below any method change and far above the
# rounding.
T_SWIFT_DB = 1e-7
# The same, on a capture rendered through a biquad. A 20 Hz high-pass at
# 96 kHz has a pole 1.3e−3 inside the unit circle, and the direct-form
# recursion in scipy's C loop and in the Swift loop accumulate rounding
# differently over two million samples: measured 1.6e−4 dB on a bin at
# −166 dBc (the noise floor, where an absolute difference of 1e−15 is
# 1e−7 of the bin), 1.2e−5 dB on the capture floor, and ≤ 1e−9 on every
# content product. Set 1e−3, still a thousandth of a decibel.
T_SWIFT_DB_FILTERED = 1e-3
# Swift vs Python on the truth amplitudes: the Swift's separable
# quadrature against the Python's 2-D FFT of the same 4096² grid, as a
# relative error. Measured ≤ 2.7e−10 on every content recipe (the
# 4096-point sums of tanh's values round differently in the two).
T_SWIFT_TRUTH_RELATIVE = 1e-8
# The polynomial's closed form against the quadrature, relative.
# Measured ≤ 4.4e−14 (the trapezoid rule is exact for a cubic).
# RAISED 1e−10 → 1e−9 on 2026-09-22 (the drift ruling, `machine_floor.py`):
# a bar at the machine floor claims agreement the machine does not
# reproduce between two runners, and the document's bound "≤ floor" beside
# it would claim nothing; 1e−9 is a decade above the floor.
T_CLOSED_FORM_RELATIVE = 1e-9
# An analytically empty recipe on a noiseless capture reads numerical
# dust on both sides: the two FFTs' dust differs freely, so the pin is
# that both sit under this depth re the louder tone. Measured worst
# −274 dBc (the identity on the octave's lattice).
EMPTY_DEPTH_DBC = -200.0

# The shipped read against the truth on the content recipes, in dB,
# AFTER the noise allowance: a product's bin holds the noise too, so a
# read can sit up to 20·log10(1 + 10^((floor + spread − truth)/20)) from
# the truth by the noise alone (the loudest empty bin adding in
# amplitude); that allowance is subtracted before the bar is applied,
# and what remains is the method's own error. Two classes, because a
# device applied per sample at fs folds what it makes above Nyquist back
# onto the lattice (chapter one's finding, here on a two-tone lattice
# where a folded high-order product lands EXACTLY on a low-order bin —
# every lattice point is a multiple of g): the bandlimited devices (a
# squarer, a cubic, tanh at this drive, whose torus coefficients are gone
# by the time they reach Nyquist) read the truth INSIDE the allowance on
# every case (residues −1e−6 dB and below), while the two KINKED devices —
# the hard clip, a near-square wave whose coefficients fall as 1/k, and
# the asymmetric clipper, whose slope breaks at zero so its coefficients
# fall as 1/k² — fold a measured 0.013 dB (the hard clip, at f1+4f2) and
# 0.030 dB (the asymmetric clipper, at 7f1) onto their products. The
# phantom twin of each case (the same truth amplitudes as a phantom) is
# the alias-free control and reads to 3e−10 on every one. The measured
# residues are quoted in the chapter's parity table beside each case.
T_TRUTH_BANDLIMITED_DB = 1e-3
T_TRUTH_KINKED_DB = 0.05
T_TRUTH_PHANTOM_DB = 1e-8

# The identity through seeded noise: the capture floor (the upper median
# of the empty bins' reads) against the analytic median of the same noise
# through the analyzer's scale. Measured 0.2 dB at 2^21 (53 bins) and
# 1.7 dB at 2^17 (37 bins) — a median of a few dozen Rayleigh draws.
T_FLOOR_VS_EXPECTED_DB = 3.0
# The coherence check on the clean identity: interprets, under the bar,
# and its excess over the local floor within this of the clean-noise
# reference for 36 bins (measured 6.3 / 6.7 / 7.3 dB against 7.8).
T_COHERENCE_EXCESS_VS_NOISE_DB = 6.0
# The worked example analyzed 100 samples late against itself at zero
# latency: a shift is a phase on a bin-centred lattice, so no content
# product's MAGNITUDE moves — except by the noise. The capture's −120 dBFS
# noise stream is not shifted with the window, so the late segment
# exchanges 100 of its 2^21 noise samples for 100 new ones, and a bin's
# noise phasor moves by about √(100/N) of itself. Measured 2026-09-20:
# 2.24e−6 dB on the quietest content product (f1+6f2 at −88.5 dBc) and
# ≤ 4.2e−7 on every product above −80 dBc; the EMPTY recipes, which ARE the
# noise, move by up to 0.05 dB and are deliberately not compared. Set 1e−5:
# four times the measured worst, a hundred times under a method change
# (the first draft typed 1e−6 below the measurement — the class the
# provenance rule exists to forbid).
T_LATENCY_SHIFT_DB = 1e-5


@dataclass(frozen=True)
class Case:
    name: str
    args: List[str]
    kind: str  # lattice | refusal | device | kinked | phantom | noise | corpus | wander | loud

    @property
    def noisy(self) -> bool:
        return "--noise-db" in self.args

    @property
    def filtered(self) -> bool:
        return "--pre" in self.args or "--post" in self.args

    @property
    def swift_tolerance_db(self) -> float:
        return T_SWIFT_DB_FILTERED if self.filtered else T_SWIFT_DB


_PEAK = ["--amplitude", "0.5"]
_QUIET = ["--noise-db", "-120"]

CASES = [
    # (a) the lattice choice alone — the identity at every grid and on the
    # fallbacks, an octave, the major third, and the refusal.
    Case("a-fifth-96k", ["--source", "identity"], "lattice"),
    Case("a-fifth-48k", ["--source", "identity", "--rate", "48000"], "lattice"),
    Case("a-fifth-88k", ["--source", "identity", "--rate", "88200"], "lattice"),
    Case("a-fifth-44k", ["--source", "identity", "--rate", "44100"], "lattice"),
    Case("a-fifth-corpus", ["--source", "identity", "--length", "131072"], "lattice"),
    Case("a-fifth-interactive", ["--source", "identity", "--rate", "48000", "--length", "32768"], "lattice"),
    Case("a-octave-96k", ["--source", "identity", "--note1", "A2", "--note2", "A3"], "lattice"),
    Case("a-octave-corpus", ["--source", "identity", "--note1", "A2", "--note2", "A3", "--length", "131072"], "lattice"),
    Case("a-third-96k", ["--source", "identity", "--note1", "A2", "--note2", "C#3"], "lattice"),
    Case("a-refusal", ["--source", "identity", "--note1", "D1", "--note2", "D2", "--length", "65536"], "refusal"),
    # (b) the polynomial devices at the loudest hardware drive on the shipped fifth.
    Case("b-poly", ["--source", "poly", "--a2", "0.2", "--a3", "0.3"] + _PEAK + _QUIET, "device"),
    Case("b-squarer", ["--source", "poly", "--a2", "1"] + _PEAK + _QUIET, "device"),
    Case("b-asym", ["--source", "asymmetric", "--gain", "2", "--negative-scale", "0.5"] + _PEAK + _QUIET, "kinked"),
    # (c) the two clippers.
    Case("c-tanh", ["--source", "tanh", "--gain", "2"] + _PEAK + _QUIET, "device"),
    Case("c-hardclip", ["--source", "hardclip", "--threshold", "0.1"] + _PEAK + _QUIET, "kinked"),
    # (d) the phantom: every enumerated recipe at a chosen level, no noise.
    Case("d-phantom", ["--source", "phantom", "--products", "LADDER"], "phantom"),
    # (e) the identity through seeded noise.
    Case("e-identity-80", ["--source", "identity", "--noise-db", "-80"], "noise"),
    Case("e-identity-110", ["--source", "identity", "--noise-db", "-110"], "noise"),
    Case("e-identity-corpus-80", ["--source", "identity", "--length", "131072", "--noise-db", "-80"], "noise"),
    # (f) filters: the squarer behind a post-filter, tanh behind a pre-filter.
    Case("f-squarer-hp", ["--source", "poly", "--a2", "1", "--post", "highpass", "--post-hz", "20"] + _PEAK + _QUIET, "device"),
    Case("f-squarer-lp", ["--source", "poly", "--a2", "1", "--post", "lowpass", "--post-hz", "1550"] + _PEAK + _QUIET, "device"),
    Case("f-tanh-prehp", ["--source", "tanh", "--gain", "2", "--pre", "highpass", "--pre-hz", "40"] + _PEAK + _QUIET, "device"),
    # (g) the corpus lattice: refusals by position, the neighbour rule.
    Case("g-corpus-squarer", ["--source", "poly", "--a2", "1", "--length", "131072"] + _PEAK + ["--noise-db", "-100"], "corpus"),
    Case("g-corpus-cubic", ["--source", "poly", "--a2", "0.3", "--a3", "1", "--length", "131072"] + _PEAK + ["--noise-db", "-100"], "corpus"),
    # (h) the wander fixture: the legacy path on the corpus lattice, the detector on the shipped one.
    Case("h-wander-legacy", ["--source", "identity", "--length", "131072", "--wander", "6.1e-5", "--cycles", "2", "--legacy", "--noise-db", "-110"], "wander"),
    Case("h-wander-shipped", ["--source", "identity", "--wander", "6.1e-5", "--cycles", "1", "--noise-db", "-110"], "wander"),
    # (i) a device whose loudest product stands above the played tones.
    Case("i-loud-squarer", ["--source", "poly", "--a2", "40"] + _PEAK + _QUIET, "loud"),
    # (j) a deliberate latency error on the worked example.
    Case("j-latency", ["--source", "tanh", "--gain", "2", "--latency-error", "100"] + _PEAK + _QUIET, "device"),
]

WORKED = "c-tanh"


def phantom_ladder(m: dict) -> str:
    """Every enumerated recipe on the shipped fifth at a level ladder,
    −20 dBc for the first and 1.5 dB lower per recipe, in enumeration order."""
    signal, _, n = ci.plan_signal("A2", "E3", 0.05, 96_000.0, int(m["chordIMD"]["plan"]["standardFFTLength"]), m)
    limit = 0.95 * signal.fs / 2
    bw = signal.fs / n
    seen = {ci.swift_round(signal.f1 / bw), ci.swift_round(signal.f2 / bw), 0}
    entries = []
    for order in range(2, int(m["chordIMD"]["analyzer"]["defaultMaxOrder"]) + 1):
        for mm in range(-order, order + 1):
            nm = order - abs(mm)
            for nn in (nm, -nm):
                if abs(mm) + abs(nn) != order:
                    continue
                f = mm * signal.f1 + nn * signal.f2
                if not (bw < f < limit):
                    continue
                b = ci.swift_round(f / bw)
                if b in seen:
                    continue
                seen.add(b)
                entries.append("%d,%d,%s" % (mm, nn, ci.fmt(-20.0 - 1.5 * len(entries))))
    return ";".join(entries)


def resolved_args(case: Case, m: dict) -> List[str]:
    return [phantom_ladder(m) if a == "LADDER" else a for a in case.args]


def phantom_twin(case: Case, swift_text: str) -> Case:
    """The alias-free control: the case's own truth amplitudes as a phantom
    on the same lattice (every content recipe at its truth dBc)."""
    d = parse(swift_text)
    products = []
    for row in d.rows:
        t = row["truth_dbc"]
        if math.isfinite(t) and t > -150:
            products.append("%d,%d,%s" % (int(row["m"]), int(row["n"]), ci.fmt(t)))
    grid = [a for a in case.args if a in ("--rate", "--length", "--note1", "--note2")]
    extra = []
    for key in ("--rate", "--length", "--note1", "--note2"):
        if key in case.args:
            extra += [key, case.args[case.args.index(key) + 1]]
    amplitude = case.args[case.args.index("--amplitude") + 1] if "--amplitude" in case.args else "0.05"
    return Case(case.name + "-twin", ["--source", "phantom", "--products", ";".join(products), "--amplitude", amplitude] + extra, "phantom")


# --- Running the two implementations --------------------------------------


def build_tool() -> str:
    subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    out = subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE,
                          "--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
    return os.path.join(out, "analysisdump")


def run_swift(tool: str, args: List[str]) -> str:
    return subprocess.run([tool, "imd-synth"] + args, check=True, capture_output=True, text=True).stdout


def run_python(args: List[str], manifest: Optional[str] = None) -> str:
    # A phantom's product list can begin with a minus sign, which argparse
    # reads as a flag; the equals form is unambiguous on both sides.
    merged: List[str] = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a == "--products" and i + 1 < len(args):
            merged.append("--products=" + args[i + 1])
            skip = True
        else:
            merged.append(a)
    cmd = [sys.executable, PY] + merged
    if manifest:
        cmd += ["--manifest", manifest]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


# --- Parsing ----------------------------------------------------------------

TEXT_LINES = ("drive level", "floor line", "coherence line, device register", "coherence line, loop-only register",
              "refused", "harmonic roles (IMDAnalysis.harmonicRoles)", "harmonic roles")
NUMBER = re.compile(r"-?(?:\d+\.\d+(?:e[-+]?\d+)?|\d+e[-+]?\d+|inf)")


@dataclass
class Dump:
    header: Dict[str, Dict[str, str]]
    text: Dict[str, str]
    rows: List[Dict[str, object]]

    def value(self, line: str, key: str) -> float:
        return _num(self.header[line][key])

    def field(self, line: str, key: str) -> str:
        return self.header[line][key]


def _num(s: str) -> float:
    return float("nan") if s == "nan" else float(s)


def parse(text: str) -> Dump:
    header: Dict[str, Dict[str, str]] = {}
    texts: Dict[str, str] = {}
    body: List[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            key, rest = line[2:].split(":", 1)
            texts[key] = rest.strip()
            fields = rest.split(" | ", 1)[0]
            header[key] = dict(re.findall(r"(\w+)=([^\s\[\]]+)", fields))
        else:
            body.append(line)
    rows: List[Dict[str, object]] = []
    if len(body) > 1:
        columns = body[0].split("\t")
        for line in body[1:]:
            if not line:
                continue
            parts = line.split("\t")
            row: Dict[str, object] = {}
            for name, value in zip(columns, parts):
                if name in ("label", "pitch", "reading", "limit_detail", "role", "grid_index", "partner"):
                    row[name] = value
                elif name in ("m", "n", "order", "bin", "off_f1_bins", "off_f2_bins", "contest"):
                    row[name] = int(value)
                else:
                    row[name] = _num(value)
            rows.append(row)
    return Dump(header, texts, rows)


def normalize_numbers(text: str, digits: int = 6) -> str:
    """Every floating number in a line rounded to `digits` significant
    figures — so two lines that differ only by last-bit rounding compare
    equal, and a line that differs by a bin does not."""
    def sub(match):
        s = match.group(0)
        if "inf" in s:
            return s
        v = float(s)
        return "0" if v == 0 else ("%.*g" % (digits, v))
    return NUMBER.sub(sub, text)


# --- The comparison --------------------------------------------------------


@dataclass
class CaseReport:
    case: Case
    swift_header_db: float          # the worst |Swift − Python| over every header dB field
    swift_row_db: float             # the same over every row dB field (content rows)
    swift_truth_relative: float
    text_mismatches: List[str]      # header text lines that differ after number normalisation
    discrete_mismatches: List[str]  # row-level discrete differences (reading, role, gate, …)
    header_field_mismatches: List[str]
    empty_worst_dbc: float          # the loudest analytically-empty recipe read on either side (noiseless cases)
    truth_error_db: float           # worst |Swift − truth| over the content recipes, raw
    truth_error_label: str
    truth_residue_db: float         # worst (|Swift − truth| − the noise allowance) over the content recipes
    truth_residue_label: str
    content_count: int
    closed_form_relative: float
    swift: Dump
    python: Dump


HEADER_DB_KEYS = {
    "tones": ["tone1_amp", "tone2_amp", "truth_tone1_amp", "truth_tone2_amp"],
    "noise": ["expected_median_dbc", "broadband_dbc", "per_bin_below_broadband_db"],
    "stored tiles (capture time)": ["smpte", "ccif", "total"],
    "shipped derivedPercentages (read time)": ["smpte", "ccif", "total"],
    "shipped verdict": ["floor_dbc", "floor_spread_db"],
    "coherence (IMDAnalysis.coherenceReading)": ["worst_dbc", "floor_dbc", "excess_over_floor_db", "excess_over_bar_db",
                                                 "loudest_product_dbc", "expected_noise_excess_db", "pair_f1_dbc",
                                                 "pair_f2_dbc", "pair_difference_db", "expected_difference_db"],
    "loudest skirt": ["loudest_dbc", "skirt_db"],
    "shipped features, device register (FeatureExtractor.extract(imd:))": ["imd_to_harmonic_ratio_db", "ratio_confidence"],
}
HEADER_EXACT_KEYS = {
    "lattice": ["tier", "standard_a", "standard_b", "naive_bin1", "naive_bin2", "radius1", "radius2", "max_order",
                "bar_bins", "resolvable_count", "nondegenerate_count", "min_reduced_sum", "bin1", "bin2", "g", "a", "b",
                "reduced_sum", "headroom"],
    "tones": ["bin", "fft_length", "pitch1", "pitch2"],
    "stimulus": ["samples", "latency_error_samples", "legacy_payload"],
    "window": ["start", "length", "steady_end", "fade_overrun", "overruns"],
    "shipped verdict": ["present", "absent", "unresolved", "out_of_band", "floor_samples"],
    "floor line": ["absence", "noise_reads", "read", "needed", "refused"],
    "enumeration": ["recipes", "orders"],
    "coherence (IMDAnalysis.coherenceReading)": ["source", "exceeds", "spacing_bins", "max_offset_bins", "clearance_bins",
                                                 "lattice_clear", "interprets_device", "interprets_loop_only",
                                                 "not_trustworthy_device", "not_trustworthy_loop_only", "readable_offsets",
                                                 "unreadable_offsets", "level_limited", "read_bin_count"],
    "loudest skirt": ["loudest", "g", "under_skirt"],
    "shipped features, device register (FeatureExtractor.extract(imd:))": ["imd_resolved_nothing"],
}
HEADER_DB_LATTICE = ["standard_interval_cents", "requested_cents", "cents1", "cents2", "interval_cents", "cents_budget"]
ROW_DB_KEYS = ["level_dbc", "truth_dbc", "err_db", "partner_excess_db"]
ROW_EXACT_KEYS = ["bin", "off_f1_bins", "off_f2_bins", "pitch", "above_floor", "reading", "grid_index", "role", "contest",
                  "partner", "partner_inconsistent"]


def _details_agree(a: str, b: str, tolerance: float) -> bool:
    """A reading's evidence string: the numbers within the tolerance, the
    words identical."""
    na, nb = NUMBER.findall(a), NUMBER.findall(b)
    if len(na) != len(nb) or NUMBER.sub("#", a) != NUMBER.sub("#", b):
        return False
    return all(_diff(_num(x), _num(y)) <= tolerance for x, y in zip(na, nb))


def _diff(a: float, b: float) -> float:
    if math.isnan(a) and math.isnan(b):
        return 0.0
    if math.isinf(a) and math.isinf(b) and a == b:
        return 0.0
    return abs(a - b)


# On a NOISELESS capture every empty bin is numerical dust (~−280 dBc), and
# the two FFTs' dust differs freely — so the floor, the verdict counts, the
# coherence reading and the role sums of a noiseless case are not
# comparable and are not compared; only the lattice, the tones, the
# window, the content rows and the depth of the dust are. A noisy case is
# compared in full.
DUST_FREE_DB_LINES = {"tones", "noise"}
DUST_FREE_EXACT_LINES = {"lattice", "tones", "stimulus", "window", "enumeration"}
DUST_FREE_TEXT_LINES = ("drive level", "refused")


def compare(case: Case, swift_text: str, python_text: str) -> CaseReport:
    sw, py = parse(swift_text), parse(python_text)
    assert set(sw.header) == set(py.header), f"{case.name}: header lines differ: {set(sw.header) ^ set(py.header)}"
    full = case.noisy
    header_db = 0.0
    field_mismatches: List[str] = []
    for line, keys in HEADER_DB_KEYS.items():
        if line not in sw.header or (not full and line not in DUST_FREE_DB_LINES):
            continue
        for key in keys:
            if key in sw.header[line] or key in py.header[line]:
                header_db = max(header_db, _diff(_num(sw.header[line].get(key, "nan")), _num(py.header[line].get(key, "nan"))))
    for key in HEADER_DB_LATTICE:
        header_db = max(header_db, _diff(_num(sw.header["lattice"].get(key, "nan")), _num(py.header["lattice"].get(key, "nan"))))
    for line, keys in HEADER_EXACT_KEYS.items():
        if line not in sw.header or (not full and line not in DUST_FREE_EXACT_LINES):
            continue
        for key in keys:
            a, b = sw.header[line].get(key), py.header[line].get(key)
            if a != b:
                field_mismatches.append(f"{line}.{key}: {a} vs {b}")
    text_mismatches = []
    for key in (TEXT_LINES if full else DUST_FREE_TEXT_LINES):
        if key in sw.text or key in py.text:
            a, b = normalize_numbers(sw.text.get(key, "")), normalize_numbers(py.text.get(key, ""))
            if a != b:
                text_mismatches.append(f"{key}: {sw.text.get(key, '')!r} vs {py.text.get(key, '')!r}")
    swift_rows = {(r["m"], r["n"]): r for r in sw.rows}
    python_rows = {(r["m"], r["n"]): r for r in py.rows}
    assert set(swift_rows) == set(python_rows), f"{case.name}: recipe sets differ"
    assert [(r["m"], r["n"]) for r in sw.rows] == [(r["m"], r["n"]) for r in py.rows], f"{case.name}: row order differs"
    row_db = 0.0
    truth_rel = 0.0
    closed_rel = 0.0
    discrete: List[str] = []
    empty_worst = -math.inf
    truth_error = 0.0
    truth_label = ""
    residue = -math.inf
    residue_label = ""
    content = 0
    verdict = sw.header.get("shipped verdict", {})
    floor = _num(verdict.get("floor_dbc", "nan"))
    spread = _num(verdict.get("floor_spread_db", "nan"))
    for key, s in swift_rows.items():
        p = python_rows[key]
        t = s["truth_dbc"]
        is_content = math.isfinite(t) and t > -150
        if is_content:
            for k in ROW_DB_KEYS:
                row_db = max(row_db, _diff(s[k], p[k]))
        elif full:
            # An empty recipe on a noisy capture: both sides read the noise
            # (compared), both truths are dust (asserted empty, not compared).
            row_db = max(row_db, _diff(s["level_dbc"], p["level_dbc"]), _diff(s["partner_excess_db"], p["partner_excess_db"]))
            if not (p["truth_dbc"] < -150):
                discrete.append(f"{s['label']}.truth_dbc: Python reads content {p['truth_dbc']} where Swift reads none")
        if is_content or full:
            # A noiseless content row's reading rests on a dust floor; its
            # level, bin and truth are compared, its verdict is not.
            for k in (ROW_EXACT_KEYS if full else ["bin", "off_f1_bins", "off_f2_bins", "pitch", "grid_index", "role", "contest"]):
                if str(s[k]) != str(p[k]):
                    discrete.append(f"{s['label']}.{k}: {s[k]} vs {p[k]}")
            if full and not _details_agree(s["limit_detail"], p["limit_detail"], case.swift_tolerance_db):
                discrete.append(f"{s['label']}.limit_detail: {s['limit_detail']!r} vs {p['limit_detail']!r}")
            a = s["amplitude"]
            if a > 0:
                row_db = max(row_db, abs(20 * math.log10(p["amplitude"] / a)))
        else:
            empty_worst = max(empty_worst, s["level_dbc"], p["level_dbc"])
        if is_content:
            ta, tb = s["truth_amplitude"], p["truth_amplitude"]
            if ta > 0:
                truth_rel = max(truth_rel, abs(tb - ta) / ta)
            if math.isfinite(s["truth_closed_amplitude"]) and s["truth_closed_amplitude"] > 0:
                closed_rel = max(closed_rel, abs(s["truth_closed_amplitude"] - ta) / ta)
            if math.isfinite(s["err_db"]):
                content += 1
                err = abs(s["err_db"])
                if err > truth_error:
                    truth_error, truth_label = err, s["label"]
                allowance = 0.0
                if full and math.isfinite(floor):
                    allowance = 20 * math.log10(1 + 10 ** ((floor + (spread if math.isfinite(spread) else 0.0) - t) / 20))
                if err - allowance > residue:
                    residue, residue_label = err - allowance, s["label"]
    return CaseReport(case, header_db, row_db, truth_rel, text_mismatches, discrete, field_mismatches,
                      empty_worst, truth_error, truth_label, residue, residue_label, content, closed_rel, sw, py)


def truth_tolerance(case: Case) -> float:
    if case.kind == "phantom":
        return T_TRUTH_PHANTOM_DB
    if case.kind == "kinked":
        return T_TRUTH_KINKED_DB
    return T_TRUTH_BANDLIMITED_DB


def run_all(tool: str, m: dict) -> Dict[str, Tuple[Case, str, str]]:
    results: Dict[str, Tuple[Case, str, str]] = {}
    for case in CASES:
        args = resolved_args(case, m)
        swift = run_swift(tool, args)
        results[case.name] = (case, swift, run_python(args))
        if case.kind in ("device", "kinked"):
            twin = phantom_twin(case, swift)
            results[twin.name] = (twin, run_swift(tool, twin.args), run_python(twin.args))
    return results


def measure(argv=None) -> int:
    """Print the measured distributions the tolerances are set from."""
    m = ci.load_manifest()
    tool = build_tool()
    results = run_all(tool, m)
    print("%-26s %10s %10s %10s %10s %8s %8s %10s %10s %-10s %s" % (
        "case", "hdr dB", "row dB", "truth rel", "closed rel", "empty", "content", "vs truth", "residue", "at", "issues"))
    for name, (case, swift, python) in results.items():
        r = compare(case, swift, python)
        issues = r.text_mismatches + r.discrete_mismatches + r.header_field_mismatches
        print("%-26s %10.2e %10.2e %10.2e %10.2e %8.1f %8d %10.2e %10.2e %-10s %s" % (
            name, r.swift_header_db, r.swift_row_db, r.swift_truth_relative, r.closed_form_relative,
            r.empty_worst_dbc, r.content_count, r.truth_error_db, r.truth_residue_db, r.truth_residue_label, len(issues)))
        for issue in issues[:6]:
            print("    ", issue[:220])
    return 0


if __name__ == "__main__":
    sys.exit(measure())
