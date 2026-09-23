#!/usr/bin/env python3
"""Waveform Matrix — an independent reimplementation of PedalScope's measured
waveform matrix (the "scope view"), written from the methods manifest
(``Docs/Methods/generated/manifest.json``, the ``waveformMatrix`` object)
and the technical chapter's own statements, NOT by transliterating the
Swift.

This instrument has NO estimator. Its payload is the capture: raw Float32
input and output tiles, a fixed number of stimulus periods each, over a
note × level grid. What this module reimplements is therefore the five
decisions that say WHICH samples are kept and how they are LABELLED:

1. the two lattices — the note lattice (12-TET-snapped, refined around
   the span's middle note with the standard note guaranteed on it) and the
   amplitude lattice (refined per side around the rig's anchor, the floor
   a fixed span below the anchor, the ceiling absolute);
2. the stimulus — one stepped tone per note row (chapter five's
   ``SteppedToneSignal``, IMPORTED from ``compression_curve.py`` and never
   copied), inside a silent pre-roll and tail;
3. the extraction — every tile starts at the first upward zero crossing of
   the stimulus at or after its step's measurement window, the output tile
   the same span at the loop's latency; a tile that cannot fit RAISES;
4. the encoding — Float32 little-endian base64 with the layout stated per
   array, and a reader that refuses an unknown encoding or a count mismatch;
5. the row noise stamp and its read-time use — the pre-roll's rms (a mirror
   of the app's two inline computations, the manifest says so) against a
   6 dB margin for the "≈ noise" badge.

It imports ``harmonic_distortion.py`` for the device family, the noise
generator and the seed sequence, ``transfer_curve.py`` for the biquad
filters, the parametric clipper and the steady-state series truth, and
``compression_curve.py`` for the stepped tone. It produces the same TSV
``analysisdump matrix-synth`` produces (same header lines, same column set,
same conventions), so one comparator serves both, and
``test_parity_matrix.py`` pins the two against each other and against the
exact truth — EQUALITY where the method is exact.

Conventions, repeated from the manifest because they decide what a number
means:

* dBFS is digital full scale (1.0 = full scale); the anchor is a VOLTAGE
  (168 mV pk at the pedal input) expressed in the rig's dBFS through its
  volts factor, or −26 dBFS by convention where no factor is known;
* a tile is stored as it was captured — Float32, the capture rate, no
  resampling — and every statistic here is computed from the DECODED
  Float32 samples, exactly as the app's reader computes them;
* the stamp is the capture's own pre-roll rms; the truth stamp is the noise
  this module injected.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import struct
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import compression_curve as cp
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
# Pitch (manifest ``waveformMatrix.lattice.noteSnapRule``)

NOTE_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]


def describe(frequency: float) -> Optional[Tuple[str, float]]:
    """Nearest 12-TET name (A4 = 440 Hz) and the deviation in cents; None
    outside midi 0…127 or for a non-positive frequency."""
    if frequency <= 0:
        return None
    midi = 69 + 12 * math.log2(frequency / 440)
    nearest = swift_round(midi)
    if nearest < 0 or nearest > 127:
        return None
    cents = (midi - nearest) * 100
    return NOTE_NAMES[nearest % 12] + str(nearest // 12 - 1), cents


def midi_frequency(midi: int) -> float:
    return 440 * 2 ** ((midi - 69) / 12)


def note_frequency(name: str, wm: dict) -> Optional[float]:
    """``TransferCurvePlan.frequency(note:)``: the note anchor's NAME returns
    the app's standard frequency verbatim (E2 → 82.4, never 12-TET's
    82.407); every other name is exact 12-TET."""
    anchor_hz = float(wm["lattice"]["noteAnchorHz"])
    anchor_name = describe(anchor_hz)[0]
    if name == anchor_name:
        return anchor_hz
    text = name.strip()
    if not text:
        return None
    letter = text[0].upper()
    if letter not in "CDEFGAB":
        return None
    semitones = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter]
    rest = text[1:]
    accidental = 0
    if rest[:1] in ("#", "♯"):
        accidental, rest = 1, rest[1:]
    elif rest[:1] in ("b", "♭"):
        accidental, rest = -1, rest[1:]
    try:
        octave = int(rest)
    except ValueError:
        return None
    midi = (octave + 1) * 12 + semitones + accidental
    if midi < 0 or midi > 127:
        return None
    return midi_frequency(midi)


def snap(hz: float, wm: dict) -> Optional[float]:
    d = describe(hz)
    return None if d is None else note_frequency(d[0], wm)


# ---------------------------------------------------------------------------
# The two lattices (manifest ``waveformMatrix.lattice``)


def note_frequencies(count: int, low_hz: float, high_hz: float, anchor_hz: Optional[float], wm: dict) -> List[float]:
    """``WaveformMatrixPlan.noteFrequencies``: the snapped endpoints seed;
    the cross-check guarantee (the anchor, when count ≥ 3 and it lies
    strictly inside the span); the centre guarantee (the snapped
    log-midpoint); then per-side refinement around the centre — the side
    with fewer interior points first (ties to the low side), the widest
    log gap first (ties by lower index), a colliding midpoint skipped, an
    honest shortfall when no gap accepts a point."""
    if count < 1 or low_hz <= 0 or high_hz <= low_hz:
        return []
    low, high = snap(low_hz, wm), snap(high_hz, wm)
    if low is None or high is None:
        return []
    if count == 1 or high <= low:
        return [low]
    points = [low, high]
    if count >= 3 and anchor_hz is not None:
        anchor = snap(anchor_hz, wm)
        if anchor is not None and low < anchor < high:
            points.insert(1, anchor)
    centre = None
    mid = snap(math.sqrt(low * high), wm)
    if mid is not None and low < mid < high:
        if mid in points:
            centre = mid
        elif len(points) < count:
            points.insert(next(i for i, p in enumerate(points) if p > mid), mid)
            centre = mid
    while len(points) < count:
        inserted = False
        if centre is not None and centre in points:
            c = points.index(centre)
            below = range(0, c)
            above = range(c, len(points) - 1)
            below_interior = c - 1
            above_interior = len(points) - c - 2
            sides = [below, above] if below_interior <= above_interior else [above, below]
        else:
            sides = [range(0, len(points) - 1)]
        for side in sides:
            gaps = sorted(side, key=lambda i: (-(points[i + 1] / points[i]), i))
            for i in gaps:
                snapped = snap(math.sqrt(points[i] * points[i + 1]), wm)
                if snapped is not None and points[i] < snapped < points[i + 1]:
                    points.insert(i + 1, snapped)
                    inserted = True
                    break
            if inserted:
                break
        if not inserted:
            break
    return points


def anchor_dbfs(volts_at_full_scale: Optional[float], wm: dict) -> float:
    """``WaveformMatrixPlan.anchorDBFS``: the dBFS delivering the standard
    drive's volts on this rig, or the no-volts convention."""
    lat = wm["lattice"]
    if volts_at_full_scale is None or volts_at_full_scale <= 0:
        return float(lat["noVoltsAnchorDBFS"])
    return 20 * math.log10(float(lat["anchorVoltsPeak"]) / volts_at_full_scale)


