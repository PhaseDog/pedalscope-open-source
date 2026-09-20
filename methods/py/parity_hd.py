#!/usr/bin/env python3
"""The Harmonic Distortion parity comparison — shared by the CI test
(`test_parity_hd.py`) and the document generator (`make methods-docs`
writes `generated/parity-hd.tex` from the same numbers), so the chapter's
worked-example table and the test's verdict cannot disagree.

Three comparisons per case, over every (order, f0) the shipped validity
bound accepts INSIDE the excited band (f0 ≤ the sweep's fade-out edge —
the last grid point sits ON f2, under the fade, and the app's calibrated-
band bound removes it on every compensated record):

* Swift vs Python — `|mag_db(Python) − mag_db(Swift)| ≤ T_SWIFT` at every
  point of every order that carries content;
* both vs analytic — `|mag_db − expected_db| ≤ T_ANALYTIC[case]` over the
  case's analytic band (see `analytic_band`);
* analytically EMPTY orders (the symmetric clipper's even orders, the
  phantom's unlisted orders) must read below `EMPTY_ORDER_CEILING_DB` on
  both sides and agree to `T_SWIFT_EMPTY` — a reimplementation that
  invents content, or one that fails to reproduce the residue the
  finite-precision synthesis leaves, fails here.

The tolerances were SET FROM MEASUREMENT on 2026-09-08 (the #305 handoff
quotes the distributions), not from hope; each carries its measured value.
"""
from __future__ import annotations

import io
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
TOOL_PACKAGE = os.path.join(REPO, "Tools", "analysisdump")
PY = os.path.join(HERE, "harmonic_distortion.py")

# --- Tolerances ------------------------------------------------------------

# Swift vs Python on orders that carry content. Measured maximum
# 4.3e−14 dB (noiseless) and 4.0e−11 dB (seeded noise, 4 averages) — the
# two implementations differ only by FFT and transcendental rounding. Set
# 250× above the noisy figure and six orders below the tightest analytic
# tolerance, so a method change is red and library rounding never is: a
# ONE-sample shortening of order 1's 19 200-sample window reads 9.7e−6 dB
# on the hard clip and under 1e−6 on the gentler sources (measured
# 2026-09-08), which is why the bar sits below 1e−6.
T_SWIFT = 1e-8

# Swift vs Python on analytically empty orders — numerical residue at
# −65…−240 dB re input, reproduced to ≤ 6.4e−3 dB (measured; the residue
# is the finite-precision synthesis, not noise, and both sides compute it).
T_SWIFT_EMPTY = 0.05
# Where an order is analytically empty, neither implementation may read it
# closer than this to the case's LOUDEST content order. What an empty
# order holds is the synthesis's own aliasing residue (per-sample, #231),
# and it scales with how much of the device's spectrum lies past Nyquist:
# measured depths below the loudest order — phantom 131.6 dB, poly ≥ 143,
# tanh(2) 69.6 (H4 at −65.4 against H1 at +4.2), hardClip(0.1) 22.9 (H4 at
# −34.8 against H1 at −11.9: a near-square wave's 1/k ladder carries
# dozens of orders past Nyquist). The bound is a floor on that depth; the
# Swift-vs-Python agreement on the same reads (`T_SWIFT_EMPTY`) is what
# shows the reimplementation invents nothing the shipped code does not.
EMPTY_ORDER_DEPTH_DB = 20.0

# Both vs analytic truth, alias-free case (a phantom is exact by
# construction): measured maximum 0.0052 dB — at f0 = 30 Hz on H1, the
# analyzer's low-edge read — for every source, every order, over the whole
# excited valid band.
T_ANALYTIC_ALIAS_FREE = 0.01

# Both vs analytic truth, per-sample nonlinearity cases, over the LOWER
# HALF of each order's validity band (f0 ≤ maxValid(k)/2): the per-sample
# synthesis aliases content above Nyquist back into the band and the
# aliasing is worst in the top half-octave (#231, measured 2026-08-31).
# Measured maxima: tanh(2) 0.0049, poly(0.2, 0.3) 0.0052, hardClip(0.1)
# 0.279 (a near-square wave whose spectrum falls only as 1/k² carries far
# more energy past Nyquist). The FULL-band figures — tanh 0.554,
# hardclip 3.10, poly 0.0052 — are reported by `full_band_max`, not
# asserted; they are the synthetic device's aliasing, and the phantom twin
# of each case (its own first nine Fourier amplitudes as a phantom) is the
# alias-free control that pins the analyzer to ≤ 0.01 dB on the same
# amplitudes.
T_ANALYTIC_PER_SAMPLE = {"tanh": 0.01, "poly": 0.01, "hardclip": 0.30}

