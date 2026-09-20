#!/usr/bin/env python3
"""Transfer Curve — an independent reimplementation of PedalScope's X–Y
transfer-curve method, written from the methods manifest
(``Docs/Methods/generated/manifest.json``, the ``transferCurve`` object) and
the chapter's own equations, NOT by transliterating the Swift.

It produces the same TSV ``analysisdump transfer-synth`` produces — the same
header lines, the same column set — so one comparator serves both, and
``test_parity_transfer.py`` pins the two against each other and against the
closed-form truths.

What is reimplemented, in the order the pipeline runs it:

* the stimulus (``TransferCurvePlan``'s tone: a faded sine, pre-roll and
  tail) and the device — a nonlinearity from ``harmonic_distortion.py``'s
  own family between two optional RBJ biquads, from the manifest's
  coefficient rules;
* the phase-binned averaged cycle (``binning``), the box normalization, the
  unsigned lobe area with its self-crossing split and per-lobe floor
  (``figure``), the fundamental ellipse and its residual, the per-branch
  static curve;
* the read-time predicates: the cycle's fundamental phase and the #97
  orientation resolution against the paired H1's robust polarity, the
  fundamental-presence reading, and the §6.5 removal — fittable terms, the
  frame fit, the anchored sequential lattice fold, the monotone-cubic
  deviation and the full-band unity-magnitude all-pass — with the #95 class
  and the #96 polarity confirmation;
* the pairing itself: the same device through ``harmonic_distortion.py``'s
  sweep and analyzer (one family, one source);
* the ground truth, by the manifest's ``synthesis`` rules.

Only the manifest's RULES are read; every number the rules produce is
recomputed here. The two function-body literals the rules carry (the frame
fit's 0.05- and 0.001-sample scan steps) are parsed out of the rule string
rather than typed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import lfilter

import harmonic_distortion as hd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = hd.DEFAULT_MANIFEST

COLUMNS = ["section", "index", "x", "y", "y_comp", "y_truth_raw", "y_truth_comp"]

fmt = hd.fmt
swift_round = hd.swift_round


def load_manifest(path: str = DEFAULT_MANIFEST) -> dict:
    """The WHOLE manifest: ``harmonicDistortion`` for the pairing,
    ``transferCurve`` for everything else."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def wrap(angle: float) -> float:
    """Principal value, the way ``atan2(sin, cos)`` folds it."""
    return math.atan2(math.sin(angle), math.cos(angle))


# ---------------------------------------------------------------------------
# The biquad (manifest ``biquad``)


