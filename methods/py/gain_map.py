#!/usr/bin/env python3
"""Gain Map — an independent reimplementation of PedalScope's level-resolved
harmonic measurement, written from the methods manifest
(``Docs/Methods/generated/manifest.json``, the ``gainMap`` object) and the
technical chapter's own equations, NOT by transliterating the Swift.

The per-level analysis is chapter one's: this module IMPORTS
``harmonic_distortion.py`` for the sweep, the device, the phantom, the
noise generator and the analyzer, and adds only what the Gain Map adds — the
level lattice, the per-level stimulus with its silence before and after,
the aligned cut, the journey's own analyzer configuration, the export grid,
the THD and harmonic cells, the validity fade and the edge masks, the
presence cells and verdict, the calibration stamp read through a running
median with the drive term's clamp, the operative-floor path, the analyzer's
own residue (chapter one's analyzer on the identity capture, per sweep
length, worst), the composition, the peak tile's two passes and the
corroboration, the three-state cleanup and the tile's column, and the
summaries' journey cleanup.

It produces the same TSV ``analysisdump journey-synth`` produces (same header
lines, same column set, same conventions), so one comparator serves both,
and ``test_parity_journey.py`` pins the two against each other and against
the closed-form ladder.

Conventions, repeated from the manifest because they decide what a number
means:

* The journey's harmonic cells are UNCOMPENSATED: the chain gain the loop
  applies is IN the stored H1 (and every other order), so a cell's delivered
  fundamental is ``level + H1`` in absolute dBFS.
* The calibration is the identity loop through the same gain and the same
  noise generator — the stamp is a THD read of the loop's own noise at the
  calibration's drive, and the margins compose it with the analyzer's own
  residue: the larger floor is the smaller margin.
* A nonlinearity is applied PER SAMPLE at the sample rate (the simulated-DUT
  arm's convention); the phantom is alias-free by construction.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import harmonic_distortion as hd
import transfer_curve as tc

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = hd.DEFAULT_MANIFEST
fmt = hd.fmt
swift_round = hd.swift_round

ORDERS = list(range(1, 10))


def load_manifest(path: str = DEFAULT_MANIFEST) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# The lattice and the grid (manifest ``gainMap.plan``)


def levels(min_db: float, max_db: float, count: int) -> List[float]:
    """``levels(minDB:maxDB:count:)``: evenly spaced in dB, end points inclusive;
    a count of one is the ceiling alone."""
    if count <= 1:
        return [max_db]
    return [min_db + (max_db - min_db) * i / (count - 1) for i in range(count)]


def export_grid(f1: float, f2: float, count: int) -> List[float]:
    """``exportGrid()``: ``count`` log-spaced fundamentals from ``f1`` to ``f2``
    INCLUSIVE — the first and last columns sit AT the sweep's edges."""
    return [f1 * (f2 / f1) ** (i / (count - 1)) for i in range(count)]


@dataclass(frozen=True)
class JourneyPlan:
    f1: float
    f2: float
    duration: float
    fs: float
    levels_db: List[float]
    preroll: float
    tail: float

    @property
    def preroll_samples(self) -> int:
        return int(self.preroll * self.fs)

    @property
    def tail_samples(self) -> int:
        return int(self.tail * self.fs)

    def sweep(self, level_index: int, hdm: dict) -> hd.Sweep:
        """The level's own synchronized sweep at its amplitude — chapter one's
        object, with the fingerprint sweep's fades."""
        return hd.Sweep.from_manifest(hdm, f1=self.f1, f2=self.f2, requested_duration=self.duration,
                                      fs=self.fs, amplitude=10 ** (self.levels_db[level_index] / 20))

    def stimulus(self, sweep: hd.Sweep) -> np.ndarray:
        return np.concatenate([np.zeros(self.preroll_samples), sweep.samples(), np.zeros(self.tail_samples)])

    def aligned(self, captured: np.ndarray, sweep: hd.Sweep, latency: int) -> np.ndarray:
        """``alignedCapture``: the sweep and the tail cut out of the capture at
        the preroll plus the loop's latency."""
        offset = self.preroll_samples + latency
        end = min(len(captured), offset + sweep.sample_count + self.tail_samples)
        return captured[min(offset, end):end]

    def grid(self, count: int) -> List[float]:
        return export_grid(self.f1, self.f2, count)


def journey_manifest(m: dict, sweep_f1: float) -> dict:
    """Chapter one's analyzer at the JOURNEY's configuration: the manifest's
    ``gainMap.plan`` harmonic count, response length and window cap replace
    the fingerprint analyzer's, and the deconvolver's taper follows the
    sweep it is handed (``f1/2`` to ``f1``, the HD manifest's rule)."""
    hdm = copy.deepcopy(m["harmonicDistortion"])
    plan = m["gainMap"]["plan"]
    hdm["extraction"]["harmonicCount"] = int(plan["harmonicCount"])
    hdm["extraction"]["responseFFTLength"] = int(plan["responseFFTLength"])
    hdm["extraction"]["maxWindowHalfWidthS"] = float(plan["maxWindowHalfWidthS"])
    hdm["deconvolution"]["taperLowHz"] = sweep_f1 / 2
    hdm["deconvolution"]["taperHighHz"] = sweep_f1
    return hdm


def calibration_manifest(m: dict, sweep_f1: float) -> dict:
    """The fingerprint analyzer's own configuration (the calibrator's), with
    the taper following the calibration sweep."""
    hdm = copy.deepcopy(m["harmonicDistortion"])
    hdm["deconvolution"]["taperLowHz"] = sweep_f1 / 2
    hdm["deconvolution"]["taperHighHz"] = sweep_f1
    return hdm


# ---------------------------------------------------------------------------
# The device, the loop, the calibration


@dataclass
class Source:
    kind: str                       # a nonlinearity kind, or "phantom"
    device: Optional[tc.Device]
    ladders: Optional[List[List[float]]]

    def ladder(self, level_index: int) -> List[float]:
        assert self.ladders is not None
        return self.ladders[0] if len(self.ladders) == 1 else self.ladders[level_index]

    @property
    def label(self) -> str:
        if self.kind == "phantom":
            return "phantom(" + ";".join("[" + ",".join(fmt(a) for a in l) + "]" for l in self.ladders) + ")"
        return tc.device_label(self.device.kind, self.device.params)


