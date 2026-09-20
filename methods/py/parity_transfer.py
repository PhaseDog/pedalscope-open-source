#!/usr/bin/env python3
"""The Transfer Curve parity comparison — shared by the CI test
(`test_parity_transfer.py`) and the document generator (`make methods-docs`
writes `generated/parity-transfer.tex` from the same numbers), so the
chapter's worked-example table and the test's verdict cannot disagree.

Every case runs the shipped tool (`analysisdump transfer-synth`) and the
Python reimplementation (`transfer_curve.py`) on one synthetic device and
compares, per case:

* Swift vs Python — the displayed cycle, the static curve, the compensated
  cycle where accepted, the three areas, ψ1, the frame shift, the residual,
  every fit term, the ground truth both sides computed, and every discrete
  reading (class, flip, polarity, tile, verdict, presence) exactly;
* the shipped result vs the closed-form truth — the fundamental ellipse's
  area against (π/4)·(R/y_max)·|sin φ_1|, the raw and compensated figures
  against the series truth, the frame shift against the planted advance,
  the compensated areas against zero, and the class the truth predicts.

The tolerances were SET FROM MEASUREMENT on 2026-09-17 (the #306
chapter-two handoff quotes the distributions), not from hope; each carries
its measured value.
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

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
TOOL_PACKAGE = os.path.join(REPO, "Tools", "analysisdump")
PY = os.path.join(HERE, "transfer_curve.py")

# --- Tolerances ------------------------------------------------------------

# Swift vs Python on every continuous quantity: the displayed and
# compensated cycles, the static curves, the three areas, ψ1, the
# residuals, the fit terms. Measured maximum 2.5e−13 (a paired device behind
# a biquad — scipy's filter loop and the Swift loop round differently over
# 144 000 samples) and 2.2e−16 with no filter (double rounding only). Set
# 400× above the filtered figure; a one-bin change in the phase binning
# moves a cycle value by ~1e−3, so the bar is far below any method change.
T_SWIFT = 1e-10
# The fitted frame shift: measured 0 on every case (the two scans walk the
# same doubles); a tie flipped by a last-ulp cosine difference would move
# it by one fine step (0.001), which the bar is set to catch.
T_SWIFT_SHIFT = 1e-9
# The two truths (Swift's recurrence quadrature vs the Python's FFT of the
# same 2^18-point grid, 200 orders): measured ≤ 3.1e−12.
T_SWIFT_TRUTH = 1e-9

# The shipped fundamental-ellipse area against its closed form
# (π/4)·(R/y_max)·|sin φ_1|, as a RATIO. Measured on the identity behind a
# single-pole low-pass at E2 / A6 / C7 and behind a 50-sample advance at
# E2 / A4 / C7: 0.9925…0.9980 at the plan's 1.5 s tone, 0.9995…0.9999 at
# 15 s. The deficit is the tone's fade-out, whose samples the analyzer bins
# (only the START is skipped): a phase-dependent ramp weighting over the
# last 20 ms, whose share falls with the tone's length.
T_ELLIPSE_RATIO = 0.01
T_ELLIPSE_RATIO_LONG = 0.001

# The raw figure against the series truth, as a fraction of the truth's
# output peak. Measured: static curve — smooth memoryless devices ≤ 0.0075
# (the parametric clip's knee), the hard clip 0.027 (a 256-bin cycle
# rounds a corner by about an eighth of a bin's input span), open ellipses
# ≤ 0.036 (the branch-mean static curve of an open loop is least
# trustworthy where the branches meet, at the input's extremes); cycle —
# ≤ 0.014 everywhere (the fade-out's ramp share, and at the corners the
# bin-mean of a kinked function).
T_RAW_STATIC_TRUTH = {"memoryless": 0.01, "hardclip": 0.05, "ellipse": 0.05, "paired": 0.02}
T_RAW_CYCLE_TRUTH = 0.02

# The COMPENSATED figure against the memoryless-lattice truth — what the
# §6.5 removal should recover — as a fraction of the peak. Measured:
# static ≤ 0.0055, cycle ≤ 0.013 (the pre-dispersive case, whose orders
# above the voting set are extrapolated).
T_COMP_STATIC_TRUTH = 0.01
T_COMP_CYCLE_TRUTH = 0.02

# The fitted frame shift against the planted advance, samples. Measured
# ≤ 0.39: the paired H1's phase is read at the NEAREST bin (1.46 Hz), and
# the read's error times the filter's phase slope is absorbed by the fit as
# a shift — up to half a bin width's worth.
T_FRAME_SHIFT_SAMPLES = 0.5
# The pairing residual on a genuine pairing, rad. Measured ≤ 0.024 (the
# pre-dispersive case); the shipped accept bar is 0.25.
T_RESIDUAL_RMS = 0.05
# The compensated areas of a memoryless device behind a filter: measured
# linear ≤ 0.0028, nonlinear ≤ 0.0014 — a tenth of the 0.05 verdict bar.
T_COMP_AREA = 0.005
# The raw nonlinear area of a memoryless unfiltered device: measured
# ≤ 0.00196 (the hard clip) — bin jitter in the residual trajectory.
T_MEMORYLESS_NONLINEAR = 0.005


@dataclass(frozen=True)
class Case:
    name: str
    args: List[str]
    kind: str  # memoryless | hardclip | ellipse | ellipse-long | paired | paired-noop

    @property
    def paired(self) -> bool:
        return "--paired" in self.args


CASES = [
    # (a) memoryless devices at the loudest hardware drive the sheet offers
    # (0.5 = −6 dBFS; the plan's default 0.05 clips none of them — the
    # `a-tanh-plan` case shows that).
    Case("a-tanh", ["--source", "tanh", "--gain", "2", "--amplitude", "0.5"], "memoryless"),
    Case("a-tanh-plan", ["--source", "tanh", "--gain", "2"], "memoryless"),
    Case("a-hardclip", ["--source", "hardclip", "--threshold", "0.1", "--amplitude", "0.5"], "hardclip"),
    Case("a-asym", ["--source", "asymmetric", "--gain", "2", "--negative-scale", "0.5", "--amplitude", "0.5"], "memoryless"),
    Case("a-param", ["--source", "parametric", "--threshold", "0.3", "--knee", "0.5", "--asymmetry", "0", "--amplitude", "0.5"], "memoryless"),
    # (b) the identity behind a single-pole low-pass (#352's own check).
    Case("b-lp-E2", ["--source", "identity", "--post", "lowpass", "--post-hz", "1550", "--note", "E2", "--amplitude", "0.5"], "ellipse"),
    Case("b-lp-A6", ["--source", "identity", "--post", "lowpass", "--post-hz", "1550", "--note", "A6", "--amplitude", "0.5"], "ellipse"),
    Case("b-lp-C7", ["--source", "identity", "--post", "lowpass", "--post-hz", "1550", "--note", "C7", "--amplitude", "0.5"], "ellipse"),
    Case("b-lp-E2-15s", ["--source", "identity", "--post", "lowpass", "--post-hz", "1550", "--note", "E2", "--amplitude", "0.5", "--duration", "15"], "ellipse-long"),
    Case("b-lp-A6-15s", ["--source", "identity", "--post", "lowpass", "--post-hz", "1550", "--note", "A6", "--amplitude", "0.5", "--duration", "15"], "ellipse-long"),
    Case("b-lp-C7-15s", ["--source", "identity", "--post", "lowpass", "--post-hz", "1550", "--note", "C7", "--amplitude", "0.5", "--duration", "15"], "ellipse-long"),
    # (c) the identity under a deliberate 50-sample alignment error (#348).
    Case("c-delay-E2", ["--source", "identity", "--latency-error", "50", "--note", "E2", "--amplitude", "0.5"], "ellipse"),
    Case("c-delay-A4", ["--source", "identity", "--latency-error", "50", "--note", "A4", "--amplitude", "0.5"], "ellipse"),
    Case("c-delay-C7", ["--source", "identity", "--latency-error", "50", "--note", "C7", "--amplitude", "0.5"], "ellipse"),
    # (d) a soft clipper behind a post-filter, paired.
    Case("d-tanh-lp", ["--source", "tanh", "--gain", "2", "--amplitude", "0.5", "--post", "lowpass", "--post-hz", "1550", "--paired"], "paired"),
    Case("d-tanh-hp", ["--source", "tanh", "--gain", "2", "--amplitude", "0.5", "--post", "highpass", "--post-hz", "20", "--paired"], "paired"),
    # (e) a soft clipper behind a PRE-clipper high-pass (pre-dispersive), paired.
    Case("e-tanh-prehp", ["--source", "tanh", "--gain", "2", "--amplitude", "0.5", "--pre", "highpass", "--pre-hz", "40", "--paired"], "paired"),
    # (f) an asymmetric clipper behind a DC-blocking high-pass (#353), paired.
    Case("f-asym-hp", ["--source", "asymmetric", "--gain", "2", "--negative-scale", "0.5", "--amplitude", "0.5", "--post", "highpass", "--post-hz", "20", "--paired"], "paired"),
    # (g) the orientation resolution, the polarity reading, the no-op class.
    Case("g-tanh-shift", ["--source", "tanh", "--gain", "2", "--amplitude", "0.5", "--half-cycle-shift", "--paired"], "paired-noop"),
    Case("g-tanh-inv-lp", ["--source", "tanh", "--gain", "2", "--amplitude", "0.5", "--invert", "--post", "lowpass", "--post-hz", "1550", "--paired"], "paired"),
    Case("g-tanh-paired", ["--source", "tanh", "--gain", "2", "--amplitude", "0.5", "--paired"], "paired-noop"),
]


# --- Running the two implementations --------------------------------------


def build_tool() -> str:
    subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    out = subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE,
                          "--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
    return os.path.join(out, "analysisdump")


def run_swift(tool: str, case: Case) -> str:
    return subprocess.run([tool, "transfer-synth"] + case.args, check=True, capture_output=True, text=True).stdout


def run_python(case: Case, manifest: Optional[str] = None) -> str:
    cmd = [sys.executable, PY] + case.args
    if manifest:
        cmd += ["--manifest", manifest]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


@dataclass
class Dump:
    header: Dict[str, Dict[str, str]]
    terms: List[Dict[str, str]]
    table: np.ndarray

    def value(self, line: str, key: str) -> float:
        return float(self.header[line][key])

    def text(self, line: str, key: str) -> str:
        return self.header[line][key]


def parse(text: str) -> Dump:
    header: Dict[str, Dict[str, str]] = {}
    terms: List[Dict[str, str]] = []
    body: List[str] = []
    for line in text.splitlines(True):
        if line.startswith("#"):
            key, rest = line[2:].split(":", 1)
            kv = dict(re.findall(r"(\w+)=(\S+)", rest))
            if key == "term":
                terms.append(kv)
            else:
                header[key] = kv
        else:
            body.append(line)
    table = np.genfromtxt(io.StringIO("".join(body)), delimiter="\t", names=True, dtype=None, encoding="utf-8")
    return Dump(header, terms, table)


# --- The comparison --------------------------------------------------------


@dataclass
class CaseReport:
    case: Case
    figure_class: str
    expected_class: str
    flipped: bool
    polarity_inverting: Optional[bool]
    peak: float
    # Swift vs Python, maxima
    swift_cycle: float
    swift_static: float
    swift_compensated: float
    swift_areas: float
    swift_psi1: float
    swift_shift: float
    swift_residual: float
    swift_terms: float
    swift_truth: float
    discrete_match: bool
    # Swift vs truth
    linear: float
    expected_linear: float
    nonlinear: float
    raw_static_truth: float
    raw_cycle_truth: float
    comp_static_truth: float
    comp_cycle_truth: float
    comp_linear: float
    comp_nonlinear: float
    frame_shift: float
    expected_shift: float
    residual_rms: float
    voting: int
    support_hz: float
    python_raw_static_truth: float
    python_comp_static_truth: float

    @property
    def ellipse_ratio(self) -> float:
        return self.linear / self.expected_linear if self.expected_linear > 1e-6 else float("nan")

    @property
    def has_compensated(self) -> bool:
        return math.isfinite(self.comp_static_truth)


def _flag(s: str) -> Optional[bool]:
    return None if s == "nan" else s == "1"


def _num(s: str) -> float:
    return float("nan") if s == "nan" else float(s)


def _maxabs(a) -> float:
    a = np.asarray(a, dtype=np.float64)
    return float(np.nanmax(np.abs(a))) if np.any(np.isfinite(a)) else float("nan")


def compare(case: Case, swift_text: str, python_text: str) -> CaseReport:
    sw, py = parse(swift_text), parse(python_text)
    assert list(sw.table.dtype.names) == list(py.table.dtype.names), f"{case.name}: column sets differ"
    assert len(sw.table) == len(py.table), f"{case.name}: {len(sw.table)} Swift rows vs {len(py.table)} Python rows"
    cyc = sw.table["section"] == "cycle"
    st = ~cyc
    t, p = sw.table, py.table
    peak = sw.value("truth", "output_peak")
    fig, exp, ori = sw.header["figure"], sw.header["expected"], sw.header["orientation"]
    pfig, pori = py.header["figure"], py.header["orientation"]
    discrete = all(fig[k] == pfig[k] for k in ("class", "memory_verdict", "tile_inverting", "fundamental")) \
        and ori["flipped"] == pori["flipped"] \
        and sw.header["polarity"]["inverting"] == py.header["polarity"]["inverting"] \
        and sw.header["polarity"]["confident"] == py.header["polarity"]["confident"]
    fit, pfit = sw.header.get("fit", {}), py.header.get("fit", {})
    has_fit = "frame_shift_samples" in fit
    shift = _num(fit.get("frame_shift_samples", "nan"))
    areas = max(abs(_num(fig[k]) - _num(pfig[k])) for k in ("hyst", "linear", "nonlinear")
                if fig[k] != "nan")
    if fig["comp_hyst"] != "nan":
        areas = max(areas, *(abs(_num(fig[k]) - _num(pfig[k])) for k in ("comp_hyst", "comp_linear", "comp_nonlinear")))
    terms = max((abs(float(a[k]) - float(b[k])) for a, b in zip(sw.terms, py.terms)
                 for k in ("rel_mag", "residual", "lattice_excess")), default=float("nan"))
    has_comp = np.any(np.isfinite(t["y_comp"]))
    return CaseReport(
        case=case,
        figure_class=fig["class"],
        expected_class=exp["class"],
        flipped=ori["flipped"] == "1",
        polarity_inverting=_flag(fig["tile_inverting"]),
        peak=peak,
        swift_cycle=_maxabs(t["y"][cyc] - p["y"][cyc]),
        swift_static=_maxabs(t["y"][st] - p["y"][st]),
        swift_compensated=_maxabs(t["y_comp"] - p["y_comp"]) if has_comp else float("nan"),
        swift_areas=areas,
        swift_psi1=abs(_num(ori["psi1"]) - _num(pori["psi1"])),
        swift_shift=abs(shift - _num(pfit.get("frame_shift_samples", "nan"))) if has_fit else float("nan"),
        swift_residual=abs(_num(fit.get("harmonic_residual_rms", "nan")) - _num(pfit.get("harmonic_residual_rms", "nan"))) if has_fit else float("nan"),
        swift_terms=terms,
        swift_truth=max(_maxabs(t["y_truth_raw"] - p["y_truth_raw"]), _maxabs(t["y_truth_comp"] - p["y_truth_comp"])),
        discrete_match=discrete,
        linear=_num(fig["linear"]),
        expected_linear=_num(exp["linear"]),
        nonlinear=_num(fig["nonlinear"]),
        raw_static_truth=_maxabs(t["y"][st] - t["y_truth_raw"][st]) / peak,
        raw_cycle_truth=_maxabs(t["y"][cyc] - t["y_truth_raw"][cyc]) / peak,
        comp_static_truth=_maxabs(t["y_comp"][st] - t["y_truth_comp"][st]) / peak if has_comp else float("nan"),
        comp_cycle_truth=_maxabs(t["y_comp"][cyc] - t["y_truth_comp"][cyc]) / peak if has_comp else float("nan"),
        comp_linear=_num(fig["comp_linear"]),
        comp_nonlinear=_num(fig["comp_nonlinear"]),
        frame_shift=shift,
        expected_shift=_num(exp["frame_shift_samples"]),
        residual_rms=_num(fit.get("harmonic_residual_rms", "nan")),
        voting=int(fit["voting"]) if "voting" in fit else 0,
        support_hz=_num(fit.get("support_hz", "nan")),
        python_raw_static_truth=_maxabs(p["y"][st] - p["y_truth_raw"][st]) / peak,
        python_comp_static_truth=_maxabs(p["y_comp"][st] - p["y_truth_comp"][st]) / peak if has_comp else float("nan"),
    )


def raw_static_tolerance(case: Case) -> float:
    # The no-op cases: the plain paired clipper is memoryless (measured
    # 0.003), the half-cycle case keeps a residual advance of
    # round(P/2) − P/2 = 0.48 samples after the flip, so its raw figure is a
    # slightly open loop (measured 0.011) — the paired bucket.
    key = {"memoryless": "memoryless", "hardclip": "hardclip", "ellipse": "ellipse", "ellipse-long": "ellipse",
           "paired": "paired", "paired-noop": "paired"}[case.kind]
    return T_RAW_STATIC_TRUTH[key]


def ellipse_tolerance(case: Case) -> float:
    return T_ELLIPSE_RATIO_LONG if case.kind == "ellipse-long" else T_ELLIPSE_RATIO


def run_all(tool: str) -> Dict[str, Tuple[Case, str, str]]:
    return {c.name: (c, run_swift(tool, c), run_python(c)) for c in CASES}