def default_floor_dbfs(anchor: float, wm: dict) -> float:
    return anchor - float(wm["lattice"]["defaultFloorSpanBelowAnchorDB"])


def amplitudes_dbfs(count: int, floor_dbfs: float, ceiling_dbfs: float, anchor: Optional[float]) -> List[float]:
    """``WaveformMatrixPlan.amplitudesDBFS``: [floor, ceiling] seed; the
    anchor joins when count ≥ 3 and it lies inside the span by 0.5 dB;
    then anchor-centred per-side refinement — the side with fewer interior
    points (ties to the quiet side), its widest gap (the FIRST widest by
    strict >, the #372 tie) split at its midpoint in dB. Without a usable
    anchor: the widest gap overall, ties to the quieter gap."""
    if count < 1:
        return []
    if count == 1:
        return [ceiling_dbfs]
    points = [floor_dbfs, ceiling_dbfs]
    usable = count >= 3 and anchor is not None and floor_dbfs + 0.5 < anchor < ceiling_dbfs - 0.5
    if not usable:
        while len(points) < count:
            widest = 0
            for i in range(len(points) - 1):
                if points[i + 1] - points[i] > points[widest + 1] - points[widest]:
                    widest = i
            points.insert(widest + 1, (points[widest] + points[widest + 1]) / 2)
        return points
    points.insert(1, anchor)
    while len(points) < count:
        anchor_index = next(i for i, p in enumerate(points) if abs(p - anchor) < 1e-12)
        below_interior = anchor_index - 1
        above_interior = len(points) - anchor_index - 2
        gap_range = range(0, anchor_index) if below_interior <= above_interior else range(anchor_index, len(points) - 1)
        widest = gap_range.start
        for i in gap_range:
            if points[i + 1] - points[i] > points[widest + 1] - points[widest]:
                widest = i
        points.insert(widest + 1, (points[widest] + points[widest + 1]) / 2)
    return points


# ---------------------------------------------------------------------------
# The plan and the stimulus (manifest ``waveformMatrix.stimulus``)


@dataclass(frozen=True)
class MatrixPlan:
    frequencies_hz: Tuple[float, ...]
    amplitudes_dbfs: Tuple[float, ...]
    fs: float
    period_count: int
    preroll_s: float
    tail_s: float
    settle_s: float
    measure_s: float
    ramp_s: float

    @property
    def preroll_samples(self) -> int:
        return int(self.preroll_s * self.fs)

    @property
    def tail_samples(self) -> int:
        return int(self.tail_s * self.fs)

    def row_signal(self, row: int) -> cp.SteppedTone:
        """The compression chapter's stepped tone — imported, never copied —
        at this row's note, walked over the amplitude lattice quiet to loud."""
        return cp.SteppedTone.build(self.frequencies_hz[row], self.fs,
                                    [10 ** (a / 20) for a in self.amplitudes_dbfs],
                                    self.settle_s, self.measure_s, self.ramp_s)

    def row_stimulus(self, row: int) -> np.ndarray:
        return np.concatenate([np.zeros(self.preroll_samples), self.row_signal(row).samples(),
                               np.zeros(self.tail_samples)])

    def tile_sample_count(self, row: int) -> int:
        """``periodCount`` whole periods ROUNDED to the capture rate."""
        return swift_round(self.period_count * self.fs / self.frequencies_hz[row])

    def tile_start(self, row: int, step: int) -> int:
        """The first sample at or after the step's measurement window whose
        stimulus phase is a whole number of cycles (an upward zero
        crossing), never before the window."""
        signal = self.row_signal(row)
        f0 = self.frequencies_hz[row]
        lo, _ = signal.measure_range(step)
        cycle = math.ceil(lo * f0 / self.fs)
        return max(swift_round(cycle * self.fs / f0), lo)


def ramp_s_from(wm: dict, cm: dict) -> float:
    """The ramp is the stepped tone's DEFAULT argument, carried only in the
    rule strings; read from the matrix block's rule and checked against
    the compression block's delivered ramp."""
    import re
    m = re.search(r"rampDuration \(([0-9.]+) s", wm["stimulus"]["rampRule"])
    value = float(m.group(1))
    assert abs(value - float(cm["stimulus"]["rampS"])) < 1e-12, "the two chapters disagree on the ramp"
    return value


