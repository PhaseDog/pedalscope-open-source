#!/usr/bin/env python3
"""Harmonic Distortion — an independent reimplementation of PedalScope's
synchronized-swept-sine method, written from the methods manifest
(``Docs/Methods/generated/manifest.json``) and the published definition
(Farina 2000; Novák, Lotton and Simon 2015), NOT by transliterating the
Swift.

It produces the same TSV `analysisdump synth` produces (same column set,
same conventions), so one comparator serves both, and
``test_parity_hd.py`` pins the two against each other and against analytic
ground truth.

Conventions, all stated in the manifest and repeated here because they
decide what a number means:

* Every harmonic response is INPUT-NORMALIZED: ``H_k`` is the k-th harmonic
  output amplitude divided by the sweep amplitude, so a unit-gain linear
  device reads ``H_1 = 1`` (0 dB).
* ``H_k`` lives on the OUTPUT frequency axis; the k-th harmonic of a
  fundamental ``f0`` is read at ``k·f0``.
* A nonlinearity is applied PER SAMPLE at the sample rate, so the digital
  aliasing of content above Nyquist is included exactly as the Swift
  includes it (the simulated-DUT arm's convention). The phantom source is
  alias-free by construction.

Only the manifest's RULES are read; every number the rules produce (the
rate constant, the windows, the bin width) is recomputed here and, where
the manifest also states it, checked against it.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.normpath(os.path.join(HERE, "..", "generated", "manifest.json"))

COLUMNS = [
    "order", "f0_hz", "out_hz", "window_s", "valid", "mag_db", "expected_db",
    "err_db", "reading", "snr_db", "coherence", "scatter_db",
]

# ---------------------------------------------------------------------------
# Manifest


def load_manifest(path: str = DEFAULT_MANIFEST) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["harmonicDistortion"]


# ---------------------------------------------------------------------------
# The stimulus


def swift_round(x: float) -> int:
    """Swift's ``.rounded()`` — half away from zero."""
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


@dataclass(frozen=True)
class Sweep:
    """A synchronized exponential sine sweep (manifest ``stimulus``).

    ``x(t) = A·sin(φ(t))``, ``φ(t) = 2π·f1·L·(e^{t/L} − 1)``, with the
    rate constant ``L`` chosen so that ``f1·L`` is an integer
    (Novák 2015): ``L = round(f1·T_requested / ln(f2/f1)) / f1``.
    """

    f1: float
    f2: float
    requested_duration: float
    fs: float
    amplitude: float
    fade_in: float
    fade_out: float

    @property
    def log_ratio(self) -> float:
        return math.log(self.f2 / self.f1)

    @property
    def rate_constant(self) -> float:
        cycles = max(1.0, float(round(self.f1 * self.requested_duration / self.log_ratio)))
        return cycles / self.f1

    @property
    def duration(self) -> float:
        return self.rate_constant * self.log_ratio

    @property
    def sample_count(self) -> int:
        return swift_round(self.duration * self.fs)

    def phase(self, t: np.ndarray) -> np.ndarray:
        L = self.rate_constant
        return 2 * np.pi * self.f1 * L * (np.exp(t / L) - 1)

    def instantaneous_frequency(self, t) -> np.ndarray:
        return self.f1 * np.exp(np.asarray(t) / self.rate_constant)

    def harmonic_delay(self, k: int) -> float:
        """``Δt_k = L·ln(k)`` — how much EARLIER order k's pulse arrives."""
        return self.rate_constant * math.log(k)

    def times(self) -> np.ndarray:
        return np.arange(self.sample_count, dtype=np.float64) * (1.0 / self.fs)

    def fade_envelope(self) -> np.ndarray:
        n = self.sample_count
        env = np.ones(n)
        n_in = int(self.fade_in * self.fs)
        n_out = int(self.fade_out * self.fs)
        i = np.arange(n)
        if n_in > 0:
            head = i < n_in
            env[head] = 0.5 * (1 - np.cos(np.pi * i[head] / n_in))
        if n_out > 0:
            tail = i >= n - n_out
            env[tail] = env[tail] * 0.5 * (1 - np.cos(np.pi * (n - 1 - i[tail]) / n_out))
        return env

    def samples(self) -> np.ndarray:
        return self.amplitude * np.sin(self.phase(self.times())) * self.fade_envelope()

    @property
    def excited_band_bottom(self) -> float:
        return min(self.f2, float(self.instantaneous_frequency(min(self.fade_in, self.duration))))

    @property
    def excited_band_top(self) -> float:
        return min(self.f2, float(self.instantaneous_frequency(max(0.0, self.duration - self.fade_out))))

    @classmethod
    def from_manifest(cls, m: dict, **overrides) -> "Sweep":
        s = m["stimulus"]
        values = dict(
            f1=s["startHz"], f2=s["endHz"], requested_duration=s["requestedDurationS"],
            fs=s["sampleRateHz"], amplitude=s["amplitude"], fade_in=s["fadeInS"],
            fade_out=s["fadeOutS"])
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    def check_against(self, m: dict) -> None:
        """When this sweep IS the manifest's, the derived numbers must equal
        the shipped ones exactly — the rules were read right or not at all."""
        s = m["stimulus"]
        same = all(abs(getattr(self, a) - s[b]) == 0 for a, b in [
            ("f1", "startHz"), ("f2", "endHz"), ("requested_duration", "requestedDurationS"),
            ("fs", "sampleRateHz"), ("amplitude", "amplitude"),
            ("fade_in", "fadeInS"), ("fade_out", "fadeOutS")])
        if not same:
            return
        assert self.rate_constant == s["rateConstantS"], (self.rate_constant, s["rateConstantS"])
        assert self.duration == s["durationS"], (self.duration, s["durationS"])
        assert self.sample_count == s["sampleCount"], (self.sample_count, s["sampleCount"])
        assert self.excited_band_bottom == s["excitedBandBottomHz"]
        assert abs(self.excited_band_top - s["excitedBandTopHz"]) <= 1e-9 * s["excitedBandTopHz"]