@dataclass(frozen=True)
class Biquad:
    b0: float
    b1: float
    b2: float
    a1: float
    a2: float
    fs: float

    @classmethod
    def lowpass(cls, frequency: float, q: float, fs: float) -> "Biquad":
        w = 2 * math.pi * frequency / fs
        alpha = math.sin(w) / (2 * q)
        c = math.cos(w)
        a0 = 1 + alpha
        return cls((1 - c) / 2 / a0, (1 - c) / a0, (1 - c) / 2 / a0, -2 * c / a0, (1 - alpha) / a0, fs)

    @classmethod
    def highpass(cls, frequency: float, q: float, fs: float) -> "Biquad":
        w = 2 * math.pi * frequency / fs
        alpha = math.sin(w) / (2 * q)
        c = math.cos(w)
        a0 = 1 + alpha
        return cls((1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0, -2 * c / a0, (1 - alpha) / a0, fs)

    def process(self, x: np.ndarray) -> np.ndarray:
        """Direct form II transposed from zero state (the manifest's
        topology; scipy's ``lfilter`` is that structure)."""
        return lfilter([self.b0, self.b1, self.b2], [1.0, self.a1, self.a2], x)

    def response(self, f: float) -> complex:
        w = 2 * math.pi * f / self.fs
        z = np.exp(-1j * w)
        return complex((self.b0 + self.b1 * z + self.b2 * z * z) / (1 + self.a1 * z + self.a2 * z * z))

    def pole_radius(self) -> float:
        disc = self.a1 * self.a1 - 4 * self.a2
        if disc < 0:
            return math.sqrt(self.a2)
        root = math.sqrt(disc)
        return max(abs((-self.a1 + root) / 2), abs((-self.a1 - root) / 2))


@dataclass(frozen=True)
class Filter:
    kind: str  # "lowPass" | "highPass"
    frequency: float
    q: float

    def biquad(self, fs: float) -> Biquad:
        return (Biquad.lowpass if self.kind == "lowPass" else Biquad.highpass)(self.frequency, self.q, fs)

    @property
    def label(self) -> str:
        return f"{self.kind}(frequency: {fmt(self.frequency)}, q: {fmt(self.q)})"


# ---------------------------------------------------------------------------
# The device


def nonlinearity(kind: str, params: dict):
    if kind == "parametric":
        t, k, a = params["threshold"], params["knee"], params["asymmetry"]

        def clip(x):
            x = np.asarray(x, dtype=np.float64)
            limit = t * np.power(2.0, np.where(x >= 0, a, -a))
            u = np.abs(x) / limit
            s = min(max(k, 0.0), 1.0)
            if s <= 0:
                y = np.minimum(u, 1.0)
            else:
                d = u - (1 - s)
                y = np.where(u <= 1 - s, np.minimum(u, 1.0),
                             np.where(u >= 1 + s, 1.0, u - d * d / (4 * s)))
            return np.where(x < 0, -1.0, 1.0) * y * limit
        return clip
    return hd.nonlinearity(kind, **params)


def device_label(kind: str, params: dict) -> str:
    if kind == "parametric":
        return (f"parametricClip(threshold: {fmt(params['threshold'])}, knee: {fmt(params['knee'])}, "
                f"asymmetry: {fmt(params['asymmetry'])})")
    return hd.source_label(kind, params, None)


@dataclass(frozen=True)
class Device:
    kind: str
    params: dict
    pre: Optional[Filter] = None
    post: Optional[Filter] = None
    inverted: bool = False

    def render(self, x: np.ndarray, fs: float) -> np.ndarray:
        y = np.asarray(x, dtype=np.float64)
        if self.pre is not None:
            y = self.pre.biquad(fs).process(y)
        y = nonlinearity(self.kind, self.params)(y)
        if self.post is not None:
            y = self.post.biquad(fs).process(y)
        if self.inverted:
            y = -y
        return y

    @property
    def memoryless_unfiltered(self) -> bool:
        return self.pre is None and self.post is None


# ---------------------------------------------------------------------------
# The stimulus (manifest ``stimulus``)


@dataclass(frozen=True)
class Plan:
    frequency: float
    amplitude: float
    duration: float
    fs: float
    preroll: float
    tail: float
    fade: float
    skip_cycles: int

    @classmethod
    def from_manifest(cls, tc: dict, frequency: float, amplitude: float, duration: Optional[float],
                      fs: Optional[float]) -> "Plan":
        s = tc["stimulus"]
        return cls(frequency=frequency, amplitude=amplitude,
                   duration=s["durationS"] if duration is None else duration,
                   fs=s["sampleRateHz"] if fs is None else fs,
                   preroll=s["prerollS"], tail=s["tailS"], fade=s["fadeS"], skip_cycles=int(s["skipCycles"]))

    @property
    def level_dbfs(self) -> float:
        return 20 * math.log10(self.amplitude)

    @property
    def samples_per_cycle(self) -> float:
        return self.fs / self.frequency

    @property
    def preroll_samples(self) -> int:
        return int(self.preroll * self.fs)

    def tone(self) -> np.ndarray:
        count = int(self.duration * self.fs)
        fade = int(self.fade * self.fs)
        n = np.arange(count, dtype=np.float64)
        tone = self.amplitude * np.sin(2 * np.pi * self.frequency * n / self.fs)
        m = min(fade, count // 2)
        i = np.arange(m, dtype=np.float64)
        w = 0.5 * (1 - np.cos(np.pi * i / fade))
        tone[:m] *= w
        tone[count - 1 - np.arange(m)] *= w
        return tone

    def stimulus(self) -> np.ndarray:
        return np.concatenate([np.zeros(self.preroll_samples), self.tone(), np.zeros(int(self.tail * self.fs))])


def note_frequency(tc: dict, note: str) -> float:
    """The plan's own name→Hz: the manifest's probe table where it lists
    the note (E2 verbatim), exact 12-TET with A4 = 440 otherwise."""
    s = tc["stimulus"]
    for name, hz in zip(s["probeNotes"], s["probeNoteHz"]):
        if name == note:
            return float(hz)
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", note)
    if not m:
        raise SystemExit(f"--note '{note}' is not a note name")
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[m.group(1).upper()]
    base += {"": 0, "#": 1, "b": -1}[m.group(2)]
    midi = 12 * (int(m.group(3)) + 1) + base
    return 440.0 * 2 ** ((midi - 69) / 12)


# ---------------------------------------------------------------------------
# The averaged cycle (manifest ``binning``) and the figure (``figure``)


@dataclass
class Figure:
    frequency: float
    fs: float
    cycle_in: np.ndarray
    cycle_out: np.ndarray
    static_x: np.ndarray
    static_y: np.ndarray
    hysteresis: float
    linear: float
    nonlinear: float


def binned_cycle(tone: np.ndarray, output: np.ndarray, latency: int, f0: float, fs: float,
                 skip_cycles: int, bins: int) -> Tuple[np.ndarray, np.ndarray]:
    spc = fs / f0
    start = int(skip_cycles * spc)
    stop = min(len(tone), len(output) - latency)
    i = np.arange(start, stop)
    phase = (i / spc) % 1.0
    b = np.minimum(bins - 1, (phase * bins).astype(np.int64))
    counts = np.bincount(b, minlength=bins)
    sum_in = np.bincount(b, weights=tone[i], minlength=bins)
    sum_out = np.bincount(b, weights=output[i + latency], minlength=bins)
    cycle_in = np.where(counts > 0, sum_in / np.maximum(counts, 1), 0.0)
    cycle_out = np.where(counts > 0, sum_out / np.maximum(counts, 1), 0.0)
    return cycle_in, cycle_out


# --- LoopGeometry: the unsigned lobe area ---------------------------------


def _signed_area(pts: List[Tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2


def _earliest_crossing(v: Tuple[float, float], path: List[Tuple[float, float]]):
    if len(path) < 3:
        return None
    tail = path[-1]
    d1x, d1y = v[0] - tail[0], v[1] - tail[1]
    best = None
    for k in range(len(path) - 2):
        p3, p4 = path[k], path[k + 1]
        d2x, d2y = p4[0] - p3[0], p4[1] - p3[1]
        denom = d1x * d2y - d1y * d2x
        if abs(denom) <= 1e-30:
            continue
        rx, ry = p3[0] - tail[0], p3[1] - tail[1]
        t = (rx * d2y - ry * d2x) / denom
        u = (rx * d1y - ry * d1x) / denom
        eps = 1e-9
        if not (t > -eps and t < 1 + eps and u > -eps and u < 1 + eps):
            continue
        if best is None or t < best[2]:
            best = (k, (tail[0] + t * d1x, tail[1] + t * d1y), t)
    return None if best is None else (best[0], best[1])


def unsigned_lobe_area(xs: np.ndarray, ys: np.ndarray, floor_fraction: float) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    box = 4 * float(np.max(np.abs(xs[:n]))) * float(np.max(np.abs(ys[:n])))
    if box <= 0:
        return 0.0
    area_floor = floor_fraction * box
    total = 0.0
    path = [(float(xs[0]), float(ys[0]))]
    for i in range(1, n + 1):
        v = (float(xs[i % n]), float(ys[i % n]))
        while True:
            hit = _earliest_crossing(v, path)
            if hit is None:
                break
            edge, point = hit
            lobe = [point] + path[edge + 1:]
            area = abs(_signed_area(lobe))
            if area >= area_floor:
                total += area
            del path[edge + 1:]
            path.append(point)
        path.append(v)
    path.pop()
    outer = abs(_signed_area(path))
    if outer >= area_floor:
        total += outer
    return total


# --- the static curve ------------------------------------------------------


def _monotonic_branch(x: np.ndarray, y: np.ndarray, a: int, b: int, descending: bool):
    n = len(x)
    pts = []
    i = a
    while True:
        pts.append((float(x[i]), float(y[i])))
        if i == b:
            break
        i = (i + 1) % n
    if descending:
        pts.reverse()
    cleaned = []
    for p in pts:
        if cleaned and p[0] <= cleaned[-1][0]:
            continue
        cleaned.append(p)
    return cleaned


def _interpolate(branch, x: float) -> Optional[float]:
    if not branch:
        return None
    if x <= branch[0][0]:
        return branch[0][1]
    if x >= branch[-1][0]:
        return branch[-1][1]
    for i in range(1, len(branch)):
        if branch[i][0] >= x:
            a, b = branch[i - 1], branch[i]
            span = b[0] - a[0]
            if span <= 0:
                return a[1]
            t = (x - a[0]) / span
            return a[1] + t * (b[1] - a[1])
    return branch[-1][1]


def figure(cycle_in: np.ndarray, cycle_out: np.ndarray, frequency: float, fs: float, tc: dict) -> Figure:
    fg = tc["figure"]
    floor_fraction = float(fg["minimumLobeAreaFraction"])
    grid_count = int(fg["staticCurveGridPoints"])
    n = len(cycle_in)
    x_max = float(np.max(np.abs(cycle_in))) if n else 0.0
    y_max = float(np.max(np.abs(cycle_out))) if n else 0.0
    box = 4 * x_max * y_max
    area = unsigned_lobe_area(cycle_in, cycle_out, floor_fraction)
    hysteresis = area / box if box > 0 else 0.0

    linear = 0.0
    nonlinear = 0.0
    if n >= 3 and box > 0:
        theta = 2 * np.pi * np.arange(n) / n
        ax = float(np.sum(cycle_in * np.cos(theta))) * 2 / n
        bx = float(np.sum(cycle_in * np.sin(theta))) * 2 / n
        ay = float(np.sum(cycle_out * np.cos(theta))) * 2 / n
        by = float(np.sum(cycle_out * np.sin(theta))) * 2 / n
        dcy = float(np.sum(cycle_out)) / n
        linear = math.pi * abs(ax * by - ay * bx) / box
        residual = cycle_out - dcy - ay * np.cos(theta) - by * np.sin(theta)
        nonlinear = unsigned_lobe_area(cycle_in, residual, floor_fraction) / box

    static_x: List[float] = []
    static_y: List[float] = []
    if n >= 4 and x_max > 0:
        i_min = int(np.argmin(cycle_in)) if False else 0
        i_max = 0
        # First minimum / maximum by strict comparison, as the rule states.
        for b in range(n):
            if cycle_in[b] < cycle_in[i_min]:
                i_min = b
            if cycle_in[b] > cycle_in[i_max]:
                i_max = b
        rising = _monotonic_branch(cycle_in, cycle_out, i_min, i_max, False)
        falling = _monotonic_branch(cycle_in, cycle_out, i_max, i_min, True)
        lo, hi = float(cycle_in[i_min]), float(cycle_in[i_max])
        if hi > lo and len(rising) > 1 and len(falling) > 1:
            for g in range(grid_count):
                x = lo + (hi - lo) * g / (grid_count - 1)
                up = _interpolate(rising, x)
                down = _interpolate(falling, x)
                if up is None or down is None:
                    continue
                static_x.append(x)
                static_y.append((up + down) / 2)
    return Figure(frequency, fs, cycle_in, cycle_out, np.array(static_x), np.array(static_y),
                  hysteresis, linear, nonlinear)


# ---------------------------------------------------------------------------
# The cycle's spectrum, the paired H1's reads


def cycle_spectrum(cycle: np.ndarray) -> np.ndarray:
    """``Y[k] = Σ_i y_i e^{−j2πki/n}`` for k = 0…n/2, by direct sums."""
    n = len(cycle)
    half = n // 2
    i = np.arange(n)
    out = np.zeros(half + 1, dtype=np.complex128)
    for k in range(half + 1):
        angle = -2 * np.pi * k * i / n
        out[k] = complex(float(np.sum(cycle * np.cos(angle))), float(np.sum(cycle * np.sin(angle))))
    return out


def fundamental_phase(cycle_in: np.ndarray, cycle_out: np.ndarray) -> Optional[float]:
    n = len(cycle_out)
    if n <= 2:
        return None
    i = np.arange(n)
    angle = -2 * np.pi * i / n
    c, s = np.cos(angle), np.sin(angle)
    out_re, out_im = float(np.sum(cycle_out * c)), float(np.sum(cycle_out * s))
    in_re, in_im = float(np.sum(cycle_in * c)), float(np.sum(cycle_in * s))
    if (out_re == 0 and out_im == 0) or (in_re == 0 and in_im == 0):
        return None
    return math.atan2(out_im, out_re) - math.atan2(in_im, in_re)


def branch_phase(spectrum: np.ndarray, bin_width: float, f: float) -> Optional[float]:
    i = swift_round(f / bin_width)
    if i < 0 or i >= len(spectrum):
        return None
    return math.atan2(spectrum[i].imag, spectrum[i].real)


def polarity_reading(h1: np.ndarray, bin_width: float, low_hz: float, cap_hz: float,
                     threshold: float) -> Optional[dict]:
    if bin_width <= 0:
        return None
    low = max(1, int(math.ceil(low_hz / bin_width)))
    high = min(len(h1) - 1, int(cap_hz / bin_width))
    if low > high:
        return None
    sum_re = 0.0
    total = 0.0
    for b in range(low, high + 1):
        mag = abs(h1[b])
        if mag <= 0:
            continue
        sum_re += mag * h1[b].real
        total += mag * mag
    if total <= 0:
        return None
    mean_re = sum_re / total
    return dict(inverting=mean_re < 0, confidence=abs(mean_re), confident=abs(mean_re) >= threshold)


# ---------------------------------------------------------------------------
# Orientation (manifest ``orientation``)


def orientation_resolved(fig: Figure, h1: Optional[np.ndarray], bin_width: float, tc: dict
                         ) -> Tuple[Figure, bool, Optional[float], Optional[dict]]:
    o = tc["orientation"]
    psi1 = fundamental_phase(fig.cycle_in, fig.cycle_out)
    polarity = None
    if h1 is not None:
        polarity = polarity_reading(h1, bin_width, 20.0, 2000.0, o["polarityConfidenceThreshold"])
    n = len(fig.cycle_out)
    if h1 is None or n <= 2 or n % 2 != 0 or psi1 is None or polarity is None or not polarity["confident"]:
        return fig, False, psi1, polarity
    nearest = round(psi1 / math.pi) * math.pi
    if abs(psi1 - nearest) > o["halfCycleLockTolerance"]:
        return fig, False, psi1, polarity
    captured_inverting = math.cos(psi1) < 0
    if captured_inverting == polarity["inverting"]:
        return fig, False, psi1, polarity
    half = n // 2
    corrected = np.concatenate([fig.cycle_out[half:], fig.cycle_out[:half]])
    return figure(fig.cycle_in, corrected, fig.frequency, fig.fs, tc), True, psi1, polarity


# ---------------------------------------------------------------------------
# Fundamental presence (manifest ``fundamentalPresence``)


def presence_reading(fundamental_db: Optional[float], loudest_db: Optional[float], separation: float) -> str:
    if fundamental_db is None or loudest_db is None:
        return "undetermined"
    return "absent" if loudest_db - fundamental_db >= separation else "present"


def fundamental_presence(fig: Figure, paired: Optional[hd.Analysis], m: dict) -> str:
    tc = m["transferCurve"]
    separation = tc["fundamentalPresence"]["analyzerSeparationDB"]
    if paired is not None:
        sweep = paired.sweep
        f0 = fig.frequency
        if sweep.f1 <= f0 <= sweep.f2 and 1 in paired.spectra:
            h1 = hd.magnitude_at_output_frequency(paired.spectra[1], paired.bin_width, f0)
            if h1 is not None and h1 > 0:
                band = m["harmonicDistortion"]["audibleBand"]
                loudest = h1
                for k in paired.orders:
                    if k < 2:
                        continue
                    fk = f0 * k
                    if not (band["lowHz"] <= fk <= band["highHz"]) or not hd.is_valid(sweep, k, f0):
                        continue
                    mk = hd.magnitude_at_output_frequency(paired.spectra[k], paired.bin_width, fk)
                    if mk is None:
                        continue
                    loudest = max(loudest, mk)
                reading = presence_reading(20 * math.log10(h1), 20 * math.log10(loudest), separation)
                if reading != "undetermined":
                    return reading
    n = len(fig.cycle_out)
    max_order = 9
    if n < 2 * (max_order + 1):
        return "undetermined"
    i = np.arange(n)

    def magnitude(k):
        w = 2 * np.pi * k / n
        re = float(np.sum(fig.cycle_out * np.cos(w * i)))
        im = -float(np.sum(fig.cycle_out * np.sin(w * i)))
        return 2 * math.hypot(re, im) / n
    h1 = magnitude(1)
    if h1 <= 0:
        return "undetermined"
    loudest = max([h1] + [magnitude(k) for k in range(2, max_order + 1)])
    return presence_reading(20 * math.log10(h1), 20 * math.log10(loudest), separation)


# ---------------------------------------------------------------------------
# The §6.5 removal (manifest ``derotation``)


class MonotoneCubic:
    """Fritsch–Carlson shape-preserving cubic Hermite; constant beyond the
    end nodes; a single node is a constant, no nodes are zero."""

    def __init__(self, nodes: Sequence[Tuple[float, float]]):
        self.xs = [p[0] for p in nodes]
        self.ys = [p[1] for p in nodes]
        n = len(nodes)
        if n < 2:
            self.m = [0.0] * n
            return
        sec = [(self.ys[i + 1] - self.ys[i]) / (self.xs[i + 1] - self.xs[i]) for i in range(n - 1)]
        m = [0.0] * n
        m[0] = sec[0]
        m[-1] = sec[-1]
        for i in range(1, n - 1):
            m[i] = 0.0 if sec[i - 1] * sec[i] <= 0 else (sec[i - 1] + sec[i]) / 2
        for i in range(n - 1):
            if sec[i] == 0:
                m[i] = 0.0
                m[i + 1] = 0.0
                continue
            alpha = m[i] / sec[i]
            beta = m[i + 1] / sec[i]
            radius = alpha * alpha + beta * beta
            if radius > 9:
                scale = 3 / math.sqrt(radius)
                m[i] = scale * alpha * sec[i]
                m[i + 1] = scale * beta * sec[i]
        self.m = m

    def value(self, x: float) -> float:
        if not self.xs:
            return 0.0
        if x <= self.xs[0]:
            return self.ys[0]
        if x >= self.xs[-1]:
            return self.ys[-1]
        i = 0
        while self.xs[i + 1] < x:
            i += 1
        h = self.xs[i + 1] - self.xs[i]
        t = (x - self.xs[i]) / h
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * self.ys[i] + (t3 - 2 * t2 + t) * h * self.m[i]
                + (-2 * t3 + 3 * t2) * self.ys[i + 1] + (t3 - t2) * h * self.m[i + 1])


def scan_steps(rule: str) -> Tuple[float, float]:
    """The frame fit's coarse and fine steps, from the rule string (they are
    function-body literals, recorded there and nowhere else)."""
    coarse = float(re.search(r"steps of ([0-9.]+) samples", rule).group(1))
    fine = float(re.search(r"in steps of ([0-9.]+);", rule).group(1))
    return coarse, fine


@dataclass
class Fit:
    frame_shift: float
    residual_rms: float
    harmonic_residual_rms: float
    terms: List[dict]
    fundamental_lattice_inverted: Optional[bool]

    @property
    def voting(self) -> int:
        return len(self.terms)

    @property
    def highest_voting_order(self) -> int:
        return max(t["order"] for t in self.terms) if self.terms else 0


@dataclass
class Compensation:
    kind: str  # compensated | pairing_mismatch | insufficient_evidence | negligible_raw_loop | metric_guard_tripped
    figure: Optional[Figure] = None
    fit: Optional[Fit] = None
    fittable_terms: Optional[int] = None
    negligible_total: Optional[float] = None
    guard_comp: Optional[float] = None
    guard_raw: Optional[float] = None

    @property
    def accepted(self) -> Optional[Figure]:
        return self.figure if self.kind == "compensated" else None

    def confirmed_polarity_inverting(self, tolerance: float) -> Optional[bool]:
        if self.kind not in ("compensated", "negligible_raw_loop") or self.fit is None:
            return None
        if self.fit.harmonic_residual_rms > tolerance:
            return None
        return self.fit.fundamental_lattice_inverted


def branch_convention(order: int) -> float:
    return wrap((order - 1) * math.pi / 2)


def branch_phase_compensation(fig: Figure, paired: hd.Analysis, m: dict) -> Compensation:
    tc = m["transferCurve"]
    d = tc["derotation"]
    o = tc["orientation"]
    dead_zone = d["deadZone"]
    raw_total = fig.hysteresis
    in_dead_zone = raw_total < dead_zone

    def unfittable(count: int) -> Compensation:
        if in_dead_zone:
            return Compensation("negligible_raw_loop", negligible_total=raw_total)
        return Compensation("insufficient_evidence", fittable_terms=count)

    n = len(fig.cycle_out)
    half = n // 2
    f0, fs = fig.frequency, fig.fs
    if n <= 4 or f0 <= 0 or fs <= 0:
        return unfittable(0)
    Y = cycle_spectrum(fig.cycle_out)
    X1 = cycle_spectrum(fig.cycle_in)[1] if True else None
    # The input's fundamental phase by the same direct sum (Y's convention).
    i = np.arange(n)
    angle = -2 * np.pi * i / n
    in_re, in_im = float(np.sum(fig.cycle_in * np.cos(angle))), float(np.sum(fig.cycle_in * np.sin(angle)))
    if in_re == 0 and in_im == 0:
        return unfittable(0)
    input_phase = math.atan2(in_im, in_re)
    mag1 = abs(Y[1])
    if 1 not in paired.spectra:
        return unfittable(0)
    h1 = paired.spectra[1]
    bw = paired.bin_width
    branch_mag1 = hd.magnitude_at_output_frequency(h1, bw, f0)
    if mag1 <= 0 or branch_mag1 is None or branch_mag1 <= 0:
        return unfittable(0)

    floor = d["fitMagnitudeFloor"]
    terms = []
    for k in paired.orders:
        if k < 1 or k > half:
            continue
        fk = k * f0
        if not hd.is_valid(paired.sweep, k, f0):
            continue
        bp = branch_phase(paired.spectra[k], bw, fk)
        bm = hd.magnitude_at_output_frequency(paired.spectra[k], bw, fk)
        if bp is None or bm is None:
            continue
        cycle_mag = abs(Y[k]) / mag1
        branch_rel = bm / branch_mag1
        if k != 1 and not (cycle_mag >= floor and branch_rel >= floor):
            continue
        cyc = math.atan2(Y[k].imag, Y[k].real) - k * input_phase
        raw = cyc - bp - branch_convention(k)
        terms.append(dict(order=k, diff=wrap(raw), weight=min(1.0, cycle_mag), cyc=cyc))
    if len(terms) < int(d["minimumFitTerms"]):
        return unfittable(len(terms))

    omega0 = 2 * math.pi * f0 / fs
    period = fs / f0
    coarse, fine_step = scan_steps(d["frameFitRule"])

    def coherence(shift: float) -> float:
        score = 0.0
        for t in terms:
            score += t["weight"] * math.cos(t["diff"] - t["order"] * omega0 * shift)
        return score

    best_shift = 0.0
    best_score = -math.inf
    shift = -period / 2
    while shift <= period / 2:
        s = coherence(shift)
        if s > best_score:
            best_score, best_shift = s, shift
        shift += coarse
    fine = best_shift - coarse
    while fine <= best_shift + coarse:
        s = coherence(fine)
        if s > best_score:
            best_score, best_shift = s, fine
        fine += fine_step

    weighted = total = harmonic = harmonic_total = 0.0
    residuals: Dict[int, float] = {}
    mapped: Dict[int, float] = {}
    for t in terms:
        r = wrap(t["diff"] - t["order"] * omega0 * best_shift)
        residuals[t["order"]] = r
        mapped[t["order"]] = t["cyc"] - r
        weighted += t["weight"] * r * r
        total += t["weight"]
        if t["order"] >= 2:
            harmonic += t["weight"] * r * r
            harmonic_total += t["weight"]
    if 1 not in mapped:
        return unfittable(len(terms))
    mapped1 = mapped[1]
    polarity = polarity_reading(h1, bw, 20.0, 2000.0, o["polarityConfidenceThreshold"])
    fundamental_inverted: Optional[bool] = None
    if polarity is not None and polarity["confident"]:
        sigma1 = math.pi if polarity["inverting"] else 0.0
        fundamental_inverted = polarity["inverting"]
    else:
        sigma1 = round(mapped1 / math.pi) * math.pi
        excess = mapped1 - sigma1
        if abs(excess) <= d["latticeSignConfidence"]:
            fundamental_inverted = int(round(sigma1 / math.pi)) % 2 != 0
    excess1 = wrap(mapped1 - sigma1)

    # Unwrapped H1 phase at every harmonic frequency.
    phi1u = [0.0] * (half + 1)
    prev = 0.0
    have = False
    for k in range(1, half + 1):
        p = branch_phase(h1, bw, k * f0)
        if p is not None:
            if have:
                prev = p + 2 * math.pi * round((prev - p) / (2 * math.pi))
            else:
                prev = p
                have = True
        phi1u[k] = prev
    fundamental_burden = excess1 - omega0 * best_shift

    def filter_model(k: int) -> float:
        return phi1u[k] - phi1u[1] + fundamental_burden

    def folded(value: float, trend: float) -> float:
        return value - round((value - trend) / math.pi) * math.pi

    fit_orders = sorted(t["order"] for t in terms)
    weight_by_order = {t["order"]: t["weight"] for t in terms}
    burdens = {1: excess1}
    slope = 0.0
    share_num = share_den = 0.0
    for k in fit_orders:
        if k < 2:
            continue
        trend = slope * k + filter_model(k) if share_den > 0 else k * excess1
        burden = folded(mapped.get(k, 0.0), trend)
        burdens[k] = burden
        w = weight_by_order.get(k, 0.0)
        share_num += w * k * (burden - filter_model(k))
        share_den += w * k * k
        slope = share_num / share_den

    out_terms = []
    for t in terms:
        burden = burdens.get(t["order"], 0.0)
        out_terms.append(dict(order=t["order"], rel_mag=t["weight"], residual=residuals.get(t["order"], 0.0),
                              lattice_excess=wrap(burden)))
    fit = Fit(frame_shift=best_shift,
              residual_rms=math.sqrt(weighted / total) if total > 0 else math.inf,
              harmonic_residual_rms=math.sqrt(harmonic / harmonic_total) if harmonic_total > 0 else math.inf,
              terms=out_terms, fundamental_lattice_inverted=fundamental_inverted)
    if in_dead_zone:
        return Compensation("negligible_raw_loop", fit=fit, negligible_total=raw_total)
    if fit.harmonic_residual_rms > d["pairingResidualTolerance"]:
        return Compensation("pairing_mismatch", fit=fit)

    deviation = MonotoneCubic([(float(k), burdens[k] - slope * k - filter_model(k)) for k in fit_orders if k in burdens])
    top = half - 1 if n % 2 == 0 else half
    Yc = Y.copy()
    for k in range(1, top + 1):
        theta = slope * k + filter_model(k) + deviation.value(float(k))
        c, s = math.cos(-theta), math.sin(-theta)
        re, im = Yc[k].real, Yc[k].imag
        Yc[k] = complex(re * c - im * s, re * s + im * c)
    compensated = np.zeros(n)
    for idx in range(n):
        total_i = Yc[0].real
        for k in range(1, half + 1):
            ang = 2 * math.pi * k * idx / n
            w = 1.0 if (k == half and n % 2 == 0) else 2.0
            total_i += w * (Yc[k].real * math.cos(ang) - Yc[k].imag * math.sin(ang))
        compensated[idx] = total_i / n
    comp_fig = figure(fig.cycle_in, compensated, f0, fs, tc)
    tol = d["compensationLoopTolerance"]
    if comp_fig.linear > fig.linear + tol:
        return Compensation("metric_guard_tripped", fit=fit, guard_comp=comp_fig.linear, guard_raw=fig.linear)
    if comp_fig.nonlinear > fig.nonlinear + tol:
        return Compensation("metric_guard_tripped", fit=fit, guard_comp=comp_fig.nonlinear, guard_raw=fig.nonlinear)
    return Compensation("compensated", figure=comp_fig, fit=fit)


# ---------------------------------------------------------------------------
# Ground truth (manifest ``synthesis``)


@dataclass
class Truth:
    kind: str
    amplitude: float
    omega0: float
    pre_gain: float
    pre_phase: float
    post: np.ndarray  # complex response at k·f0, k = 0…K
    advance: float
    sign: float
    C: np.ndarray  # coefficients k = 0…K
    device: Device
    orders: int

    @classmethod
    def build(cls, device: Device, plan: Plan, advance: float, tc: dict) -> "Truth":
        sy = tc["synthesis"]
        K = int(sy["truthOrders"])
        N = int(sy["quadraturePoints"])
        fs, f0, A = plan.fs, plan.frequency, plan.amplitude
        if device.pre is not None:
            r = device.pre.biquad(fs).response(f0)
            pre_gain, pre_phase = abs(r), math.atan2(r.imag, r.real)
        else:
            pre_gain, pre_phase = 1.0, 0.0
        post = np.ones(K + 1, dtype=np.complex128)
        if device.post is not None:
            bq = device.post.biquad(fs)
            post = np.array([bq.response(k * f0) for k in range(K + 1)])
        kind = "memoryless" if device.memoryless_unfiltered and advance == 0 else "series"
        theta = 2 * np.pi * np.arange(N) / N
        v = nonlinearity(device.kind, device.params)(pre_gain * A * np.sin(theta))
        C = np.fft.rfft(v)[: K + 1] / N
        return cls(kind, A, 2 * math.pi * f0 / fs, pre_gain, pre_phase, post, advance,
                   -1.0 if device.inverted else 1.0, C, device, K)

    def memoryless(self, x):
        return self.sign * nonlinearity(self.device.kind, self.device.params)(np.asarray(x, dtype=np.float64))

    def _series(self, theta, shifted: bool):
        scalar = np.ndim(theta) == 0
        theta = np.atleast_1d(np.asarray(theta, dtype=np.float64))
        k = np.arange(1, self.orders + 1)
        gains = np.abs(self.post[1:])
        y = np.full_like(theta, self.C[0].real * self.post[0].real)
        if shifted:
            angles = np.outer(theta + self.pre_phase + self.omega0 * self.advance, k) + np.angle(self.post[1:])
        else:
            angles = np.outer(theta, k)
        y = y + 2 * np.sum(gains * (self.C[1:].real * np.cos(angles) - self.C[1:].imag * np.sin(angles)), axis=1)
        y = self.sign * y
        return float(y[0]) if scalar else y

    def raw(self, theta):
        if self.kind == "memoryless":
            return self.memoryless(self.amplitude * np.sin(theta))
        return self._series(theta, True)

    def compensated(self, theta):
        if self.kind == "memoryless":
            return self.memoryless(self.amplitude * np.sin(theta))
        return self._series(theta, False)

    def phase_of_input(self, x, ascending: bool):
        s = np.clip(np.asarray(x, dtype=np.float64) / self.amplitude, -1, 1)
        t = np.arcsin(s)
        return t if ascending else np.pi - t

    def raw_bin(self, b: int, n: int, x: float):
        """Bin b's truth: y(x_b) for the memoryless kind, the series at the
        bin's centre phase otherwise (the manifest's cycleTruthRule)."""
        return self.memoryless(x) if self.kind == "memoryless" else self.raw(2 * math.pi * (b + 0.5) / n)

    def compensated_bin(self, b: int, n: int, x: float):
        return self.memoryless(x) if self.kind == "memoryless" else self.compensated(2 * math.pi * (b + 0.5) / n)

    def raw_at(self, x, ascending: bool):
        return self.memoryless(x) if self.kind == "memoryless" else self.raw(self.phase_of_input(x, ascending))

    def compensated_at(self, x, ascending: bool):
        return self.memoryless(x) if self.kind == "memoryless" else self.compensated(self.phase_of_input(x, ascending))

    def raw_static(self, x):
        if self.kind == "memoryless":
            return self.memoryless(x)
        return (self.raw_at(x, True) + self.raw_at(x, False)) / 2

    def compensated_static(self, x):
        if self.kind == "memoryless":
            return self.memoryless(x)
        return (self.compensated_at(x, True) + self.compensated_at(x, False)) / 2

    @property
    def fundamental(self) -> Tuple[float, float]:
        c1 = self.C[1]
        if self.kind == "memoryless":
            a, b = 2 * c1.real * self.sign, -2 * c1.imag * self.sign
        else:
            psi = self.pre_phase + self.omega0 * self.advance + math.atan2(self.post[1].imag, self.post[1].real)
            g = 2 * abs(self.post[1]) * self.sign
            a = g * (c1.real * math.cos(psi) - c1.imag * math.sin(psi))
            b = g * (-c1.real * math.sin(psi) - c1.imag * math.cos(psi))
        return math.hypot(a, b), math.atan2(a, b)

    @property
    def output_peak(self) -> float:
        n = 4096
        grid = 2 * np.pi * np.arange(n) / n
        values = np.abs(self.raw(grid))
        at = int(np.argmax(values))
        peak = float(values[at])
        lo = 2 * math.pi * (at - 1) / n
        hi = 2 * math.pi * (at + 1) / n
        phi = (math.sqrt(5) - 1) / 2
        a = hi - phi * (hi - lo)
        b = lo + phi * (hi - lo)
        fa = float(abs(self.raw(np.array([a]))[0]))
        fb = float(abs(self.raw(np.array([b]))[0]))
        for _ in range(60):
            if fa > fb:
                hi, b, fb = b, a, fa
                a = hi - phi * (hi - lo)
                fa = float(abs(self.raw(np.array([a]))[0]))
            else:
                lo, a, fa = a, b, fb
                b = lo + phi * (hi - lo)
                fb = float(abs(self.raw(np.array([b]))[0]))
        return max(peak, fa, fb)

    @property
    def expected_linear(self) -> float:
        peak = self.output_peak
        if peak <= 0:
            return 0.0
        R, phi = self.fundamental
        return math.pi / 4 * (R / peak) * abs(math.sin(phi))

    @property
    def tail_ratio(self) -> float:
        c1 = abs(self.C[1])
        return abs(self.C[self.orders]) / c1 if c1 > 0 else math.nan


# ---------------------------------------------------------------------------
# The run


@dataclass
class SynthPlan:
    device: Device
    plan: Plan
    note: Optional[str]
    latency_error: int = 0
    half_cycle_shift: bool = False
    paired: bool = False
    sweep_duration: float = 10.0
    sweep_amplitude: Optional[float] = None

    @property
    def half_cycle_samples(self) -> int:
        return swift_round(self.plan.samples_per_cycle / 2)

    @property
    def analyzed_latency(self) -> int:
        return self.latency_error + (self.half_cycle_samples if self.half_cycle_shift else 0)


@dataclass
class Result:
    synth: SynthPlan
    captured: Figure
    paired: Optional[hd.Analysis]
    displayed: Figure
    flipped: bool
    psi1: Optional[float]
    polarity: Optional[dict]
    fundamental: str
    compensation: Optional[Compensation]
    truth: Truth


def pairing_sweep(m: dict, synth: SynthPlan) -> hd.Sweep:
    s = m["harmonicDistortion"]["stimulus"]
    return hd.Sweep(f1=s["startHz"], f2=s["endHz"], requested_duration=synth.sweep_duration,
                    fs=synth.plan.fs,
                    amplitude=synth.plan.amplitude if synth.sweep_amplitude is None else synth.sweep_amplitude,
                    fade_in=s["fadeInS"], fade_out=s["fadeOutS"])


def run(synth: SynthPlan, m: dict) -> Result:
    tc = m["transferCurve"]
    plan = synth.plan
    capture = synth.device.render(plan.stimulus(), plan.fs)
    output = capture[min(plan.preroll_samples, len(capture)):]
    cycle_in, cycle_out = binned_cycle(plan.tone(), output, synth.analyzed_latency, plan.frequency, plan.fs,
                                       plan.skip_cycles, int(tc["binning"]["phaseBins"]))
    captured = figure(cycle_in, cycle_out, plan.frequency, plan.fs, tc)
    paired = None
    if synth.paired:
        sweep = pairing_sweep(m, synth)
        hd_m = m["harmonicDistortion"]
        sweep_capture = np.concatenate([synth.device.render(sweep.samples(), sweep.fs),
                                        np.zeros(int(hd_m["synthesis"]["padSamples"]))])
        paired = hd.analyze(sweep_capture, sweep, hd_m)
    h1 = paired.spectra.get(1) if paired is not None else None
    bw = paired.bin_width if paired is not None else 0.0
    displayed, flipped, psi1, polarity = orientation_resolved(captured, h1, bw, tc)
    fundamental = fundamental_presence(displayed, paired, m)
    compensation = branch_phase_compensation(displayed, paired, m) if paired is not None else None
    advance = float(synth.analyzed_latency) - (plan.samples_per_cycle / 2 if flipped else 0.0)
    truth = Truth.build(synth.device, plan, advance, tc)
    return Result(synth, captured, paired, displayed, flipped, psi1, polarity, fundamental, compensation, truth)


def expected_class(result: Result, tc: dict) -> str:
    if result.paired is None:
        return "raw_no_reference"
    if result.truth.kind == "memoryless":
        return "negligible_raw_loop"
    if result.truth.expected_linear >= tc["derotation"]["deadZone"]:
        return "compensated"
    return "nan"


def figure_class(result: Result) -> str:
    if result.fundamental == "absent":
        return "raw_fundamental_absent"
    if result.compensation is None:
        return "raw_no_reference"
    return result.compensation.kind


def memory_verdict(area: float, tc: dict) -> str:
    v = tc["memoryVerdict"]
    if area < v["memorylessBelow"]:
        return "memoryless_ish"
    if area < v["memoryEffectsFrom"]:
        return "hint_or_filter_residue"
    return "memory_effects"


def flag(b) -> str:
    return "nan" if b is None else ("1" if b else "0")


def write_tsv(result: Result, m: dict, out) -> None:
    tc = m["transferCurve"]
    synth = result.synth
    plan = synth.plan
    dev = synth.device
    truth = result.truth
    comp = result.compensation
    accepted = comp.accepted if comp is not None else None
    fig = result.displayed
    fs = plan.fs
    out.write(f"# device: label={device_label(dev.kind, dev.params)} pre={dev.pre.label if dev.pre else 'none'} "
              f"post={dev.post.label if dev.post else 'none'} inverted={flag(dev.inverted)}\n")
    out.write(f"# stimulus: note={synth.note or 'none'} f0_hz={fmt(plan.frequency)} amplitude={fmt(plan.amplitude)} "
              f"level_dbfs={fmt(plan.level_dbfs)} fs={fmt(fs)} duration_s={fmt(plan.duration)} preroll_s={fmt(plan.preroll)} "
              f"tail_s={fmt(plan.tail)} fade_s={fmt(plan.fade)} skip_cycles={plan.skip_cycles} "
              f"phase_bins={len(fig.cycle_in)} samples_per_cycle={fmt(plan.samples_per_cycle)} "
              f"latency_error_samples={synth.latency_error} half_cycle_shift={flag(synth.half_cycle_shift)} "
              f"half_cycle_samples={synth.half_cycle_samples} analyzed_latency_samples={synth.analyzed_latency}\n")
    if result.paired is not None:
        sw = result.paired.sweep
        out.write(f"# pairing: sweep f1={fmt(sw.f1)} f2={fmt(sw.f2)} duration_s={fmt(sw.duration)} L={fmt(sw.rate_constant)} "
                  f"fs={fmt(sw.fs)} amplitude={fmt(sw.amplitude)} orders={int(m['harmonicDistortion']['extraction']['harmonicCount'])} "
                  f"measured={len(result.paired.orders)}\n")
    else:
        out.write("# pairing: none\n")
    skip_samples = int(plan.skip_cycles * plan.samples_per_cycle)

    def settling(f: Optional[Filter]):
        if f is None:
            return None, None
        r = f.biquad(fs).pole_radius()
        return r, r ** skip_samples
    pre_r, pre_res = settling(dev.pre)
    post_r, post_res = settling(dev.post)
    out.write(f"# settling: skip_samples={skip_samples} pre_pole_radius={fmt(pre_r)} pre_residual={fmt(pre_res)} "
              f"post_pole_radius={fmt(post_r)} post_residual={fmt(post_res)}\n")
    R, phi1 = truth.fundamental
    out.write(f"# truth: kind={truth.kind} orders={truth.orders} quadrature_points={int(tc['synthesis']['quadraturePoints'])} "
              f"pre_gain={fmt(truth.pre_gain)} pre_phase={fmt(truth.pre_phase)} post_gain_f0={fmt(abs(truth.post[1]))} "
              f"post_phase_f0={fmt(math.atan2(truth.post[1].imag, truth.post[1].real))} post_gain_dc={fmt(abs(truth.post[0]))} "
              f"advance_samples={fmt(truth.advance)} fundamental_magnitude={fmt(R)} fundamental_phase={fmt(phi1)} "
              f"output_peak={fmt(truth.output_peak)} tail_ratio={fmt(truth.tail_ratio)}\n")
    expected_linear = truth.expected_linear
    memoryless = truth.kind == "memoryless"
    linear_device = dev.kind == "identity"
    exp_nonlinear = 0.0 if (memoryless or linear_device) else None
    exp_hyst = 0.0 if memoryless else (expected_linear if linear_device else None)
    paired = result.paired is not None
    out.write(f"# expected: linear={fmt(expected_linear)} nonlinear={fmt(exp_nonlinear)} hyst={fmt(exp_hyst)} "
              f"comp_linear={fmt(0.0 if paired else None)} comp_nonlinear={fmt(0.0 if paired else None)} "
              f"comp_hyst={fmt(0.0 if paired else None)} frame_shift_samples={fmt(truth.advance if paired else None)} "
              f"class={expected_class(result, tc)} polarity_inverting={flag(dev.inverted)} "
              f"flipped={flag(synth.half_cycle_shift and paired)} psi1={fmt(phi1)}\n")
    psi1 = result.psi1
    lattice = None if psi1 is None else round(psi1 / math.pi) * math.pi
    dist = None if psi1 is None else abs(psi1 - lattice)
    out.write(f"# orientation: psi1={fmt(psi1)} lattice_distance={fmt(dist)} "
              f"lock_detectable={flag(None if dist is None else dist <= tc['orientation']['halfCycleLockTolerance'])} "
              f"captured_inverting={flag(None if psi1 is None else math.cos(psi1) < 0)} flipped={flag(result.flipped)}\n")
    pol = result.polarity
    out.write(f"# polarity: inverting={flag(None if pol is None else pol['inverting'])} "
              f"confidence={fmt(None if pol is None else pol['confidence'])} "
              f"confident={flag(None if pol is None else pol['confident'])}\n")
    shown = accepted if (accepted is not None and result.fundamental != "absent") else fig
    cls = figure_class(result)
    tile = None if result.fundamental == "absent" or comp is None else comp.confirmed_polarity_inverting(
        tc["derotation"]["pairingResidualTolerance"])
    shown_comp = accepted if result.fundamental != "absent" else None
    out.write(f"# figure: class={cls} fundamental={result.fundamental} hyst={fmt(fig.hysteresis)} linear={fmt(fig.linear)} "
              f"nonlinear={fmt(fig.nonlinear)} comp_hyst={fmt(None if shown_comp is None else shown_comp.hysteresis)} "
              f"comp_linear={fmt(None if shown_comp is None else shown_comp.linear)} "
              f"comp_nonlinear={fmt(None if shown_comp is None else shown_comp.nonlinear)} "
              f"memory_verdict={memory_verdict(shown.nonlinear, tc)} captured_input_peak={fmt(float(np.max(np.abs(fig.cycle_in))))} "
              f"tile_inverting={flag(tile)}\n")
    fit = comp.fit if comp is not None else None
    if fit is not None:
        out.write(f"# fit: frame_shift_samples={fmt(fit.frame_shift)} residual_rms={fmt(fit.residual_rms)} "
                  f"harmonic_residual_rms={fmt(fit.harmonic_residual_rms)} voting={fit.voting} "
                  f"highest_voting_order={fit.highest_voting_order} support_hz={fmt(fit.highest_voting_order * plan.frequency)} "
                  f"fundamental_lattice_inverted={flag(fit.fundamental_lattice_inverted)} "
                  f"negligible_total_area={fmt(comp.negligible_total)} guard_comp_area={fmt(comp.guard_comp)} "
                  f"guard_raw_area={fmt(comp.guard_raw)}\n")
        for t in sorted(fit.terms, key=lambda t: t["order"]):
            out.write(f"# term: order={t['order']} rel_mag={fmt(t['rel_mag'])} residual={fmt(t['residual'])} "
                      f"lattice_excess={fmt(t['lattice_excess'])}\n")
    else:
        out.write(f"# fit: none fittable_terms={fmt(None if comp is None else comp.fittable_terms)}\n")
    out.write("\t".join(COLUMNS) + "\n")
    n = len(fig.cycle_in)
    for b in range(n):
        x = float(fig.cycle_in[b])
        comp_y = None if accepted is None else float(accepted.cycle_out[b])
        out.write("\t".join(["cycle", str(b), fmt(x), fmt(float(fig.cycle_out[b])), fmt(comp_y),
                             fmt(float(truth.raw_bin(b, n, x))), fmt(float(truth.compensated_bin(b, n, x)))]) + "\n")
    for g in range(len(fig.static_x)):
        x = float(fig.static_x[g])
        comp_y = None
        if accepted is not None and g < len(accepted.static_y):
            comp_y = float(accepted.static_y[g])
        out.write("\t".join(["static", str(g), fmt(x), fmt(float(fig.static_y[g])), fmt(comp_y),
                             fmt(float(truth.raw_static(x))), fmt(float(truth.compensated_static(x)))]) + "\n")


# ---------------------------------------------------------------------------
# CLI — the same options as `analysisdump transfer-synth`


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--source", required=True,
                   choices=["identity", "tanh", "hardclip", "poly", "asymmetric", "parametric"])
    p.add_argument("--gain", type=float)
    p.add_argument("--threshold", type=float)
    p.add_argument("--a2", type=float, default=0.0)
    p.add_argument("--a3", type=float, default=0.0)
    p.add_argument("--negative-scale", type=float, default=0.5)
    p.add_argument("--knee", type=float, default=0.5)
    p.add_argument("--asymmetry", type=float, default=0.0)
    p.add_argument("--note")
    p.add_argument("--frequency", type=float)
    p.add_argument("--amplitude", type=float)
    p.add_argument("--rate", type=float)
    p.add_argument("--duration", type=float)
    p.add_argument("--pre", choices=["lowpass", "highpass"])
    p.add_argument("--pre-hz", type=float)
    p.add_argument("--pre-q", type=float)
    p.add_argument("--post", choices=["lowpass", "highpass"])
    p.add_argument("--post-hz", type=float)
    p.add_argument("--post-q", type=float)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--latency-error", type=int, default=0)
    p.add_argument("--half-cycle-shift", action="store_true")
    p.add_argument("--paired", action="store_true")
    p.add_argument("--sweep-duration", type=float, default=10.0)
    p.add_argument("--sweep-amplitude", type=float)
    p.add_argument("--out")
    return p


def plan_from_args(args, m: dict) -> SynthPlan:
    tc = m["transferCurve"]
    default_q = tc["biquad"]["defaultQ"]

    def filt(kind, hz, q):
        if kind is None:
            return None
        if hz is None:
            raise SystemExit(f"--{kind} needs its corner in Hz")
        return Filter("lowPass" if kind == "lowpass" else "highPass", hz, default_q if q is None else q)
    # The tool's defaults for each source (synth's own: tanh gain 4, hard
    # clip 0.1, asymmetric gain 3 / 0.5; parametric 0.3 / 0.5 / 0).
    gain_default = {"tanh": 4.0, "asymmetric": 3.0}.get(args.source, 4.0)
    threshold_default = 0.3 if args.source == "parametric" else 0.1
    params = dict(gain=gain_default if args.gain is None else args.gain,
                  threshold=threshold_default if args.threshold is None else args.threshold,
                  a2=args.a2, a3=args.a3, negative_scale=args.negative_scale)
    if args.source == "parametric":
        params = dict(threshold=params["threshold"], knee=args.knee, asymmetry=args.asymmetry)
    device = Device(args.source, params, filt(args.pre, args.pre_hz, args.pre_q),
                    filt(args.post, args.post_hz, args.post_q), args.invert)
    s = tc["stimulus"]
    if args.note:
        frequency = note_frequency(tc, args.note)
        note = args.note
    else:
        frequency = s["defaultFrequencyHz"] if args.frequency is None else args.frequency
        note = s["defaultNote"] if frequency == s["defaultFrequencyHz"] else None
    plan = Plan.from_manifest(tc, frequency, s["defaultAmplitude"] if args.amplitude is None else args.amplitude,
                              args.duration, args.rate)
    return SynthPlan(device, plan, note, args.latency_error, args.half_cycle_shift, args.paired,
                     args.sweep_duration, args.sweep_amplitude)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    m = load_manifest(args.manifest)
    synth = plan_from_args(args, m)
    result = run(synth, m)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            write_tsv(result, m, f)
    else:
        write_tsv(result, m, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