def make_plan(dimension: int, low_hz: float, high_hz: float, floor_dbfs: Optional[float], ceiling_dbfs: float,
              volts_at_full_scale: Optional[float], fs: float, period_count: int, m: dict) -> Tuple[MatrixPlan, float]:
    """The measurement of record's own sequence (manifest ``lattice``)."""
    wm = m["waveformMatrix"]
    anchor = anchor_dbfs(volts_at_full_scale, wm)
    floor = default_floor_dbfs(anchor, wm) if floor_dbfs is None else floor_dbfs
    st = wm["stimulus"]
    plan = MatrixPlan(
        tuple(sorted(note_frequencies(dimension, low_hz, high_hz, float(wm["lattice"]["noteAnchorHz"]), wm))),
        tuple(sorted(amplitudes_dbfs(dimension, floor, ceiling_dbfs, anchor))),
        fs, period_count, float(st["prerollS"]), float(st["tailS"]), float(st["settleS"]), float(st["measureS"]),
        ramp_s_from(wm, m["compression"]))
    return plan, anchor


# ---------------------------------------------------------------------------
# The device, carried state, the loop (manifest ``waveformMatrix.synthesis``)


@dataclass(frozen=True)
class MatrixDevice:
    kind: str                    # a transfer_curve device kind, or "crossover"
    params: dict
    pre: Optional[tc.Filter] = None
    post: Optional[tc.Filter] = None
    inverted: bool = False

    def apply(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if self.kind == "crossover":
            d = self.params["dead_zone"]
            return np.where(x > d, x - d, np.where(x < -d, x + d, 0.0))
        return tc.nonlinearity(self.kind, self.params)(x)

    def render(self, x: np.ndarray, fs: float) -> np.ndarray:
        y = np.asarray(x, dtype=np.float64)
        if self.pre is not None:
            y = self.pre.biquad(fs).process(y)
        y = self.apply(y)
        if self.post is not None:
            y = self.post.biquad(fs).process(y)
        if self.inverted:
            y = -y
        return y

    @property
    def memoryless_unfiltered(self) -> bool:
        return self.pre is None and self.post is None

    @property
    def transfer_device(self) -> Optional[tc.Device]:
        if self.kind == "crossover":
            return None
        return tc.Device(self.kind, self.params, self.pre, self.post, self.inverted)

    @property
    def label(self) -> str:
        if self.kind == "crossover":
            return f"crossover(deadZone: {fmt(self.params['dead_zone'])})"
        return tc.device_label(self.kind, self.params)


@dataclass
class Plan:
    device: MatrixDevice
    plan: MatrixPlan
    volts_at_full_scale: Optional[float]
    anchor_dbfs: float
    carried_state: bool = True
    latency: int = 0
    latency_error: int = 0
    chain_gain_db: float = 0.0
    noise_rms: Optional[float] = None
    seed: int = 1

    @property
    def chain_gain(self) -> float:
        return 10 ** (self.chain_gain_db / 20)

    @property
    def analyzed_latency(self) -> int:
        return self.latency + self.latency_error


def row_seed(plan: Plan, row: int, increment: int) -> int:
    return hd.repeat_seed(plan.seed, row, increment)


def rendered(plan: Plan) -> Tuple[List[np.ndarray], Optional[np.ndarray]]:
    """Carried state: the rows' stimuli concatenated in capture order,
    rendered ONCE, then sliced; independent rows: each from zero state."""
    stimuli = [plan.plan.row_stimulus(r) for r in range(len(plan.plan.frequencies_hz))]
    if plan.carried_state:
        stream = plan.device.render(np.concatenate(stimuli), plan.plan.fs)
        rows, offset = [], 0
        for s in stimuli:
            rows.append(stream[offset:offset + len(s)])
            offset += len(s)
        return rows, stream
    return [plan.device.render(s, plan.plan.fs) for s in stimuli], None


def through_loop(row: int, rows: List[np.ndarray], stream: Optional[np.ndarray], plan: Plan, increment: int) -> np.ndarray:
    count = len(rows[row])
    d = plan.latency
    captured = np.zeros(count)
    if stream is not None:
        row_start = sum(len(r) for r in rows[:row])
        j = np.arange(count) + row_start - d
        valid = j >= 0
        captured[valid] = stream[j[valid]]
    elif d < count:
        captured[d:] = rows[row][:count - d]
    if plan.noise_rms is not None:
        captured = captured + hd.gaussian_noise(count, plan.noise_rms, row_seed(plan, row, increment), increment)
    if plan.chain_gain != 1:
        captured = captured * plan.chain_gain
    return captured


def captures(plan: Plan, increment: int) -> List[np.ndarray]:
    rows, stream = rendered(plan)
    return [through_loop(r, rows, stream, plan, increment) for r in range(len(rows))]


# ---------------------------------------------------------------------------
# The stamp (the mirror), the encoding, the cut (manifest ``noise`` / ``encoding`` / ``extraction``)


def noise_stamp(captured: np.ndarray, plan: MatrixPlan) -> float:
    """THE MIRROR: √(Σ x²/N) over the capture's first pre-roll samples, 0
    when that window is empty — both call sites' inline expression."""
    w = captured[:min(plan.preroll_samples, len(captured))]
    return 0.0 if len(w) == 0 else float(math.sqrt(float(np.dot(w, w)) / len(w)))


ENCODING = "float32le-base64"


@dataclass(frozen=True)
class SampleArray:
    encoding: str
    channel: str
    sample_count: int
    data: bytes

    @classmethod
    def make(cls, channel: str, samples: np.ndarray) -> "SampleArray":
        f32 = np.asarray(samples, dtype=np.float32)
        return cls(ENCODING, channel, len(f32), f32.astype("<f4").tobytes())

    def samples(self) -> Optional[np.ndarray]:
        """None — a refusal the caller states — on an unknown encoding or a
        byte count that disagrees with the stated sample count."""
        if self.encoding != ENCODING or len(self.data) != self.sample_count * 4:
            return None
        return np.frombuffer(self.data, dtype="<f4").astype(np.float32)

    def json(self) -> dict:
        return {"encoding": self.encoding, "channel": self.channel, "sampleCount": self.sample_count,
                "data": base64.b64encode(self.data).decode("ascii")}

    @classmethod
    def from_json(cls, d: dict) -> "SampleArray":
        return cls(d["encoding"], d["channel"], int(d["sampleCount"]), base64.b64decode(d["data"]))


class ExtractionFailure(Exception):
    pass


@dataclass(frozen=True)
class Tile:
    frequency_index: int
    amplitude_index: int
    input: SampleArray
    output: SampleArray


def tiles(plan: MatrixPlan, row: int, captured: np.ndarray, latency: int) -> List[Tile]:
    """The shipped cut: for each step the zero-crossing start, the window
    check (RAISES — never a truncated tile), the capture check (RAISES),
    then Float32 of the tone and of the capture over the same span."""
    signal = plan.row_signal(row)
    tone = signal.samples()
    f0 = plan.frequencies_hz[row]
    count = plan.tile_sample_count(row)
    out = []
    for step in range(len(plan.amplitudes_dbfs)):
        lo, hi = signal.measure_range(step)
        start = plan.tile_start(row, step)
        if start + count > hi - signal.ramp_samples:
            raise ExtractionFailure("Tile at %.1f Hz step %d does not fit its measurement window (%d samples needed, %d available)."
                                    % (f0, step, count, hi - signal.ramp_samples - start))
        captured_start = plan.preroll_samples + latency + start
        if captured_start < 0 or captured_start + count > len(captured):
            raise ExtractionFailure("Capture too short for the tile at %.1f Hz step %d (need %d samples at offset %d, have %d)."
                                    % (f0, step, count, captured_start, len(captured)))
        out.append(Tile(row, step, SampleArray.make("input", tone[start:start + count]),
                        SampleArray.make("output", captured[captured_start:captured_start + count])))
    return out


@dataclass(frozen=True)
class Statistics:
    sample_count: int
    rms: float
    peak: float
    mean: float

    @classmethod
    def of(cls, samples: np.ndarray) -> "Statistics":
        """Over Float32 samples accumulated in float64 — the app's
        ``SampleStatistics``: rms, peak (max |x|), mean."""
        if len(samples) == 0:
            return cls(0, 0.0, 0.0, 0.0)
        d = np.asarray(samples, dtype=np.float64)
        return cls(len(d), float(math.sqrt(float(np.sum(d * d)) / len(d))), float(np.max(np.abs(d))),
                   float(np.sum(d) / len(d)))


def noise_margin_db(output: np.ndarray, row_noise_rms: Optional[float]) -> Optional[float]:
    if row_noise_rms is None or row_noise_rms <= 0 or len(output) == 0:
        return None
    r = Statistics.of(output).rms
    if r <= 0:
        return -math.inf
    return 20 * math.log10(r / row_noise_rms)


def payload_bytes(plan: MatrixPlan, all_tiles: List[Tile], row_noise_rms: List[float]) -> int:
    """The encoded payload's size as the app writes it: JSON, sorted keys,
    no spaces (JSONEncoder's ``.sortedKeys`` without pretty printing)."""
    obj = {"sampleRate": plan.fs, "periodCount": plan.period_count, "frequenciesHz": list(plan.frequencies_hz),
           "amplitudesDBFS": list(plan.amplitudes_dbfs), "rowNoiseRMS": row_noise_rms,
           "tiles": [{"frequencyIndex": t.frequency_index, "amplitudeIndex": t.amplitude_index,
                      "input": t.input.json(), "output": t.output.json()} for t in all_tiles]}
    return len(_swift_json(obj))


def _swift_json(obj) -> str:
    """Foundation's JSONEncoder spelling, as far as the byte count needs it:
    sorted keys, no whitespace, an integral double written without its
    fraction (96000, not 96000.0), other doubles as the shortest round-trip,
    and a forward slash in a string ESCAPED as ``\\/`` (the encoder's
    default; base64 holds one in every ~64 characters)."""
    if isinstance(obj, dict):
        return "{" + ",".join('"%s":%s' % (k, _swift_json(obj[k])) for k in sorted(obj)) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(_swift_json(v) for v in obj) + "]"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return str(int(obj)) if obj == int(obj) and abs(obj) < 1e15 else fmt(obj)
    return '"' + str(obj).replace("\\", "\\\\").replace('"', '\\"').replace("/", "\\/") + '"'


# ---------------------------------------------------------------------------
# The truth


@dataclass
class TileRow:
    frequency_index: int
    amplitude_index: int
    frequency_hz: float
    amplitude_dbfs: float
    note: str
    cents: float
    amp_mv_pk: Optional[float]
    input_start: int
    captured_start: int
    sample_count: int
    input: Statistics
    output: Statistics
    row_noise_rms: float
    noise_margin_db: Optional[float]
    noise_badge: Optional[bool]
    float32_error: float
    dead_fraction: float
    truth_kind: str
    truth_max_error: float
    truth_rms_error: float
    truth: Statistics
    truth_stamp: Optional[float]
    truth_margin_db: Optional[float]
    truth_badge: Optional[bool]
    truth_dead_fraction: float
    truth_samples: np.ndarray


def truth_tile(plan: Plan, row: int, step: int, start: int, count: int, tone: np.ndarray, m: dict) -> Tuple[str, np.ndarray]:
    """Memoryless unfiltered: the device's function of the float64 tone at
    the tile's own samples; filtered: the transfer module's steady-state
    series at each sample's stimulus phase (reduced mod 2π)."""
    device = plan.device
    g = plan.chain_gain
    sign = -1.0 if device.inverted else 1.0
    if device.memoryless_unfiltered:
        return "memoryless", sign * g * device.apply(tone[start:start + count])
    td = device.transfer_device
    if td is None:
        raise SystemExit("the crossover device has no series truth — it is memoryless only; remove --pre/--post or use a reference nonlinearity")
    f0 = plan.plan.frequencies_hz[row]
    fs = plan.plan.fs
    amplitude = 10 ** (plan.plan.amplitudes_dbfs[step] / 20)
    tplan = tc.Plan.from_manifest(m["transferCurve"], f0, amplitude, 1.0, fs)
    truth = tc.Truth.build(td, tplan, 0.0, m["transferCurve"])
    w = 2 * math.pi * f0 / fs
    n = np.arange(start, start + count, dtype=np.float64)
    theta = np.fmod(w * n, 2 * math.pi)
    return "series", g * truth.raw(theta)


@dataclass
class Result:
    plan: Plan
    captures: List[np.ndarray]
    tiles: List[Tile]
    row_noise_rms: List[float]
    truth_stamp: Optional[float]
    rows: List[TileRow]
    payload_bytes: int


def run(plan: Plan, m: dict) -> Result:
    increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
    mp = plan.plan
    wm = m["waveformMatrix"]
    margin_bar = float(wm["noise"]["noiseClearMarginDB"])
    caps = captures(plan, increment)
    all_tiles: List[Tile] = []
    stamps: List[float] = []
    for r in range(len(mp.frequencies_hz)):
        stamps.append(noise_stamp(caps[r], mp))
        all_tiles += tiles(mp, r, caps[r], plan.analyzed_latency)
    truth_stamp = None if plan.noise_rms is None else plan.noise_rms * plan.chain_gain
    tones = [mp.row_signal(r).samples() for r in range(len(mp.frequencies_hz))]
    rows: List[TileRow] = []
    for t in all_tiles:
        f, a = t.frequency_index, t.amplitude_index
        hz, level = mp.frequencies_hz[f], mp.amplitudes_dbfs[a]
        inp = t.input.samples()
        out = t.output.samples()
        assert inp is not None and out is not None
        count = t.output.sample_count
        start = mp.tile_start(f, a)
        captured_start = mp.preroll_samples + plan.analyzed_latency + start
        segment = caps[f][captured_start:captured_start + count]
        f32_error = float(np.max(np.abs(out.astype(np.float64) - segment))) if count else 0.0
        kind, truth = truth_tile(plan, f, a, start, count, tones[f], m)
        e = out.astype(np.float64) - truth
        truth32 = truth.astype(np.float32)
        margin = noise_margin_db(out, stamps[f])
        tmargin = noise_margin_db(truth32, truth_stamp)
        d = describe(hz)
        rows.append(TileRow(
            f, a, hz, level, d[0] if d else "—", d[1] if d else float("nan"),
            None if plan.volts_at_full_scale is None else plan.volts_at_full_scale * 10 ** (level / 20) * 1000,
            start, captured_start, count, Statistics.of(inp), Statistics.of(out), stamps[f], margin,
            None if margin is None else margin < margin_bar,
            f32_error, float(np.sum(out == 0)) / max(count, 1),
            kind, float(np.max(np.abs(e))), float(math.sqrt(float(np.sum(e * e)) / max(count, 1))),
            Statistics.of(truth32), truth_stamp, tmargin, None if tmargin is None else tmargin < margin_bar,
            float(np.sum(truth == 0)) / max(count, 1), truth))
    return Result(plan, caps, all_tiles, stamps, truth_stamp, rows, payload_bytes(mp, all_tiles, stamps))


# ---------------------------------------------------------------------------
# The cross-check (manifest ``synthesis.crossCheckRule``)


@dataclass
class CrossCheck:
    frequency_index: int
    amplitude_index: int
    tile_amplitude: float
    transfer_amplitude: float
    amplitude_ratio_db: float
    bins: int
    bins_filled: int
    cycle_peak: float
    cycle_input_peak: float
    input_deficit_db: float
    max_difference: float
    rms_difference: float
    tile_binned: np.ndarray
    cycle_output: np.ndarray


def cross_check(result: Result, transfer_amplitude: float, m: dict) -> CrossCheck:
    plan = result.plan
    mp = plan.plan
    wm = m["waveformMatrix"]
    tcm = m["transferCurve"]
    anchor_hz = float(wm["lattice"]["noteAnchorHz"])
    f = next((i for i, hz in enumerate(mp.frequencies_hz) if abs(hz - anchor_hz) < 1e-9), None)
    if f is None:
        raise SystemExit("the note anchor %s Hz is not on this lattice — no cross-check" % fmt(anchor_hz))
    a = next((i for i, db in enumerate(mp.amplitudes_dbfs) if abs(db - plan.anchor_dbfs) < 1e-12), None)
    if a is None:
        raise SystemExit("the amplitude anchor %s dBFS is not on this lattice — no cross-check" % fmt(plan.anchor_dbfs))
    td = plan.device.transfer_device
    if td is None:
        raise SystemExit("the crossover device is not a transfer-oracle device — no cross-check")
    fs = mp.fs
    f0 = mp.frequencies_hz[f]
    tplan = tc.Plan.from_manifest(tcm, f0, transfer_amplitude, None, fs)
    captured = td.render(tplan.stimulus(), fs) * plan.chain_gain
    output = captured[min(tplan.preroll_samples, len(captured)):]
    cycle_in, cycle_out = tc.binned_cycle(tplan.tone(), output, 0, f0, fs, tplan.skip_cycles, int(tcm["binning"]["phaseBins"]))
    bins = len(cycle_out)
    tile = next(r for r in result.rows if r.frequency_index == f and r.amplitude_index == a)
    out = next(t for t in result.tiles if t.frequency_index == f and t.amplitude_index == a).output.samples().astype(np.float64)
    spc = fs / f0
    base = tile.input_start / spc
    last = base + (len(out) - 1) / spc
    binned = np.full(bins, np.nan)
    diffs = []
    for b in range(bins):
        centre = (b + 0.5) / bins
        total, n = 0.0, 0
        for p in range(mp.period_count + 1):
            target = math.floor(base) + p + centre
            if target < base or target > last:
                continue
            j = (target - base) * spc
            i = int(math.floor(j))
            t = j - i
            y0 = out[i]
            y1 = out[i + 1] if i + 1 < len(out) else y0
            total += y0 + (y1 - y0) * t
            n += 1
        if n == 0:
            continue
        binned[b] = total / n
        diffs.append(binned[b] - cycle_out[b])
    diffs = np.array(diffs)
    tile_amplitude = 10 ** (mp.amplitudes_dbfs[a] / 20)
    return CrossCheck(f, a, tile_amplitude, transfer_amplitude, 20 * math.log10(tile_amplitude / transfer_amplitude),
                      bins, len(diffs), float(np.max(np.abs(cycle_out))), float(np.max(np.abs(cycle_in))),
                      20 * math.log10(float(np.max(np.abs(cycle_in))) / transfer_amplitude),
                      float(np.max(np.abs(diffs))) if len(diffs) else 0.0,
                      float(math.sqrt(float(np.mean(diffs * diffs)))) if len(diffs) else float("nan"),
                      binned, cycle_out)


# ---------------------------------------------------------------------------
# The refusals


def refusals(plan: Plan, window_period_count: int, m: dict) -> dict:
    array = SampleArray.make("input", np.array([0.5, -0.5, 0.25]))
    j = array.json()
    j["encoding"] = "float64be-hex"
    unknown = SampleArray.from_json(j).samples() is not None
    j = array.json()
    j["sampleCount"] = 7
    count = SampleArray.from_json(j).samples() is not None
    increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
    mp = plan.plan
    caps = captures(plan, increment)
    last_step = len(mp.amplitudes_dbfs) - 1
    end = mp.preroll_samples + plan.analyzed_latency + mp.tile_start(0, last_step) + mp.tile_sample_count(0)
    short = None
    try:
        tiles(mp, 0, caps[0][:end - 1], plan.analyzed_latency)
    except ExtractionFailure as e:
        short = str(e)
    wide = MatrixPlan(mp.frequencies_hz, mp.amplitudes_dbfs, mp.fs, window_period_count, mp.preroll_s, mp.tail_s,
                      mp.settle_s, mp.measure_s, mp.ramp_s)
    window = None
    try:
        tiles(wide, 0, wide.row_stimulus(0), 0)
    except ExtractionFailure as e:
        window = str(e)
    return {"unknown": unknown, "count": count, "short": short, "window": window}


# ---------------------------------------------------------------------------
# Output — the oracle's exact lines


def _list(values) -> str:
    return "[" + ",".join(fmt(v) for v in values) + "]"


def write_tsv(result: Result, m: dict, raw: dict, out, samples: bool, check: Optional[CrossCheck]) -> None:
    plan = result.plan
    mp = plan.plan
    wm = m["waveformMatrix"]
    d = plan.device
    names = [(describe(hz) or ("—", 0))[0] for hz in mp.frequencies_hz]
    signals = [mp.row_signal(r) for r in range(len(mp.frequencies_hz))]
    out.write("# source: %s carried_state=%s pre=%s post=%s inverted=%s\n" % (
        d.label, fmt(plan.carried_state), d.pre.label if d.pre else "none", d.post.label if d.post else "none", fmt(d.inverted)))
    out.write("# grid: dimension=%s low_hz=%s high_hz=%s floor_db=%s ceiling_db=%s volts_at_full_scale=%s anchor_dbfs=%s "
              "default_floor_dbfs=%s note_anchor_hz=%s fs=%s period_count=%d notes=%d f_hz=%s note_names=[%s] levels=%d amp_dbfs=%s tiles=%d\n" % (
                  raw.get("dimension", "default"), raw.get("low_hz", "default"), raw.get("high_hz", "default"),
                  raw.get("floor_db", "default"), raw.get("ceiling_db", "plugin" if raw.get("plugin_ceiling") else "default"),
                  fmt(plan.volts_at_full_scale), fmt(plan.anchor_dbfs), fmt(default_floor_dbfs(plan.anchor_dbfs, wm)),
                  fmt(float(wm["lattice"]["noteAnchorHz"])), fmt(mp.fs), mp.period_count, len(mp.frequencies_hz),
                  _list(mp.frequencies_hz), ",".join(names), len(mp.amplitudes_dbfs), _list(mp.amplitudes_dbfs), len(result.tiles)))
    out.write("# plan: preroll_s=%s tail_s=%s settle_s=%s measure_s=%s preroll_samples=%d tail_samples=%d settle_samples=[%s] "
              "measure_samples=[%s] ramp_samples=[%s] row_samples=[%s] tile_samples=[%s]\n" % (
                  fmt(mp.preroll_s), fmt(mp.tail_s), fmt(mp.settle_s), fmt(mp.measure_s), mp.preroll_samples, mp.tail_samples,
                  ",".join(str(s.settle_samples) for s in signals), ",".join(str(s.measure_samples) for s in signals),
                  ",".join(str(s.ramp_samples) for s in signals),
                  ",".join(str(len(mp.row_stimulus(r))) for r in range(len(signals))),
                  ",".join(str(mp.tile_sample_count(r)) for r in range(len(signals)))))
    increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
    out.write("# loop: latency_samples=%d latency_error_samples=%d analyzed_latency_samples=%d chain_gain_db=%s chain_gain=%s "
              "noise_rms_dbfs=%s seed=%d row_seeds=[%s]\n" % (
                  plan.latency, plan.latency_error, plan.analyzed_latency, fmt(plan.chain_gain_db), fmt(plan.chain_gain),
                  raw.get("noise_db", "none"), plan.seed,
                  ",".join(str(row_seed(plan, r, increment)) for r in range(len(signals)))))
    out.write("# mirror: the row noise stamp is computed inline at both call sites (MeasurementService.measureWaveformMatrix's noiseWindow, "
              "ModelMeasurer.waveformMatrix's noise) — sqrt(sum(x^2)/N) over the capture's first preroll_samples — and reproduced here in "
              "MatrixSynthDump.noiseStamp; the grid, stimulus, cut and payload are the shipped WaveformMatrixPlan's own calls\n")
    excess = [fmt(20 * math.log10(s / result.truth_stamp)) if (result.truth_stamp and s > 0) else "nan" for s in result.row_noise_rms]
    out.write("# stamps: row_noise_rms=%s truth_stamp=%s excess_db=[%s] noise_clear_margin_db=%s payload_bytes=%d\n" % (
        _list(result.row_noise_rms), fmt(result.truth_stamp), ",".join(excess), fmt(float(wm["noise"]["noiseClearMarginDB"])),
        result.payload_bytes))
    if check is not None:
        out.write("# cross-check: freq_index=%d amp_index=%d tile_amplitude=%s transfer_amplitude=%s amplitude_ratio_db=%s bins=%d "
                  "bins_filled=%d cycle_peak=%s cycle_input_peak=%s input_deficit_db=%s max_difference=%s rms_difference=%s "
                  "max_difference_re_peak_db=%s\n" % (
                      check.frequency_index, check.amplitude_index, fmt(check.tile_amplitude), fmt(check.transfer_amplitude),
                      fmt(check.amplitude_ratio_db), check.bins, check.bins_filled, fmt(check.cycle_peak), fmt(check.cycle_input_peak),
                      fmt(check.input_deficit_db), fmt(check.max_difference), fmt(check.rms_difference),
                      fmt(20 * math.log10(check.max_difference / check.cycle_peak) if check.cycle_peak > 0 else float("nan"))))
        out.write("# cross-check bins: " + " ".join("%s:%s" % (fmt(x), fmt(y)) for x, y in zip(check.tile_binned, check.cycle_output)) + "\n")
    if samples:
        out.write("freq_index\tamp_index\tsample\tinput\toutput\ttruth\n")
        for t, r in zip(result.tiles, result.rows):
            inp, o = t.input.samples(), t.output.samples()
            for i in range(len(inp)):
                out.write("%d\t%d\t%d\t%s\t%s\t%s\n" % (t.frequency_index, t.amplitude_index, i, _f32(inp[i]), _f32(o[i]), fmt(float(r.truth_samples[i]))))
        return
    out.write("freq_index\tamp_index\tfreq_hz\tnote\tcents\tamp_dbfs\tamp_mv_pk\tinput_start\tcaptured_start\ttile_samples\t"
              "input_peak\tinput_rms\tinput_mean\toutput_peak\toutput_rms\toutput_mean\trow_noise_rms\tnoise_margin_db\tnoise_badge\t"
              "float32_error\tdead_fraction\ttruth_kind\ttruth_max_error\ttruth_rms_error\ttruth_peak\ttruth_rms\ttruth_mean\t"
              "truth_stamp\ttruth_margin_db\ttruth_badge\ttruth_dead_fraction\n")
    for r in result.rows:
        cols = [str(r.frequency_index), str(r.amplitude_index), fmt(r.frequency_hz), r.note, fmt(r.cents), fmt(r.amplitude_dbfs),
                fmt(r.amp_mv_pk), str(r.input_start), str(r.captured_start), str(r.sample_count),
                fmt(r.input.peak), fmt(r.input.rms), fmt(r.input.mean), fmt(r.output.peak), fmt(r.output.rms), fmt(r.output.mean),
                fmt(r.row_noise_rms), fmt(r.noise_margin_db), "nan" if r.noise_badge is None else fmt(r.noise_badge),
                fmt(r.float32_error), fmt(r.dead_fraction), r.truth_kind, fmt(r.truth_max_error), fmt(r.truth_rms_error),
                fmt(r.truth.peak), fmt(r.truth.rms), fmt(r.truth.mean), fmt(r.truth_stamp), fmt(r.truth_margin_db),
                "nan" if r.truth_badge is None else fmt(r.truth_badge), fmt(r.truth_dead_fraction)]
        out.write("\t".join(cols) + "\n")


def _f32(v) -> str:
    """A Float32 the way Swift prints one (shortest round-trip)."""
    return str(np.float32(v))


# ---------------------------------------------------------------------------
# Command line — the oracle's options


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--source", required=True,
                   choices=["identity", "tanh", "hardclip", "poly", "asymmetric", "parametric", "crossover"])
    p.add_argument("--gain", type=float)
    p.add_argument("--threshold", type=float)
    p.add_argument("--a2", type=float, default=0.0)
    p.add_argument("--a3", type=float, default=0.0)
    p.add_argument("--negative-scale", type=float, default=0.5)
    p.add_argument("--knee", type=float, default=0.5)
    p.add_argument("--asymmetry", type=float, default=0.0)
    p.add_argument("--dead-zone", type=float)
    p.add_argument("--pre", choices=["lowpass", "highpass"])
    p.add_argument("--pre-hz", type=float)
    p.add_argument("--pre-q", type=float)
    p.add_argument("--post", choices=["lowpass", "highpass"])
    p.add_argument("--post-hz", type=float)
    p.add_argument("--post-q", type=float)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--dimension")
    p.add_argument("--low-hz")
    p.add_argument("--high-hz")
    p.add_argument("--floor-db")
    p.add_argument("--ceiling-db")
    p.add_argument("--plugin-ceiling", action="store_true")
    p.add_argument("--volts-at-full-scale", type=float)
    p.add_argument("--rate", type=float, default=96_000.0)
    p.add_argument("--period-count", type=int)
    p.add_argument("--independent-rows", action="store_true")
    p.add_argument("--latency-samples", type=int, default=0)
    p.add_argument("--latency-error", type=int, default=0)
    p.add_argument("--chain-gain-db", type=float, default=0.0)
    p.add_argument("--noise-db")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--cross-check", action="store_true")
    p.add_argument("--cross-check-amplitude", type=float)
    p.add_argument("--samples", action="store_true")
    p.add_argument("--refusals", action="store_true")
    p.add_argument("--window-period-count", type=int, default=64)
    p.add_argument("--out")
    return p