# The noisy, averaged case: on points the SHIPPED predicate reads as
# shaped on both sides, |mag − expected| ≤ 3 × the read's own stated
# 1σ scatter (`scatter_db`, the Rician dB uncertainty the predicate
# reports) + the noiseless tolerance. Measured 2026-09-08 at −80 dBFS,
# 4 averages, seed 3: worst H9 4.70 dB against a stated 3.27 dB scatter
# (1.4σ), H7 0.52 against 0.66, H5 0.08 against 0.47.
NOISY_SCATTER_MULTIPLE = 3.0


@dataclass(frozen=True)
class Case:
    name: str
    source: str
    args: List[str]
    amps: Optional[List[float]] = None
    averages: int = 1
    noise_db: Optional[float] = None
    seed: int = 1

    def cli(self) -> List[str]:
        out = ["--source", self.source] + list(self.args) + ["--seed", str(self.seed),
                                                          "--averages", str(self.averages)]
        if self.amps is not None:
            out += ["--amps", ",".join(repr(a) for a in self.amps)]
        if self.noise_db is not None:
            out += ["--noise-db", repr(self.noise_db)]
        return out


# One parameter set each (the kickoff's four), plus the phantom twins.
CASES = [
    Case("phantom", "phantom", [], amps=[1.0, 0.3, 0.1]),
    Case("tanh", "tanh", ["--gain", "2"]),
    Case("hardclip", "hardclip", ["--threshold", "0.1"]),
    Case("poly", "poly", ["--a2", "0.2", "--a3", "0.3"]),
]
NOISY = Case("tanh-noisy-averaged", "tanh", ["--gain", "2"], averages=4, noise_db=-80.0, seed=3)
NOISY_SINGLE = Case("tanh-noisy-single", "tanh", ["--gain", "2"], averages=1, noise_db=-80.0, seed=3)


# --- Running the two implementations --------------------------------------


