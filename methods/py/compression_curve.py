#!/usr/bin/env python3
"""Compression — an independent reimplementation of PedalScope's stepped-tone
level-response measurement (the "touch response" curve), written from the
methods manifest (``Docs/Methods/generated/manifest.json``, the
``compression`` object) and the technical chapter's own equations, NOT by
transliterating the Swift.

This instrument is NOT the sweep: it has no deconvolution and no extraction
window. This module IMPORTS ``harmonic_distortion.py`` for the device
family, the noise generator and the seed sequence, and
``transfer_curve.py`` for the biquad filters and the parametric clipper —
and adds everything the compression measurement is: the probe grid with its
fine window and cap, the stepped tone with its cycle snap and ramps, the
app's stimulus assembly (a mirror the manifest states as such), the
pre-roll noise stamp, the latency cut, the one-bin Hann estimator, the
per-step gate, the harmonic sum under its two tops, the sort, the curve;
then the read-time layer — the incremental slopes, the hinge fit with its
1025-candidate sweep, ridge, no-break test, unity guard, bound zone and 5 %
band; the cleanup's three states; the √2 noise bound; the null-run
amplitude interpolation and its span rule; the stated floor; the maximum;
the classes and runs; the source label; the summed presence reading and
majority verdict; and the summaries' four features.

It produces the same TSV ``analysisdump compression-synth`` produces (same
header lines, same column set, same conventions), so one comparator serves
both, and ``test_parity_compression.py`` pins the two against each other
and against the closed-form ladder.

Conventions, repeated from the manifest because they decide what a number
means:

* The curve's INPUT is the tone amplitude the device is driven with (dBFS
  = 20·log10 of it); the OUTPUT is the fundamental's amplitude at the probe
  note as the one-bin estimator reads it — the loop's gain is IN it.
* THD is a ratio of AMPLITUDES over the declared band (THD, not THD+N).
* The noise stamp is the capture's own pre-roll rms; the compression floor
  reads NO calibration stamp.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import harmonic_distortion as hd
import transfer_curve as tc

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = hd.DEFAULT_MANIFEST
fmt = hd.fmt
swift_round = hd.swift_round


def load_manifest(path: str = DEFAULT_MANIFEST) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# The probe grid (manifest ``compression.probe``)


def levels_db(min_db: float, max_db: float, steps: int, fine_step_db: float, maximum_fine_points: int,
              fine_range: Optional[Tuple[float, float]] = None) -> List[float]:
    """``CompressionProbe.levelsDB``: the uniform lattice, a fine window merged
    (clamped inside the sweep, spaced at the fine step, widened to honour the
    cap, near-duplicates dropped), sorted ascending."""
    assert steps >= 2 and max_db > min_db
    levels = [min_db + (max_db - min_db) * i / (steps - 1) for i in range(steps)]
    if fine_range is None:
        return levels
    lo = max(fine_range[0], min_db)
    hi = min(fine_range[1], max_db)
    if hi <= lo:
        return levels
    requested = int((hi - lo) / fine_step_db) + 1
    count = min(requested, maximum_fine_points)
    if count < 2:
        return levels
    fine = [lo + (hi - lo) * j / (count - 1) for j in range(count)]
    for level in fine:
        if not any(abs(x - level) < fine_step_db / 10 for x in levels):
            levels.append(level)
    return sorted(levels)


def log_spaced_amplitudes(min_db: float, max_db: float, steps: int) -> List[float]:
    """``SteppedToneSignal.logSpacedAmplitudes``: Simulation Mode's ladder."""
    return [10 ** ((min_db + (max_db - min_db) * i / (steps - 1)) / 20) for i in range(steps)]


# ---------------------------------------------------------------------------
# The stepped tone (manifest ``compression.stimulus``)