@dataclass
class Plan:
    source: Source
    plan: JourneyPlan
    latency: int = 0
    chain_gain_db: float = 0.0
    noise_rms: Optional[float] = None
    seed: int = 1
    operative_rms: Optional[float] = None
    cal_level_db: float = -26.0

    @property
    def chain_gain(self) -> float:
        return 10 ** (self.chain_gain_db / 20)


def through_loop(rendered: np.ndarray, plan: Plan, seed: int, noisy: bool, increment: int) -> np.ndarray:
    """The loop: delayed by the latency (the capture keeps the stimulus's
    length), plus one seeded noise stream at the interface's input, then
    scaled by the chain gain — signal and noise alike, as an input-gain knob
    does."""
    captured = np.zeros_like(rendered)
    d = plan.latency
    if d < len(rendered):
        captured[d:] = rendered[:len(rendered) - d]
    if noisy and plan.noise_rms is not None:
        captured = captured + hd.gaussian_noise(len(captured), plan.noise_rms, seed, increment)
    if plan.chain_gain != 1:
        captured = captured * plan.chain_gain
    return captured


def capture_seed(plan: Plan, level_index: Optional[int], increment: int) -> int:
    """The calibration is repeat 0, level i is repeat i + 1."""
    return hd.repeat_seed(plan.seed, 0 if level_index is None else level_index + 1, increment)


def rendered(plan: Plan, level_index: int, hdm: dict, synthesis: dict) -> Tuple[hd.Sweep, np.ndarray]:
    sweep = plan.plan.sweep(level_index, hdm)
    if plan.source.kind == "phantom":
        phantom = hd.phantom_capture(sweep, plan.source.ladder(level_index), synthesis["phantomNyquistGateFraction"])
        out = np.concatenate([np.zeros(plan.plan.preroll_samples), phantom, np.zeros(plan.plan.tail_samples)])
        return sweep, out
    return sweep, plan.source.device.render(plan.plan.stimulus(sweep), plan.plan.fs)


@dataclass
class Calibration:
    sweep: hd.Sweep
    level_dbfs: float
    latency: int
    chain_gain_db: Optional[float]
    stamp: List[Tuple[float, float]]    # (frequency, thd) — the usable points (thd > 0)
    stamp_all: List[Tuple[float, float]]
    analysis: hd.Analysis

    @property
    def delivered_dbfs(self) -> Optional[float]:
        return None if self.chain_gain_db is None else self.level_dbfs + self.chain_gain_db


def thd_at(analysis: hd.Analysis, f0: float, band: Tuple[float, float]) -> Optional[float]:
    """THD (not THD+N) at ``f0`` over the declared band, excluding the orders
    the sweep's own validity bound rejects; None outside the swept band or
    without a fundamental."""
    s = analysis.sweep
    if not (s.f1 <= f0 <= s.f2) or 1 not in analysis.spectra:
        return None
    h1 = hd.magnitude_at_output_frequency(analysis.spectra[1], analysis.bin_width, f0)
    if h1 is None or h1 <= 0:
        return None
    total = 0.0
    for k in analysis.orders:
        if k < 2:
            continue
        fk = f0 * k
        if not (band[0] <= fk <= band[1]) or not hd.is_valid(s, k, f0):
            continue
        mk = hd.magnitude_at_output_frequency(analysis.spectra[k], analysis.bin_width, fk)
        if mk is None:
            continue
        total += mk * mk
    return math.sqrt(total) / h1


def thd_curve(analysis: hd.Analysis, points: int, band: Tuple[float, float]) -> List[Tuple[float, float]]:
    """``thdCurve(points:)``: log-spaced from 1.5·f1 to f2 (the 1.5× is a
    literal in the kernel), points with no THD dropped."""
    lo, hi = math.log(analysis.sweep.f1 * 1.5), math.log(analysis.sweep.f2)
    out = []
    for i in range(points):
        f0 = math.exp(lo + (hi - lo) * i / (points - 1))
        t = thd_at(analysis, f0, band)
        if t is not None:
            out.append((f0, t))
    return out


