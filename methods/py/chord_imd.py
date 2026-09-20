#!/usr/bin/env python3
"""Chord IMD — the two-tone intermodulation method, reimplemented from the
methods manifest (`generated/manifest.json`, object `chordIMD`) and the
published definition of coherent-sampling two-tone analysis, NOT from the
Swift. It is the parity oracle's other half: it produces the same TSV
`analysisdump imd-synth` produces, and `test_parity_imd.py` holds the two
to each other and both to the torus-quadrature truth.

The method, in the manifest's own words, step by step:

1.  The plan (`chordIMD.plan`): two notes → 12-TET frequencies; the
    analysis length is a DURATION (the power of two nearest 2^21 samples at
    96 kHz), the stimulus duration is derived from it (fade + settle +
    N/fs + fade + settle), and the length actually analyzed is the longest
    power of two whose rectangular window fits the steady state.
2.  The lattice (`chordIMD.lattice`): the tone bins are k1 = g·a, k2 = g·b
    with a : b chosen ONCE against every standard grid (no collisions, g at
    or above the bar on every grid, both tones inside the cents budget,
    then the interval closest to the request) and scaled to the grid at
    hand; a g-search is the fallback on grids where no multiple fits, and
    a refusal follows when the budget cannot escape exact degeneracy.
3.  The analyzer (`chordIMD.window`, `chordIMD.analyzer`): a rectangular
    window of exactly N samples inside the steady state, the bin-exact
    read of every enumerated recipe m·f1 + n·f2 (orders 2…7, lowest order
    keeping a shared bin), each judged against the median of a product-
    free, detector-free neighbourhood (the local floor, a frequency span),
    the three capture-time percentage sums, and the coherence detector.
4.  The read-time predicates (`chordIMD.resolution`, `.coherence`,
    `.harmonicRoles`): the per-product reading with its seven-step
    precedence, the capture floor as a summary of bins already judged,
    the coherence reading with the per-offset level rule and the two
    registers' sentences, and the harmonic-role partition classified at
    the requested interval and measured at the lattice.
5.  The truth: the exact 2-D Fourier coefficients of the memoryless device
    on the (θ1, θ2) torus, scaled by the post-filter's analytic response,
    the polynomial's closed form beside it, the phantom's listed levels.

Run: python chord_imd.py --source tanh --gain 2 --amplitude 0.5 [...]
with the options `analysisdump imd-synth --help` lists.
"""
from __future__ import annotations

import argparse
import json
import math
import os
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

COLUMNS = [
    "m", "n", "order", "label", "freq_hz", "bin", "off_f1_bins", "off_f2_bins", "pitch", "amplitude",
    "level_dbc", "above_floor", "reading", "limit_detail", "grid_index", "role", "contest", "partner",
    "partner_excess_db", "partner_inconsistent", "truth_amplitude", "truth_closed_amplitude",
    "truth_dbc", "err_db",
]