def plan_from_args(args, m: dict) -> Tuple[Plan, dict]:
    wm = m["waveformMatrix"]
    lat = wm["lattice"]
    dimension = int(args.dimension) if args.dimension is not None else int(lat["defaultDimension"])
    low = float(args.low_hz) if args.low_hz is not None else float(lat["defaultLowFrequencyHz"])
    high = float(args.high_hz) if args.high_hz is not None else float(lat["defaultHighFrequencyHz"])
    floor = float(args.floor_db) if args.floor_db is not None else None
    if args.ceiling_db is not None:
        ceiling = float(args.ceiling_db)
    else:
        ceiling = float(lat["pluginCeilingDBFS"] if args.plugin_ceiling else lat["defaultCeilingDBFS"])
    period_count = args.period_count if args.period_count is not None else int(wm["stimulus"]["defaultPeriodCount"])
    plan, anchor = make_plan(dimension, low, high, floor, ceiling, args.volts_at_full_scale, args.rate, period_count, m)
    default_q = float(m["transferCurve"]["biquad"]["defaultQ"])

    def filt(kind, hz, q):
        if kind is None:
            return None
        return tc.Filter("lowPass" if kind == "lowpass" else "highPass", hz, default_q if q is None else q)

    if args.source == "crossover":
        dz = float(wm["synthesis"]["crossoverDeadZone"]) if args.dead_zone is None else args.dead_zone
        device = MatrixDevice("crossover", {"dead_zone": dz}, filt(args.pre, args.pre_hz, args.pre_q),
                              filt(args.post, args.post_hz, args.post_q), args.invert)
    else:
        threshold_default = 0.3 if args.source == "parametric" else 0.1
        gain_default = 3.0 if args.source == "asymmetric" else 4.0
        params = dict(gain=gain_default if args.gain is None else args.gain,
                      threshold=threshold_default if args.threshold is None else args.threshold,
                      a2=args.a2, a3=args.a3, negative_scale=args.negative_scale)
        if args.source == "parametric":
            params = dict(threshold=params["threshold"], knee=args.knee, asymmetry=args.asymmetry)
        device = MatrixDevice(args.source, params, filt(args.pre, args.pre_hz, args.pre_q),
                              filt(args.post, args.post_hz, args.post_q), args.invert)
    noise = None if args.noise_db is None else 10 ** (float(args.noise_db) / 20)
    p = Plan(device, plan, args.volts_at_full_scale, anchor, not args.independent_rows, args.latency_samples,
             args.latency_error, args.chain_gain_db, noise, args.seed)
    raw = {}
    for key in ("dimension", "low_hz", "high_hz", "floor_db", "ceiling_db", "noise_db"):
        v = getattr(args, key)
        if v is not None:
            raw[key] = v
    raw["plugin_ceiling"] = args.plugin_ceiling
    return p, raw


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    m = load_manifest(args.manifest)
    plan, raw = plan_from_args(args, m)
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    if args.refusals:
        r = refusals(plan, args.window_period_count, m)
        out.write("# refusal unknown_encoding: decodes=%s\n" % fmt(r["unknown"]))
        out.write("# refusal count_mismatch: decodes=%s\n" % fmt(r["count"]))
        out.write("# refusal short_capture: threw=%s message=%s\n" % (fmt(r["short"] is not None), r["short"] or "none"))
        out.write("# refusal window: threw=%s message=%s\n" % (fmt(r["window"] is not None), r["window"] or "none"))
        return 0
    try:
        result = run(plan, m)
    except ExtractionFailure as e:
        raise SystemExit(str(e))
    check = None
    if args.cross_check:
        amplitude = float(m["transferCurve"]["stimulus"]["defaultAmplitude"]) if args.cross_check_amplitude is None else args.cross_check_amplitude
        check = cross_check(result, amplitude, m)
    write_tsv(result, m, raw, out, args.samples, check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