def chain_gain_db(analysis: hd.Analysis) -> Optional[float]:
    """The median in-band |H1| on a log grid from max(100, 2·f1) to
    min(5000, f2/2) in steps of 0.02 decades — the calibrator's own statistic."""
    s = analysis.sweep
    low = max(100.0, 2 * s.f1)
    high = min(5000.0, 0.5 * s.f2)
    if high <= low or 1 not in analysis.spectra:
        return None
    mags = []
    i = 0
    while True:
        e = math.log10(low) + 0.02 * i
        if e > math.log10(high):
            break
        m = hd.magnitude_at_output_frequency(analysis.spectra[1], analysis.bin_width, 10 ** e)
        if m is not None and m > 0:
            mags.append(m)
        i += 1
    if not mags:
        return None
    mags.sort()
    return 20 * math.log10(mags[len(mags) // 2])


def calibrate(plan: Plan, m: dict, increment: int) -> Calibration:
    """The app's calibration through the loop: 20 Hz to round(0.45·fs) for
    ten seconds at the calibration level, silence before and after, the
    identity loop (noiseless when the plan is the render path), analyzed by
    the fingerprint analyzer from the cut the calibrator makes at the loop's
    latency (which the Swift MEASURES and this module KNOWS)."""
    g = m["gainMap"]["synthesis"]
    fs = plan.plan.fs
    f2 = float(swift_round(g["calibrationEndFraction"] * fs))
    hdm = calibration_manifest(m, g["calibrationStartHz"])
    sweep = hd.Sweep.from_manifest(hdm, f1=g["calibrationStartHz"], f2=f2, requested_duration=g["calibrationDurationS"],
                                   fs=fs, amplitude=10 ** (plan.cal_level_db / 20))
    preroll = int(g["calibrationPrerollS"] * fs)
    tail = int(g["calibrationTailS"] * fs)
    stimulus = np.concatenate([np.zeros(preroll), sweep.samples(), np.zeros(tail)])
    captured = through_loop(stimulus, plan, capture_seed(plan, None, increment), plan.operative_rms is None, increment)
    offset = preroll + plan.latency
    end = min(len(captured), offset + sweep.sample_count + int(0.2 * fs))
    aligned = captured[min(offset, len(captured)):end]
    analysis = hd.analyze(aligned, sweep, hdm)
    band = (m["gainMap"]["summary"]["band"]["lowHz"], m["gainMap"]["summary"]["band"]["highHz"])
    stamp_all = thd_curve(analysis, 128, band)
    return Calibration(sweep, 20 * math.log10(max(sweep.amplitude, 1e-12)), plan.latency, chain_gain_db(analysis),
                       [p for p in stamp_all if p[1] > 0], stamp_all, analysis)


# ---------------------------------------------------------------------------
# The summary grid (manifest ``gainMap.summary``)


@dataclass
class Summary:
    frequencies: List[float]
    levels_db: List[float]
    orders: List[int]
    thd: List[List[Optional[float]]]                 # [level][column]
    harmonic_db: Dict[int, List[List[Optional[float]]]]  # order → [level][column]
    fs: float
    band: Tuple[float, float]


def summarize(analyses: List[hd.Analysis], levels_db: List[float], frequencies: List[float],
              band: Tuple[float, float]) -> Summary:
    orders = analyses[0].orders if analyses else []
    thd = [[thd_at(a, f, band) for f in frequencies] for a in analyses]
    harm: Dict[int, List[List[Optional[float]]]] = {}
    for k in orders:
        rows = []
        for a in analyses:
            row = []
            for f in frequencies:
                mk = hd.magnitude_at_output_frequency(a.spectra[k], a.bin_width, f * k)
                row.append(20 * math.log10(mk) if mk is not None and mk > 0 else None)
            rows.append(row)
        harm[k] = rows
    return Summary(list(frequencies), list(levels_db), orders, thd, harm, analyses[0].sweep.fs, band)


def grid_valid(s: Summary, order: int, f0: float) -> bool:
    """The summary's validity: the grid's own span and the alias-image bound
    (journey levels are uncompensated — no calibrated-band bound)."""
    lo, hi = s.frequencies[0], s.frequencies[-1]
    return lo <= f0 <= hi and f0 <= min(hi, s.fs / (2 * order + 1))


def truncated_columns(s: Summary) -> List[bool]:
    return [any(k >= 2 and s.band[0] <= f * k <= s.band[1] and not grid_valid(s, k, f) for k in s.orders)
            for f in s.frequencies]


def edge_columns(s: Summary, ratio: float) -> Tuple[List[bool], List[bool]]:
    lo, hi = s.frequencies[0], s.frequencies[-1]
    return [f <= lo * ratio for f in s.frequencies], [f >= hi / ratio for f in s.frequencies]


def presence_cells(s: Summary, separation_db: float) -> List[List[str]]:
    """``fundamentalPresenceCells``: the reference is the loudest order stored
    for that cell; no rig floor enters here."""
    out = []
    for i in range(len(s.levels_db)):
        row = []
        for j in range(len(s.frequencies)):
            h1 = s.harmonic_db[1][i][j] if 1 in s.harmonic_db else None
            if h1 is None:
                row.append("undetermined")
                continue
            loudest = h1
            for k in s.orders:
                if k == 1:
                    continue
                mk = s.harmonic_db[k][i][j]
                if mk is not None:
                    loudest = max(loudest, mk)
            row.append("absent" if loudest - h1 >= separation_db else "present")
        out.append(row)
    return out


def presence_depths(s: Summary) -> List[List[Optional[float]]]:
    out = []
    for i in range(len(s.levels_db)):
        row = []
        for j in range(len(s.frequencies)):
            h1 = s.harmonic_db[1][i][j] if 1 in s.harmonic_db else None
            if h1 is None:
                row.append(None)
                continue
            loudest = h1
            for k in s.orders:
                if k != 1 and s.harmonic_db[k][i][j] is not None:
                    loudest = max(loudest, s.harmonic_db[k][i][j])
            row.append(loudest - h1)
        out.append(row)
    return out


@dataclass
class Verdict:
    absent: bool
    fraction: float
    median_depth: Optional[float]
    evaluated: int


def presence_verdict(s: Summary, cells: List[List[str]], depths, bottom: List[bool], top: List[bool]) -> Verdict:
    readings = []
    for i in range(len(s.levels_db)):
        for j in range(len(s.frequencies)):
            if bottom[j] or top[j]:
                continue
            readings.append((cells[i][j], depths[i][j]))
    evaluable = [r for r in readings if r[0] != "undetermined"]
    if not evaluable:
        return Verdict(False, 0.0, None, 0)
    absent = sorted(d for r, d in evaluable if r == "absent")
    fraction = len(absent) / len(evaluable)
    return Verdict(fraction > 0.5, fraction, absent[len(absent) // 2] if absent else None, len(evaluable))


# ---------------------------------------------------------------------------
# The floor (manifest ``gainMap.floor``)


def pooled_floor_db(curve: List[Tuple[float, float]], f: float, median_points: int) -> Optional[float]:
    """The stamp in dB at ``f``: each point replaced by the running median of
    its neighbours' dB over an odd window, then linear on the (log f, dB)
    plane, clamped to the end values."""
    assert median_points >= 1 and median_points % 2 == 1
    points = sorted((p for p in curve if p[1] > 0 and p[0] > 0), key=lambda p: p[0])
    if not points or f <= 0:
        return None
    raw = [20 * math.log10(p[1]) for p in points]
    half = (median_points - 1) // 2
    if half == 0:
        smoothed = raw
    else:
        smoothed = []
        for i in range(len(raw)):
            window = sorted(raw[max(0, i - half):min(len(raw) - 1, i + half) + 1])
            n = len(window)
            smoothed.append(window[n // 2] if n % 2 == 1 else (window[n // 2 - 1] + window[n // 2]) / 2)
    if f <= points[0][0]:
        return smoothed[0]
    if f >= points[-1][0]:
        return smoothed[-1]
    for i in range(1, len(points)):
        if f <= points[i][0]:
            a, b = points[i - 1], points[i]
            t = math.log(f / a[0]) / math.log(b[0] / a[0])
            return smoothed[i - 1] + (smoothed[i] - smoothed[i - 1]) * t
    return smoothed[-1]


def rig_noise_margins(s: Summary, cal: Calibration, operative_rms: Optional[float], median_points: int):
    """The rig-noise half of the composed margin: the stamp (an ABSOLUTE
    noise, read through the median, drive-adjusted but never below its own
    ratio) and the operative floor (absolute dBFS, no chain-gain term), the
    larger governing; None when neither source is usable."""
    if 1 not in s.harmonic_db:
        return None
    cal_noise = None
    if cal.chain_gain_db is not None and any(p[1] > 0 for p in cal.stamp_all):
        cal_noise = cal.level_dbfs + cal.chain_gain_db
    operative = None
    if operative_rms is not None and operative_rms > 0:
        operative = 20 * math.log10(math.sqrt(2) * operative_rms)
    if cal_noise is None and operative is None:
        return None
    out = []
    for i in range(len(s.levels_db)):
        row = []
        for j, f in enumerate(s.frequencies):
            t = s.thd[i][j]
            h1 = s.harmonic_db[1][i][j]
            if t is None or t <= 0 or h1 is None:
                row.append(None)
                continue
            delivered = s.levels_db[i] + h1
            candidates = []
            if cal_noise is not None:
                stamp = pooled_floor_db(cal.stamp_all, f, median_points)
                if stamp is not None:
                    candidates.append(stamp + max(0.0, cal_noise - delivered))
            if operative is not None:
                candidates.append(operative - delivered)
            if not candidates:
                row.append(None)
                continue
            row.append(20 * math.log10(t) - max(candidates))
        out.append(row)
    return out


def residue_db(frequencies: List[float], fs: float, band: Tuple[float, float], seconds: float,
               m: dict, drive_dbfs: float, tail: float) -> List[Optional[float]]:
    """One sweep length's analyzer residue: the plan's own sweep at the
    standard drive, handed back as its own capture with the tail's silence,
    through chapter one's analyzer at the journey's configuration — the THD
    of nothing, per column, in dB re the fundamental."""
    hdm = journey_manifest(m, frequencies[0])
    sweep = hd.Sweep.from_manifest(hdm, f1=frequencies[0], f2=frequencies[-1], requested_duration=seconds,
                                   fs=fs, amplitude=10 ** (drive_dbfs / 20))
    capture = np.concatenate([sweep.samples(), np.zeros(int(tail * fs))])
    analysis = hd.analyze(capture, sweep, hdm)
    out = []
    for f in frequencies:
        t = thd_at(analysis, f, band)
        out.append(None if t is None else 20 * math.log10(max(t, 1e-300)))
    return out


def worst_residue(per_length: Dict[float, List[Optional[float]]], n: int) -> List[Optional[float]]:
    worst: List[Optional[float]] = [None] * n
    for seconds in sorted(per_length):
        one = per_length[seconds]
        for j in range(n):
            if worst[j] is None:
                worst[j] = one[j]
            elif one[j] is not None:
                worst[j] = max(worst[j], one[j])
    return worst


def composed_margins(s: Summary, noise, residue: Optional[List[Optional[float]]]):
    if noise is None:
        return None
    if residue is None:
        return noise
    out = []
    for i in range(len(s.levels_db)):
        row = []
        for j in range(len(s.frequencies)):
            nm = noise[i][j]
            t = s.thd[i][j]
            if nm is None or t is None or t <= 0:
                row.append(nm)
                continue
            r = residue[j]
            row.append(nm if r is None else min(nm, 20 * math.log10(t) - r))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# The tiles (manifest ``gainMap.peak`` / ``gainMap.cleanup``)


def flags(thd, excluded: List[bool], margins, minimum_margin: float):
    clear = [[(not excluded[j]) and thd[i][j] is not None and (margins is None or (margins[i][j] if margins[i][j] is not None else -math.inf) >= minimum_margin)
              for j in range(len(excluded))] for i in range(len(thd))]
    corroborated = []
    for i in range(len(clear)):
        row = []
        for j in range(len(excluded)):
            if not clear[i][j]:
                row.append(False)
            elif margins is None:
                row.append(True)
            else:
                row.append(any(0 <= j + dj < len(excluded) and clear[i][j + dj] for dj in (-1, 1)))
        corroborated.append(row)
    return clear, corroborated


def peak_reading(thd, excluded, margins, verdict: Verdict, minimum_margin: float):
    """``PeakDistortionReading``: (state, value) — the verdict outranks both
    states; else the maximum over corroborated clear cells, else the bound
    over every unmasked measured cell."""
    if verdict.absent:
        return ("fundamental_absent", verdict.median_depth)
    _, corroborated = flags(thd, excluded, margins, minimum_margin)
    clearest = None
    bound = None
    for i in range(len(thd)):
        for j in range(len(excluded)):
            if excluded[j] or thd[i][j] is None:
                continue
            t = thd[i][j]
            bound = t if bound is None else max(bound, t)
            if corroborated[i][j]:
                clearest = t if clearest is None else max(clearest, t)
    if clearest is not None:
        return ("peak", clearest * 100)
    if bound is not None:
        return ("at_floor", bound * 100)
    return ("none", None)


def cleanup_reading(curve: List[Tuple[float, float]], threshold: float):
    """``CleanupReading(thdVersusLevel:)``: (state, level) — the crossing
    interpolated between the two measured levels that straddle it."""
    if not curve:
        return ("none", None)
    if curve[0][1] >= threshold:
        return ("never_clean", None)
    for i in range(1, len(curve)):
        if curve[i][1] >= threshold:
            a, b = curve[i - 1], curve[i]
            t = (threshold - a[1]) / max(b[1] - a[1], 1e-12)
            return ("cleans_up", a[0] + t * (b[0] - a[0]))
    return ("always_clean", None)


def column_curve(s: Summary, j: int) -> List[Tuple[float, float]]:
    return [(s.levels_db[i], s.thd[i][j]) for i in range(len(s.levels_db)) if s.thd[i][j] is not None]


def nearest_column(frequencies: List[float], f: float) -> Optional[int]:
    """``cleanupColumn(nearFrequency:)``: nearest in log frequency, the first
    on a tie."""
    if not frequencies:
        return None
    return min(range(len(frequencies)), key=lambda j: abs(math.log(frequencies[j] / f)))


def summaries_cleanup(s: Summary, reference_hz: float, threshold: float, verdict: Verdict):
    """``extractJourneyCleanup``: the column nearest the reference in LINEAR
    frequency, at least three levels, the same interpolation, confidence
    0.7; nothing when the map's fundamental is absent (the extractor's gate)."""
    if verdict.absent or not s.frequencies or len(s.levels_db) < 3:
        return ("none", None, None)
    j = min(range(len(s.frequencies)), key=lambda j: abs(s.frequencies[j] - reference_hz))
    curve = column_curve(s, j)
    if len(curve) < 3:
        return ("none", None, None)
    if curve[0][1] >= threshold:
        return ("never_clean", None, None)
    if curve[-1][1] < threshold:
        return ("always_clean", None, None)
    for i in range(1, len(curve)):
        if curve[i][1] >= threshold:
            a, b = curve[i - 1], curve[i]
            t = (threshold - a[1]) / max(b[1] - a[1], 1e-12)
            return ("cleans_up", a[0] + t * (b[0] - a[0]), 0.7)
    return ("none", None, None)


def residue_drive_dbfs(gm: dict) -> float:
    """The residue capture's drive — a literal inside the kernel, carried by
    the manifest's rule string and read from there (the HD writer's
    minimum-half-width precedent)."""
    m = re.search(r"at ([\u2212-]?\d+(?:\.\d+)?) dBFS", gm["floor"]["residueRule"])
    return float(m.group(1).replace("\u2212", "-"))


def summaries_reference_hz(gm: dict) -> float:
    """The summaries' reference note — a default-argument literal, read from
    the rule string."""
    return float(re.search(r"nearest (\d+(?:\.\d+)?) Hz", gm["cleanup"]["summariesRule"]).group(1))


# ---------------------------------------------------------------------------
# The read-time half, as one object (the stored-record reader's own reads)


@dataclass
class Reading:
    bottom: List[bool]
    top: List[bool]
    truncated: List[bool]
    excluded: List[bool]
    presence: List[List[str]]
    verdict: Verdict
    rig_margins: Optional[List[List[Optional[float]]]]
    residue_per_length: Dict[float, List[Optional[float]]]
    residue: List[Optional[float]]
    margins: Optional[List[List[Optional[float]]]]
    clear: List[List[bool]]
    corroborated: List[List[bool]]
    peak: Tuple[str, Optional[float]]
    tile_column: Optional[int]
    tile: Tuple[str, Optional[float]]
    columns: List[Tuple[str, Optional[float]]]
    summaries: Tuple[str, Optional[float], Optional[float]]


def read(s: Summary, cal: Optional[Calibration], operative_rms: Optional[float], m: dict,
         residue_per_length: Optional[Dict[float, List[Optional[float]]]] = None) -> Reading:
    gm = m["gainMap"]
    separation = float(m["harmonicDistortion"]["fundamentalPresence"]["analyzerSeparationDB"])
    ratio = float(gm["masks"]["bottomEdgeGuardRatio"])
    minimum_margin = float(gm["peak"]["minimumMarginDB"])
    threshold = float(gm["cleanup"]["threshold"])
    bottom, top = edge_columns(s, ratio)
    truncated = truncated_columns(s)
    excluded = [truncated[j] or bottom[j] or top[j] for j in range(len(s.frequencies))]
    cells = presence_cells(s, separation)
    depths = presence_depths(s)
    verdict = presence_verdict(s, cells, depths, bottom, top)
    rig = None if cal is None else rig_noise_margins(s, cal, operative_rms, int(gm["floor"]["stampMedianPoints"]))
    if residue_per_length is None:
        residue_per_length = {sec: residue_db(s.frequencies, s.fs, s.band, sec, m, residue_drive_dbfs(gm), float(gm["plan"]["tailS"]))
                              for sec in gm["plan"]["sweepDurationChoicesS"]}
    residue = worst_residue(residue_per_length, len(s.frequencies))
    margins = composed_margins(s, rig, residue)
    tile_cells = [[None if cells[i][j] == "absent" else s.thd[i][j] for j in range(len(s.frequencies))]
                  for i in range(len(s.levels_db))]
    clear, corroborated = flags(tile_cells, excluded, margins, minimum_margin)
    peak = peak_reading(tile_cells, excluded, margins, verdict, minimum_margin)
    tile_column = nearest_column(s.frequencies, float(gm["cleanup"]["tileFrequencyHz"]))
    tile = ("none", None) if verdict.absent or tile_column is None else cleanup_reading(column_curve(s, tile_column), threshold)
    columns = [cleanup_reading(column_curve(s, j), threshold) for j in range(len(s.frequencies))]
    return Reading(bottom, top, truncated, excluded, cells, verdict, rig, residue_per_length, residue, margins,
                   clear, corroborated, peak, tile_column, tile, columns,
                   summaries_cleanup(s, summaries_reference_hz(gm), threshold, verdict))


# ---------------------------------------------------------------------------
# The truth (manifest ``gainMap.synthesis``)


def ladder(nl, amplitude: float, orders: int, points: int) -> List[float]:
    """The memoryless device's closed-form ladder at ``amplitude``:
    |Fourier_k| / amplitude on ``points`` equispaced phases (the trapezoid
    rule, exact for the periodic integrand's resolved orders)."""
    theta = 2 * np.pi * np.arange(points) / points
    y = nl(amplitude * np.sin(theta))
    out = []
    for k in range(1, orders + 1):
        a = float(np.sum(y * np.sin(k * theta)))
        b = float(np.sum(y * np.cos(k * theta)))
        out.append(math.hypot(a, b) * (2 / points) / amplitude)
    return out


def truth_summary(plan: Plan, s: Summary, m: dict, hdm: dict) -> Summary:
    """The truth grid: per (level, column) the ladder at the level's drive
    after any pre-filter, scaled by the pre-filter's gain at f0, the
    post-filter's at k·f0 and the chain gain; nil at or above Nyquist or
    where the ladder is zero; THD as the definition applied to it."""
    points = int(m["gainMap"]["synthesis"]["quadraturePoints"])
    fs = plan.plan.fs
    nyquist = fs / 2
    g = plan.chain_gain
    orders = s.orders
    kmax = max(orders) if orders else 1
    harm: Dict[int, List[List[Optional[float]]]] = {k: [[None] * len(s.frequencies) for _ in s.levels_db] for k in orders}
    thd: List[List[Optional[float]]] = [[None] * len(s.frequencies) for _ in s.levels_db]
    cache: Dict[float, List[float]] = {}
    device = plan.source.device
    nl = None if device is None else tc.nonlinearity(device.kind, device.params)
    pre = None if device is None or device.pre is None else device.pre.biquad(fs)
    post = None if device is None or device.post is None else device.post.biquad(fs)
    for i, level_db in enumerate(s.levels_db):
        amplitude = 10 ** (level_db / 20)
        sweep = plan.plan.sweep(i, hdm)
        for j, f0 in enumerate(s.frequencies):
            if plan.source.kind == "phantom":
                lad = plan.source.ladder(i)
                truth = [abs(lad[k - 1]) if k <= len(lad) else 0.0 for k in range(1, kmax + 1)]
            else:
                pre_gain = 1.0 if pre is None else abs(pre.response(f0))
                drive = amplitude * pre_gain
                if drive not in cache:
                    cache[drive] = ladder(nl, drive, kmax, points)
                truth = [t * pre_gain for t in cache[drive]]
            total = 0.0
            h1 = None
            for k in orders:
                fk = f0 * k
                t = truth[k - 1] if k <= len(truth) else 0.0
                if post is not None:
                    t *= abs(post.response(fk))
                t *= g
                harm[k][i][j] = 20 * math.log10(t) if (t > 0 and fk < nyquist) else None
                if k == 1:
                    h1 = t if t > 0 else None
                if k >= 2 and s.band[0] <= fk <= s.band[1] and hd.is_valid(sweep, k, f0) and fk < nyquist:
                    total += t * t
            thd[i][j] = None if h1 is None else math.sqrt(total) / h1
    return Summary(list(s.frequencies), list(s.levels_db), list(orders), thd, harm, fs, s.band)


# ---------------------------------------------------------------------------
# The run and the table


@dataclass
class Result:
    plan: Plan
    cal: Calibration
    summary: Summary
    reading: Reading
    truth: Summary
    truth_reading: Reading
    actual_duration: float
    rate_constant: float
    sweep_samples: int


def run(plan: Plan, m: dict) -> Result:
    gm = m["gainMap"]
    synthesis = m["harmonicDistortion"]["synthesis"]
    increment = int(synthesis["noiseGeneratorIncrement"], 16)
    hdm = journey_manifest(m, plan.plan.f1)
    cal = calibrate(plan, m, increment)
    analyses = []
    sweep0 = None
    for i in range(len(plan.plan.levels_db)):
        sweep, out = rendered(plan, i, hdm, synthesis)
        sweep0 = sweep0 or sweep
        captured = through_loop(out, plan, capture_seed(plan, i, increment), True, increment)
        analyses.append(hd.analyze(plan.plan.aligned(captured, sweep, cal.latency), sweep, hdm))
    band = (gm["summary"]["band"]["lowHz"], gm["summary"]["band"]["highHz"])
    frequencies = plan.plan.grid(int(gm["plan"]["exportFrequencyCount"]))
    s = summarize(analyses, plan.plan.levels_db, frequencies, band)
    residues = {sec: residue_db(frequencies, plan.plan.fs, band, sec, m, residue_drive_dbfs(gm), plan.plan.tail)
                for sec in gm["plan"]["sweepDurationChoicesS"]}
    reading = read(s, cal, plan.operative_rms, m, residues)
    truth = truth_summary(plan, s, m, hdm)
    truth_reading = read(truth, cal, plan.operative_rms, m, residues)
    return Result(plan, cal, s, reading, truth, truth_reading, sweep0.duration, sweep0.rate_constant, sweep0.sample_count)


def presence_label(x: str) -> str:
    return x


def peak_fields(peak) -> str:
    state, value = peak
    if state == "peak":
        return f"state=peak peak_pct={fmt(value)} bound_pct=nan depth_db=nan"
    if state == "at_floor":
        return f"state=at_floor peak_pct=nan bound_pct={fmt(value)} depth_db=nan"
    if state == "fundamental_absent":
        return f"state=fundamental_absent peak_pct=nan bound_pct=nan depth_db={fmt(value)}"
    return "state=none peak_pct=nan bound_pct=nan depth_db=nan"


def cleanup_fields(reading) -> str:
    state, value = reading
    return f"state={state} level_dbfs={fmt(value)}"


def cleanup_behavior_fields(reading) -> str:
    state, value, confidence = reading
    return f"state={state} level_dbfs={fmt(value)} confidence={fmt(confidence)}"


def verdict_line(v: Verdict) -> str:
    return (f"fundamental verdict: absent={fmt(v.absent)} absent_fraction={fmt(v.fraction)} "
            f"median_depth_db={fmt(v.median_depth)} evaluated={v.evaluated}")


def write_tsv(r: Result, m: dict, noise_db_text: str, out) -> None:
    gm = m["gainMap"]
    p = r.plan.plan
    s = r.summary
    cal = r.cal
    increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
    choices = [float(x) for x in gm["plan"]["sweepDurationChoicesS"]]
    out.write(f"# source: {r.plan.source.label}\n")
    out.write(f"# plan: levels={len(p.levels_db)} level_dbfs=[{','.join(fmt(l) for l in p.levels_db)}] "
              f"f1={fmt(p.f1)} f2={fmt(p.f2)} duration_s={fmt(p.duration)} "
              f"actual_duration_s={fmt(r.actual_duration)} L={fmt(r.rate_constant)} fs={fmt(p.fs)} "
              f"preroll_s={fmt(p.preroll)} tail_s={fmt(p.tail)} preroll_samples={p.preroll_samples} tail_samples={p.tail_samples} "
              f"sweep_samples={r.sweep_samples} harmonic_count={int(gm['plan']['harmonicCount'])} "
              f"response_fft_length={int(gm['plan']['responseFFTLength'])} "
              f"max_window_half_width_s={fmt(gm['plan']['maxWindowHalfWidthS'])} "
              f"export_frequency_count={int(gm['plan']['exportFrequencyCount'])} "
              f"sweep_duration_choices=[{','.join(fmt(c) for c in choices)}] "
              f"band_hz={fmt(s.band[0])}-{fmt(s.band[1])}\n")
    out.write(f"# grid: f_hz=[{','.join(fmt(f) for f in s.frequencies)}] orders=[{','.join(str(k) for k in s.orders)}]\n")
    out.write(f"# loop: latency_samples={r.plan.latency} chain_gain_db={fmt(r.plan.chain_gain_db)} chain_gain={fmt(r.plan.chain_gain)} "
              f"noise_rms_dbfs={noise_db_text} seed={r.plan.seed} "
              f"calibration_seed={capture_seed(r.plan, None, increment)} "
              f"level_seeds=[{','.join(str(capture_seed(r.plan, i, increment)) for i in range(len(p.levels_db)))}] "
              f"calibration_noisy={fmt(r.plan.operative_rms is None and r.plan.noise_rms is not None)}\n")
    g = gm["synthesis"]
    out.write(f"# calibration: f1={fmt(cal.sweep.f1)} f2={fmt(cal.sweep.f2)} duration_s={fmt(cal.sweep.duration)} "
              f"L={fmt(cal.sweep.rate_constant)} amplitude={fmt(cal.sweep.amplitude)} level_dbfs={fmt(cal.level_dbfs)} "
              f"preroll_samples={int(g['calibrationPrerollS'] * p.fs)} tail_samples={int(g['calibrationTailS'] * p.fs)} "
              f"latency_samples={cal.latency} fractional_latency=nan peak_quality=nan "
              f"chain_gain_db={fmt(cal.chain_gain_db)} resolved_chain_gain_db={fmt(cal.chain_gain_db)} "
              f"delivered_dbfs={fmt(cal.delivered_dbfs)} stamp_points={len(cal.stamp_all)} "
              f"usable_stamp_points={len(cal.stamp)} "
              f"stamp_median_points={int(gm['floor']['stampMedianPoints'])} analyzed_sweep_count={int(gm['floor']['calibrationAnalyzedSweepCount'])}\n")
    out.write("# stamp: " + " ".join(f"{fmt(f)}:{fmt(t)}" for f, t in cal.stamp_all) + "\n")
    if r.plan.operative_rms is not None and r.plan.operative_rms > 0:
        rms = r.plan.operative_rms
        out.write(f"# precheck: operative_rms={fmt(rms)} operative_dbfs={fmt(20 * math.log10(rms))} "
                  f"absolute_dbfs={fmt(20 * math.log10(math.sqrt(2) * rms))} in_signal_governs=0\n")
    else:
        out.write("# precheck: none\n")
    rd = r.reading
    out.write(f"# masks: bottom_edge=[{','.join(fmt(b) for b in rd.bottom)}] top_edge=[{','.join(fmt(b) for b in rd.top)}] "
              f"truncated=[{','.join(fmt(b) for b in rd.truncated)}] bottom_edge_guard_ratio={fmt(gm['masks']['bottomEdgeGuardRatio'])}\n")
    for sec in choices:
        res = rd.residue_per_length[sec]
        out.write(f"# residue length_s={fmt(sec)}: " + " ".join(f"{j}:{fmt(v)}" for j, v in enumerate(res)) + "\n")
    out.write(f"# analyzer residue (dB re fundamental, worst over sweep lengths {'/'.join(fmt(c) for c in choices)} s; "
              f"stamp median {int(gm['floor']['stampMedianPoints'])} points): "
              + " ".join(f"{j}:{fmt(v)}" for j, v in enumerate(rd.residue)) + "\n")
    for label, reading in (("", r.reading), ("truth ", r.truth_reading)):
        out.write(f"# {label}" + verdict_line(reading.verdict) + "\n")
        out.write(f"# {label}peak tile: {peak_fields(reading.peak)} margins_derivable={fmt(reading.margins is not None)} "
                  f"minimum_margin_db={fmt(gm['peak']['minimumMarginDB'])}\n")
        col = reading.tile_column
        out.write(f"# {label}cleanup tile (nearest column to {fmt(float(gm["cleanup"]["tileFrequencyHz"]))} Hz): "
                  f"{cleanup_fields(reading.tile)} column={'nan' if col is None else col} "
                  f"column_hz={fmt(None if col is None else s.frequencies[col])}"
                  + (" (not stated: fundamental absent, #154)" if reading.verdict.absent else "") + "\n")
        for j, f in enumerate(s.frequencies):
            out.write(f"# {label}column {j} f_hz={fmt(f)} {cleanup_fields(reading.columns[j])}\n")
        out.write(f"# {label}summaries cleanup (FeatureExtractor.extract(journey:)): {cleanup_behavior_fields(reading.summaries)}\n")
    orders = s.orders
    header = (["level_index", "level_dbfs", "freq_index", "freq_hz", "thd", "thd_pct"] + [f"h{k}_db" for k in orders]
              + ["truncated", "bottom_edge", "top_edge", "presence", "rig_margin_db", "residue_db", "margin_db", "clear", "corroborated",
                 "truth_thd"] + [f"truth_h{k}_db" for k in orders]
              + ["truth_presence", "truth_rig_margin_db", "truth_margin_db", "truth_clear", "truth_corroborated"])
    out.write("\t".join(header) + "\n")
    t = r.truth
    tr = r.truth_reading
    for i, level in enumerate(s.levels_db):
        for j, f in enumerate(s.frequencies):
            thd = s.thd[i][j]
            cols = [str(i), fmt(level), str(j), fmt(f), fmt(thd), fmt(None if thd is None else thd * 100)]
            cols += [fmt(s.harmonic_db[k][i][j]) for k in orders]
            cols += [fmt(rd.truncated[j]), fmt(rd.bottom[j]), fmt(rd.top[j]), rd.presence[i][j],
                     fmt(None if rd.rig_margins is None else rd.rig_margins[i][j]), fmt(rd.residue[j]),
                     fmt(None if rd.margins is None else rd.margins[i][j]), fmt(rd.clear[i][j]), fmt(rd.corroborated[i][j]),
                     fmt(t.thd[i][j])]
            cols += [fmt(t.harmonic_db[k][i][j]) for k in orders]
            cols += [tr.presence[i][j], fmt(None if tr.rig_margins is None else tr.rig_margins[i][j]),
                     fmt(None if tr.margins is None else tr.margins[i][j]), fmt(tr.clear[i][j]), fmt(tr.corroborated[i][j])]
            out.write("\t".join(cols) + "\n")


# ---------------------------------------------------------------------------
# Command line — the options of `analysisdump journey-synth`


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--source", required=True,
                   choices=["identity", "tanh", "hardclip", "poly", "asymmetric", "parametric", "phantom"])
    p.add_argument("--gain", type=float)
    p.add_argument("--threshold", type=float)
    p.add_argument("--a2", type=float, default=0.0)
    p.add_argument("--a3", type=float, default=0.0)
    p.add_argument("--negative-scale", type=float, default=0.5)
    p.add_argument("--knee", type=float, default=0.5)
    p.add_argument("--asymmetry", type=float, default=0.0)
    p.add_argument("--amps")
    p.add_argument("--amps-per-level")
    p.add_argument("--pre", choices=["lowpass", "highpass"])
    p.add_argument("--pre-hz", type=float)
    p.add_argument("--pre-q", type=float)
    p.add_argument("--post", choices=["lowpass", "highpass"])
    p.add_argument("--post-hz", type=float)
    p.add_argument("--post-q", type=float)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--floor-db", type=float)
    p.add_argument("--ceiling-db", type=float)
    p.add_argument("--levels", type=int)
    p.add_argument("--plugin-window", action="store_true")
    p.add_argument("--duration", type=float)
    p.add_argument("--rate", type=float)
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.add_argument("--latency-samples", type=int, default=0)
    p.add_argument("--chain-gain-db", type=float, default=0.0)
    p.add_argument("--noise-db", type=float)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--operative-floor-rms", type=float)
    p.add_argument("--cal-level-db", type=float)
    p.add_argument("--out")
    return p


def plan_from_args(args, m: dict) -> Plan:
    gm = m["gainMap"]
    probe, plan = gm["probe"], gm["plan"]
    fs = args.rate if args.rate is not None else float(plan["sampleRateHz"])
    plugin = args.plugin_window
    floor = args.floor_db if args.floor_db is not None else float(probe["pluginFloorDBFS"] if plugin else probe["floorDBFS"])
    ceiling = args.ceiling_db if args.ceiling_db is not None else float(probe["pluginCeilingDBFS"] if plugin else probe["ceilingDBFS"])
    count = args.levels if args.levels is not None else int(probe["defaultLevels"])
    jp = JourneyPlan(
        f1=args.start if args.start is not None else float(plan["startHz"]),
        f2=args.end if args.end is not None else float(plan["endHz"]),
        duration=args.duration if args.duration is not None else float(plan["sweepDurationS"]),
        fs=fs, levels_db=levels(floor, ceiling, count),
        preroll=float(plan["prerollS"]), tail=float(plan["tailS"]))
    default_q = float(m["transferCurve"]["biquad"]["defaultQ"])

    def filt(kind, hz, q):
        if kind is None:
            return None
        return tc.Filter("lowPass" if kind == "lowpass" else "highPass", hz, default_q if q is None else q)

    if args.source == "phantom":
        if args.amps_per_level:
            ladders = [[float(a) for a in l.split(",")] for l in args.amps_per_level.split(";")]
        elif args.amps:
            ladders = [[float(a) for a in args.amps.split(",")]]
        else:
            raise SystemExit("--source phantom needs --amps or --amps-per-level")
        source = Source("phantom", None, ladders)
    else:
        threshold_default = 0.3 if args.source == "parametric" else 0.1
        gain_default = 3.0 if args.source == "asymmetric" else 4.0
        params = dict(gain=gain_default if args.gain is None else args.gain,
                      threshold=threshold_default if args.threshold is None else args.threshold,
                      a2=args.a2, a3=args.a3, negative_scale=args.negative_scale)
        if args.source == "parametric":
            params = dict(threshold=params["threshold"], knee=args.knee, asymmetry=args.asymmetry)
        device = tc.Device(args.source, params, filt(args.pre, args.pre_hz, args.pre_q),
                           filt(args.post, args.post_hz, args.post_q), args.invert)
        source = Source(args.source, device, None)
    noise = None if args.noise_db is None else 10 ** (args.noise_db / 20)
    return Plan(source, jp, args.latency_samples, args.chain_gain_db, noise, args.seed, args.operative_floor_rms,
                float(gm["floor"]["calibrationLevelDBFS"]) if args.cal_level_db is None else args.cal_level_db)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    m = load_manifest(args.manifest)
    plan = plan_from_args(args, m)
    result = run(plan, m)
    noise_text = "none" if args.noise_db is None else fmt(args.noise_db)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            write_tsv(result, m, noise_text, f)
    else:
        write_tsv(result, m, noise_text, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