def load_manifest(path: str = DEFAULT_MANIFEST) -> dict:
    """The WHOLE manifest: `chordIMD` for the method, `transferCurve.biquad`
    for the filters' formulas (chapter two's rules, reused)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def flag(b) -> str:
    return "nan" if b is None else ("1" if b else "0")


def db20(x: float) -> float:
    return 20 * math.log10(x)


# ---------------------------------------------------------------------------
# Pitch (manifest ``pitch``)


def midi_frequency(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def note_frequency(name: str) -> Optional[float]:
    """`pitch.parseRule`: a letter C…G, an optional accidental, an octave."""
    text = name.strip()
    if not text:
        return None
    letter = text[0].upper()
    if letter not in "CDEFGAB":
        return None
    semitones = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter]
    text = text[1:]
    accidental = 0
    if text and text[0] in "#♯":
        accidental, text = 1, text[1:]
    elif text and text[0] in "b♭":
        accidental, text = -1, text[1:]
    try:
        octave = int(text)
    except ValueError:
        return None
    midi = (octave + 1) * 12 + semitones + accidental
    if not 0 <= midi <= 127:
        return None
    return midi_frequency(midi)


def describe(frequency: float, names: Sequence[str]) -> Optional[Tuple[str, float]]:
    """`pitch.describeRule`."""
    if frequency <= 0:
        return None
    midi = 69 + 12 * math.log2(frequency / 440)
    nearest = swift_round(midi)
    if not 0 <= nearest <= 127:
        return None
    cents = (midi - nearest) * 100
    return names[nearest % 12] + str(nearest // 12 - 1), cents


def pitch_label(frequency: float, names: Sequence[str]) -> str:
    d = describe(frequency, names)
    if d is None:
        return "—"
    return "%s %+.0f¢" % (d[0], d[1])


# ---------------------------------------------------------------------------
# The plan and the stimulus (manifest ``plan``, ``stimulus``, ``window``)


def intended_length(fs: float, ceiling: int, pl: dict) -> int:
    samples = pl["standardFFTLength"] * fs / pl["standardSampleRateHz"]
    nearest = 1 << max(0, swift_round(math.log2(samples)))
    return min(ceiling, nearest)


def stimulus_duration(fs: float, ceiling: int, pl: dict, fade: float, settle: float) -> float:
    n = intended_length(fs, ceiling, pl)
    return fade + settle + n / fs + fade + settle


@dataclass(frozen=True)
class Signal:
    f1: float
    f2: float
    a1: float
    a2: float
    fs: float
    duration: float
    fade: float

    @property
    def sample_count(self) -> int:
        return swift_round(self.duration * self.fs)

    def fade_envelope(self) -> np.ndarray:
        count = self.sample_count
        n_fade = int(self.fade * self.fs)
        env = np.ones(count)
        i = np.arange(n_fade)
        env[:n_fade] *= 0.5 * (1 - np.cos(np.pi * i / n_fade))
        env[count - n_fade:] *= 0.5 * (1 - np.cos(np.pi * (n_fade - 1 - i) / n_fade))
        return env

    def samples(self) -> np.ndarray:
        """`stimulus.toneRule`."""
        i = np.arange(self.sample_count, dtype=np.float64)
        s = self.a1 * np.sin(2 * np.pi * self.f1 / self.fs * i) + self.a2 * np.sin(2 * np.pi * self.f2 / self.fs * i)
        return s * self.fade_envelope()


@dataclass(frozen=True)
class Window:
    start: int
    length: int
    steady_end: int

    @property
    def end(self) -> int:
        return self.start + self.length

    @property
    def fade_overrun(self) -> int:
        return self.end - self.steady_end

    @property
    def overruns(self) -> bool:
        return self.fade_overrun > 0


def window(signal: Signal, latency: int, n: int, settle: float) -> Window:
    """`window.windowRule`."""
    fs = signal.fs
    n_fade = int(signal.fade * fs)
    return Window(latency + n_fade + int(settle * fs), n, latency + signal.sample_count - n_fade)


def analysis_length(signal: Signal, ceiling: int, minimum: int, settle: float) -> int:
    """`plan.analysisLengthRule`."""
    n = ceiling
    while n > minimum and window(signal, 0, n, settle).overruns:
        n >>= 1
    return n


# ---------------------------------------------------------------------------
# The lattice (manifest ``lattice``)


def gcd(a: int, b: int) -> int:
    x, y = abs(a), abs(b)
    while y:
        x, y = y, x % y
    return x


def minimum_reduced_sum(max_order: int) -> int:
    return 2 * max_order + 1


def search_radius(frequency: float, bin_width: float, budget: float) -> int:
    return int(math.ceil(frequency * (2 ** (budget / 1200) - 1) / bin_width))


@dataclass(frozen=True)
class Grid:
    fs: float
    n: int

    @property
    def bin_width(self) -> float:
        return self.fs / self.n


def placement(a: int, b: int, grid: Grid, f1: float, f2: float, budget: float, minimum_spacing: int):
    """`lattice.placementRule`: (g, c1, c2) or None."""
    bw = grid.bin_width
    ratio = 2 ** (budget / 1200)
    g_low = max(minimum_spacing, int(math.ceil(f1 / ratio / (a * bw))))
    g_high = int(math.floor(f1 * ratio / (a * bw)))
    if g_low > g_high:
        return None
    best = None
    for g in range(g_low, g_high + 1):
        if g * b * bw >= grid.fs / 2:
            continue
        c1 = 1200 * math.log2(g * a * bw / f1)
        c2 = 1200 * math.log2(g * b * bw / f2)
        if abs(c1) > budget or abs(c2) > budget:
            continue
        worst = max(abs(c1), abs(c2))
        if best is not None and best[3] <= worst:
            continue
        best = (g, c1, c2, worst)
    return None if best is None else best[:3]


@dataclass(frozen=True)
class RatioCandidate:
    a: int
    b: int
    interval_cents: float
    interval_error_cents: float
    placements: Tuple[Tuple[int, float, float], ...]  # (g, c1, c2) per grid

    @property
    def minimum_spacing(self) -> int:
        return min(p[0] for p in self.placements)

    @property
    def reduced_sum(self) -> int:
        return self.a + self.b


def _ratio_outranks(lhs: RatioCandidate, rhs: RatioCandidate) -> bool:
    """`lattice.ratioObjectiveRule`."""
    le, re = abs(lhs.interval_error_cents), abs(rhs.interval_error_cents)
    if abs(le - re) > 1e-9:
        return le < re
    if lhs.minimum_spacing != rhs.minimum_spacing:
        return lhs.minimum_spacing > rhs.minimum_spacing
    if lhs.reduced_sum != rhs.reduced_sum:
        return lhs.reduced_sum < rhs.reduced_sum
    return (lhs.a, lhs.b) < (rhs.a, rhs.b)


def _sort_by(outranks, items):
    """Insertion sort under a total order stated as `outranks` — a
    stable sort by a comparison the manifest states as a sequence of
    tie-breaks."""
    out: List = []
    for item in items:
        i = len(out)
        while i > 0 and outranks(item, out[i - 1]):
            i -= 1
        out.insert(i, item)
    return out


def ratio_search(f1: float, f2: float, grids: Sequence[Grid], max_order: int, budget: float, bar: int):
    """`lattice.ratioSearchRule`: (chosen, survivors, requested_cents)."""
    requested = 1200 * math.log2(f2 / f1)
    minimum = minimum_reduced_sum(max_order)
    ratio = 2 ** (budget / 1200)
    coarsest = max(g.bin_width for g in grids)
    a_max = int(math.floor(f1 * ratio / (bar * coarsest)))
    r = f2 / f1
    survivors: List[RatioCandidate] = []
    for a in range(1, a_max + 1):
        b_low = max(a + 1, int(math.ceil(a * r / (ratio * ratio))))
        b_high = int(math.floor(a * r * ratio * ratio))
        for b in range(b_low, b_high + 1):
            if gcd(a, b) != 1 or a + b < minimum:
                continue
            placements = []
            for grid in grids:
                p = placement(a, b, grid, f1, f2, budget, bar)
                if p is None:
                    break
                placements.append(p)
            if len(placements) != len(grids):
                continue
            interval = 1200 * math.log2(b / a)
            survivors.append(RatioCandidate(a, b, interval, interval - requested, tuple(placements)))
    survivors = _sort_by(_ratio_outranks, survivors)
    return (survivors[0] if survivors else None), survivors, requested


@dataclass(frozen=True)
class SnapCandidate:
    k1: int
    k2: int
    g: int
    a: int
    b: int
    c1: float
    c2: float

    @property
    def reduced_sum(self) -> int:
        return self.a + self.b

    @property
    def worst_cents(self) -> float:
        return max(abs(self.c1), abs(self.c2))

    @property
    def interval_cents(self) -> float:
        return 1200 * math.log2(self.b / self.a)


def _snap_outranks(lhs: SnapCandidate, rhs: SnapCandidate) -> bool:
    """`lattice.candidateOrderRule`."""
    if lhs.g != rhs.g:
        return lhs.g > rhs.g
    if lhs.worst_cents != rhs.worst_cents:
        return lhs.worst_cents < rhs.worst_cents
    return (lhs.k1, lhs.k2) < (rhs.k1, rhs.k2)


@dataclass
class SnapSearch:
    naive1: int
    naive2: int
    radius1: int
    radius2: int
    budget: float
    max_order: int
    bar: int
    standard: Optional[RatioCandidate]
    standard_placement: Optional[SnapCandidate]
    resolvable: Optional[SnapCandidate]
    resolvable_count: int
    best_non_degenerate: Optional[SnapCandidate]
    non_degenerate_count: int
    widest: Optional[SnapCandidate]

    @property
    def emitted(self) -> Optional[SnapCandidate]:
        return self.standard_placement or self.resolvable or self.best_non_degenerate

    @property
    def tier(self) -> str:
        if self.standard_placement is not None:
            return "standard_resolvable" if self.standard_placement.g >= self.bar else "standard_degraded"
        if self.resolvable is not None:
            return "resolvable"
        if self.best_non_degenerate is not None:
            return "degraded"
        return "refused"

    @property
    def max_order_headroom(self) -> Optional[int]:
        e = self.emitted
        return None if e is None else (e.reduced_sum - 1) // 2


def snap_search(f1: float, f2: float, grid: Grid, max_order: int, budget: float, bar: int,
                standard: Optional[RatioCandidate]) -> SnapSearch:
    """`lattice.snapSearchRule`."""
    bw = grid.bin_width
    naive1, naive2 = swift_round(f1 / bw), swift_round(f2 / bw)
    radius1, radius2 = search_radius(f1, bw, budget), search_radius(f2, bw, budget)
    minimum = minimum_reduced_sum(max_order)
    standard_placement = None
    if standard is not None:
        p = placement(standard.a, standard.b, grid, f1, f2, budget, 1)
        if p is not None:
            g, c1, c2 = p
            standard_placement = SnapCandidate(g * standard.a, g * standard.b, g, standard.a, standard.b, c1, c2)
    resolvable = best_nd = widest = None
    resolvable_count = nd_count = 0
    for k1 in range(naive1 - radius1, naive1 + radius1 + 1):
        if k1 < 1:
            continue
        c1 = 1200 * math.log2(k1 * bw / f1)
        if abs(c1) > budget:
            continue
        for k2 in range(naive2 - radius2, naive2 + radius2 + 1):
            if k2 <= k1 or k2 * bw >= grid.fs / 2:
                continue
            c2 = 1200 * math.log2(k2 * bw / f2)
            if abs(c2) > budget:
                continue
            g = gcd(k1, k2)
            cand = SnapCandidate(k1, k2, g, k1 // g, k2 // g, c1, c2)
            if widest is None or _snap_outranks(cand, widest):
                widest = cand
            if cand.reduced_sum < minimum:
                continue
            nd_count += 1
            if best_nd is None or _snap_outranks(cand, best_nd):
                best_nd = cand
            if g < bar:
                continue
            resolvable_count += 1
            if resolvable is None or _snap_outranks(cand, resolvable):
                resolvable = cand
    return SnapSearch(naive1, naive2, radius1, radius2, budget, max_order, bar, standard, standard_placement,
                      resolvable, resolvable_count, best_nd, nd_count, widest)


class LatticeRefusal(Exception):
    def __init__(self, search: SnapSearch, f1: float, f2: float, n: int, bin_width: float):
        super().__init__("refused")
        self.search, self.f1, self.f2, self.n, self.bin_width = search, f1, f2, n, bin_width


def standard_grids(pl: dict) -> List[Grid]:
    return [Grid(fs, intended_length(fs, pl["standardFFTLength"], pl)) for fs in pl["supportedSampleRatesHz"]]


def plan_signal(note1: str, note2: str, peak: float, fs: float, ceiling: int, m: dict):
    """`plan.signalRule`: the snapped signal, its search and the length it
    was snapped to — or a LatticeRefusal."""
    imd = m["chordIMD"]
    pl, st, wn, lat = imd["plan"], imd["stimulus"], imd["window"], imd["lattice"]
    f1, f2 = note_frequency(note1), note_frequency(note2)
    if f1 is None or f2 is None or f2 <= f1:
        raise ValueError(f"bad notes {note1!r} {note2!r}")
    duration = stimulus_duration(fs, ceiling, pl, st["fadeS"], wn["settleS"])
    base = Signal(f1, f2, peak / 2, peak / 2, fs, duration, st["fadeS"])
    n = analysis_length(base, ceiling, pl["minimumFFTLength"], wn["settleS"])
    max_order, budget, bar = int(lat["maxOrder"]), float(lat["toneCentsBudget"]), int(lat["resolvableSpacingBins"])
    chosen, _, _ = ratio_search(f1, f2, standard_grids(pl), max_order, budget, bar)
    search = snap_search(f1, f2, Grid(fs, n), max_order, budget, bar, chosen)
    emitted = search.emitted
    if emitted is None:
        raise LatticeRefusal(search, f1, f2, n, fs / n)
    bw = fs / n
    return Signal(emitted.k1 * bw, emitted.k2 * bw, base.a1, base.a2, fs, duration, st["fadeS"]), search, n


def contestants(m_: int, n_: int, frequency: float, f1: float, f2: float, fs: float, max_order: int) -> List[Tuple[int, int, int]]:
    """`lattice.contestRule`."""
    limit = 0.95 * fs / 2
    tol = 1e-6 * max(frequency, 1.0)
    found = []
    for order in range(2, max(2, max_order) + 1):
        for mm in range(-order, order + 1):
            nm = order - abs(mm)
            for nn in ([0] if nm == 0 else [nm, -nm]):
                if mm == m_ and nn == n_:
                    continue
                f = mm * f1 + nn * f2
                if not (0 < f < limit):
                    continue
                if abs(f - frequency) <= tol:
                    found.append((mm, nn, order))
    return found


# ---------------------------------------------------------------------------
# The analyzer (manifest ``analyzer``)


def recipe_label(m_: int, n_: int) -> str:
    def term(k, name):
        if k == 0:
            return ""
        if k == 1:
            return name
        if k == -1:
            return "−" + name
        return f"{k}{name}" if k > 0 else f"−{-k}{name}"
    a, b = term(m_, "f1"), term(n_, "f2")
    if not a:
        return b
    if not b:
        return a
    return a + b if b.startswith("−") else a + "+" + b


@dataclass
class Product:
    m: int
    n: int
    order: int
    frequency: float
    amplitude: float
    above_floor: bool

    @property
    def label(self) -> str:
        return recipe_label(self.m, self.n)


@dataclass
class Detector:
    fft_length: int
    floor1: float
    sidebands1: List[Tuple[int, float]]
    floor2: float
    sidebands2: List[Tuple[int, float]]


@dataclass
class Analysis:
    signal: Signal
    tone1: float
    tone2: float
    products: List[Product]
    smpte: float
    ccif: float
    total: float
    band: Tuple[float, float]
    detector: Optional[Detector]

    @property
    def tone_reference(self) -> float:
        return max(self.tone1, self.tone2)


def detector_bins(tone_bin: int, bin_count: int, offsets: Sequence[int]) -> List[int]:
    out = []
    for d in offsets:
        if tone_bin - d > 0:
            out.append(tone_bin - d)
        if tone_bin + d < bin_count:
            out.append(tone_bin + d)
    return sorted(out)


def outer_offset_bins(bin_width: float, an: dict) -> int:
    return max(int(an["localFloorMinimumOffsets"]), swift_round(an["localFloorSpanHz"] / bin_width))


def local_floor(bin_: int, magnitude: np.ndarray, bin_width: float, excluded: set, an: dict) -> float:
    """`analyzer.localFloorRule`: the upper median over the neighbourhood."""
    inner = int(an["localFloorInnerOffsetBins"])
    outer = outer_offset_bins(bin_width, an)
    if outer < inner:
        return 0.0
    neighbours = []
    count = len(magnitude)
    for offset in range(inner, outer + 1):
        below, above = bin_ - offset, bin_ + offset
        if below > 0 and below not in excluded:
            neighbours.append(below)
        if above < count and above not in excluded:
            neighbours.append(above)
    if not neighbours:
        return 0.0
    values = sorted(float(magnitude[i]) for i in neighbours)
    return values[len(values) // 2]


def analyze(captured: np.ndarray, signal: Signal, latency: int, n: int, m: dict) -> Analysis:
    imd = m["chordIMD"]
    an, wn, band = imd["analyzer"], imd["window"], imd["audibleBand"]
    fs = signal.fs
    w = window(signal, latency, n, wn["settleS"])
    end = min(len(captured), w.end)
    segment = np.zeros(n)
    if w.start < end:
        segment[: end - w.start] = captured[w.start:end]
    spectrum = np.fft.rfft(segment)
    bins = n // 2 + 1
    scale = 2.0 / min(n, max(1, end - w.start))
    magnitude = np.abs(spectrum[:bins]) * scale
    bw = fs / n

    def bin_of(f: float) -> int:
        return swift_round(f / bw)

    def level(f: float) -> float:
        b = bin_of(f)
        return float(magnitude[b]) if 0 < b < bins else 0.0

    f1, f2 = signal.f1, signal.f2
    tone1, tone2 = level(f1), level(f2)
    limit = 0.95 * fs / 2
    max_order = int(an["defaultMaxOrder"])
    seen = {bin_of(f1), bin_of(f2), 0}
    recipes = []
    for order in range(2, max_order + 1):
        for mm in range(-order, order + 1):
            nm = order - abs(mm)
            for nn in (nm, -nm):
                if abs(mm) + abs(nn) != order:
                    continue
                f = mm * f1 + nn * f2
                if not (bw < f < limit):
                    continue
                b = bin_of(f)
                if b in seen:
                    continue
                seen.add(b)
                recipes.append((mm, nn, order, f, b))
    tone_bins = [bin_of(f1), bin_of(f2)]
    offsets = imd["coherence"]["detectorOffsets"]
    excluded = set(seen)
    for tb in tone_bins:
        excluded.update(detector_bins(tb, bins, offsets))
    products = []
    for mm, nn, order, f, b in recipes:
        amp = level(f)
        floor = local_floor(b, magnitude, bw, excluded, an)
        products.append(Product(mm, nn, order, f, amp, amp > 4 * floor))
    products.sort(key=lambda p: -p.amplitude)

    def tone_detector(tb: int):
        floor = local_floor(tb, magnitude, bw, excluded, an)
        return floor, [(b - tb, float(magnitude[b])) for b in detector_bins(tb, bins, offsets)]
    fl1, sb1 = tone_detector(tone_bins[0])
    fl2, sb2 = tone_detector(tone_bins[1])
    detector = Detector(n, fl1, sb1, fl2, sb2)

    lo, hi = float(band["lowHz"]), float(band["highHz"])
    counted = [p for p in products if lo <= p.frequency <= hi]
    tone_power = tone1 * tone1 + tone2 * tone2

    def percent(power_sum, reference):
        return 100 * math.sqrt(power_sum / reference) if reference > 0 else 0.0
    smpte = sum(p.amplitude ** 2 for p in counted if abs(p.n) == 1 and p.m != 0 and abs(p.m) <= 4)
    ccif = sum(p.amplitude ** 2 for p in counted if (p.m, p.n) in ((-1, 1), (2, -1), (-1, 2)))
    total = sum(p.amplitude ** 2 for p in counted if p.above_floor)
    return Analysis(signal, tone1, tone2, products, percent(smpte, tone2 * tone2), percent(ccif, tone_power),
                    percent(total, tone_power), (lo, hi), detector)


# ---------------------------------------------------------------------------
# Read time: the resolution predicate (manifest ``resolution``)


@dataclass
class Reading:
    kind: str          # present | absent | unmeasurable | floor_not_observed | analyzer_window |
                       # near_played_tone | near_louder_product | under_loudest_skirt | out_of_band
    detail: Dict[str, object] = field(default_factory=dict)

    @property
    def is_present(self) -> bool:
        return self.kind == "present"

    @property
    def is_absent(self) -> bool:
        return self.kind == "absent"

    @property
    def is_out_of_band(self) -> bool:
        return self.kind == "out_of_band"

    @property
    def is_unresolved(self) -> bool:
        return self.kind in ("unmeasurable", "floor_not_observed", "analyzer_window", "near_played_tone",
                             "near_louder_product", "under_loudest_skirt")

    def detail_text(self) -> str:
        d = self.detail
        if self.kind == "present":
            return "margin=" + ("nan" if d.get("margin") is None else fmt(d["margin"]))
        if self.kind == "absent":
            return "bound=" + fmt(d["bound"])
        if self.kind == "near_played_tone":
            return "%s%s%d" % (d["tone"], "+" if d["offset"] >= 0 else "", d["offset"])
        if self.kind == "analyzer_window":
            return "separation=" + fmt(d["separation"])
        if self.kind == "floor_not_observed":
            return "samples=%d" % d["samples"]
        if self.kind == "near_louder_product":
            return "%s%s%d neighbour_dbc=%s" % (d["label"], "+" if d["offset"] >= 0 else "", d["offset"], fmt(d["level"]))
        if self.kind == "under_loudest_skirt":
            return "depth=%s skirt=%s loudest=%s loudest_dbc=%s g=%d" % (
                fmt(d["depth"]), fmt(d["skirt"]), d["loudest"], fmt(d["loudest_dbc"]), d["g"])
        if self.kind == "unmeasurable":
            return ""
        if self.kind == "out_of_band":
            return "hz=%s low_edge_hz=%s" % (fmt(d["hz"]), fmt(d["low_edge"]))
        raise ValueError(self.kind)


class Resolver:
    """Every read-time accessor of one analysis at one length, the
    manifest's `resolution` block."""

    def __init__(self, analysis: Analysis, n: int, m: dict):
        self.a = analysis
        self.n = n
        self.m = m
        self.rs = m["chordIMD"]["resolution"]
        self.co = m["chordIMD"]["coherence"]
        self.bw = analysis.signal.fs / n
        self.neighbourhood = int(self.rs["playedToneNeighbourhoodBins"])
        self.bin1 = swift_round(analysis.signal.f1 / self.bw)
        self.bin2 = swift_round(analysis.signal.f2 / self.bw)

    # --- levels
    def level_dbc(self, p: Product) -> Optional[float]:
        ref = self.a.tone_reference
        if ref <= 0 or p.amplitude <= 0:
            return None
        return db20(p.amplitude / ref)

    def loudest_component(self) -> Optional[float]:
        loudest = max([self.a.tone_reference] + [p.amplitude for p in self.a.products])
        return loudest if loudest > 0 else None

    def loudest_product(self) -> Optional[Tuple[Product, float]]:
        best = None
        for p in self.a.products:
            lv = self.level_dbc(p)
            if lv is None:
                continue
            if best is not None and best[1] >= lv:
                continue
            best = (p, lv)
        return best

    def loudest_product_dbc(self) -> Optional[float]:
        levels = [lv for lv in (self.level_dbc(p) for p in self.a.products) if lv is not None]
        return max(levels) if levels else None

    # --- positions
    def bin_of(self, p: Product) -> int:
        return swift_round(p.frequency / self.bw)

    def proximity(self, p: Product):
        """`resolution.proximityRule`: (tone, offset) of the nearest reference bin."""
        b = self.bin_of(p)
        candidates = [("f1", b - self.bin1), ("f2", b - self.bin2), ("DC", b)]
        best = candidates[0]
        for c in candidates[1:]:
            if abs(c[1]) < abs(best[1]):
                best = c
        return best

    def inside_neighbourhood(self, p: Product) -> bool:
        return abs(self.proximity(p)[1]) <= self.neighbourhood

    def out_of_band(self, p: Product) -> bool:
        return p.frequency < self.a.band[0]

    def louder_neighbour(self, p: Product):
        """`resolution.louderNeighbourRule`."""
        mine = self.bin_of(p)
        best = None
        for other in self.a.products:
            if not other.above_floor or other.amplitude <= p.amplitude:
                continue
            offset = mine - self.bin_of(other)
            if offset == 0 or abs(offset) > self.neighbourhood:
                continue
            if best is None or abs(offset) < abs(best[1]) or (abs(offset) == abs(best[1]) and other.amplitude > best[0].amplitude):
                best = (other, offset)
        if best is None:
            return None
        lv = self.level_dbc(best[0])
        return None if lv is None else (best[0], best[1], lv)

    # --- the floor
    def noise_reads(self) -> List[float]:
        out = []
        for p in self.a.products:
            if p.above_floor or self.inside_neighbourhood(p) or self.out_of_band(p):
                continue
            if self.louder_neighbour(p) is not None:
                continue
            lv = self.level_dbc(p)
            if lv is not None:
                out.append(lv)
        return sorted(out)

    def capture_floor(self):
        reads = self.noise_reads()
        if len(reads) < int(self.rs["minimumFloorSamples"]):
            return None
        median = reads[len(reads) // 2]
        return median, len(reads), (reads[-1] if reads else median) - median

    def analyzer_separation(self) -> Optional[float]:
        w = window(self.a.signal, 0, self.n, self.m["chordIMD"]["window"]["settleS"])
        return self.rs["fadeContaminatedSeparationDB"] if w.overruns else None

    def lattice_spacing(self) -> Optional[int]:
        g = gcd(self.bin1, self.bin2)
        return g if g > 0 else None

    def skirt_depth(self, g: int) -> float:
        return 20 * math.log10(math.pi * max(1, g))

    def loudest_skirt(self):
        """`resolution.loudestSkirtRule`."""
        g = self.lattice_spacing()
        loudest = self.loudest_product()
        if g is None or loudest is None or loudest[1] <= 0:
            return None
        reading = self.coherence_reading()
        if reading is not None and reading.interprets("device"):
            return None
        return dict(product=loudest[0], level=loudest[1], g=g, skirt=self.skirt_depth(g))

    # --- the reading
    def resolution(self, p: Product, floor, separation: Optional[float], skirt) -> Reading:
        """`resolution.precedenceRule`."""
        tone, offset = self.proximity(p)
        if abs(offset) <= self.neighbourhood:
            return Reading("near_played_tone", dict(tone=tone, offset=offset))
        if self.out_of_band(p):
            return Reading("out_of_band", dict(hz=p.frequency, low_edge=self.a.band[0]))
        level = self.level_dbc(p)
        if level is None:
            return Reading("unmeasurable")
        nb = self.louder_neighbour(p)
        if nb is not None:
            return Reading("near_louder_product", dict(label=nb[0].label, offset=nb[1], level=nb[2]))
        loudest = self.loudest_component()
        depth = None if loudest is None or p.amplitude <= 0 else db20(loudest / p.amplitude)
        if separation is not None and depth is not None and depth >= separation:
            return Reading("analyzer_window", dict(separation=separation))
        if skirt is not None:
            d = skirt["level"] - level
            if d > skirt["skirt"]:
                return Reading("under_loudest_skirt", dict(depth=d, skirt=skirt["skirt"], loudest=skirt["product"].label,
                                                           loudest_dbc=skirt["level"], g=skirt["g"]))
        if p.above_floor:
            return Reading("present", dict(margin=None if floor is None else level - floor[0]))
        if floor is None:
            return Reading("floor_not_observed", dict(samples=len(self.noise_reads())))
        return Reading("absent", dict(bound=level))

    def resolutions(self) -> List[Reading]:
        floor, separation, skirt = self.capture_floor(), self.analyzer_separation(), self.loudest_skirt()
        return [self.resolution(p, floor, separation, skirt) for p in self.a.products]

    def verdict(self) -> dict:
        readings = self.resolutions()
        floor = self.capture_floor()
        present = sum(r.is_present for r in readings)
        absent = sum(r.is_absent for r in readings)
        unresolved = sum(r.is_unresolved for r in readings)
        oob = sum(r.is_out_of_band for r in readings)
        refused = unresolved + oob
        reads = len(self.noise_reads())
        if floor is None:
            absence = "every_product_resolved" if refused == 0 else \
                "too_few_empty_bins read=%d needed=%d refused=%d" % (reads, int(self.rs["minimumFloorSamples"]), refused)
        else:
            absence = "none"
        return dict(floor=floor, separation=self.analyzer_separation(), present=present, absent=absent,
                    unresolved=unresolved, out_of_band=oob, noise_reads=reads, refused=refused, absence=absence)

    def floor_line(self, v: dict) -> str:
        """`resolution.floorLineRule`."""
        floor = v["floor"]
        if floor is not None:
            return ("Measurement floor for this capture: %.1f dBc — the median of %d bins that hold no product, "
                    "scattering %.1f dB above it." % (floor[0], floor[1], floor[2]))
        if v["refused"] == 0:
            return ("This capture resolved every product it enumerated, so it never read empty spectrum — "
                    "no measurement floor to quote.")
        refused = v["refused"]
        read = v["noise_reads"]
        refusal = "1 product could not be read" if refused == 1 else "%d products could not be read" % refused
        if read == 0:
            remaining = "no bin of empty spectrum remains"
        elif read == 1:
            remaining = "only 1 bin of empty spectrum remains"
        else:
            remaining = "only %d bins of empty spectrum remain" % read
        return "No measurement floor to quote: %s, and %s — fewer than the %d a floor needs." % (
            refusal, remaining, int(self.rs["minimumFloorSamples"]))

    def derived_percentages(self):
        """`resolution.derivedPercentagesRule`."""
        unreadable = [p for p in self.a.products if self.inside_neighbourhood(p)]
        keys = {(p.m, p.n) for p in unreadable}
        lo, hi = self.a.band
        in_band = [p for p in self.a.products if lo <= p.frequency <= hi]
        counted = [p for p in in_band if (p.m, p.n) not in keys]
        in_band_keys = {(p.m, p.n) for p in in_band}
        excluded = [p for p in unreadable if (p.m, p.n) in in_band_keys]
        tone_power = self.a.tone1 ** 2 + self.a.tone2 ** 2

        def percent(power_sum, reference):
            return 100 * math.sqrt(power_sum / reference) if reference > 0 else 0.0
        smpte = sum(p.amplitude ** 2 for p in counted if abs(p.n) == 1 and p.m != 0 and abs(p.m) <= 4)
        ccif = sum(p.amplitude ** 2 for p in counted if (p.m, p.n) in ((-1, 1), (2, -1), (-1, 2)))
        total = sum(p.amplitude ** 2 for p in counted if p.above_floor)
        return percent(smpte, self.a.tone2 ** 2), percent(ccif, tone_power), percent(total, tone_power), excluded

    # --- the partner check and the contest
    def contest(self, p: Product) -> List[Tuple[int, int, int]]:
        max_order = max(int(self.m["chordIMD"]["analyzer"]["defaultMaxOrder"]),
                        max((q.order for q in self.a.products), default=0))
        return contestants(p.m, p.n, p.frequency, self.a.signal.f1, self.a.signal.f2, self.a.signal.fs, max_order)

    def partner_check(self, p: Product):
        """`resolution.partnerRule`: (partner label, measured, expected) or None."""
        if p.order != 2 or p.amplitude <= 0 or self.contest(p):
            return None
        second = abs(p.m) == 2 or abs(p.n) == 2
        partner = None
        for c in self.a.products:
            if c.order != 2 or (c.m == p.m and c.n == p.n):
                continue
            if (abs(c.m) == 2 or abs(c.n) == 2) == second:
                partner = c
                break
        if partner is None or partner.amplitude <= 0 or self.contest(partner):
            return None
        measured = db20(p.amplitude / partner.amplitude)
        expected = 0.0
        if second:
            if self.a.tone1 <= 0 or self.a.tone2 <= 0:
                return None
            gap = db20(self.a.tone1 / self.a.tone2)
            expected = 2 * gap if abs(p.m) == 2 else -2 * gap
        return partner.label, measured, expected

    # --- the coherence reading (manifest ``coherence``)
    def coherence_reading(self):
        s = self.a.signal
        if s.f1 <= 0 or s.f2 <= 0:
            return None
        expected = db20(s.f2 / s.f1)
        if self.a.detector is not None:
            return self._detector_reading(expected)
        return self._stored_products_reading(expected)

    def _dbc(self, amplitude: float) -> Optional[float]:
        ref = self.a.tone_reference
        return db20(amplitude / ref) if amplitude > 0 and ref > 0 else None

    def _detector_reading(self, expected: float):
        det = self.a.detector
        if self.a.tone_reference <= 0:
            return None
        bw = self.a.signal.fs / det.fft_length
        k1, k2 = swift_round(self.a.signal.f1 / bw), swift_round(self.a.signal.f2 / bw)
        if k1 <= 0 or k2 <= 0:
            return None
        g = gcd(k1, k2)
        pairs = []
        widest = 0
        for tone, floor, sidebands in (("f1", det.floor1, det.sidebands1), ("f2", det.floor2, det.sidebands2)):
            reads = []
            for offset, amp in sidebands:
                lv = self._dbc(amp)
                if lv is None:
                    continue
                widest = max(widest, abs(offset))
                reads.append(("%s%s%d" % (tone, "+" if offset >= 0 else "−", abs(offset)), offset, lv))
            if reads:
                pairs.append(Pair(tone, sorted(reads, key=lambda r: r[1]), self._dbc(floor)))
        if not pairs:
            return None
        return CoherenceReading("detector", pairs, expected, g, widest, self.loudest_product_dbc(), self.co)

    def _stored_products_reading(self, expected: float):
        near = [(p, self.proximity(p)) for p in self.a.products]
        near = [(p, prox) for p, prox in near if abs(prox[1]) <= self.neighbourhood and prox[0] != "DC"]
        g = self.lattice_spacing()
        if not near or g is None:
            return None
        floor = self.capture_floor()
        floor_dbc = None if floor is None else floor[0]
        pairs = []
        widest = 0
        for tone in ("f1", "f2"):
            reads = []
            for p, (t, offset) in near:
                if t != tone:
                    continue
                lv = self.level_dbc(p)
                if lv is None:
                    continue
                widest = max(widest, abs(offset))
                reads.append((p.label, offset, lv))
            if reads:
                pairs.append(Pair(tone, sorted(reads, key=lambda r: r[1]), floor_dbc))
        if not pairs:
            return None
        return CoherenceReading("stored_products", pairs, expected, g, widest, self.loudest_product_dbc(), self.co)

    # --- the harmonic roles (manifest ``harmonicRoles``)
    def harmonic_roles(self):
        roles = self.m["chordIMD"]["harmonicRoles"]
        names = self.m["chordIMD"]["pitch"]["noteNames"]
        interval = interval_recovered(self.a.signal, roles, names)
        if interval is None:
            return None
        v = self.verdict()
        floor, separation, skirt = v["floor"], v["separation"], self.loudest_skirt()
        ordered = sorted(self.a.products, key=lambda p: -p.amplitude)
        seen = set()
        buckets = {r: dict(counted=[], absent=[], unread=[]) for r in ("thickening", "subOctave", "addedColour", "clash")}
        total = dict(counted=[], absent=[], unread=[])
        unplaced = []
        lo, hi = self.a.band
        for p in ordered:
            reading = self.resolution(p, floor, separation, skirt)
            index = p.m * interval.a + p.n * interval.b
            point = grid_point(index, interval, roles, names)
            c = dict(product=p, point=point, reading=reading, level=self.level_dbc(p))
            if point["role"] is None or reading.is_out_of_band or not (lo <= p.frequency <= hi):
                unplaced.append(c)
                continue
            bucket = buckets[point["role"]]
            if reading.is_present:
                key = swift_round(p.frequency / self.bw)
                if key in seen:
                    continue
                seen.add(key)
                bucket["counted"].append(c)
                total["counted"].append(c)
            elif reading.is_absent:
                bucket["absent"].append(c)
                total["absent"].append(c)
            else:
                bucket["unread"].append(c)
                total["unread"].append(c)
        return interval, buckets, total, unplaced


def role_level(counted) -> Optional[float]:
    power = sum(10 ** (c["level"] / 10) for c in counted if c["level"] is not None)
    return 10 * math.log10(power) if power > 0 else None


# ---------------------------------------------------------------------------
# Coherence (manifest ``coherence``)


@dataclass
class Pair:
    tone: str
    sidebands: List[Tuple[str, int, float]]  # (label, offset, level) ascending by offset
    floor: Optional[float]

    @property
    def below(self):
        below = [s for s in self.sidebands if s[1] < 0]
        return max(below, key=lambda s: s[1]) if below else None

    @property
    def above(self):
        above = [s for s in self.sidebands if s[1] > 0]
        return min(above, key=lambda s: s[1]) if above else None

    @property
    def innermost(self):
        return [s for s in (self.below, self.above) if s is not None]

    @property
    def level(self) -> float:
        inner = self.innermost
        return sum(s[2] for s in inner) / len(inner)


class CoherenceReading:
    def __init__(self, source, pairs, expected_difference, g, widest, loudest_product_dbc, co: dict):
        self.source = source
        self.pairs = pairs
        self.expected_difference = expected_difference
        self.g = g
        self.widest = widest
        self.loudest_product_dbc = loudest_product_dbc
        self.co = co

    def pair_about(self, tone):
        return next((p for p in self.pairs if p.tone == tone), None)

    @property
    def clearance(self) -> int:
        return self.g - self.widest

    @property
    def lattice_clear(self) -> bool:
        return self.clearance >= int(self.co["minimumClearanceBins"])

    @property
    def offsets_present(self) -> List[int]:
        return sorted({abs(s[1]) for p in self.pairs for s in p.sidebands})

    def ceiling(self, d: int) -> float:
        if d <= 0 or self.g - d <= 0:
            return -math.inf
        return 20 * math.log10((self.g - d) / d) - self.co["productSkirtMarginDB"]

    @property
    def readable_offsets(self) -> List[int]:
        if self.source != "detector" or not self.lattice_clear:
            return self.offsets_present
        loudest = -math.inf if self.loudest_product_dbc is None else self.loudest_product_dbc
        return [d for d in self.offsets_present if loudest <= self.ceiling(d)]

    @property
    def unreadable_offsets(self) -> List[int]:
        readable = set(self.readable_offsets)
        return [d for d in self.offsets_present if d not in readable]

    @property
    def level_limited(self) -> bool:
        return bool(self.unreadable_offsets)

    def read_sidebands(self, pair: Pair):
        readable = set(self.readable_offsets)
        return [s for s in pair.sidebands if abs(s[1]) in readable]

    @property
    def read_bin_count(self) -> int:
        return sum(len(self.read_sidebands(p)) for p in self.pairs)

    @property
    def expected_noise_excess(self) -> Optional[float]:
        n = self.read_bin_count
        if n <= 0:
            return None
        harmonic = sum(1.0 / k for k in range(1, n + 1))
        return 10 * math.log10(harmonic / math.log(2))

    def figure_sidebands(self, pair: Pair):
        read = self.read_sidebands(pair)
        return read if read else pair.sidebands

    def worst_sideband(self, pair: Pair):
        return max(self.figure_sidebands(pair), key=lambda s: s[2])

    def worst_excess(self, pair: Pair) -> Optional[float]:
        return None if pair.floor is None else self.worst_sideband(pair)[2] - pair.floor

    @property
    def worst(self):
        return max((self.worst_sideband(p) for p in self.pairs), key=lambda s: s[2])

    @property
    def worst_level(self) -> float:
        return self.worst[2]

    @property
    def worst_excess_over_floor(self) -> Optional[float]:
        excesses = [e for e in (self.worst_excess(p) for p in self.pairs) if e is not None]
        return max(excesses) if excesses else None

    @property
    def floor(self) -> Optional[float]:
        with_floor = [p for p in self.pairs if self.worst_excess(p) is not None]
        if not with_floor:
            return None
        return max(with_floor, key=lambda p: self.worst_excess(p)).floor

    @property
    def excess_over_threshold(self) -> Optional[float]:
        e = self.worst_excess_over_floor
        return None if e is None else e - self.co["thresholdOverFloorDB"]

    @property
    def exceeds(self) -> bool:
        e = self.excess_over_threshold
        return e is not None and e > 0

    @property
    def pair_difference(self) -> Optional[float]:
        f1, f2 = self.pair_about("f1"), self.pair_about("f2")
        if f1 is None or f2 is None:
            return None
        return f2.level - f1.level

    def interprets(self, subject: str) -> bool:
        if self.worst_excess_over_floor is None:
            return False
        if self.lattice_clear:
            return bool(self.readable_offsets)
        return subject == "loopOnly"

    def not_trustworthy(self, subject: str) -> bool:
        return self.interprets(subject) and self.exceeds

    # --- the wording (`coherence.wordingRule`)
    @staticmethod
    def level_text(dbc: float) -> str:
        return ("+%.1f dBc" if dbc >= 0 else "%.1f dBc") % dbc

    @staticmethod
    def decibels(value: float) -> str:
        rounded = swift_round(value * 10) / 10
        return "%.1f" % (0.0 if rounded == 0 else rounded)

    @staticmethod
    def bins_text(count: int) -> str:
        return "1 bin" if count == 1 else "%d bins" % count

    @staticmethod
    def offset_range(offsets: List[int]) -> str:
        if not offsets:
            return "none"
        if len(offsets) == 1:
            return "±%d" % offsets[0]
        if offsets == list(range(offsets[0], offsets[-1] + 1)):
            return "±%d…±%d" % (offsets[0], offsets[-1])
        return ", ".join("±%d" % d for d in offsets)

    def offsets_phrase(self) -> str:
        if self.source == "detector":
            if self.level_limited and self.loudest_product_dbc is not None:
                return ("the bins beside the played notes at %s — the offsets this record can read (spacing %s; %s sit too close "
                        "to a product at %s to read) — read " % (
                            self.offset_range(self.readable_offsets), self.bins_text(self.g),
                            self.offset_range(self.unreadable_offsets), self.level_text(self.loudest_product_dbc)))
            return ("the bins beside the played notes — offsets ±1…±%d, which no product of this lattice can reach "
                    "(spacing %s) — read " % (self.widest, self.bins_text(self.g)))
        return ("the bins beside the played notes (the short-window lattice's stored near-note products, %s out) read "
                % self.bins_text(self.widest))

    def noise_phrase(self) -> str:
        e = self.expected_noise_excess
        if e is None:
            return ""
        return " — the worst of %s, where noise alone would put it ≈ %s dB over —" % (
            self.bins_text(self.read_bin_count), self.decibels(e))

    def floor_phrase(self) -> str:
        return "the local floor beside that note" if self.source == "detector" else "this capture's measured floor"

    @staticmethod
    def subject_label(subject: str) -> str:
        return "loop only" if subject == "loopOnly" else "device in the loop"

    def line(self, subject: str) -> str:
        bar = self.co["thresholdOverFloorDB"]
        excess, over = self.worst_excess_over_floor, self.excess_over_threshold
        if self.interprets(subject) and excess is not None and over is not None:
            text = ("Coherence check (%s): " % self.subject_label(subject) + self.offsets_phrase()
                    + "%s at worst, " % self.level_text(self.worst_level)
                    + "%s dB above %s%s and " % (self.decibels(excess), self.floor_phrase(), self.noise_phrase())
                    + "%s dB %s the %s dB bar: " % (self.decibels(abs(over)), "over" if over > 0 else "under", self.decibels(bar)))
            text += ("the played notes did not stay stationary across the analysis window — from some source in the chain, "
                     "which this reading cannot name — so the whole spectrum is smeared and this capture's floor and product "
                     "levels are not trustworthy." if self.exceeds else
                     "the played notes stayed stationary across the analysis window, so the analyzer's coherence premise held.")
        elif self.worst_excess_over_floor is None:
            text = ("Coherence bins (%s): the bins beside the played notes read %s at worst — this capture observed no floor "
                    "to read them against, so nothing is concluded." % (self.subject_label(subject), self.level_text(self.worst_level)))
        elif self.lattice_clear and not self.readable_offsets and self.loudest_product_dbc is not None:
            owner = "the device's" if subject == "device" else "this capture's"
            its = "its" if subject == "device" else "the"
            nearest = self.ceiling(self.offsets_present[0] if self.offsets_present else 1)
            text = ("Coherence bins (not readable beside %s products): the bins beside the played notes read %s at worst — "
                    "%s products are louder than the played tones (%s loudest reads %s, against a %s ceiling for even the "
                    "nearest bin), so the bins beside the notes would read the products' coherence, not the tones'; this "
                    "reading does not interpret." % (owner, self.level_text(self.worst_level), owner, its,
                                                    self.level_text(self.loudest_product_dbc), self.level_text(nearest)))
        else:
            text = ("Coherence bins (not attributable at this lattice): the bins beside the played notes read %s at worst — "
                    % self.level_text(self.worst_level))
            if self.source == "detector":
                where = ("inside the detector's own span" if self.clearance < 0
                         else "within %s of them" % self.bins_text(self.clearance))
                text += "this lattice puts a product %s (spacing %s), so " % (where, self.bins_text(self.g))
            text += ("with a pedal in the loop they hold its own products inseparably from any loss of coherence, so this "
                     "number is a reading of neither.")
        return text + " " + self.pair_sentence()

    def pair_sentence(self) -> str:
        def pair_text(pair: Pair) -> str:
            levels = [self.level_text(s[2]) for s in pair.innermost]
            joined = " / ".join(l.replace(" dBc", "") for l in levels)
            text = "%s dBc" % joined
            if self.source == "detector":
                inner = min((abs(s[1]) for s in pair.innermost), default=1)
                text += " at ±%d" % inner
                worst = self.worst_sideband(pair)
                if abs(worst[1]) != inner:
                    text += " (worst of the set %s at %s%d)" % (self.level_text(worst[2]), "+" if worst[1] > 0 else "−", abs(worst[1]))
            return text
        parts = []
        f1, f2 = self.pair_about("f1"), self.pair_about("f2")
        if f1 is not None:
            parts.append("beside f1 " + pair_text(f1))
        if f2 is not None:
            parts.append("beside f2 " + pair_text(f2))
        text = "Pair " + ", ".join(parts)
        d = self.pair_difference
        if d is not None:
            text += (" — the f2 pair %.1f dB %s (a shared frequency wander would separate them by %.1f dB; amplitude or "
                     "frequency-independent phase modulation leaves them equal)" % (abs(d), "higher" if d >= 0 else "lower",
                                                                                     self.expected_difference))
        return text + "."


# ---------------------------------------------------------------------------
# Harmonic roles (manifest ``harmonicRoles``)


def is_five_limit(value: int) -> bool:
    v = value
    if v <= 0:
        return False
    for prime in (2, 3, 5):
        while v % prime == 0:
            v //= prime
    return v == 1


@dataclass(frozen=True)
class Interval:
    lower: str
    upper: str
    lower_hz: float
    upper_hz: float
    a: int
    b: int

    @property
    def grid_hz(self) -> float:
        return self.lower_hz / self.a

    @property
    def label(self) -> str:
        return "%s + %s" % (self.lower, self.upper)


def just_ratio(cents: float, roles: dict):
    """`harmonicRoles.justRatioRule`."""
    limit, tol = int(roles["justRatioSearchLimit"]), roles["pitchToleranceCents"]
    best = None
    for a in range(1, limit + 1):
        if not is_five_limit(a):
            continue
        for b in range(a, a * 16 + 1):
            if not is_five_limit(b) or gcd(a, b) != 1:
                continue
            g = gcd(a, b)
            ra, rb = a // g, b // g
            error = abs(1200 * math.log2(rb / ra) - cents)
            if error > tol:
                continue
            if best is None:
                best = (ra, rb, error)
            else:
                s, cs = a + b, best[0] + best[1]
                if s < cs or (s == cs and error < best[2]):
                    best = (ra, rb, error)
    return None if best is None else (best[0], best[1])


def interval(lower: str, upper: str, roles: dict, names: Sequence[str]) -> Optional[Interval]:
    lo, hi = note_frequency(lower), note_frequency(upper)
    if lo is None or hi is None or hi <= lo:
        return None
    ratio = just_ratio(1200 * math.log2(hi / lo), roles)
    if ratio is None:
        return None
    dl, du = describe(lo, names), describe(hi, names)
    return Interval(dl[0] if dl else lower, du[0] if du else upper, lo, hi, ratio[0], ratio[1])


def interval_recovered(signal: Signal, roles: dict, names: Sequence[str]) -> Optional[Interval]:
    """`harmonicRoles.intervalRecoveryRule`."""
    lo, hi = describe(signal.f1, names), describe(signal.f2, names)
    if lo is None or hi is None:
        return None
    return interval(lo[0], hi[0], roles, names)


def odd_part(value: int) -> int:
    v = abs(value)
    if v == 0:
        return 0
    while v % 2 == 0:
        v //= 2
    return v


def grid_point(index: int, iv: Interval, roles: dict, names: Sequence[str]) -> dict:
    """`harmonicRoles.pitchClassRule` and `roleRule`."""
    frequency = index * iv.grid_hz
    if index <= 0:
        return dict(index=index, frequency=frequency, pitch="—", cents=0.0, semitone=None, role=None,
                    chord_tone=False, between_frets=False)
    described = describe(frequency, names)
    root_odd, upper_odd, point_odd = odd_part(iv.a), odd_part(iv.b), odd_part(index)
    cents = 1200 * math.log2(point_odd / root_odd)
    cents = math.fmod(cents, 1200)
    if cents < 0:
        cents += 1200
    semitone = swift_round(cents / 100)
    deviation = cents - semitone * 100
    semitone_class = semitone % 12
    chord_tone = point_odd == root_odd or point_odd == upper_odd
    between = abs(deviation) > roles["pitchToleranceCents"]
    if chord_tone:
        role = "thickening" if index >= iv.a else "subOctave"
    elif between:
        role = "clash"
    else:
        role = "addedColour" if semitone_class in set(roles["addedColourSemitoneClasses"]) else "clash"
    return dict(index=index, frequency=frequency, pitch=described[0] if described else "—",
                cents=described[1] if described else 0.0,
                semitone=0 if chord_tone and point_odd == root_odd else semitone_class,
                role=role, chord_tone=chord_tone, between_frets=between)


# ---------------------------------------------------------------------------
# The drive line (manifest ``driveLevel``)


def drive_line(signal: Signal) -> str:
    def dbfs(a):
        return "%.1f dBFS" % (20 * math.log10(max(a, 1e-12)))
    text = "Drive level: %s combined peak" % dbfs(signal.a1 + signal.a2)
    if signal.a1 == signal.a2:
        text += " — two equal tones at %s each" % dbfs(signal.a1)
    else:
        text += " — tone 1 at %s, tone 2 at %s" % (dbfs(signal.a1), dbfs(signal.a2))
    return text + "."


# ---------------------------------------------------------------------------
# The truth (manifest ``synthesis``)


@dataclass(frozen=True)
class Device:
    kind: str
    params: dict
    pre: Optional[tc.Filter] = None
    post: Optional[tc.Filter] = None
    inverted: bool = False

    def render(self, x: np.ndarray, fs: float) -> np.ndarray:
        return tc.Device(self.kind, self.params, self.pre, self.post, self.inverted).render(x, fs)

    @property
    def label(self) -> str:
        return tc.device_label(self.kind, self.params)


class Truth:
    def __init__(self, source, signal: Signal, max_order: int, points: int):
        self.max_order = max_order
        self.points = points
        self.f1, self.f2 = signal.f1, signal.f2
        self.reference = max(signal.a1, signal.a2)
        self.phantom = None
        self.post = None
        self.polynomial = None
        self.coefficients = None
        if isinstance(source, list):
            self.kind = "phantom"
            self.phantom = source
            self.drive1, self.drive2 = signal.a1, signal.a2
            self.pre1 = self.pre2 = 1.0
            return
        device: Device = source
        fs = signal.fs
        g1 = g2 = 1.0
        if device.pre is not None:
            bq = device.pre.biquad(fs)
            g1, g2 = abs(bq.response(signal.f1)), abs(bq.response(signal.f2))
        self.pre1, self.pre2 = g1, g2
        self.drive1, self.drive2 = signal.a1 * g1, signal.a2 * g2
        self.post = device.post.biquad(fs) if device.post is not None else None
        if device.kind == "identity":
            self.kind = "identity"
            return
        self.kind = "device"
        if device.kind == "poly":
            self.polynomial = (device.params["a2"], device.params["a3"])
        self.coefficients = self.torus(tc.nonlinearity(device.kind, device.params), self.drive1, self.drive2, points)

    @staticmethod
    def torus(f, a1: float, a2: float, points: int) -> np.ndarray:
        """`synthesis.truthRule`: 2|c(m,n)| for every (m, n) by the trapezoid
        rule on a P×P torus grid — one 2-D FFT of f(A1 sin θ1 + A2 sin θ2)."""
        theta = 2 * np.pi * np.arange(points) / points
        y = f(a1 * np.sin(theta)[:, None] + a2 * np.sin(theta)[None, :])
        return 2 * np.abs(np.fft.fft2(y)) / (points * points)

    def post_gain(self, f: float) -> float:
        return 1.0 if self.post is None else abs(self.post.response(f))

    def amplitude(self, m_: int, n_: int) -> Optional[float]:
        f = m_ * self.f1 + n_ * self.f2
        if self.kind == "identity":
            if (m_, n_) == (1, 0):
                return self.drive1 * self.post_gain(f)
            if (m_, n_) == (0, 1):
                return self.drive2 * self.post_gain(f)
            return 0.0
        if self.kind == "phantom":
            if (m_, n_) == (1, 0):
                return self.drive1
            if (m_, n_) == (0, 1):
                return self.drive2
            for pm, pn, level in self.phantom:
                if (pm, pn) == (m_, n_):
                    return 10 ** (level / 20) * self.reference
            return 0.0
        if abs(m_) > self.max_order or abs(n_) > self.max_order:
            return None
        return float(self.coefficients[m_ % self.points, n_ % self.points]) * self.post_gain(f)

    def closed_form(self, m_: int, n_: int) -> Optional[float]:
        """`synthesis.closedFormRule`."""
        if self.polynomial is None:
            return None
        a2, a3 = self.polynomial
        A1, A2 = self.drive1, self.drive2
        f = m_ * self.f1 + n_ * self.f2
        key = (abs(m_), abs(n_))
        raw = {
            (1, 0): A1 + a3 * (0.75 * A1 ** 3 + 1.5 * A1 * A2 ** 2),
            (0, 1): A2 + a3 * (0.75 * A2 ** 3 + 1.5 * A1 ** 2 * A2),
            (2, 0): abs(a2) * A1 * A1 / 2, (0, 2): abs(a2) * A2 * A2 / 2, (1, 1): abs(a2) * A1 * A2,
            (3, 0): abs(a3) * A1 ** 3 / 4, (0, 3): abs(a3) * A2 ** 3 / 4,
            (2, 1): 0.75 * abs(a3) * A1 * A1 * A2, (1, 2): 0.75 * abs(a3) * A1 * A2 * A2,
        }.get(key, 0.0)
        return raw * self.post_gain(f)

    @property
    def tone1(self):
        return self.amplitude(1, 0)

    @property
    def tone2(self):
        return self.amplitude(0, 1)

    @property
    def tone_reference(self):
        t1, t2 = self.tone1, self.tone2
        return None if t1 is None or t2 is None else max(t1, t2)


# ---------------------------------------------------------------------------
# Synthesis


@dataclass
class SynthPlan:
    source: object            # Device or a list of (m, n, dBc)
    note1: str
    note2: str
    peak: float
    fs: float
    ceiling: int
    latency_error: int = 0
    noise_rms: Optional[float] = None
    noise_db_text: str = "none"
    seed: int = 1
    wander: Optional[Tuple[float, float, bool]] = None   # (delta, cycles, ramp)
    legacy: bool = False


def wandering(signal: Signal, n: int, delta: float, rate_bins: float, ramp: bool) -> np.ndarray:
    """`synthesis.wanderRule`."""
    fs = signal.fs
    t = np.arange(signal.sample_count) / fs
    fm = rate_bins * fs / n

    def phase(f):
        if ramp:
            return 2 * np.pi * f * (t + delta * (t * t / (2 * signal.duration) - t / 2))
        return 2 * np.pi * f * t + (delta * f / fm) * np.sin(2 * np.pi * fm * t)
    s = signal.a1 * np.sin(phase(signal.f1)) + signal.a2 * np.sin(phase(signal.f2))
    return s * signal.fade_envelope()


def phantom_capture(signal: Signal, products) -> np.ndarray:
    """`synthesis.phantomRule`."""
    fs = signal.fs
    i = np.arange(signal.sample_count, dtype=np.float64)
    w1, w2 = 2 * np.pi * signal.f1 / fs, 2 * np.pi * signal.f2 / fs
    s = signal.a1 * np.sin(w1 * i) + signal.a2 * np.sin(w2 * i)
    reference = max(signal.a1, signal.a2)
    for pm, pn, level in products:
        s += 10 ** (level / 20) * reference * np.sin((pm * w1 + pn * w2) * i)
    return s * signal.fade_envelope()


@dataclass
class Result:
    plan: SynthPlan
    signal: Signal
    search: SnapSearch
    n: int
    window: Window
    analysis: Analysis
    truth: Truth
    resolver: Resolver


def run(plan: SynthPlan, m: dict) -> Result:
    imd = m["chordIMD"]
    signal, search, n = plan_signal(plan.note1, plan.note2, plan.peak, plan.fs, plan.ceiling, m)
    if isinstance(plan.source, list):
        captured = phantom_capture(signal, plan.source)
    else:
        stimulus = signal.samples() if plan.wander is None else wandering(signal, n, *plan.wander)
        captured = plan.source.render(stimulus, signal.fs)
    if plan.noise_rms is not None:
        increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
        captured = captured + hd.gaussian_noise(len(captured), plan.noise_rms, hd.repeat_seed(plan.seed, 0, increment), increment)
    analysis = analyze(captured, signal, plan.latency_error, n, m)
    if plan.legacy:
        analysis.detector = None
    truth = Truth(plan.source, signal, int(imd["analyzer"]["defaultMaxOrder"]), int(imd["synthesis"]["quadraturePoints"]))
    w = window(signal, plan.latency_error, n, imd["window"]["settleS"])
    return Result(plan, signal, search, n, w, analysis, truth, Resolver(analysis, n, m))


def expected_noise(rms: float, n: int, reference: float):
    """`synthesis.expectedNoiseRule`."""
    median = 2 * rms * math.sqrt(math.log(2) / n)
    median_dbc, broadband_dbc = db20(median / reference), db20(rms / reference)
    return median_dbc, broadband_dbc, broadband_dbc - median_dbc


# ---------------------------------------------------------------------------
# The TSV — the oracle's exact lines


def lattice_line(search: SnapSearch, emitted: Optional[SnapCandidate], fs: float, n: int, duration: float,
                 max_order: int) -> str:
    st = search.standard
    fields = ("tier=%s standard_a=%s standard_b=%s standard_interval_cents=%s requested_cents=%s "
              "naive_bin1=%d naive_bin2=%d radius1=%d radius2=%d cents_budget=%s max_order=%d bar_bins=%d "
              "resolvable_count=%d nondegenerate_count=%d min_reduced_sum=%d " % (
                  search.tier, "nan" if st is None else st.a, "nan" if st is None else st.b,
                  fmt(None if st is None else st.interval_cents),
                  fmt(None if st is None else st.interval_cents - st.interval_error_cents),
                  search.naive1, search.naive2, search.radius1, search.radius2, fmt(search.budget), search.max_order,
                  search.bar, search.resolvable_count, search.non_degenerate_count, minimum_reduced_sum(search.max_order)))
    if emitted is not None:
        fields += ("bin1=%d bin2=%d g=%d a=%d b=%d reduced_sum=%d cents1=%s cents2=%s interval_cents=%s headroom=%d" % (
            emitted.k1, emitted.k2, emitted.g, emitted.a, emitted.b, emitted.reduced_sum, fmt(emitted.c1), fmt(emitted.c2),
            fmt(emitted.interval_cents), search.max_order_headroom))
        return fields + " | " + disclosure_line(search, emitted, fs, n, duration)
    w = search.widest
    fields += ("bin1=%s bin2=%s g=%s a=%s b=%s reduced_sum=%s cents1=%s cents2=%s interval_cents=%s headroom=nan" % (
        "nan" if w is None else w.k1, "nan" if w is None else w.k2, "nan" if w is None else w.g,
        "nan" if w is None else w.a, "nan" if w is None else w.b, "nan" if w is None else w.reduced_sum,
        fmt(None if w is None else w.c1), fmt(None if w is None else w.c2), fmt(None if w is None else w.interval_cents)))
    return fields


def disclosure_line(search: SnapSearch, emitted: SnapCandidate, fs: float, n: int, duration: float) -> str:
    st = search.standard
    requested = emitted.interval_cents if st is None else st.interval_cents - st.interval_error_cents
    tier = {
        "standard_resolvable": "standard ratio, resolvable",
        "standard_degraded": "standard ratio, under the %d-bin bar (degraded)" % search.bar,
        "resolvable": "no in-budget multiple of the standard ratio here — widest lattice in budget, resolvable",
        "degraded": "no in-budget multiple of the standard ratio here — widest lattice in budget, under the %d-bin bar (degraded)" % search.bar,
        "refused": "refused",
    }[search.tier]
    return ("lattice: bins %d:%d = %d × %d:%d (spacing %d bins, reduced sum %d) · interval %.1f¢ (requested %.1f¢) · "
            "tones %+.1f¢ / %+.1f¢ · %s · analysis 2^%d bins of %.4f Hz over a %.1f s stimulus" % (
                emitted.k1, emitted.k2, emitted.g, emitted.a, emitted.b, emitted.g, emitted.reduced_sum,
                emitted.interval_cents, requested, emitted.c1, emitted.c2, tier, swift_round(math.log2(n)), fs / n, duration))


def refusal_description(r: LatticeRefusal, names: Sequence[str]) -> str:
    requested = "%s + %s" % (pitch_label(r.f1, names), pitch_label(r.f2, names))
    length = "2^%d bins of %.3f Hz" % (swift_round(math.log2(r.n)), r.bin_width)
    budget = ("±%.0f¢" if r.search.budget == swift_round(r.search.budget) else "±%.1f¢") % r.search.budget
    bound = minimum_reduced_sum(r.search.max_order)
    w = r.search.widest
    if w is None:
        return ("This interval (%s) cannot be measured at this record length (%s): no tone-bin pair lies within %s of "
                "both requested pitches." % (requested, length, budget))
    return ("This interval (%s) cannot be resolved at this record length (%s): within %s of the requested pitches every "
            "tone-bin pair is degenerate — the best is a %d:%d tone ratio with a lattice spacing of %d bins, whose reduced "
            "sum %d is below the %d that keeps products up to order %d on distinct bins. Pick a less consonant interval."
            % (requested, length, budget, w.a, w.b, w.g, w.reduced_sum, bound, r.search.max_order))


def rows(result: Result, m: dict) -> List[dict]:
    imd = m["chordIMD"]
    names = imd["pitch"]["noteNames"]
    r = result.resolver
    a = result.analysis
    v = r.verdict()
    floor, separation, skirt = v["floor"], v["separation"], r.loudest_skirt()
    roles = r.harmonic_roles()
    placed: Dict[Tuple[int, int], dict] = {}
    if roles is not None:
        iv = roles[0]
        for p in a.products:
            placed[(p.m, p.n)] = grid_point(p.m * iv.a + p.n * iv.b, iv, imd["harmonicRoles"], names)
    truth = result.truth
    reference = truth.tone_reference
    out = []
    for p in sorted(a.products, key=lambda q: (q.order, q.m, -q.n)):
        b = r.bin_of(p)
        reading = r.resolution(p, floor, separation, skirt)
        point = placed.get((p.m, p.n))
        partner = r.partner_check(p)
        expected = truth.amplitude(p.m, p.n)
        truth_dbc = None
        error = None
        if expected is not None and reference is not None and reference > 0:
            truth_dbc = db20(expected / reference) if expected > 0 else -math.inf
        if expected is not None and expected > 0 and p.amplitude > 0:
            error = db20(p.amplitude / expected)
        out.append(dict(
            m=p.m, n=p.n, order=p.order, label=p.label, freq_hz=p.frequency, bin=b,
            off_f1_bins=b - r.bin1, off_f2_bins=b - r.bin2, pitch=pitch_label(p.frequency, names),
            amplitude=p.amplitude, level_dbc=r.level_dbc(p), above_floor=p.above_floor,
            reading=reading.kind, limit_detail=reading.detail_text(),
            grid_index="nan" if point is None else str(point["index"]),
            role="nan" if point is None else (point["role"] or "none"),
            contest=len(r.contest(p)),
            partner="nan" if partner is None else partner[0],
            partner_excess_db=None if partner is None else partner[1] - partner[2],
            partner_inconsistent=None if partner is None else (partner[1] - partner[2]) > r.rs["partnerToleranceDB"],
            truth_amplitude=expected, truth_closed_amplitude=truth.closed_form(p.m, p.n),
            truth_dbc=truth_dbc, err_db=error))
    return out


def write_tsv(result: Result, m: dict, out) -> None:
    imd = m["chordIMD"]
    names = imd["pitch"]["noteNames"]
    plan, signal, a, r, n, truth = result.plan, result.signal, result.analysis, result.resolver, result.n, result.truth
    bw = signal.fs / n
    pl = imd["plan"]
    source = plan.source
    if isinstance(source, list):
        out.write("# source: phantom(%s)\n" % ";".join("%d,%d,%s" % (pm, pn, fmt(lv)) for pm, pn, lv in source))
    else:
        out.write("# source: %s pre=%s post=%s inverted=%s\n" % (
            source.label, source.pre.label if source.pre else "none", source.post.label if source.post else "none",
            flag(source.inverted)))
    intended = intended_length(plan.fs, plan.ceiling, pl)
    duration = stimulus_duration(plan.fs, plan.ceiling, pl, imd["stimulus"]["fadeS"], imd["window"]["settleS"])
    out.write("# plan: note1=%s note2=%s peak_amplitude=%s fs=%s ceiling=%d intended_length=%d stimulus_duration_s=%s standard_grids=%s\n" % (
        plan.note1, plan.note2, fmt(plan.peak), fmt(plan.fs), plan.ceiling, intended, fmt(duration),
        ",".join("%d/%d" % (g.fs, g.n) for g in standard_grids(pl))))
    emitted = result.search.emitted
    out.write("# lattice: " + lattice_line(result.search, emitted, signal.fs, n, signal.duration,
                                           int(imd["analyzer"]["defaultMaxOrder"])) + "\n")
    out.write("# tones: f1=%s Hz bin=%d f2=%s Hz bin=%d fs=%s fft_length=%d bin_width_hz=%s tone1_amp=%s tone2_amp=%s "
              "truth_tone1_amp=%s truth_tone2_amp=%s pitch1=%s pitch2=%s\n" % (
                  fmt(signal.f1), r.bin1, fmt(signal.f2), r.bin2, fmt(signal.fs), n, fmt(bw), fmt(a.tone1), fmt(a.tone2),
                  fmt(truth.tone1), fmt(truth.tone2), pitch_label(signal.f1, names).replace(" ", "_"),
                  pitch_label(signal.f2, names).replace(" ", "_")))
    out.write("# stimulus: amplitude1=%s amplitude2=%s duration_s=%s fade_s=%s samples=%d band_hz=%s-%s "
              "latency_error_samples=%d legacy_payload=%s\n" % (
                  fmt(signal.a1), fmt(signal.a2), fmt(signal.duration), fmt(signal.fade), signal.sample_count,
                  fmt(a.band[0]), fmt(a.band[1]), plan.latency_error, flag(plan.legacy)))
    w = result.window
    out.write("# window: start=%d length=%d steady_end=%d fade_overrun=%d overruns=%s settle_s=%s analyzer_separation_db=%s\n" % (
        w.start, w.length, w.steady_end, w.fade_overrun, flag(w.overruns), fmt(imd["window"]["settleS"]),
        fmt(r.analyzer_separation())))
    out.write("# drive level: " + drive_line(signal) + "\n")
    if plan.noise_rms is not None and truth.tone_reference is not None:
        increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
        med, broad, gap = expected_noise(plan.noise_rms, n, truth.tone_reference)
        out.write("# noise: rms_dbfs=%s rms=%s seed=%d stream_seed=%d expected_median_dbc=%s broadband_dbc=%s per_bin_below_broadband_db=%s\n" % (
            plan.noise_db_text, fmt(plan.noise_rms), plan.seed, hd.repeat_seed(plan.seed, 0, increment), fmt(med), fmt(broad), fmt(gap)))
    else:
        out.write("# noise: rms_dbfs=none rms=nan seed=%d stream_seed=nan expected_median_dbc=nan broadband_dbc=nan per_bin_below_broadband_db=nan\n" % plan.seed)
    if plan.wander is not None:
        delta, cycles, ramp = plan.wander
        out.write("# wander: delta=%s cycles=%s ramp=%s rate_hz=%s\n" % (fmt(delta), fmt(cycles), flag(ramp), fmt(cycles * signal.fs / n)))
    else:
        out.write("# wander: delta=nan cycles=nan ramp=0 rate_hz=nan\n")
    out.write("# truth: kind=%s quadrature_points=%d max_order=%d drive_amp1=%s drive_amp2=%s pre_gain1=%s pre_gain2=%s tone_reference=%s\n" % (
        truth.kind, truth.points, truth.max_order, fmt(truth.drive1), fmt(truth.drive2), fmt(truth.pre1), fmt(truth.pre2),
        fmt(truth.tone_reference)))
    out.write("# stored tiles (capture time): smpte=%s ccif=%s total=%s\n" % (fmt(a.smpte), fmt(a.ccif), fmt(a.total)))
    smpte, ccif, total, excluded = r.derived_percentages()
    out.write("# shipped derivedPercentages (read time): smpte=%s ccif=%s total=%s excluded=%d%s\n" % (
        fmt(smpte), fmt(ccif), fmt(total), len(excluded),
        "" if not excluded else " [" + " ".join("%s@%s%s%d" % (p.label, r.proximity(p)[0], "+" if r.proximity(p)[1] >= 0 else "", r.proximity(p)[1]) for p in excluded) + "]"))
    v = r.verdict()
    floor = v["floor"]
    out.write("# shipped verdict: present=%d absent=%d unresolved=%d out_of_band=%d floor_dbc=%s floor_samples=%d floor_spread_db=%s\n" % (
        v["present"], v["absent"], v["unresolved"], v["out_of_band"], fmt(None if floor is None else floor[0]),
        0 if floor is None else floor[1], fmt(None if floor is None else floor[2])))
    out.write("# floor line: absence=%s noise_reads=%d | %s\n" % (v["absence"], v["noise_reads"], r.floor_line(v)))
    orders = [p.order for p in a.products]
    out.write("# enumeration: recipes=%d orders=%d-%d\n" % (len(a.products), min(orders) if orders else 0, max(orders) if orders else 0))
    roles = r.harmonic_roles()
    if roles is not None:
        iv, buckets, total_bucket, unplaced = roles

        def cell(name, bucket):
            counted, absent, unread = bucket["counted"], bucket["absent"], bucket["unread"]
            return (name + "=" + fmt(role_level(counted)) + " n=%d absent=%d unread=%d bound=%d [" % (
                len(counted), len(absent), len(unread), 1 if unread else 0)
                + " ".join("%s@%d=%s" % (c["product"].label, c["point"]["index"], fmt(c["level"])) for c in counted)
                + ("" if not unread else " unread:" + ",".join(c["product"].label for c in unread)) + "]")
        out.write("# harmonic roles (IMDAnalysis.harmonicRoles): interval=%s ratio=%d:%d grid_hz=%s %s %s unplaced=%s\n" % (
            iv.label.replace(" ", "_"), iv.a, iv.b, fmt(iv.grid_hz),
            " ".join(cell(name, buckets[name]) for name in ("thickening", "subOctave", "addedColour", "clash")),
            cell("total", total_bucket), ",".join(c["product"].label for c in unplaced)))
    else:
        out.write("# harmonic roles: absent — the delivered notes name no 12-TET interval\n")
    coherence = r.coherence_reading()
    if coherence is not None:
        def pair(p: Optional[Pair]) -> str:
            if p is None:
                return "nan"
            return fmt(p.level) + " floor=%s [" % fmt(p.floor) + " ".join(
                "%s@%s%d=%s" % (s[0], "+" if s[1] >= 0 else "", s[1], fmt(s[2])) for s in p.sidebands) + "]"
        co = imd["coherence"]
        out.write("# coherence (IMDAnalysis.coherenceReading): source=%s worst_dbc=%s floor_dbc=%s excess_over_floor_db=%s "
                  "bar_over_floor_db=%s excess_over_bar_db=%s exceeds=%d spacing_bins=%d max_offset_bins=%d clearance_bins=%d "
                  "lattice_clear=%d interprets_device=%d interprets_loop_only=%d not_trustworthy_device=%d not_trustworthy_loop_only=%d "
                  "loudest_product_dbc=%s readable_offsets=%s unreadable_offsets=%s level_limited=%d read_bin_count=%d "
                  "expected_noise_excess_db=%s pair_f1_dbc=%s pair_f2_dbc=%s pair_difference_db=%s expected_difference_db=%s\n" % (
                      coherence.source, fmt(coherence.worst_level), fmt(coherence.floor), fmt(coherence.worst_excess_over_floor),
                      fmt(float(co["thresholdOverFloorDB"])), fmt(coherence.excess_over_threshold), 1 if coherence.exceeds else 0,
                      coherence.g, coherence.widest, coherence.clearance, 1 if coherence.lattice_clear else 0,
                      1 if coherence.interprets("device") else 0, 1 if coherence.interprets("loopOnly") else 0,
                      1 if coherence.not_trustworthy("device") else 0, 1 if coherence.not_trustworthy("loopOnly") else 0,
                      fmt(coherence.loudest_product_dbc), offsets_field(coherence.readable_offsets),
                      offsets_field(coherence.unreadable_offsets), 1 if coherence.level_limited else 0,
                      coherence.read_bin_count, fmt(coherence.expected_noise_excess), pair(coherence.pair_about("f1")),
                      pair(coherence.pair_about("f2")), fmt(coherence.pair_difference), fmt(coherence.expected_difference)))
        out.write("# coherence line, device register: " + coherence.line("device") + "\n")
        out.write("# coherence line, loop-only register: " + coherence.line("loopOnly") + "\n")
    else:
        out.write("# coherence: absent — no detector stored and no product beside a played note on this lattice; nothing to read\n")
    skirt = r.loudest_skirt()
    if skirt is not None:
        under = sum(1 for p in a.products if r.resolution(p, floor, v["separation"], skirt).kind == "under_loudest_skirt")
        out.write("# loudest skirt: present loudest=%s loudest_dbc=%s g=%d skirt_db=%s under_skirt=%d\n" % (
            skirt["product"].label, fmt(skirt["level"]), skirt["g"], fmt(skirt["skirt"]), under))
    else:
        out.write("# loudest skirt: absent — loudest product not above 0 dBc, or the coherence reading interprets\n")
    near = sum(1 for p in a.products if r.resolution(p, None, None, None).kind == "near_louder_product")
    out.write("# near louder product: %d refused (g=%s)\n" % (near, fmt(r.lattice_spacing()) if r.lattice_spacing() is not None else "nan"))
    # The summary features (`FingerprintFeatures.extractIMDFeatures`): the
    # resolved products split into cross and harmonic recipes.
    resolved = [p for p in a.products if r.resolution(p, floor, v["separation"], skirt).is_present]
    cross = [p for p in resolved if p.m != 0 and p.n != 0]
    harmonic = [p for p in resolved if (p.m == 0) != (p.n == 0)]
    cross_power = sum(p.amplitude ** 2 for p in cross)
    harmonic_power = sum(p.amplitude ** 2 for p in harmonic)
    ratio = None if cross_power <= 0 or harmonic_power <= 0 else 10 * math.log10(cross_power / harmonic_power)
    confidence = None if ratio is None else min(1.0, len(cross) / 6) * min(1.0, len(harmonic) / 4)
    for register in ("device", "control"):
        out.write("# shipped features, %s register (FeatureExtractor.extract(imd:)): imd_resolved_nothing=%d imd_to_harmonic_ratio_db=%s ratio_confidence=%s\n" % (
            register, 0 if resolved else 1, fmt(ratio), fmt(confidence)))
    out.write("\t".join(COLUMNS) + "\n")
    for row in rows(result, m):
        out.write("\t".join(fmt(row[c]) for c in COLUMNS) + "\n")


def offsets_field(offsets: List[int]) -> str:
    s = sorted(offsets)
    if not s:
        return "none"
    if s == list(range(1, len(s) + 1)):
        return "1..%d" % len(s)
    return ",".join(str(d) for d in s)


def write_refusal(plan: SynthPlan, refusal: LatticeRefusal, m: dict, out) -> None:
    imd = m["chordIMD"]
    pl = imd["plan"]
    source = plan.source
    if isinstance(source, list):
        out.write("# source: phantom(%s)\n" % ";".join("%d,%d,%s" % (pm, pn, fmt(lv)) for pm, pn, lv in source))
    else:
        out.write("# source: %s pre=%s post=%s inverted=%s\n" % (
            source.label, source.pre.label if source.pre else "none", source.post.label if source.post else "none",
            flag(source.inverted)))
    intended = intended_length(plan.fs, plan.ceiling, pl)
    duration = stimulus_duration(plan.fs, plan.ceiling, pl, imd["stimulus"]["fadeS"], imd["window"]["settleS"])
    out.write("# plan: note1=%s note2=%s peak_amplitude=%s fs=%s ceiling=%d intended_length=%d stimulus_duration_s=%s standard_grids=%s\n" % (
        plan.note1, plan.note2, fmt(plan.peak), fmt(plan.fs), plan.ceiling, intended, fmt(duration),
        ",".join("%d/%d" % (g.fs, g.n) for g in standard_grids(pl))))
    out.write("# lattice: " + lattice_line(refusal.search, None, plan.fs, intended, duration,
                                           int(imd["analyzer"]["defaultMaxOrder"])) + "\n")
    out.write("# refused: " + refusal_description(refusal, imd["pitch"]["noteNames"]) + "\n")


# ---------------------------------------------------------------------------
# CLI — the same options as `analysisdump imd-synth`


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
    p.add_argument("--products")
    p.add_argument("--note1", default="A2")
    p.add_argument("--note2", default="E3")
    p.add_argument("--amplitude", type=float, default=0.05)
    p.add_argument("--rate", type=float)
    p.add_argument("--length", type=int)
    p.add_argument("--pre", choices=["lowpass", "highpass"])
    p.add_argument("--pre-hz", type=float)
    p.add_argument("--pre-q", type=float)
    p.add_argument("--post", choices=["lowpass", "highpass"])
    p.add_argument("--post-hz", type=float)
    p.add_argument("--post-q", type=float)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--latency-error", type=int, default=0)
    p.add_argument("--noise-db", type=float)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--wander", type=float)
    p.add_argument("--cycles", type=float, default=1.0)
    p.add_argument("--ramp", action="store_true")
    p.add_argument("--legacy", action="store_true")
    p.add_argument("--out")
    return p


def plan_from_args(args, m: dict) -> SynthPlan:
    imd = m["chordIMD"]
    default_q = m["transferCurve"]["biquad"]["defaultQ"]

    def filt(kind, hz, q):
        if kind is None:
            return None
        if hz is None:
            raise SystemExit(f"--{kind} needs its corner in Hz")
        return tc.Filter("lowPass" if kind == "lowpass" else "highPass", hz, default_q if q is None else q)
    if args.source == "phantom":
        if not args.products:
            raise SystemExit("--source phantom needs --products m,n,dBc;...")
        source = []
        for entry in args.products.split(";"):
            pm, pn, level = entry.split(",")
            source.append((int(pm), int(pn), float(level)))
    else:
        gain_default = {"tanh": 4.0, "asymmetric": 3.0}.get(args.source, 4.0)
        threshold_default = 0.3 if args.source == "parametric" else 0.1
        params = dict(gain=gain_default if args.gain is None else args.gain,
                      threshold=threshold_default if args.threshold is None else args.threshold,
                      a2=args.a2, a3=args.a3, negative_scale=args.negative_scale)
        if args.source == "parametric":
            params = dict(threshold=params["threshold"], knee=args.knee, asymmetry=args.asymmetry)
        source = Device(args.source, params, filt(args.pre, args.pre_hz, args.pre_q),
                        filt(args.post, args.post_hz, args.post_q), args.invert)
    fs = float(imd["plan"]["standardSampleRateHz"] if args.rate is None else args.rate)
    ceiling = imd["plan"]["standardFFTLength"] if args.length is None else args.length
    noise = None if args.noise_db is None else 10 ** (args.noise_db / 20)
    wander = None if args.wander is None else (args.wander, args.cycles, args.ramp)
    return SynthPlan(source, args.note1, args.note2, args.amplitude, fs, ceiling, args.latency_error, noise,
                     "none" if args.noise_db is None else ("%g" % args.noise_db), args.seed, wander, args.legacy)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    m = load_manifest(args.manifest)
    plan = plan_from_args(args, m)
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        try:
            result = run(plan, m)
        except LatticeRefusal as refusal:
            write_refusal(plan, refusal, m, out)
            return 0
        write_tsv(result, m, out)
    finally:
        if args.out:
            out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