def build_tool() -> str:
    """The shipped tool, release build. Returns the binary path."""
    subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    out = subprocess.run(["swift", "build", "-c", "release", "--package-path", TOOL_PACKAGE,
                          "--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
    return os.path.join(out, "analysisdump")


def load_tsv(text: str):
    lines = [l for l in text.splitlines(True) if not l.startswith("#")]
    return np.genfromtxt(io.StringIO("".join(lines)), delimiter="\t", names=True, dtype=None, encoding="utf-8")


def run_swift(tool: str, case: Case) -> str:
    return subprocess.run([tool, "synth"] + case.cli(), check=True, capture_output=True, text=True).stdout


def run_python(case: Case, manifest: Optional[str] = None) -> str:
    cmd = [sys.executable, PY] + case.cli()
    if manifest:
        cmd += ["--manifest", manifest]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


# --- The comparison --------------------------------------------------------


@dataclass
class OrderReport:
    order: int
    expected_db: float
    has_content: bool
    points: int
    max_swift_vs_python: float
    max_swift_vs_analytic_band: float
    max_python_vs_analytic_band: float
    max_swift_vs_analytic_full: float
    band_points: int
    shaped_both: int = 0
    max_scatter_normalized: float = float("nan")  # noisy case: |err| / (3·scatter + T)


@dataclass
class CaseReport:
    case: Case
    orders: List[OrderReport] = field(default_factory=list)

    def content_orders(self):
        return [o for o in self.orders if o.has_content]

    def empty_orders(self):
        return [o for o in self.orders if not o.has_content]


def excited_band_top(manifest: dict) -> float:
    return manifest["stimulus"]["excitedBandTopHz"]


def analytic_band(case: Case, sweep_fs: float, f2: float, order: int, f0: np.ndarray) -> np.ndarray:
    """Where the analytic comparison is asserted: the whole excited valid
    band for an alias-free phantom, the lower half of each order's
    validity band for a per-sample nonlinearity."""
    if case.source == "phantom":
        return np.ones_like(f0, dtype=bool)
    top = min(f2, sweep_fs / (2 * order + 1))
    return f0 <= top / 2


def compare(case: Case, swift_text: str, python_text: str, manifest: dict) -> CaseReport:
    sw = load_tsv(swift_text)
    py = load_tsv(python_text)
    assert len(sw) == len(py), f"{case.name}: {len(sw)} Swift rows vs {len(py)} Python rows"
    assert list(sw.dtype.names) == list(py.dtype.names), "column sets differ"
    fs = manifest["stimulus"]["sampleRateHz"]
    f2 = manifest["stimulus"]["endHz"]
    top = excited_band_top(manifest)
    report = CaseReport(case)
    for k in sorted(set(int(o) for o in sw["order"])):
        ms = (sw["order"] == k) & (sw["valid"] == 1) & (sw["f0_hz"] <= top)
        mp = (py["order"] == k) & (py["valid"] == 1) & (py["f0_hz"] <= top)
        assert np.array_equal(sw["f0_hz"][ms], py["f0_hz"][mp]), "grids differ"
        assert np.array_equal(sw["valid"][sw["order"] == k], py["valid"][py["order"] == k]), \
            f"H{k}: validity masks differ"
        expected = float(sw["expected_db"][ms][0])
        has_content = np.isfinite(expected) and expected > -100
        f0 = sw["f0_hz"][ms]
        a, b = sw["mag_db"][ms], py["mag_db"][mp]
        d_sp = np.abs(a - b)
        band = analytic_band(case, fs, f2, k, f0)
        e_sw = np.abs(a - expected) if has_content else np.full_like(a, np.nan)
        e_py = np.abs(b - expected) if has_content else np.full_like(b, np.nan)
        o = OrderReport(
            order=k, expected_db=expected, has_content=bool(has_content), points=int(ms.sum()),
            max_swift_vs_python=float(np.nanmax(d_sp)),
            max_swift_vs_analytic_band=float(np.nanmax(e_sw[band])) if has_content and band.any() else float("nan"),
            max_python_vs_analytic_band=float(np.nanmax(e_py[band])) if has_content and band.any() else float("nan"),
            max_swift_vs_analytic_full=float(np.nanmax(e_sw)) if has_content else float("nan"),
            band_points=int(band.sum()))
        if case.noise_db is not None and has_content:
            shaped = (sw["reading"][ms] == "shaped") & (py["reading"][mp] == "shaped") & band
            o.shaped_both = int(shaped.sum())
            if shaped.any():
                allowance = NOISY_SCATTER_MULTIPLE * sw["scatter_db"][ms][shaped] + T_ANALYTIC_PER_SAMPLE["tanh"]
                o.max_scatter_normalized = float(np.max(np.maximum(e_sw[shaped], e_py[shaped]) / allowance))
        report.orders.append(o)
    return report


def empty_order_ceiling(case: Case, swift_text: str, python_text: str, manifest: dict) -> Dict[int, float]:
    """Per analytically empty order: the louder of the two implementations'
    maximum read inside the excited valid band (dB re input)."""
    sw = load_tsv(swift_text)
    py = load_tsv(python_text)
    top = excited_band_top(manifest)
    out = {}
    for k in sorted(set(int(o) for o in sw["order"])):
        ms = (sw["order"] == k) & (sw["valid"] == 1) & (sw["f0_hz"] <= top)
        mp = (py["order"] == k) & (py["valid"] == 1) & (py["f0_hz"] <= top)
        expected = float(sw["expected_db"][ms][0])
        if np.isfinite(expected) and expected > -100:
            continue
        out[k] = float(max(np.nanmax(sw["mag_db"][ms]), np.nanmax(py["mag_db"][mp])))
    return out


def loudest_expected_db(swift_text: str) -> float:
    """The case's loudest analytic order, dB re input."""
    sw = load_tsv(swift_text)
    return float(np.nanmax(sw["expected_db"][np.isfinite(sw["expected_db"])]))


def phantom_twin(case: Case, swift_text: str) -> Case:
    """The case's own first-K Fourier amplitudes as a phantom — the
    alias-free control with the same content."""
    sw = load_tsv(swift_text)
    amps = []
    for k in sorted(set(int(o) for o in sw["order"])):
        e = float(sw["expected_db"][sw["order"] == k][0])
        amps.append(0.0 if not (np.isfinite(e) and e > -100) else 10 ** (e / 20))
    return Case(f"{case.name}-phantom-twin", "phantom", [], amps=amps, seed=case.seed)


def full_band_max(report: CaseReport) -> float:
    return max((o.max_swift_vs_analytic_full for o in report.content_orders()), default=float("nan"))