@dataclass(frozen=True)
class SteppedTone:
    frequency: float
    fs: float
    amplitudes: Tuple[float, ...]
    settle_samples: int
    measure_samples: int
    ramp_samples: int

    @classmethod
    def build(cls, frequency: float, fs: float, amplitudes: Sequence[float],
              settle: float, measure: float, ramp: float) -> "SteppedTone":
        cycles = max(4, swift_round(measure * frequency))
        measure_samples = swift_round(cycles / frequency * fs)
        settle_samples = int(settle * fs)
        ramp_samples = min(int(ramp * fs), settle_samples // 2)
        return cls(frequency, fs, tuple(amplitudes), settle_samples, measure_samples, ramp_samples)

    @property
    def step_samples(self) -> int:
        return self.settle_samples + self.measure_samples

    @property
    def sample_count(self) -> int:
        return len(self.amplitudes) * self.step_samples

    def measure_range(self, step: int) -> Tuple[int, int]:
        start = step * self.step_samples + self.settle_samples
        return start, start + self.measure_samples

    def envelope(self) -> np.ndarray:
        """A[n]: the raised-cosine ramp from the previous step's amplitude
        over the first ramp samples of each step, then the hold."""
        out = np.zeros(self.sample_count)
        previous = 0.0
        i = np.arange(self.step_samples)
        ramp = i < self.ramp_samples
        t = i[ramp] / self.ramp_samples if self.ramp_samples > 0 else np.zeros(0)
        for step, target in enumerate(self.amplitudes):
            base = step * self.step_samples
            a = np.full(self.step_samples, target)
            a[ramp] = previous + (target - previous) * 0.5 * (1 - np.cos(np.pi * t))
            out[base:base + self.step_samples] = a
            previous = target
        return out

    def fade(self, out: np.ndarray) -> np.ndarray:
        """The final fade to zero over the last ramp samples of the whole tone."""
        count = len(out)
        start = max(0, count - self.ramp_samples)
        i = np.arange(start, count)
        out[start:] *= 0.5 * (1 - np.cos(np.pi * (count - 1 - i) / self.ramp_samples))
        return out

    def samples(self) -> np.ndarray:
        w = 2 * np.pi * self.frequency / self.fs
        n = np.arange(self.sample_count)
        return self.fade(self.envelope() * np.sin(w * n))

    def phantom(self, ladders: List[List[float]]) -> np.ndarray:
        """Σ_k m_k·A[n]·sin(k·ω·n) on the tone's own envelope, orders at or
        above Nyquist dropped; one ladder for all steps or one per step."""
        w = 2 * np.pi * self.frequency / self.fs
        nyquist = self.fs / 2
        n = np.arange(self.sample_count)
        env = self.envelope()
        out = np.zeros(self.sample_count)
        for step in range(len(self.amplitudes)):
            amps = ladders[0] if len(ladders) == 1 else ladders[step]
            base = step * self.step_samples
            sl = slice(base, base + self.step_samples)
            s = np.zeros(self.step_samples)
            for index, m in enumerate(amps):
                k = index + 1
                if m == 0 or k * self.frequency >= nyquist:
                    continue
                s += m * np.sin(k * w * n[sl])
            out[sl] = env[sl] * s
        return self.fade(out)


# ---------------------------------------------------------------------------
# The device, the assembly, the loop (manifest ``compression.assembly`` / ``synthesis``)


@dataclass
class Source:
    kind: str                       # a nonlinearity kind, or "phantom"
    device: Optional[tc.Device]
    ladders: Optional[List[List[float]]]

    @property
    def label(self) -> str:
        if self.kind == "phantom":
            return "phantom(" + ";".join("[" + ",".join(fmt(a) for a in l) + "]" for l in self.ladders) + ")"
        return tc.device_label(self.device.kind, self.device.params)


@dataclass
class Plan:
    source: Source
    levels_db: List[float]
    frequency: float
    fs: float
    settle: Optional[float]
    measure: Optional[float]
    ramp: Optional[float]
    assembly: str                   # "app" | "simulation"
    latency: int = 0
    latency_error: int = 0
    chain_gain_db: float = 0.0
    noise_rms: Optional[float] = None
    seed: int = 1
    operative_rms: Optional[float] = None
    null_run: bool = False
    loop_cubic: Optional[float] = None

    @property
    def chain_gain(self) -> float:
        return 10 ** (self.chain_gain_db / 20)


def tone_for(plan: Plan, cm: dict) -> SteppedTone:
    """The tone at the plan's grid with the manifest's default-argument
    durations unless the plan overrides them."""
    st = cm["stimulus"]
    # The defaults are recorded as delivered counts and as the rule's
    # literals; the rule's figures are what a reimplementation reads.
    settle = st["settleS"] if plan.settle is None else plan.settle
    ramp = st["rampS"] if plan.ramp is None else plan.ramp
    measure = default_measure_s(cm) if plan.measure is None else plan.measure
    return SteppedTone.build(plan.frequency, plan.fs, [10 ** (l / 20) for l in plan.levels_db], settle, measure, ramp)


def default_measure_s(cm: dict) -> float:
    """The measure duration is a default-argument literal the manifest
    carries only in its rule string (the delivered count is a snapped cycle
    count, so it cannot be read back); read from there, and checked: the
    literal must reproduce the manifest's delivered measureSamples."""
    import re
    m = re.search(r"measureDuration ([0-9.]+) s", cm["stimulus"]["durationsRule"])
    value = float(m.group(1))
    st = cm["stimulus"]
    check = SteppedTone.build(st["frequencyHz"], st["sampleRateHz"], [1], st["settleS"], value, st["rampS"])
    assert check.measure_samples == st["measureSamples"] and check.settle_samples == st["settleSamples"] \
        and check.ramp_samples == st["rampSamples"], "the rule's durations do not reproduce the delivered counts"
    return value


def preroll_samples(plan: Plan, cm: dict) -> int:
    return int(cm["assembly"]["prerollS"] * plan.fs) if plan.assembly == "app" else 0


def tail_samples(plan: Plan, cm: dict) -> int:
    return int(cm["assembly"]["tailS"] * plan.fs) if plan.assembly == "app" else 0


def analyzed_latency(plan: Plan, cm: dict) -> int:
    return preroll_samples(plan, cm) + plan.latency + plan.latency_error


def stimulus(plan: Plan, tone: SteppedTone, cm: dict) -> np.ndarray:
    return np.concatenate([np.zeros(preroll_samples(plan, cm)), tone.samples(), np.zeros(tail_samples(plan, cm))])


def rendered(plan: Plan, tone: SteppedTone, cm: dict) -> np.ndarray:
    if plan.source.kind == "phantom":
        return np.concatenate([np.zeros(preroll_samples(plan, cm)), tone.phantom(plan.source.ladders),
                               np.zeros(tail_samples(plan, cm))])
    return plan.source.device.render(stimulus(plan, tone, cm), plan.fs)


def capture_seed(plan: Plan, null_run: bool, increment: int) -> int:
    return hd.repeat_seed(plan.seed, 1 if null_run else 0, increment)


def through_loop(x: np.ndarray, plan: Plan, seed: int, increment: int) -> np.ndarray:
    captured = np.zeros_like(x)
    d = plan.latency
    if d < len(x):
        captured[d:] = x[:len(x) - d]
    if plan.noise_rms is not None:
        captured = captured + hd.gaussian_noise(len(captured), plan.noise_rms, seed, increment)
    if plan.chain_gain != 1:
        captured = captured * plan.chain_gain
    if plan.loop_cubic is not None:
        captured = captured + plan.loop_cubic * captured * captured * captured
    return captured


def noise_stamp(plan: Plan, captured: np.ndarray, cm: dict) -> Optional[float]:
    """The app's stamp: the rms of the first pre-roll samples; none under
    the simulation assembly."""
    if plan.assembly != "app":
        return None
    n = min(preroll_samples(plan, cm), len(captured))
    if n == 0:
        return None
    w = captured[:n]
    return float(math.sqrt(float(np.dot(w, w)) / n))


# ---------------------------------------------------------------------------
# The estimator and the analyzer (manifest ``compression.estimator`` / ``analyzer``)


def tone_amplitude(x: np.ndarray, frequency: float, fs: float) -> float:
    """The one-bin Hann estimate: 2·|Σ x·w·e^{−jωn}| / Σ w, the window-local
    index, the symmetric Hann; 0 for eight samples or fewer."""
    n = len(x)
    if n <= 8:
        return 0.0
    k = np.arange(n)
    w = 0.5 * (1 - np.cos(2 * np.pi * k / (n - 1)))
    theta = 2 * np.pi * frequency / fs * k
    xw = x * w
    re = float(np.sum(xw * np.cos(theta)))
    im = -float(np.sum(xw * np.sin(theta)))
    return 2 * math.hypot(re, im) / float(np.sum(w))


def rms(x: np.ndarray) -> float:
    return 0.0 if len(x) == 0 else float(math.sqrt(float(np.dot(x, x)) / len(x)))


@dataclass
class Point:
    input_amplitude: float
    output_amplitude: float
    output_rms: float
    thd: float

    @property
    def gain_db(self) -> float:
        return 20 * math.log10(max(self.output_amplitude, 1e-12) / self.input_amplitude)

    @property
    def input_db(self) -> float:
        return 20 * math.log10(self.input_amplitude)

    @property
    def output_db(self) -> float:
        return 20 * math.log10(max(self.output_amplitude, 1e-12))


@dataclass
class Curve:
    frequency: float
    fs: float
    points: List[Point]
    noise_floor_rms: Optional[float]
    dropped: Optional[int]


def harmonic_orders_summed(f0: float, fs: float, harmonic_count: int, band: Tuple[float, float]) -> List[int]:
    """The analyzer's order rule: k = 2…K in order; the loop ENDS at the
    first k·f0 ≥ 0.95·Nyquist or > band top; an order under the band's
    bottom is skipped."""
    orders = []
    for k in range(2, harmonic_count + 1):
        fk = k * f0
        if fk >= fs / 2 * 0.95 or fk > band[1]:
            break
        if fk < band[0]:
            continue
        orders.append(k)
    return orders


def analyze(captured: np.ndarray, tone: SteppedTone, latency: int, harmonic_count: int, band: Tuple[float, float],
            stamp: Optional[float], snr_db: float) -> Tuple[Curve, List[Optional[List[Optional[float]]]], List[Optional[float]], List[bool]]:
    """``CompressionAnalyzer.analyze`` — and, beside the curve, what the oracle
    prints per step: the estimator's amplitude per order, the window rms,
    and the skipped flag."""
    fs = tone.fs
    f0 = tone.frequency
    nyquist = fs / 2
    gate = None if stamp is None else stamp * 10 ** (snr_db / 20)
    dropped = 0
    points: List[Tuple[float, Point]] = []
    harmonics: List[Optional[List[Optional[float]]]] = []
    window_rms: List[Optional[float]] = []
    skipped: List[bool] = []
    summed = harmonic_orders_summed(f0, fs, harmonic_count, band)
    for step, a in enumerate(tone.amplitudes):
        lo, hi = tone.measure_range(step)
        lo += latency
        hi += latency
        if not (lo >= 0 and hi <= len(captured)):
            harmonics.append(None)
            window_rms.append(None)
            skipped.append(True)
            continue
        skipped.append(False)
        window = captured[lo:hi]
        r = rms(window)
        window_rms.append(r)
        if gate is not None and r <= gate:
            dropped += 1
            harmonics.append(None)
            continue
        per_order: List[Optional[float]] = []
        for k in range(1, harmonic_count + 1):
            per_order.append(tone_amplitude(window, k * f0, fs) if k * f0 < nyquist else None)
        fundamental = per_order[0]
        power = sum(per_order[k - 1] ** 2 for k in summed)
        points.append((a, Point(a, fundamental, r, math.sqrt(power) / fundamental if fundamental > 0 else 0.0)))
        harmonics.append(per_order)
    points.sort(key=lambda p: p[0])
    curve = Curve(f0, fs, [p for _, p in points], stamp, dropped if stamp is not None else None)
    return curve, harmonics, window_rms, skipped


# ---------------------------------------------------------------------------
# The read-time layer (manifest ``compression.knee`` / ``cleanup`` / ``floor`` / ``fundamentalPresence``)


def incremental_slopes(curve: Curve) -> List[float]:
    out = []
    for i in range(1, len(curve.points)):
        d_in = curve.points[i].input_db - curve.points[i - 1].input_db
        d_out = curve.points[i].output_db - curve.points[i - 1].output_db
        out.append(d_out / d_in if d_in > 0 else 1.0)
    return out


def _line_fit(xs: List[float], ys: List[float]) -> Tuple[float, float, float]:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0 else 0.0
    intercept = my - slope * mx
    sse = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    return slope, intercept, sse


def _hinge_fit(xs: List[float], ys: List[float], k: float):
    """The normal equations of [1, x, max(0, x − k)] with the 1e−9 ridge,
    solved by Gaussian elimination with partial pivoting (the shipped
    arithmetic, step for step — a different solver differs at the last
    bits and the parity measures that)."""
    a = [[0.0] * 3 for _ in range(3)]
    b = [0.0] * 3
    for x, y in zip(xs, ys):
        row = [1.0, x, max(0.0, x - k)]
        for r in range(3):
            b[r] += row[r] * y
            for c in range(3):
                a[r][c] += row[r] * row[c]
    for d in range(3):
        a[d][d] += 1e-9
    m = [r[:] for r in a]
    v = b[:]
    for col in range(3):
        pivot = col
        for r in range(col + 1, 3):
            if abs(m[r][col]) > abs(m[pivot][col]):
                pivot = r
        if abs(m[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
            v[col], v[pivot] = v[pivot], v[col]
        for r in range(col + 1, 3):
            f = m[r][col] / m[col][col]
            for c in range(col, 3):
                m[r][c] -= f * m[col][c]
            v[r] -= f * v[col]
    c = [0.0] * 3
    for row in (2, 1, 0):
        s = v[row]
        for col in range(row + 1, 3):
            s -= m[row][col] * c[col]
        c[row] = s / m[row][row]
    sse = sum((y - (c[0] + c[1] * x + c[2] * max(0.0, x - k))) ** 2 for x, y in zip(xs, ys))
    return c[0], c[1], c[2], sse


@dataclass
class Knee:
    input_db: float
    is_bound: bool
    resolution_db: float
    pre_slope: float
    post_slope: float

    def compressed_throughout(self, tolerance: float) -> bool:
        return self.is_bound and self.pre_slope < 1 - tolerance

    @property
    def display_decimals(self) -> int:
        return 1 if self.resolution_db <= 0.5 else 0

    @property
    def label(self) -> str:
        level = "%.*f" % (self.display_decimals, self.input_db)
        return ("≤ %s dBFS" % level) if self.is_bound else ("%s dBFS" % level)


def knee_estimate(curve: Curve, slope_threshold: float, tolerance: float) -> Optional[Knee]:
    xs = [p.input_db for p in curve.points]
    ys = [p.output_db for p in curve.points]
    n = len(xs)
    if n < 4 or xs[-1] <= xs[0]:
        return None
    x0 = xs[0]
    probe_step = xs[1] - x0
    lin_slope, _, lin_sse = _line_fit(xs, ys)
    k_lo, k_hi = xs[1], xs[n - 2]
    if k_hi <= k_lo:
        return None
    steps = 1024
    best_sse = math.inf
    best = (k_lo, 1.0, 1.0)
    profile = []
    for i in range(steps + 1):
        k = k_lo + (k_hi - k_lo) * i / steps
        fit = _hinge_fit(xs, ys, k)
        if fit is None:
            continue
        profile.append((k, fit[3]))
        if fit[3] < best_sse:
            best_sse = fit[3]
            best = (k, fit[1], fit[1] + fit[2])
    if not profile:
        return None
    if best_sse > 0.5 * lin_sse:
        if lin_slope >= 1 - tolerance:
            return None
        return Knee(x0, True, probe_step, lin_slope, lin_slope)
    if best[2] >= slope_threshold:
        return None
    if best[1] < 1 - tolerance:
        return Knee(x0, True, probe_step, best[1], best[2])
    if best[0] <= x0 + probe_step:
        return Knee(best[0], True, probe_step, best[1], best[2])
    tol = best_sse * 1.05 + 1e-12
    in_band = [k for k, sse in profile if sse <= tol]
    half = ((max(in_band) if in_band else best[0]) - (min(in_band) if in_band else best[0])) / 2
    fine = (k_hi - k_lo) / steps
    return Knee(best[0], False, max(half, fine), best[1], best[2])


def cleanup_input_db(curve: Curve, threshold: float) -> Optional[float]:
    if not curve.points:
        return None
    if curve.points[0].thd >= threshold:
        return None
    for i in range(1, len(curve.points)):
        if curve.points[i].thd >= threshold:
            a, b = curve.points[i - 1], curve.points[i]
            t = (threshold - a.thd) / max(b.thd - a.thd, 1e-12)
            return a.input_db + t * (b.input_db - a.input_db)
    return curve.points[-1].input_db


def cleanup_reading(curve: Curve, threshold: float) -> Tuple[str, Optional[float]]:
    """``CleanupReading(curve:)``: (state, level)."""
    if not curve.points:
        return ("none", None)
    db = cleanup_input_db(curve, threshold)
    if db is None:
        return ("never_clean", None)
    if db >= curve.points[-1].input_db:
        return ("always_clean", None)
    return ("cleans_up", db)


def noise_floor_thd(curve: Curve, p: Point) -> Optional[float]:
    if curve.noise_floor_rms is None or curve.noise_floor_rms <= 0 or p.output_amplitude <= 0:
        return None
    return math.sqrt(2) * curve.noise_floor_rms / p.output_amplitude


def null_run_amplitude(reference: Curve, input_db: float) -> Optional[float]:
    """The loop's own added-harmonic AMPLITUDE at the drive: the rungs'
    (inputDB, 20·log10(thd·fundamental)), log-interpolated, nil outside."""
    rungs = sorted((p.input_db, 20 * math.log10(p.thd * p.output_amplitude)) for p in reference.points
                   if p.thd > 0 and p.output_amplitude > 0 and p.input_amplitude > 0)
    if len(rungs) < 2 or input_db < rungs[0][0] or input_db > rungs[-1][0]:
        return None
    for i in range(1, len(rungs)):
        if input_db <= rungs[i][0]:
            a, b = rungs[i - 1], rungs[i]
            t = (input_db - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
            return 10 ** ((a[1] + (b[1] - a[1]) * t) / 20)
    return 10 ** (rungs[-1][1] / 20)


def null_run_floor_thd(p: Point, reference: Optional[Curve]) -> Optional[float]:
    if reference is None or p.output_amplitude <= 0:
        return None
    a = null_run_amplitude(reference, p.input_db)
    return None if a is None else a / p.output_amplitude


def stated_floor_thd(p: Point, stated_rms: Optional[float]) -> Optional[float]:
    if stated_rms is None or stated_rms <= 0 or p.output_amplitude <= 0:
        return None
    return math.sqrt(2) * stated_rms / p.output_amplitude


def floor_thd(curve: Curve, p: Point, reference: Optional[Curve], stated_rms: Optional[float]) -> Optional[float]:
    bounds = [b for b in (noise_floor_thd(curve, p), null_run_floor_thd(p, reference), stated_floor_thd(p, stated_rms))
              if b is not None]
    return max(bounds) if bounds else None


def floor_class(curve: Curve, p: Point, reference: Optional[Curve], stated_rms: Optional[float],
                epsilon_db: float, margin_db: float) -> Optional[str]:
    floor = floor_thd(curve, p, reference, stated_rms)
    if floor is None:
        return None
    if p.thd <= 0:
        return "below_floor"
    margin = 20 * math.log10(p.thd / floor)
    if margin <= 0 + epsilon_db:
        return "below_floor"
    if margin < margin_db:
        return "noise_dominated"
    return "clear"


CLASS_RANK = {"clear": 0, "noise_dominated": 1, "below_floor": 2}


def floor_runs(curve: Curve, reference, stated_rms, epsilon_db, margin_db) -> Optional[List[Tuple[str, int]]]:
    """``thdFloorRuns`` as (class, point count) per run; None when any point
    has no class; [] under two points."""
    if len(curve.points) < 2:
        return None if not curve.points else []
    classes = []
    for p in curve.points:
        c = floor_class(curve, p, reference, stated_rms, epsilon_db, margin_db)
        if c is None:
            return None
        classes.append(c)

    def worse(a, b):
        return a if CLASS_RANK[a] >= CLASS_RANK[b] else b

    runs = []
    run_class = worse(classes[0], classes[1])
    run_count = 2
    for i in range(2, len(curve.points)):
        seg = worse(classes[i - 1], classes[i])
        if seg == run_class:
            run_count += 1
        else:
            runs.append((run_class, run_count))
            run_class = seg
            run_count = 2
    runs.append((run_class, run_count))
    return runs


def floor_source(curve: Curve, reference: Optional[Curve], stated_rms: Optional[float]) -> Optional[str]:
    if not any(floor_thd(curve, p, reference, stated_rms) is not None for p in curve.points):
        return None

    def sets(bound):
        for p in curve.points:
            b = bound(p)
            f = floor_thd(curve, p, reference, stated_rms)
            if b is not None and f is not None and b >= f:
                return True
        return False

    if reference is not None and sets(lambda p: null_run_floor_thd(p, reference)):
        return "null_run"
    if stated_rms is not None and sets(lambda p: stated_floor_thd(p, stated_rms)):
        return "stated_floor"
    return "capture_noise"


def presence_reading(p: Point, separation_db: float) -> str:
    if p.output_amplitude <= 0 or p.thd <= 0:
        return "undetermined"
    depth = 20 * math.log10(p.thd)
    return "absent" if depth >= separation_db else "present"


@dataclass
class Verdict:
    absent: bool
    fraction: float
    median_depth: Optional[float]
    evaluated: int


def presence_verdict(curve: Curve, separation_db: float) -> Verdict:
    readings = [(presence_reading(p, separation_db), p) for p in curve.points]
    evaluable = [(r, p) for r, p in readings if r != "undetermined"]
    if not evaluable:
        return Verdict(False, 0.0, None, 0)
    depths = sorted(20 * math.log10(p.thd) for r, p in evaluable if r == "absent")
    fraction = len(depths) / len(evaluable)
    return Verdict(fraction > 0.5, fraction, depths[len(depths) // 2] if depths else None, len(evaluable))


# ---------------------------------------------------------------------------
# The summaries' compression features (manifest ``compression.summaries``)


@dataclass
class Summaries:
    knee: Optional[Tuple[float, float]]          # (level, confidence)
    knee_bound: Optional[bool]
    sharpness: Optional[Tuple[float, float]]
    asymptote: Optional[Tuple[float, float]]
    cleanup: Tuple[str, Optional[float], Optional[float]]
    fundamental_absent: bool


def summaries(curve: Curve, m: dict) -> Summaries:
    cm = m["compression"]
    verdict = presence_verdict(curve, float(m["harmonicDistortion"]["fundamentalPresence"]["analyzerSeparationDB"]))
    none = Summaries(None, None, None, None, ("none", None, None), verdict.absent)
    if verdict.absent:
        return none
    slopes = incremental_slopes(curve)
    if len(curve.points) < 5 or not slopes:
        return none
    knee = knee_estimate(curve, float(cm["knee"]["slopeThreshold"]), float(cm["knee"]["preKneeUnitySlopeTolerance"]))
    knee_feature = None
    knee_bound = None
    sharpness = None
    if knee is not None:
        beyond = sum(1 for p in curve.points if p.input_db > knee.input_db)
        confidence = 0.35 if knee.is_bound else min(1.0, beyond / 3) * 0.9
        knee_feature = (knee.input_db, confidence)
        knee_bound = True if knee.is_bound else None
        start = None
        end = None
        for i, slope in enumerate(slopes):
            input_db = curve.points[i + 1].input_db
            if start is None and slope < 0.9:
                start = input_db
            if end is None and slope < 0.45:
                end = input_db
        if start is not None and not knee.is_bound:
            width = (end if end is not None else curve.points[-1].input_db + 12) - start
            sharpness = (min(max(1 - width / 24, 0.0), 1.0), 0.4 if end is None else confidence)
    max_input = curve.points[-1].input_db
    top = [s for i, s in enumerate(slopes) if curve.points[i + 1].input_db >= max_input - 6]
    if len(top) < 2:
        top = slopes[-3:]
    asymptote = (sum(top) / len(top), 0.85 if len(top) >= 3 else 0.55) if top else None
    threshold = float(cm["cleanup"]["threshold"])
    db = cleanup_input_db(curve, threshold)
    if db is None:
        cleanup = ("never_clean", None, None)
    elif db >= curve.points[-1].input_db:
        cleanup = ("always_clean", None, None)
    else:
        cleanup = ("cleans_up", db, 0.85)
    return Summaries(knee_feature, knee_bound, sharpness, asymptote, cleanup, False)


# ---------------------------------------------------------------------------
# The truth (manifest ``compression.synthesis``)


def ladder(kind: str, params: dict, amplitude: float, orders: int, points: int,
           loop_cubic: Optional[float] = None, gain: float = 1.0) -> List[float]:
    """|Fourier_k| / A for k = 1…orders by the trapezoid rule on the periodic
    integrand — chapter one's rule, every order in one pass; with a loop
    cubic, the device composed with the loop (y = L(g·D(x))/g, memoryless
    in memoryless), normalized by the drive."""
    theta = 2 * np.pi * np.arange(points) / points
    y = tc.nonlinearity(kind, params)(amplitude * np.sin(theta))
    if loop_cubic is not None:
        z = gain * y
        y = (z + loop_cubic * z * z * z) / gain
    out = []
    for k in range(1, orders + 1):
        a = float(np.sum(y * np.sin(k * theta)))
        b = float(np.sum(y * np.cos(k * theta)))
        out.append(math.hypot(a, b) * (2 / points) / amplitude)
    return out


@dataclass
class Truth:
    harmonic: List[List[Optional[float]]]   # [step][order − 1], output amplitudes
    thd: List[Optional[float]]
    rms: List[float]


def truth_for(plan: Plan, m: dict) -> Truth:
    cm = m["compression"]
    K = int(cm["analyzer"]["harmonicCount"])
    band = (float(cm["analyzer"]["band"]["lowHz"]), float(cm["analyzer"]["band"]["highHz"]))
    points = int(cm["synthesis"]["quadraturePoints"])
    fs = plan.fs
    f0 = plan.frequency
    nyquist = fs / 2
    g = plan.chain_gain
    summed = harmonic_orders_summed(f0, fs, K, band)
    harmonics: List[List[Optional[float]]] = []
    thds: List[Optional[float]] = []
    rmss: List[float] = []
    cache: Dict[float, List[float]] = {}
    for step, level in enumerate(plan.levels_db):
        a = 10 ** (level / 20)
        pre_gain = 1.0
        post = None
        if plan.source.kind == "phantom":
            lad = plan.source.ladders[0] if len(plan.source.ladders) == 1 else plan.source.ladders[step]
            truth = [abs(lad[k - 1]) if k <= len(lad) else 0.0 for k in range(1, K + 1)]
        else:
            dev = plan.source.device
            if dev.pre is not None:
                pre_gain = abs(dev.pre.biquad(fs).response(f0))
            if dev.post is not None:
                post = dev.post.biquad(fs)
            drive = a * pre_gain
            if drive not in cache:
                cache[drive] = ladder(dev.kind, dev.params, drive, K, points,
                                      plan.loop_cubic if post is None else None, g)
            truth = [t * pre_gain for t in cache[drive]]
        row: List[Optional[float]] = []
        total = 0.0
        for k in range(1, K + 1):
            fk = k * f0
            t = truth[k - 1]
            if post is not None:
                t *= abs(post.response(fk))
            t *= g * a
            if fk >= nyquist:
                row.append(None)
                continue
            row.append(t)
            total += t * t
        h1 = row[0] if row[0] is not None and row[0] > 0 else None
        power = sum(row[k - 1] ** 2 for k in summed if row[k - 1] is not None)
        harmonics.append(row)
        thds.append(None if h1 is None else math.sqrt(power) / h1)
        rmss.append(math.sqrt(total / 2))
    return Truth(harmonics, thds, rmss)


def truth_curve(plan: Plan, truth: Truth, injected: Optional[float]) -> Curve:
    pts = []
    for i, level in enumerate(plan.levels_db):
        a = 10 ** (level / 20)
        h1 = truth.harmonic[i][0]
        pts.append(Point(a, 0.0 if h1 is None else h1, truth.rms[i], 0.0 if truth.thd[i] is None else truth.thd[i]))
    pts.sort(key=lambda p: p.input_amplitude)
    return Curve(plan.frequency, plan.fs, pts, injected if plan.assembly == "app" else None, None)


# ---------------------------------------------------------------------------
# The run


@dataclass
class Reading:
    verdict: Verdict
    knee: Optional[Knee]
    cleanup: Tuple[str, Optional[float]]
    source: Optional[str]              # with the null run offered
    source_without: Optional[str]      # the reader's own nil form
    runs: Optional[List[Tuple[str, int]]]
    features: Summaries


def read(curve: Curve, reference: Optional[Curve], stated_rms: Optional[float], m: dict) -> Reading:
    cm = m["compression"]
    separation = float(m["harmonicDistortion"]["fundamentalPresence"]["analyzerSeparationDB"])
    verdict = presence_verdict(curve, separation)
    if verdict.absent:
        knee, cleanup, source, source_without = None, ("none", None), None, None
    else:
        knee = knee_estimate(curve, float(cm["knee"]["slopeThreshold"]), float(cm["knee"]["preKneeUnitySlopeTolerance"]))
        cleanup = cleanup_reading(curve, float(cm["cleanup"]["threshold"]))
        source = floor_source(curve, reference, stated_rms)
        source_without = floor_source(curve, None, stated_rms)
    runs = floor_runs(curve, reference, stated_rms, float(cm["floor"]["atFloorEpsilonDB"]), float(cm["floor"]["thdNoiseClearMarginDB"]))
    return Reading(verdict, knee, cleanup, source, source_without, runs, summaries(curve, m))


@dataclass
class Result:
    plan: Plan
    tone: SteppedTone
    captured: np.ndarray
    stamp: Optional[float]
    injected: Optional[float]
    curve: Curve
    harmonics: list
    window_rms: list
    skipped: list
    reference: Optional[Curve]
    reading: Reading
    truth: Truth
    truth_curve: Curve
    truth_reading: Reading


def run(plan: Plan, m: dict) -> Result:
    cm = m["compression"]
    hdm = m["harmonicDistortion"]
    increment = int(hdm["synthesis"]["noiseGeneratorIncrement"], 16)
    K = int(cm["analyzer"]["harmonicCount"])
    band = (float(cm["analyzer"]["band"]["lowHz"]), float(cm["analyzer"]["band"]["highHz"]))
    snr = float(cm["probe"]["minimumStepSNRDB"])
    tone = tone_for(plan, cm)
    captured = through_loop(rendered(plan, tone, cm), plan, capture_seed(plan, False, increment), increment)
    stamp = noise_stamp(plan, captured, cm)
    latency = analyzed_latency(plan, cm)
    curve, harmonics, window_rms, skipped = analyze(captured, tone, latency, K, band, stamp, snr)
    reference = None
    if plan.null_run:
        null_capture = through_loop(stimulus(plan, tone, cm), plan, capture_seed(plan, True, increment), increment)
        reference, _, _, _ = analyze(null_capture, tone, latency, K, band, noise_stamp(plan, null_capture, cm), snr)
    injected = None if plan.noise_rms is None else plan.noise_rms * plan.chain_gain
    truth = truth_for(plan, m)
    tcurve = truth_curve(plan, truth, injected)
    return Result(plan, tone, captured, stamp, injected, curve, harmonics, window_rms, skipped, reference,
                  read(curve, reference, plan.operative_rms, m), truth, tcurve, read(tcurve, reference, plan.operative_rms, m))


# ---------------------------------------------------------------------------
# The TSV — the oracle's exact header lines and column set


def knee_line(knee: Optional[Knee], absent: bool, tolerance: float) -> str:
    if knee is not None:
        return ("state=fitted input_dbfs=%s bound=%s resolution_db=%s pre_knee_slope=%s post_knee_slope=%s "
                "compressed_throughout=%s display_decimals=%d label=%s" % (
                    fmt(knee.input_db), fmt(knee.is_bound), fmt(knee.resolution_db), fmt(knee.pre_slope),
                    fmt(knee.post_slope), fmt(knee.compressed_throughout(tolerance)), knee.display_decimals, knee.label))
    return "state=not_stated (fundamental absent, #154)" if absent else "state=none (no compression in range)"


def cleanup_fields(c: Tuple[str, Optional[float]]) -> str:
    return "state=%s level_dbfs=%s" % (c[0], fmt(c[1]))


def cleanup_behavior_fields(c: Tuple[str, Optional[float], Optional[float]]) -> str:
    return "state=%s level_dbfs=%s confidence=%s" % (c[0], fmt(c[1]), fmt(c[2]))


def feature_fields(v: Optional[Tuple[float, float]]) -> str:
    return "%s confidence=%s" % (fmt(None if v is None else v[0]), fmt(None if v is None else v[1]))


def summaries_line(s: Summaries) -> str:
    return ("knee_level_dbfs=%s knee_bound=%s sharpness=%s asymptote=%s cleanup %s fundamental_absent=%s" % (
        feature_fields(s.knee), "nan" if s.knee_bound is None else fmt(s.knee_bound), feature_fields(s.sharpness),
        feature_fields(s.asymptote), cleanup_behavior_fields(s.cleanup), fmt(s.fundamental_absent)))


def verdict_line(v: Verdict) -> str:
    return "fundamental verdict: absent=%s absent_fraction=%s median_depth_db=%s evaluated=%d" % (
        fmt(v.absent), fmt(v.fraction), fmt(v.median_depth), v.evaluated)


def source_label(s: Optional[str]) -> str:
    return "none" if s is None else s


def runs_text(runs) -> str:
    if runs is None:
        return "none"
    if not runs:
        return "empty"
    return " ".join("%s:%d" % r for r in runs)


def write_tsv(r: Result, m: dict, raw: dict, out) -> None:
    cm = m["compression"]
    p = r.plan
    tone = r.tone
    K = int(cm["analyzer"]["harmonicCount"])
    tol = float(cm["knee"]["preKneeUnitySlopeTolerance"])
    increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
    cycles = tone.measure_samples * tone.frequency / tone.fs
    app = p.assembly == "app"
    out.write("# source: %s\n" % p.source.label)
    out.write("# plan: steps=%d level_dbfs=[%s] frequency_hz=%s fs=%s settle_s=%s measure_s=%s ramp_s=%s "
              "settle_samples=%d measure_samples=%d ramp_samples=%d measure_cycles=%s step_samples=%d tone_samples=%d "
              "assembly=%s preroll_s=%s tail_s=%s preroll_samples=%d tail_samples=%d stimulus_samples=%d "
              "harmonic_count=%d band_hz=%s-%s nyquist_hz=%s\n" % (
                  len(p.levels_db), ",".join(fmt(l) for l in p.levels_db), fmt(p.frequency), fmt(p.fs),
                  fmt(p.settle), fmt(p.measure), fmt(p.ramp), tone.settle_samples, tone.measure_samples, tone.ramp_samples,
                  fmt(cycles), tone.step_samples, tone.sample_count, p.assembly,
                  fmt(cm["assembly"]["prerollS"] if app else 0.0), fmt(cm["assembly"]["tailS"] if app else 0.0),
                  preroll_samples(p, cm), tail_samples(p, cm), len(r.captured), K,
                  fmt(cm["analyzer"]["band"]["lowHz"]), fmt(cm["analyzer"]["band"]["highHz"]), fmt(p.fs / 2)))
    out.write("# grid: floor_db=%s ceiling_db=%s steps=%s plugin_window=%s fine_min=%s fine_max=%s fine_step_db=%s "
              "maximum_fine_points=%d delivered=%d minimum_step_snr_db=%s\n" % (
                  raw.get("floor_db", "default"), raw.get("ceiling_db", "default"), raw.get("steps", "default"),
                  fmt(raw.get("plugin_window", False)), raw.get("fine_min", "none"), raw.get("fine_max", "none"),
                  fmt(cm["probe"]["fineStepDB"]), int(cm["probe"]["maximumFinePoints"]), len(p.levels_db),
                  fmt(cm["probe"]["minimumStepSNRDB"])))
    out.write("# loop: latency_samples=%d latency_error_samples=%d analyzed_latency_samples=%d chain_gain_db=%s chain_gain=%s "
              "noise_rms_dbfs=%s seed=%d capture_seed=%d null_run_seed=%d loop_a3=%s\n" % (
                  p.latency, p.latency_error, analyzed_latency(p, cm), fmt(p.chain_gain_db), fmt(p.chain_gain),
                  raw.get("noise_db", "none"), p.seed, capture_seed(p, False, increment), capture_seed(p, True, increment),
                  fmt(p.loop_cubic)))
    snr = float(cm["probe"]["minimumStepSNRDB"])
    gate = None if r.stamp is None else r.stamp * 10 ** (snr / 20)
    stamp_db = None if r.stamp is None or r.stamp <= 0 else 20 * math.log10(r.stamp)
    if r.stamp == 0:
        stamp_db = -math.inf
    injected_db = None if r.injected is None else 20 * math.log10(r.injected)
    error = None if stamp_db is None or injected_db is None else stamp_db - injected_db
    out.write("# noise stamp: measured_rms=%s measured_dbfs=%s injected_rms=%s injected_dbfs=%s error_db=%s gate_rms=%s "
              "dropped=%s points=%d skipped=%d\n" % (
                  fmt(r.stamp), fmt(stamp_db), fmt(r.injected), fmt(injected_db), fmt(error), fmt(gate),
                  "nan" if r.curve.dropped is None else str(r.curve.dropped), len(r.curve.points), sum(r.skipped)))
    if p.operative_rms is not None and p.operative_rms > 0:
        rms_ = p.operative_rms
        out.write("# precheck: operative_rms=%s operative_dbfs=%s absolute_dbfs=%s in_signal_governs=0\n" % (
            fmt(rms_), fmt(20 * math.log10(rms_)), fmt(20 * math.log10(math.sqrt(2) * rms_))))
    else:
        out.write("# precheck: none\n")
    if r.reference is not None:
        ref = r.reference
        out.write("# null run: present measured_at=%s points=%d dropped=%s noise_floor_rms=%s span_dbfs=%s-%s\n" % (
            cm["shippedConstants"]["CompressionSynthDump.nullRunMeasuredAt"], len(ref.points),
            "nan" if ref.dropped is None else str(ref.dropped), fmt(ref.noise_floor_rms),
            fmt(ref.points[0].input_db if ref.points else None), fmt(ref.points[-1].input_db if ref.points else None)))
        out.write("# null run rungs: " + " ".join("%s:%s:%s" % (fmt(q.input_db), fmt(q.thd), fmt(q.output_amplitude)) for q in ref.points) + "\n")
    else:
        out.write("# null run: none\n")
    for label, rd in (("", r.reading), ("truth ", r.truth_reading)):
        out.write("# %s%s\n" % (label, verdict_line(rd.verdict)))
        out.write("# %sknee: %s\n" % (label, knee_line(rd.knee, rd.verdict.absent, tol)))
        out.write("# %scleanup: %s%s\n" % (label, cleanup_fields(rd.cleanup),
                                           " (not stated: fundamental absent, #154)" if rd.verdict.absent else ""))
        out.write("# %sfloor source: %s without_null_run=%s\n" % (label, source_label(rd.source), source_label(rd.source_without)))
        out.write("# %sfloor runs: %s\n" % (label, runs_text(rd.runs)))
        out.write("# %ssummaries (FeatureExtractor.extract(compression:)): %s\n" % (label, summaries_line(rd.features)))
    orders = list(range(1, K + 1))
    header = (["index", "input_dbfs", "input_amplitude", "dropped", "skipped", "output_db", "gain_db", "slope", "thd", "thd_pct"]
              + ["h%d" % k for k in orders]
              + ["window_rms", "noise_floor_thd", "null_run_floor_thd", "stated_floor_thd", "floor_thd", "floor_class", "presence",
                 "truth_output_db", "truth_gain_db", "truth_slope", "truth_thd"] + ["truth_h%d" % k for k in orders]
              + ["truth_rms", "truth_noise_floor_thd", "truth_null_run_floor_thd", "truth_stated_floor_thd", "truth_floor_thd",
                 "truth_floor_class", "truth_presence"])
    out.write("\t".join(header) + "\n")
    separation = float(m["harmonicDistortion"]["fundamentalPresence"]["analyzerSeparationDB"])
    epsilon = float(cm["floor"]["atFloorEpsilonDB"])
    margin = float(cm["floor"]["thdNoiseClearMarginDB"])
    slopes = incremental_slopes(r.curve)
    truth_slopes = incremental_slopes(r.truth_curve)
    by_amp = {q.input_amplitude: i for i, q in enumerate(r.curve.points)}
    truth_by_amp = {q.input_amplitude: i for i, q in enumerate(r.truth_curve.points)}
    order = sorted(range(len(p.levels_db)), key=lambda i: p.levels_db[i])
    stated = p.operative_rms
    for step in order:
        a = tone.amplitudes[step]
        pi = by_amp.get(a)
        q = None if pi is None else r.curve.points[pi]
        skipped = r.skipped[step]
        dropped = (not skipped) and q is None
        hs = r.harmonics[step] if (q is not None and r.harmonics[step] is not None) else [None] * K
        ti = truth_by_amp[a]
        t = r.truth_curve.points[ti]
        cols = [str(step), fmt(p.levels_db[step]), fmt(a), fmt(dropped), fmt(skipped),
                fmt(None if q is None else q.output_db), fmt(None if q is None else q.gain_db),
                fmt(None if pi is None or pi == 0 else slopes[pi - 1]),
                fmt(None if q is None else q.thd), fmt(None if q is None else q.thd * 100)]
        cols += [fmt(h) for h in hs]
        cols += [fmt(r.window_rms[step]),
                 fmt(None if q is None else noise_floor_thd(r.curve, q)),
                 fmt(None if q is None else null_run_floor_thd(q, r.reference)),
                 fmt(None if q is None else stated_floor_thd(q, stated)),
                 fmt(None if q is None else floor_thd(r.curve, q, r.reference, stated)),
                 "nan" if q is None else (floor_class(r.curve, q, r.reference, stated, epsilon, margin) or "nan"),
                 "nan" if q is None else presence_reading(q, separation),
                 fmt(t.output_db), fmt(t.gain_db), fmt(None if ti == 0 else truth_slopes[ti - 1]), fmt(t.thd)]
        cols += [fmt(h) for h in r.truth.harmonic[step]]
        cols += [fmt(t.output_rms), fmt(noise_floor_thd(r.truth_curve, t)), fmt(null_run_floor_thd(t, r.reference)),
                 fmt(stated_floor_thd(t, stated)), fmt(floor_thd(r.truth_curve, t, r.reference, stated)),
                 floor_class(r.truth_curve, t, r.reference, stated, epsilon, margin) or "nan", presence_reading(t, separation)]
        out.write("\t".join(cols) + "\n")


# ---------------------------------------------------------------------------
# Command line — the options of `analysisdump compression-synth`
# (the module is compression_curve.py: `compression` is a standard-library
# package from Python 3.14, and a module of that name shadows it on any
# machine whose Python has it — CI's did, 2026-09-21)


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
    p.add_argument("--amps-per-step")
    p.add_argument("--pre", choices=["lowpass", "highpass"])
    p.add_argument("--pre-hz", type=float)
    p.add_argument("--pre-q", type=float)
    p.add_argument("--post", choices=["lowpass", "highpass"])
    p.add_argument("--post-hz", type=float)
    p.add_argument("--post-q", type=float)
    p.add_argument("--invert", action="store_true")
    # Echoed verbatim on the `# grid` line, as the Swift tool echoes them.
    p.add_argument("--floor-db")
    p.add_argument("--ceiling-db")
    p.add_argument("--steps")
    p.add_argument("--fine-min")
    p.add_argument("--fine-max")
    p.add_argument("--plugin-window", action="store_true")
    p.add_argument("--frequency", type=float)
    p.add_argument("--rate", type=float)
    p.add_argument("--settle", type=float)
    p.add_argument("--measure", type=float)
    p.add_argument("--ramp", type=float)
    p.add_argument("--assembly", choices=["app", "simulation"], default="app")
    p.add_argument("--latency-samples", type=int, default=0)
    p.add_argument("--latency-error", type=int, default=0)
    p.add_argument("--chain-gain-db", type=float, default=0.0)
    p.add_argument("--noise-db")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--operative-floor-rms", type=float)
    p.add_argument("--null-run", action="store_true")
    p.add_argument("--loop-a3", type=float)
    p.add_argument("--out")
    return p


def plan_from_args(args, m: dict) -> Tuple[Plan, dict]:
    cm = m["compression"]
    probe = cm["probe"]
    plugin = args.plugin_window
    floor = float(args.floor_db) if args.floor_db is not None else float(probe["pluginFloorDBFS"] if plugin else probe["floorDBFS"])
    ceiling = float(args.ceiling_db) if args.ceiling_db is not None else float(probe["pluginCeilingDBFS"] if plugin else probe["ceilingDBFS"])
    steps = int(args.steps) if args.steps is not None else int(probe["pluginSteps"] if plugin else probe["defaultSteps"])
    fine = None
    if args.fine_min is not None and args.fine_max is not None:
        fine = (float(args.fine_min), float(args.fine_max))
    if args.assembly == "simulation":
        levels = [20 * math.log10(a) for a in log_spaced_amplitudes(floor, ceiling, steps)]
    else:
        levels = levels_db(floor, ceiling, steps, float(probe["fineStepDB"]), int(probe["maximumFinePoints"]), fine)
    default_q = float(m["transferCurve"]["biquad"]["defaultQ"])

    def filt(kind, hz, q):
        if kind is None:
            return None
        return tc.Filter("lowPass" if kind == "lowpass" else "highPass", hz, default_q if q is None else q)

    if args.source == "phantom":
        if args.amps_per_step:
            ladders = [[float(a) for a in l.split(",")] for l in args.amps_per_step.split(";")]
        elif args.amps:
            ladders = [[float(a) for a in args.amps.split(",")]]
        else:
            raise SystemExit("--source phantom needs --amps or --amps-per-step")
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
    noise = None if args.noise_db is None else 10 ** (float(args.noise_db) / 20)
    plan = Plan(source, levels,
                float(cm["stimulus"]["frequencyHz"]) if args.frequency is None else args.frequency,
                float(cm["stimulus"]["sampleRateHz"]) if args.rate is None else args.rate,
                args.settle, args.measure, args.ramp, args.assembly, args.latency_samples, args.latency_error,
                args.chain_gain_db, noise, args.seed, args.operative_floor_rms, args.null_run, args.loop_a3)
    raw = {}
    for key in ("floor_db", "ceiling_db", "steps", "fine_min", "fine_max", "noise_db"):
        v = getattr(args, key)
        if v is not None:
            raw[key] = v
    raw["plugin_window"] = args.plugin_window
    return plan, raw


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    m = load_manifest(args.manifest)
    plan, raw = plan_from_args(args, m)
    result = run(plan, m)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            write_tsv(result, m, raw, f)
    else:
        write_tsv(result, m, raw, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