# ---------------------------------------------------------------------------
# The device under test — the same family `analysisdump synth` offers


def nonlinearity(kind: str, gain: float = 4.0, threshold: float = 0.1, a2: float = 0.0,
                 a3: float = 0.0, negative_scale: float = 0.5) -> Callable[[np.ndarray], np.ndarray]:
    if kind == "identity":
        return lambda x: x
    if kind == "tanh":
        return lambda x: np.tanh(gain * x)
    if kind == "hardclip":
        return lambda x: np.minimum(np.maximum(x, -threshold), threshold)
    if kind == "poly":
        return lambda x: x + a2 * x * x + a3 * x * x * x
    if kind == "asymmetric":
        def asym(x):
            y = np.tanh(gain * x)
            return np.where(x >= 0, y, negative_scale * y)
        return asym
    raise ValueError(f"unknown nonlinearity {kind!r}")


def source_label(kind: str, params: dict, amps: Optional[Sequence[float]]) -> str:
    if kind == "phantom":
        return "phantom(" + ",".join(fmt(a) for a in amps) + ")"
    if kind == "identity":
        return "identity"
    if kind == "tanh":
        return f"tanh(gain: {fmt(params['gain'])})"
    if kind == "hardclip":
        return f"hardClip(threshold: {fmt(params['threshold'])})"
    if kind == "poly":
        return f"polynomial(a2: {fmt(params['a2'])}, a3: {fmt(params['a3'])})"
    if kind == "asymmetric":
        return f"asymmetric(gain: {fmt(params['gain'])}, negativeScale: {fmt(params['negative_scale'])})"
    raise ValueError(kind)


def phantom_capture(sweep: Sweep, amps: Sequence[float], gate_fraction: float) -> np.ndarray:
    """``Σ_k m_k·A·sin(k·φ(t))`` with the sweep's own fades: a device whose
    k-th harmonic response is exactly ``m_k``. Each term is dropped where
    ``k·f(t) ≥ fs/2`` and raised-cosine gated from ``gate_fraction·fs/2``
    (a stand-in for a converter's anti-alias filter), so nothing folds."""
    t = sweep.times()
    phi = sweep.phase(t)
    f = sweep.instantaneous_frequency(t)
    nyquist = sweep.fs / 2
    gate_start = gate_fraction * nyquist
    out = np.zeros_like(t)
    for index, m in enumerate(amps):
        if m == 0:
            continue
        k = index + 1
        fk = k * f
        term = m * (sweep.amplitude * np.sin(k * phi))
        gate = np.ones_like(t)
        gating = fk > gate_start
        gate[gating] = 0.5 * (1 + np.cos(np.pi * (fk[gating] - gate_start) / (nyquist - gate_start)))
        term = np.where(fk < nyquist, term * gate, 0.0)
        out += term
    return out * sweep.fade_envelope()


def clean_capture(sweep: Sweep, kind: str, params: dict, amps: Optional[Sequence[float]],
                  synthesis: dict) -> np.ndarray:
    if kind == "phantom":
        capture = phantom_capture(sweep, amps, synthesis["phantomNyquistGateFraction"])
    else:
        capture = nonlinearity(kind, **params)(sweep.samples())
    return np.concatenate([capture, np.zeros(int(synthesis["padSamples"]))])


# ---------------------------------------------------------------------------
# Deconvolution (manifest ``deconvolution``)


def next_power_of_two(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def inverse_filter(sweep: Sweep, n: int, taper_low: float, taper_high: float) -> np.ndarray:
    """The stationary-phase closed form (Novák 2015) on the ``n``-point DFT
    grid, bins 0…n/2: ``2·√(f/L)·exp(j(π/4 − 2π f L (1 − ln(f/f1))))``,
    zero below ``taper_low``, raised-cosine to ``taper_high``, DC and
    Nyquist zero."""
    fs = sweep.fs
    L = sweep.rate_constant
    f = np.arange(n // 2 + 1) * (fs / n)
    x = np.zeros(n // 2 + 1, dtype=np.complex128)
    m = np.arange(1, n // 2)  # 1 … n/2−1, as the rule states
    fm = f[m]
    taper = np.where(fm < taper_low, 0.0,
                     np.where(fm < taper_high,
                              0.5 * (1 - np.cos(np.pi * (fm - taper_low) / (taper_high - taper_low))),
                              1.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        mag = 2 * np.sqrt(fm / L) * taper
        ph = np.pi / 4 - 2 * np.pi * fm * L * (1 - np.log(fm / sweep.f1))
    x[m] = mag * (np.cos(ph) + 1j * np.sin(ph))
    return x


def deconvolve(sweep: Sweep, capture: np.ndarray, deconvolution: dict) -> np.ndarray:
    """The circular impulse response ``h`` — the linear pulse at index 0,
    order k's pulse ``round(Δt_k·fs)`` samples before the end."""
    fs = sweep.fs
    n = next_power_of_two(len(capture) + int(0.1 * fs))
    padded = np.zeros(n)
    padded[: len(capture)] = capture
    y = np.fft.rfft(padded)
    x = inverse_filter(sweep, n, deconvolution["taperLowHz"], deconvolution["taperHighHz"])
    s = y * x
    # irfft carries the 1/N; the 1/fs converts the sampled-signal DFT to the
    # continuous-time spectrum the analytic inverse expects.
    return np.fft.irfft(s, n) / fs


# ---------------------------------------------------------------------------
# Extraction (manifest ``extraction``)


@dataclass(frozen=True)
class Window:
    order: int
    delay_samples: float
    left: int
    right: int

    @property
    def seconds(self) -> float:
        return 0.0 if self.left < 16 or self.right < 16 else float(self.left + self.right)


def extraction_windows(sweep: Sweep, harmonic_count: int, response_fft_length: int,
                       max_half_width_s: float) -> List[Window]:
    fs = sweep.fs
    cap = min(response_fft_length / 2 - 1, max_half_width_s * fs)
    delays = [sweep.harmonic_delay(k) * fs for k in range(1, harmonic_count + 2)]
    out = []
    for k in range(1, harmonic_count + 1):
        delay = delays[k - 1]
        left = int(min(cap, (delays[k] - delay) / 2))
        right = int(cap) if k == 1 else int(min(cap, (delay - delays[k - 2]) / 2))
        out.append(Window(k, delay, left, right))
    return out


def window_seconds(w: Window, fs: float) -> float:
    return w.seconds / fs


def extract(h: np.ndarray, w: Window, response_fft_length: int, amplitude: float) -> np.ndarray:
    """Order k's complex response on bins 0…M/2 (input-normalized): the
    pulse's neighbourhood, raised-cosine windowed, placed with the pulse at
    circular index 0 of an M-point buffer."""
    n = len(h)
    M = response_fft_length
    position = 0 if w.order == 1 else n - swift_round(w.delay_samples)
    offsets = np.arange(-w.left, w.right)
    weight = np.where(offsets < 0,
                      0.5 * (1 + np.cos(np.pi * (-offsets) / w.left)),
                      0.5 * (1 + np.cos(np.pi * offsets / w.right)))
    src = (position + offsets) % n
    dst = (offsets + M) % M
    segment = np.zeros(M)
    segment[dst] = h[src] * weight
    return np.fft.rfft(segment) / amplitude


@dataclass
class Analysis:
    sweep: Sweep
    bin_width: float
    spectra: Dict[int, np.ndarray]  # order → complex bins 0…M/2
    averaged_sweep_count: int = 1

    @property
    def orders(self) -> List[int]:
        return sorted(self.spectra)


def analyze(capture: np.ndarray, sweep: Sweep, m: dict) -> Analysis:
    ex = m["extraction"]
    h = deconvolve(sweep, capture, m["deconvolution"])
    M = int(ex["responseFFTLength"])
    spectra: Dict[int, np.ndarray] = {}
    for w in extraction_windows(sweep, int(ex["harmonicCount"]), M, ex["maxWindowHalfWidthS"]):
        if w.left < 16 or w.right < 16:
            break  # the analyzer stops at the first order it cannot separate
        spectra[w.order] = extract(h, w, M, sweep.amplitude)
    return Analysis(sweep=sweep, bin_width=sweep.fs / M, spectra=spectra)


# ---------------------------------------------------------------------------
# Reading (manifest ``reading`` / ``validity``)


def magnitude_at_output_frequency(spectrum: np.ndarray, bin_width: float, f: float) -> Optional[float]:
    mag = np.abs(spectrum)
    x = f / bin_width
    if x < 0 or x > len(mag) - 1:
        return None
    i = int(x)
    if i == len(mag) - 1:
        return float(mag[i])
    frac = x - i
    return float(mag[i] * (1 - frac) + mag[i + 1] * frac)


def max_valid_fundamental(sweep: Sweep, order: int, calibrated_band_top: Optional[float] = None) -> float:
    top = min(sweep.f2, sweep.fs / (2 * order + 1))
    if calibrated_band_top is not None:
        top = min(top, calibrated_band_top / order)
    return top


def is_valid(sweep: Sweep, order: int, f0: float) -> bool:
    return sweep.f1 <= f0 <= sweep.f2 and f0 <= max_valid_fundamental(sweep, order)


def fundamental_grid(sweep: Sweep, count: int) -> np.ndarray:
    lo, hi = 1.5 * sweep.f1, sweep.f2
    log_lo, log_hi = math.log(lo), math.log(hi)
    return np.array([min(hi, math.exp(log_lo + (log_hi - log_lo) * i / (count - 1))) for i in range(count)])


# ---------------------------------------------------------------------------
# The shaping predicate (manifest ``shaping``)


def _interpolate(x: float, table: Sequence[Tuple[float, float]]) -> float:
    if x <= table[0][0]:
        return table[0][1]
    if x >= table[-1][0]:
        return table[-1][1]
    for i in range(1, len(table)):
        if x <= table[i][0]:
            a, b = table[i - 1], table[i]
            t = (x - a[0]) / (b[0] - a[0])
            return a[1] + (b[1] - a[1]) * t
    return table[-1][1]


def shaping_reading(analysis: Analysis, order: int, f0: float, window_s: float, m: dict
                    ) -> Tuple[str, Optional[float], Optional[float], Optional[float]]:
    """(label, snr_db, coherence, scatter_db) — ``undetermined`` carries nans."""
    sh = m["shaping"]
    undetermined = ("undetermined", None, None, None)
    if order < 1 or f0 <= 0 or order not in analysis.spectra or analysis.bin_width <= 0:
        return undetermined
    if window_s <= 0:
        return undetermined
    H = analysis.spectra[order]
    bin_width = analysis.bin_width
    bin_count = len(H)
    lag = max(1, int(math.ceil(sh["decorrelationFactor"] / (window_s * bin_width))))
    N = int(sh["windowSampleCount"])
    span = lag * N
    sweep = analysis.sweep
    low_bin = int(math.ceil(sweep.excited_band_bottom * order / bin_width))
    high_bin = int(math.floor(max_valid_fundamental(sweep, order) * order / bin_width))
    ceiling = min(high_bin, bin_count - 1) - lag
    if low_bin < 0 or ceiling - low_bin < span:
        return undetermined
    centre = swift_round(f0 * order / bin_width)
    start = min(max(centre - span // 2, low_bin), ceiling - span)
    idx = start + np.arange(N) * lag
    z = H[idx + lag] * np.conj(H[idx])
    total = np.sum(np.abs(z))
    if total <= 0:
        return undetermined
    coherence = float(abs(np.sum(z)) / total)
    c2s = [(p["x"], p["y"]) for p in sh["coherenceToSNR"]]
    s2c = [(p["x"], p["y"]) for p in sh["snrToScatter"]]
    snr = _interpolate(coherence, c2s)
    scatter = _interpolate(snr, s2c)
    label = "shaped" if snr >= sh["shapedSNRDB"] else "unshaped"
    return (label, snr, coherence, scatter)


# ---------------------------------------------------------------------------
# Ground truth (manifest ``synthesis.groundTruthRule``)


def expected_magnitude(kind: str, params: dict, amps: Optional[Sequence[float]], order: int,
                       amplitude: float, points: int) -> float:
    if kind == "phantom":
        return abs(amps[order - 1]) if order <= len(amps) else 0.0
    theta = 2 * np.pi * np.arange(points) / points
    y = nonlinearity(kind, **params)(amplitude * np.sin(theta))
    a = np.sum(y * np.sin(order * theta))
    b = np.sum(y * np.cos(order * theta))
    return float(math.hypot(a, b) * (2 / points) / amplitude)


# ---------------------------------------------------------------------------
# Noise (manifest ``synthesis``): SplitMix64 → Box–Muller, one stream per repeat

MASK64 = (1 << 64) - 1


def splitmix_outputs(seed: int, count: int, increment: int) -> np.ndarray:
    """The first ``count`` outputs of a SplitMix64 seeded with ``seed``.
    The state is an arithmetic progression, so the stream vectorizes:
    output j mixes ``seed + (j+1)·γ`` (mod 2^64)."""
    j = np.arange(1, count + 1, dtype=np.uint64)
    with np.errstate(over="ignore"):
        z = (np.uint64(seed) + j * np.uint64(increment))
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return z ^ (z >> np.uint64(31))


def repeat_seed(base: int, repeat_index: int, increment: int) -> int:
    """The (r+1)-th output of a SplitMix64 seeded with the base."""
    return int(splitmix_outputs(base, repeat_index + 1, increment)[-1])


def gaussian_noise(count: int, rms: float, seed: int, increment: int) -> np.ndarray:
    pairs = (count + 1) // 2
    outs = splitmix_outputs(seed, 2 * pairs, increment)
    scale = 1.0 / 9007199254740992.0
    u1 = (outs[0::2] >> np.uint64(11)).astype(np.float64) * scale
    u2 = (outs[1::2] >> np.uint64(11)).astype(np.float64) * scale
    r = np.sqrt(-2 * np.log(np.maximum(u1, 5e-324)))
    out = np.empty(2 * pairs)
    out[0::2] = rms * r * np.cos(2 * np.pi * u2)
    out[1::2] = rms * r * np.sin(2 * np.pi * u2)
    return out[:count]


# ---------------------------------------------------------------------------
# Averaging (manifest ``averaging``)


def fitted_delay_samples(analysis: Analysis, reference: Analysis, m: dict) -> float:
    av = m["averaging"]
    fs = reference.sweep.fs
    n_fit = int(av["delayFitSampleCount"])
    omegas, zs = [], []
    for order in reference.orders:
        if order not in analysis.spectra:
            continue
        ref = reference.spectra[order]
        rep = analysis.spectra[order]
        low = reference.sweep.f1 * 1.5
        high = max_valid_fundamental(reference.sweep, order)
        if high <= low:
            continue
        seen = set()
        for i in range(n_fit):
            f0 = low * (high / low) ** (i / (n_fit - 1))
            b = swift_round(f0 * order / reference.bin_width)
            if b <= 0 or b >= len(ref) or b in seen:
                continue
            seen.add(b)
            z = rep[b] * np.conj(ref[b])
            if z == 0:
                continue
            omegas.append(2 * np.pi * b * reference.bin_width / fs)
            zs.append(z)
    if not zs:
        return 0.0
    omegas = np.array(omegas)
    zs = np.array(zs)

    def score(delay: float) -> float:
        return float(np.sum((zs * np.exp(1j * omegas * delay)).real))

    limit = av["delayScanLimitSamples"]
    coarse = av["delayCoarseStepSamples"]
    fine = av["delayFineStepSamples"]
    best, best_score = 0.0, -math.inf
    delay = -limit
    while delay <= limit:
        s = score(delay)
        if s > best_score:
            best, best_score = delay, s
        delay += coarse
    d = best - coarse
    end = best + coarse
    while d <= end:
        s = score(d)
        if s > best_score:
            best, best_score = d, s
        d += fine
    return best


def derotated(analysis: Analysis, delay: float) -> Analysis:
    if delay == 0:
        return analysis
    fs = analysis.sweep.fs
    spectra = {}
    for order, H in analysis.spectra.items():
        b = np.arange(len(H))
        theta = 2 * np.pi * analysis.bin_width * delay / fs * b
        spectra[order] = H * (np.cos(theta) + 1j * np.sin(theta))
    return Analysis(analysis.sweep, analysis.bin_width, spectra, analysis.averaged_sweep_count)


def combine(repeats: List[Analysis], m: dict) -> Analysis:
    reference = repeats[0]
    total = sum(r.averaged_sweep_count for r in repeats)
    if len(repeats) == 1:
        return Analysis(reference.sweep, reference.bin_width, dict(reference.spectra), total)
    sums = {order: H.copy() for order, H in reference.spectra.items()}
    for other in repeats[1:]:
        aligned = derotated(other, fitted_delay_samples(other, reference, m))
        for order in sums:
            sums[order] = sums[order] + aligned.spectra[order]
    n = len(repeats)
    return Analysis(reference.sweep, reference.bin_width, {k: v / n for k, v in sums.items()}, total)


# ---------------------------------------------------------------------------
# The run


@dataclass
class Plan:
    kind: str
    params: dict
    amps: Optional[List[float]]
    sweep: Sweep
    averages: int = 1
    noise_rms: Optional[float] = None
    seed: int = 1
    grid_count: int = 48


def run_analysis(plan: Plan, m: dict) -> Analysis:
    synthesis = m["synthesis"]
    clean = clean_capture(plan.sweep, plan.kind, plan.params, plan.amps, synthesis)
    increment = int(synthesis["noiseGeneratorIncrement"], 16)
    repeats = []
    for r in range(plan.averages):
        capture = clean
        if plan.noise_rms is not None:
            capture = clean + gaussian_noise(len(clean), plan.noise_rms,
                                             repeat_seed(plan.seed, r, increment), increment)
        repeats.append(analyze(capture, plan.sweep, m))
    return combine(repeats, m)


def db(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return 20 * math.log10(x) if x > 0 else -math.inf


def rows(plan: Plan, analysis: Analysis, m: dict) -> List[dict]:
    ex = m["extraction"]
    windows = {w.order: w for w in extraction_windows(
        plan.sweep, int(ex["harmonicCount"]), int(ex["responseFFTLength"]), ex["maxWindowHalfWidthS"])}
    grid = fundamental_grid(plan.sweep, plan.grid_count)
    points = int(m["synthesis"]["groundTruthPoints"])
    out = []
    for order in analysis.orders:
        window_s = window_seconds(windows[order], plan.sweep.fs)
        expected = expected_magnitude(plan.kind, plan.params, plan.amps, order, plan.sweep.amplitude, points)
        expected_db = db(expected)
        for f0 in grid:
            mag = magnitude_at_output_frequency(analysis.spectra[order], analysis.bin_width, f0 * order)
            mag_db = db(mag)
            err = None
            if mag_db is not None and math.isfinite(mag_db) and math.isfinite(expected_db):
                err = mag_db - expected_db
            label, snr, coh, scatter = shaping_reading(analysis, order, f0, window_s, m)
            out.append(dict(
                order=order, f0_hz=f0, out_hz=f0 * order, window_s=window_s,
                valid=is_valid(plan.sweep, order, f0), mag_db=mag_db, expected_db=expected_db,
                err_db=err, reading=label, snr_db=snr, coherence=coh, scatter_db=scatter))
    return out


def fmt(v) -> str:
    """Shortest round-trip decimal, the way the Swift tool prints."""
    if v is None:
        return "nan"
    if isinstance(v, str):
        return v
    if isinstance(v, (bool, np.bool_)):
        return "1" if v else "0"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    v = float(v)
    if math.isnan(v):
        return "nan"
    if math.isinf(v):
        return "-inf" if v < 0 else "inf"
    if v == int(v) and abs(v) < 1e15:
        return repr(v)  # 30.0, like Swift's description
    return repr(v)


def write_tsv(plan: Plan, analysis: Analysis, table: List[dict], noise_db_text: str, out) -> None:
    s = plan.sweep
    out.write(f"# source: {source_label(plan.kind, plan.params, plan.amps)}\n")
    out.write(f"# sweep: f1={fmt(s.f1)} Hz f2={fmt(s.f2)} Hz actual_duration={fmt(s.duration)} s "
              f"L={fmt(s.rate_constant)} s fs={fmt(s.fs)} Hz amplitude={fmt(s.amplitude)}\n")
    out.write(f"# analysis: harmonicCount={len(analysis.orders)} averages={plan.averages} "
              f"noise_rms_dbfs={noise_db_text} seed={plan.seed} "
              f"averagedSweepCount={analysis.averaged_sweep_count}\n")
    out.write("\t".join(COLUMNS) + "\n")
    for r in table:
        out.write("\t".join(fmt(r[c]) for c in COLUMNS) + "\n")


def plan_from_args(args, m: dict) -> Plan:
    sweep = Sweep.from_manifest(m, f1=args.start, f2=args.end, requested_duration=args.duration,
                                fs=args.rate, amplitude=args.amplitude)
    sweep.check_against(m)
    params = dict(gain=args.gain, threshold=args.threshold, a2=args.a2, a3=args.a3,
                  negative_scale=args.negative_scale)
    amps = None
    if args.source == "phantom":
        if not args.amps:
            raise SystemExit("--source phantom needs --amps a1,a2,...")
        amps = [float(a) for a in args.amps.split(",")]
    noise = None if args.noise_db is None else 10 ** (args.noise_db / 20)
    return Plan(kind=args.source, params=params, amps=amps, sweep=sweep, averages=args.averages,
                noise_rms=noise, seed=args.seed, grid_count=args.grid)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--source", required=True,
                   choices=["phantom", "identity", "tanh", "hardclip", "poly", "asymmetric"])
    p.add_argument("--amps")
    p.add_argument("--gain", type=float, default=4.0)
    p.add_argument("--threshold", type=float, default=0.1)
    p.add_argument("--a2", type=float, default=0.0)
    p.add_argument("--a3", type=float, default=0.0)
    p.add_argument("--negative-scale", type=float, default=0.5)
    p.add_argument("--duration", type=float)
    p.add_argument("--rate", type=float)
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.add_argument("--amplitude", type=float)
    p.add_argument("--orders", type=int)
    p.add_argument("--averages", type=int, default=1)
    p.add_argument("--noise-db", type=float)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--grid", type=int, default=48)
    p.add_argument("--out")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    m = load_manifest(args.manifest)
    if args.orders is not None:
        m = json.loads(json.dumps(m))
        m["extraction"]["harmonicCount"] = args.orders
    plan = plan_from_args(args, m)
    analysis = run_analysis(plan, m)
    table = rows(plan, analysis, m)
    noise_text = "none" if args.noise_db is None else fmt(args.noise_db)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            write_tsv(plan, analysis, table, noise_text, f)
    else:
        write_tsv(plan, analysis, table, noise_text, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
