#!/usr/bin/env python3
"""The Harmonic Distortion chapter's figures (hd-*.png), the later chapters'
(transfer-*, imd-*, journey-*, compression-*) and the lay companion's
concept figures (explained-*.png) — generated from the Python
reimplementation (never screenshotted), seeded, fixed DPI, no timestamps
or version strings in the images, so the committed PNGs are a drift-check
subject. Beside every PNG a `.tsv` sidecar carries the plotted values; if a
platform ever renders text differently, the sidecars still diff exactly.

Run: python make_figures.py [--out Docs/Methods/figures] [--swift <synth tsv>]
The Swift TSV (analysisdump synth, tanh gain 2, seed 1) supplies the
three-way residual figure; without it that figure is skipped.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches  # noqa: E402
import matplotlib.colors  # noqa: E402

import harmonic_distortion as hd  # noqa: E402
import transfer_curve as tc  # noqa: E402
import chord_imd as ci  # noqa: E402
import machine_floor as mf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.normpath(os.path.join(HERE, "..", "figures"))
DPI = 110
SAVE = dict(dpi=DPI, metadata={"Software": None})

# The chapter's worked example: tanh, gain 2, seed 1 — the same run the
# parity test measures.
CASE = dict(kind="tanh", params=dict(gain=2.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5), amps=None)

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9, "legend.fontsize": 8,
    "figure.constrained_layout.use": True, "svg.hashsalt": "pedalscope-methods",
})


def load_tsv(path):
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    return np.genfromtxt(io.StringIO("".join(lines)), delimiter="\t", names=True, dtype=None, encoding="utf-8")


def write_sidecar(path, header, columns):
    """The ONE sidecar writer: every plotted value at
    `machine_floor.SIDECAR_SIGNIFICANT_FIGURES` significant figures (the
    2026-09-22 ruling — a value printed to its 17th digit is the machine's
    arithmetic, and two machines' differ there)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for row in zip(*columns):
            f.write("\t".join(mf.sidecar_value(v) for v in row) + "\n")


def fig_sweep(sweep, out):
    t = sweep.times()
    x = sweep.samples()
    f = sweep.instantaneous_frequency(t)
    fig, (a, b) = plt.subplots(2, 1, figsize=(6.4, 4.2))
    span = t <= 0.25
    a.plot(t[span], x[span], lw=0.6, color="#1f5fbf")
    a.set_xlabel("time (s)")
    a.set_ylabel("x(t)")
    a.set_title("The stimulus: a synchronized exponential sweep (first 0.25 s)")
    b.semilogy(t, f, color="#1f5fbf")
    b.axhline(sweep.f1, color="0.6", lw=0.6, ls="--")
    b.axhline(sweep.f2, color="0.6", lw=0.6, ls="--")
    b.set_xlabel("time (s)")
    b.set_ylabel("f(t) (Hz)")
    b.set_title(f"Instantaneous frequency f(t) = f1·exp(t/L), L = {hd.fmt(sweep.rate_constant)} s, T = {sweep.duration:.3f} s")
    fig.savefig(os.path.join(out, "hd-sweep.png"), **SAVE)
    plt.close(fig)
    step = 960
    write_sidecar(os.path.join(out, "hd-sweep.tsv"), ["t_s", "x", "f_hz"],
                  [t[::step], x[::step], f[::step]])


def fig_deconvolved(sweep, h, windows, out):
    fs = sweep.fs
    n = len(h)
    # Unwrap the circular response onto a negative-delay axis: index N−d ↦ −d/fs.
    span_s = 4.0
    count = int(span_s * fs)
    idx = np.arange(n - count, n)
    delay = -(n - idx) / fs
    seg = np.concatenate([h[idx], h[: int(0.05 * fs)]])
    tt = np.concatenate([delay, np.arange(int(0.05 * fs)) / fs])
    mag = 20 * np.log10(np.maximum(np.abs(seg) / sweep.amplitude, 1e-12))
    fig, a = plt.subplots(figsize=(6.4, 3.4))
    a.plot(tt, mag, lw=0.4, color="#1f5fbf")
    for w in windows:
        d = -w.delay_samples / fs
        a.axvline(d, color="#c0392b", lw=0.6, ls=":")
        a.text(d, 6, f"k={w.order}", rotation=90, va="bottom", ha="right", fontsize=7, color="#c0392b")
    a.set_ylim(-140, 20)
    a.set_xlabel("time relative to the linear pulse (s)")
    a.set_ylabel("|h| re A (dB)")
    a.set_title("The deconvolved response: harmonic pulses at −L·ln(k)")
    fig.savefig(os.path.join(out, "hd-deconvolved.png"), **SAVE)
    plt.close(fig)
    step = 480
    write_sidecar(os.path.join(out, "hd-deconvolved.tsv"), ["t_s", "h_db"], [tt[::step], mag[::step]])


def fig_windows(sweep, h, windows, out):
    fs = sweep.fs
    n = len(h)
    fig, axes = plt.subplots(3, 3, figsize=(6.6, 5.4), sharey=True)
    rows = []
    for w, a in zip(windows, axes.flat):
        position = 0 if w.order == 1 else n - hd.swift_round(w.delay_samples)
        offsets = np.arange(-w.left, w.right)
        weight = np.where(offsets < 0, 0.5 * (1 + np.cos(np.pi * (-offsets) / w.left)),
                          0.5 * (1 + np.cos(np.pi * offsets / w.right)))
        src = (position + offsets) % n
        mag = 20 * np.log10(np.maximum(np.abs(h[src]) / sweep.amplitude, 1e-12))
        t = offsets / fs
        a.plot(t, mag, lw=0.4, color="#1f5fbf")
        a2 = a.twinx()
        a2.plot(t, weight, color="#c0392b", lw=0.8)
        a2.set_ylim(0, 1.05)
        a2.set_yticks([] if w.order % 3 else [0, 1])
        a.set_ylim(-140, 20)
        a.set_title(f"k={w.order}: {w.left}+{w.right} smp, {w.seconds / fs:.4f} s", fontsize=7)
        a.set_xlabel("s from pulse", fontsize=7)
        rows.append((w.order, w.delay_samples / fs, w.left, w.right, w.seconds / fs))
    axes[1, 0].set_ylabel("|h| re A (dB)")
    fig.suptitle("The extraction windows (raised cosine, red) over each order's pulse", fontsize=9)
    fig.savefig(os.path.join(out, "hd-windows.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "hd-windows.tsv"), ["order", "delay_s", "left_samples", "right_samples", "window_s"],
                  list(zip(*rows)))


def fig_magnitude(table, sweep, out):
    orders = sorted(set(r["order"] for r in table))
    fig, a = plt.subplots(figsize=(6.6, 4.0))
    colors = plt.cm.viridis(np.linspace(0, 0.9, len(orders)))
    cols = {"order": [], "f0_hz": [], "mag_db": [], "expected_db": [], "valid": []}
    for k, c in zip(orders, colors):
        rows = [r for r in table if r["order"] == k]
        f0 = np.array([r["f0_hz"] for r in rows])
        mag = np.array([r["mag_db"] if r["mag_db"] is not None else np.nan for r in rows])
        exp = rows[0]["expected_db"]
        valid = np.array([r["valid"] for r in rows], dtype=bool)
        if exp is None or not np.isfinite(exp) or exp < -100:
            continue  # analytically empty orders carry no curve to draw
        a.semilogx(f0[valid], mag[valid], color=c, lw=1.2, label=f"H{k} measured")
        a.semilogx(f0[~valid], mag[~valid], color=c, lw=1.2, ls=":", alpha=0.5)
        a.semilogx([f0[0], f0[-1]], [exp, exp], color=c, lw=0.8, ls="--", alpha=0.8)
        top = hd.max_valid_fundamental(sweep, k)
        if top < sweep.f2:
            a.axvline(top, color=c, lw=0.5, alpha=0.5)
        cols["order"] += [k] * len(rows)
        cols["f0_hz"] += list(f0)
        cols["mag_db"] += list(mag)
        cols["expected_db"] += [exp] * len(rows)
        cols["valid"] += list(valid)
    a.axvspan(sweep.excited_band_top, sweep.f2 * 1.02, color="0.85", alpha=0.6, lw=0)
    a.set_xlim(25, sweep.f2 * 1.02)
    a.set_xlabel("fundamental f0 (Hz)")
    a.set_ylabel("|H_k(k·f0)| (dB re input)")
    a.set_title("tanh(2x): measured |H_k| (solid), exact truth (dashed), past validity (dotted)")
    a.legend(ncol=3, loc="lower left")
    fig.savefig(os.path.join(out, "hd-magnitude.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "hd-magnitude.tsv"), list(cols), [cols[c] for c in cols])


def fig_residuals(py, sw, sweep, out):
    orders = sorted(set(sw["order"]))
    fig, (a, b) = plt.subplots(2, 1, figsize=(6.6, 5.0), sharex=True)
    colors = plt.cm.viridis(np.linspace(0, 0.9, len(orders)))
    cols = {"order": [], "f0_hz": [], "py_minus_swift_db": [], "py_minus_analytic_db": [], "swift_minus_analytic_db": []}
    top = sweep.excited_band_top
    for k, c in zip(orders, colors):
        ms = (sw["order"] == k) & (sw["valid"] == 1) & (sw["f0_hz"] <= top)
        mp = (py["order"] == k) & (py["valid"] == 1) & (py["f0_hz"] <= top)
        exp = sw["expected_db"][ms][0]
        if not np.isfinite(exp) or exp < -100:
            continue
        f0 = sw["f0_hz"][ms]
        d_sw = np.abs(py["mag_db"][mp] - sw["mag_db"][ms])
        d_an = py["mag_db"][mp] - exp
        d_sa = sw["mag_db"][ms] - exp
        a.loglog(f0, np.maximum(d_sw, 1e-16), color=c, lw=1.0, label=f"H{k}")
        b.semilogx(f0, d_an, color=c, lw=1.0)
        cols["order"] += [k] * len(f0)
        cols["f0_hz"] += list(f0)
        cols["py_minus_swift_db"] += list(py["mag_db"][mp] - sw["mag_db"][ms])
        cols["py_minus_analytic_db"] += list(d_an)
        cols["swift_minus_analytic_db"] += list(d_sa)
    a.set_ylabel("|Python − Swift| (dB)")
    a.set_title("Three-way residuals, tanh(2x), valid points inside the excited band")
    a.legend(ncol=5, fontsize=7)
    b.axhline(0, color="0.5", lw=0.5)
    b.set_ylabel("Python − analytic (dB)")
    b.set_xlabel("fundamental f0 (Hz)")
    fig.savefig(os.path.join(out, "hd-residuals.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "hd-residuals.tsv"), list(cols), [cols[c] for c in cols])


# --- The lay companion's concept figures (explained-*.png) ------------------
# Computed from the reimplementation's own nonlinearity family and the exact
# Fourier amplitudes the parity code uses as truth; no randomness anywhere.

CONCEPT_DEVICES = [
    ("tanh", dict(gain=2.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5)),
    ("hardclip", dict(gain=2.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5)),
    ("asymmetric", dict(gain=2.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5)),
]
CONCEPT_TITLES = {"tanh": "soft clip", "hardclip": "hard clip", "asymmetric": "asymmetric clip"}


def fig_clipping(m, out):
    """One sine cycle in, the clipped cycle out, and the exact harmonic
    ladder the output contains — at the sweep amplitude the chapter's
    worked example uses, for the three shapes the chapter explains."""
    amplitude = float(m["stimulus"]["amplitude"])
    points = int(m["synthesis"]["groundTruthPoints"])
    orders = list(range(1, int(m["extraction"]["harmonicCount"]) + 1))
    cycle = np.linspace(0.0, 1.0, 1001)
    x = amplitude * np.sin(2 * np.pi * cycle)
    fig, axes = plt.subplots(len(CONCEPT_DEVICES), 2, figsize=(6.6, 6.6),
                             gridspec_kw={"width_ratios": [1.15, 1.0]})
    wave_cols = {"cycle": cycle, "input": x}
    ladder_cols = {"order": orders}
    floor_db = -100.0
    outputs = [hd.nonlinearity(kind, **params)(x) for kind, params in CONCEPT_DEVICES]
    # One vertical scale for every row, wide enough for the largest output —
    # a soft clipper's output exceeds the input here, and an axis that cut
    # it off would draw it as a hard clipper.
    y_limit = 1.15 * max(amplitude, max(float(np.max(np.abs(y))) for y in outputs))
    for (kind, params), y, (a, b) in zip(CONCEPT_DEVICES, outputs, axes):
        label = hd.source_label(kind, params, None)
        a.plot(cycle, x, color="0.55", lw=0.9, ls="--", label="in")
        a.plot(cycle, y, color="#1f5fbf", lw=1.4, label="out")
        a.axhline(0, color="0.8", lw=0.5)
        a.set_xlim(0, 1)
        a.set_ylim(-y_limit, y_limit)
        a.set_xlabel("one cycle of the note")
        a.set_ylabel("amplitude (re full scale)")
        a.set_title(f"{CONCEPT_TITLES[kind]}: {label}", fontsize=8)
        a.legend(loc="upper right", fontsize=7)
        levels = []
        for k in orders:
            e = hd.expected_magnitude(kind, params, None, k, amplitude, points)
            levels.append(20 * np.log10(e) if e > 0 else -np.inf)
        levels = np.array(levels)
        present = levels > floor_db
        for k, lv, p in zip(orders, levels, present):
            color = "#1f5fbf" if k % 2 else "#e67e22"
            if p:
                b.vlines(k, floor_db, lv, color=color, lw=2.0)
                b.plot([k], [lv], "o", color=color, ms=4)
            else:
                b.plot([k], [floor_db + 3], "x", color=color, ms=5)
        b.set_xticks(orders)
        b.set_xlabel("harmonic (multiple of the note)")
        b.set_ylabel("level (dB re input)")
        b.set_ylim(floor_db, 10)
        b.set_title("the harmonics it contains (x = absent)", fontsize=8)
        b.grid(axis="y", color="0.9", lw=0.5)
        wave_cols[f"out_{kind}"] = y
        ladder_cols[f"{kind}_db"] = [lv if np.isfinite(lv) else -np.inf for lv in levels]
    fig.suptitle("A sine in, a clipped sine out, and the harmonic ladder that shape contains", fontsize=9)
    fig.savefig(os.path.join(out, "explained-clipping.png"), **SAVE)
    plt.close(fig)
    step = 10
    write_sidecar(os.path.join(out, "explained-clipping.tsv"), list(wave_cols),
                  [np.asarray(v)[::step] for v in wave_cols.values()])
    write_sidecar(os.path.join(out, "explained-clipping-ladder.tsv"), list(ladder_cols),
                  [ladder_cols[c] for c in ladder_cols])


# --- The Transfer Curve chapter's figures (transfer-*.png) ------------------
# Computed from the transfer reimplementation on the parity cases' own
# devices (deterministic — no randomness anywhere in the transfer path), the
# truth from the manifest's synthesis rules. Every axis is set from what it
# PLOTS: an axis taken from the input alone once drew a soft clipper flat.

TRANSFER_AMPLITUDE = 0.5  # the loudest hardware drive the sheet offers (−6 dBFS), the parity cases' own
BLUE, RED, GREY, ORANGE, GREEN = "#1f5fbf", "#c0392b", "0.55", "#e67e22", "#2e8b57"


def _transfer_run(m, kind, params, note="E2", pre=None, post=None, inverted=False, latency_error=0,
                  paired=False, half_cycle=False, duration=None):
    tcm = m["transferCurve"]
    frequency = tc.note_frequency(tcm, note)
    plan = tc.Plan.from_manifest(tcm, frequency, TRANSFER_AMPLITUDE, duration, None)
    device = tc.Device(kind, params, pre, post, inverted)
    synth = tc.SynthPlan(device, plan, note, latency_error, half_cycle, paired)
    return tc.run(synth, m)


def _symmetric_limits(*arrays, pad=1.08):
    top = max(float(np.max(np.abs(a))) for a in arrays)
    return -pad * top, pad * top


def _closed(x):
    return np.append(x, x[0])


def fig_transfer_cycle(m, out):
    """The worked example: tanh(2x) at 0.5, no filter — the averaged cycle
    as the X–Y figure, the static curve and the truth y = tanh(2x)."""
    r = _transfer_run(m, "tanh", dict(gain=2.0), paired=False)
    fig, (a, b) = plt.subplots(1, 2, figsize=(6.6, 3.3), gridspec_kw={"width_ratios": [1.0, 1.0]})
    x, y = r.displayed.cycle_in, r.displayed.cycle_out
    truth_x = np.linspace(-TRANSFER_AMPLITUDE, TRANSFER_AMPLITUDE, 401)
    truth_y = r.truth.memoryless(truth_x)
    a.plot(_closed(x), _closed(y), color=BLUE, lw=1.0, label="averaged cycle (X–Y)")
    a.plot(r.displayed.static_x, r.displayed.static_y, color=RED, lw=1.0, ls="--", label="static curve")
    a.plot(truth_x, truth_y, color=GREY, lw=0.8, ls=":", label="truth y = tanh(2x)")
    a.set_xlim(*_symmetric_limits(x, truth_x))
    a.set_ylim(*_symmetric_limits(y, truth_y))
    a.set_xlabel("input (re full scale)")
    a.set_ylabel("output (re full scale)")
    a.set_title("tanh(2x) at A = 0.5, E2: the figure", fontsize=8)
    a.legend(fontsize=7, loc="upper left")
    a.axhline(0, color="0.85", lw=0.5)
    a.axvline(0, color="0.85", lw=0.5)
    bins = np.arange(len(x))
    b.plot(bins, x, color=GREY, lw=0.9, ls="--", label="input cycle")
    b.plot(bins, y, color=BLUE, lw=1.2, label="output cycle")
    b.set_xlim(0, len(x) - 1)
    b.set_ylim(*_symmetric_limits(x, y))
    b.set_xlabel("phase bin b (of %d)" % len(x))
    b.set_ylabel("amplitude (re full scale)")
    b.set_title("the same cycle against phase", fontsize=8)
    b.legend(fontsize=7, loc="upper right")
    fig.suptitle("The averaged cycle: a memoryless soft clipper retraces one curve (loop areas %.4f / %.4f / %.4f)"
                 % (r.displayed.hysteresis, r.displayed.linear, r.displayed.nonlinear), fontsize=8)
    fig.savefig(os.path.join(out, "transfer-cycle.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "transfer-cycle.tsv"), ["bin", "input", "output", "truth"],
                  [bins, x, y, r.truth.memoryless(x)])


def fig_transfer_loop_decomposition(m, out):
    """A filtered device: the raw loop, the fitted fundamental ellipse and
    the residual — the three areas labelled."""
    post = tc.Filter("highPass", 20.0, m["transferCurve"]["biquad"]["defaultQ"])
    r = _transfer_run(m, "tanh", dict(gain=2.0), post=post, paired=False)
    d = r.displayed
    n = len(d.cycle_in)
    theta = 2 * np.pi * np.arange(n) / n
    ax_ = float(np.sum(d.cycle_in * np.cos(theta))) * 2 / n
    bx = float(np.sum(d.cycle_in * np.sin(theta))) * 2 / n
    ay = float(np.sum(d.cycle_out * np.cos(theta))) * 2 / n
    by = float(np.sum(d.cycle_out * np.sin(theta))) * 2 / n
    dcy = float(np.sum(d.cycle_out)) / n
    ellipse_x = ax_ * np.cos(theta) + bx * np.sin(theta)
    ellipse_y = dcy + ay * np.cos(theta) + by * np.sin(theta)
    residual = d.cycle_out - ellipse_y
    fig, axes = plt.subplots(1, 3, figsize=(6.8, 2.6))
    panels = [("raw loop: total %.4f" % d.hysteresis, d.cycle_in, d.cycle_out, BLUE),
              ("fundamental ellipse: linear %.4f" % d.linear, ellipse_x, ellipse_y, GREEN),
              ("residual: nonlinear %.4f" % d.nonlinear, d.cycle_in, residual, ORANGE)]
    lo, hi = _symmetric_limits(d.cycle_in)
    ylo, yhi = _symmetric_limits(d.cycle_out, ellipse_y)
    for a, (title, px, py, color) in zip(axes, panels):
        a.plot(_closed(px), _closed(py), color=color, lw=1.0)
        a.set_xlim(lo, hi)
        a.set_ylim(ylo, yhi)
        a.set_title(title, fontsize=8)
        a.set_xlabel("input", fontsize=8)
        a.axhline(0, color="0.85", lw=0.5)
        a.axvline(0, color="0.85", lw=0.5)
    axes[0].set_ylabel("output", fontsize=8)
    fig.suptitle("tanh(2x) behind a 20 Hz high-pass at E2: the loop and its decomposition (areas re the box)", fontsize=8)
    fig.savefig(os.path.join(out, "transfer-loop-decomposition.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "transfer-loop-decomposition.tsv"),
                  ["bin", "input", "output", "ellipse_input", "ellipse_output", "residual"],
                  [np.arange(n), d.cycle_in, d.cycle_out, ellipse_x, ellipse_y, residual])


def fig_transfer_delay_loop(m, out):
    """#348: the identity under a fixed 50-sample alignment error at three
    notes — the loop a rig's residual latency draws, growing with the note."""
    notes = ["E2", "A4", "C7"]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.7))
    cols = {}
    for a, note in zip(axes, notes):
        r = _transfer_run(m, "identity", {}, note=note, latency_error=50, paired=False)
        d = r.displayed
        phi = r.truth.fundamental[1]
        a.plot(_closed(d.cycle_in), _closed(d.cycle_out), color=BLUE, lw=1.0)
        lim = _symmetric_limits(d.cycle_in, d.cycle_out)
        a.set_xlim(*lim)
        a.set_ylim(*lim)
        a.set_aspect("equal")
        a.set_title("%s (%.0f Hz): φ = %.1f°, linear %.3f\n(π/4)|sin φ| = %.3f"
                    % (note, d.frequency, math.degrees(phi), d.linear, r.truth.expected_linear), fontsize=7)
        a.set_xlabel("input", fontsize=8)
        a.axhline(0, color="0.85", lw=0.5)
        a.axvline(0, color="0.85", lw=0.5)
        cols[f"input_{note}"] = d.cycle_in
        cols[f"output_{note}"] = d.cycle_out
    axes[0].set_ylabel("output", fontsize=8)
    fig.suptitle("A wire read 50 samples late at 96 kHz: an alignment error is a phase loop that grows with the note", fontsize=8)
    fig.savefig(os.path.join(out, "transfer-delay-loop.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "transfer-delay-loop.tsv"), ["bin"] + list(cols),
                  [np.arange(len(next(iter(cols.values()))))] + [cols[c] for c in cols])


def fig_transfer_compensation(m, out):
    """Raw vs compensated for a paired filtered device (the pre-dispersive
    case), the recovered static curve against the memoryless truth."""
    pre = tc.Filter("highPass", 40.0, m["transferCurve"]["biquad"]["defaultQ"])
    r = _transfer_run(m, "tanh", dict(gain=2.0), pre=pre, paired=True)
    d = r.displayed
    c = r.compensation.accepted
    fit = r.compensation.fit
    fig, (a, b) = plt.subplots(1, 2, figsize=(6.6, 3.3))
    a.plot(_closed(d.cycle_in), _closed(d.cycle_out), color=BLUE, lw=1.0, label="raw (total %.3f)" % d.hysteresis)
    a.plot(d.static_x, d.static_y, color=BLUE, lw=0.8, ls="--", label="raw static curve")
    a.set_title("raw: linear %.3f, nonlinear %.3f" % (d.linear, d.nonlinear), fontsize=8)
    b.plot(_closed(c.cycle_in), _closed(c.cycle_out), color=GREEN, lw=1.0, label="compensated (total %.4f)" % c.hysteresis)
    b.plot(c.static_x, c.static_y, color=GREEN, lw=0.8, ls="--", label="compensated static curve")
    truth_y = r.truth.compensated_static(c.static_x)
    b.plot(c.static_x, truth_y, color=GREY, lw=0.8, ls=":", label="memoryless truth")
    b.set_title("compensated: linear %.4f, nonlinear %.4f\n%d orders voted, support %.0f Hz, residual %.3f rad"
                % (c.linear, c.nonlinear, fit.voting, fit.highest_voting_order * d.frequency, fit.harmonic_residual_rms),
                fontsize=8)
    lo, hi = _symmetric_limits(d.cycle_in)
    ylo, yhi = _symmetric_limits(d.cycle_out, c.cycle_out, truth_y)
    for ax in (a, b):
        ax.set_xlim(lo, hi)
        ax.set_ylim(ylo, yhi)
        ax.set_xlabel("input", fontsize=8)
        ax.legend(fontsize=6, loc="upper left")
        ax.axhline(0, color="0.85", lw=0.5)
        ax.axvline(0, color="0.85", lw=0.5)
    a.set_ylabel("output", fontsize=8)
    fig.suptitle("tanh(2x) behind a 40 Hz high-pass BEFORE the clipper, paired: the §6.5 removal recovers the curve", fontsize=8)
    fig.savefig(os.path.join(out, "transfer-compensation.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "transfer-compensation.tsv"),
                  ["bin", "input", "raw_output", "compensated_output", "truth_compensated"],
                  [np.arange(len(d.cycle_in)), d.cycle_in, d.cycle_out, c.cycle_out,
                   [r.truth.compensated_bin(i, len(d.cycle_in), float(d.cycle_in[i])) for i in range(len(d.cycle_in))]])


def fig_transfer_coupling(m, out):
    """#353: the asymmetric clipper before and after a DC-blocking high-pass —
    the level asymmetry gone, the shape asymmetry (the even harmonics) kept."""
    post = tc.Filter("highPass", 20.0, m["transferCurve"]["biquad"]["defaultQ"])
    params = dict(gain=2.0, negative_scale=0.5)
    bare = _transfer_run(m, "asymmetric", params, paired=False)
    coupled = _transfer_run(m, "asymmetric", params, post=post, paired=True)
    c = coupled.compensation.accepted
    fig, (a, b) = plt.subplots(1, 2, figsize=(6.6, 3.3))
    a.plot(bare.displayed.static_x, bare.displayed.static_y, color=BLUE, lw=1.2, label="no coupling capacitor")
    a.plot(c.static_x, c.static_y, color=ORANGE, lw=1.2, label="behind a 20 Hz high-pass (compensated)")
    a.axhline(0, color="0.85", lw=0.5)
    a.axvline(0, color="0.85", lw=0.5)
    lo, hi = _symmetric_limits(bare.displayed.static_x)
    a.set_xlim(lo, hi)
    a.set_ylim(*_symmetric_limits(bare.displayed.static_y, c.static_y))
    a.set_xlabel("input", fontsize=8)
    a.set_ylabel("output", fontsize=8)
    a.set_title("static curves: +%.3f / %.3f bare, +%.3f / %.3f coupled"
                % (np.max(bare.displayed.static_y), np.min(bare.displayed.static_y), np.max(c.static_y), np.min(c.static_y)),
                fontsize=8)
    a.legend(fontsize=7, loc="upper left")
    # The harmonic ladders of the two truths, exact: the coupling capacitor
    # scales every order by |H(k·f0)| ≈ 1 and removes the DC alone.
    K = 9
    f0 = bare.displayed.frequency
    bare_c = np.abs(bare.truth.C[:K + 1]) * 2
    bare_c[0] = abs(bare.truth.C[0])
    gains = np.abs(coupled.truth.post[:K + 1])
    coup_c = bare_c * gains
    orders = np.arange(K + 1)
    b.bar(orders - 0.18, 20 * np.log10(np.maximum(bare_c, 1e-12)), width=0.36, color=BLUE, label="no capacitor")
    b.bar(orders + 0.18, 20 * np.log10(np.maximum(coup_c, 1e-12)), width=0.36, color=ORANGE, label="behind the capacitor")
    b.set_xticks(orders)
    b.set_xticklabels(["DC"] + [str(k) for k in orders[1:]])
    b.set_ylim(-80, 5)
    b.set_xlabel("harmonic order (DC = mean)", fontsize=8)
    b.set_ylabel("level (dB re full scale)", fontsize=8)
    b.set_title("the exact ladder: only the mean is removed", fontsize=8)
    b.legend(fontsize=7, loc="upper right")
    fig.suptitle("An asymmetric clipper (tanh, negative half-cycle × 0.5) with and without a series capacitor", fontsize=8)
    fig.savefig(os.path.join(out, "transfer-coupling.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "transfer-coupling.tsv"),
                  ["input", "bare_static", "coupled_compensated_static"],
                  [bare.displayed.static_x, bare.displayed.static_y, c.static_y])
    write_sidecar(os.path.join(out, "transfer-coupling-ladder.tsv"),
                  ["order", "bare_db", "coupled_db"],
                  [orders, 20 * np.log10(np.maximum(bare_c, 1e-12)), 20 * np.log10(np.maximum(coup_c, 1e-12))])


# --- The lay companion's Transfer Curve concept figure (#307) --------------

def fig_explained_ellipse(m, out):
    """One sine, the same sine shifted in time, and the oval the pair draws
    — then a clipped-and-shifted output, where the bends are the clipper and
    the opening is the shift. Computed through the reimplementation's own
    pipeline (the identity and the worked example's soft clipper under a
    planted alignment error of a twelfth of a cycle at the standard note);
    the fundamental phase and the oval's closed-form area come from the
    truth the parity code uses."""
    tcm = m["transferCurve"]
    f0 = tc.note_frequency(tcm, "E2")
    spc = float(tcm["stimulus"]["sampleRateHz"]) / f0
    shift = int(round(spc / 12))         # a twelfth of a cycle: 30 degrees
    wire = _transfer_run(m, "identity", {}, latency_error=shift, paired=False)
    clipper = _transfer_run(m, "tanh", dict(gain=2.0), latency_error=shift, paired=False)
    w, c = wire.displayed, clipper.displayed
    phi = wire.truth.fundamental[1]
    bins = np.arange(len(w.cycle_in))
    fig, (a, b, d) = plt.subplots(1, 3, figsize=(7.6, 2.8), gridspec_kw={"width_ratios": [1.25, 1.0, 1.0]})
    a.plot(bins, w.cycle_in, color=GREY, lw=1.0, ls="--", label="the sine")
    a.plot(bins, w.cycle_out, color=BLUE, lw=1.3, label="the same sine, shifted")
    a.set_xlim(0, len(bins) - 1)
    a.set_ylim(*_symmetric_limits(w.cycle_in, w.cycle_out))
    a.set_xlabel("one cycle (phase bin of %d)" % len(bins), fontsize=8)
    a.set_ylabel("amplitude", fontsize=8)
    a.set_title("two sines, one shifted by %.0f° (%d samples)" % (math.degrees(phi), shift), fontsize=8)
    a.legend(fontsize=6, loc="upper right")
    a.axhline(0, color="0.85", lw=0.5)
    b.plot(_closed(w.cycle_in), _closed(w.cycle_out), color=BLUE, lw=1.0)
    lim = _symmetric_limits(w.cycle_in, w.cycle_out)
    b.set_xlim(*lim)
    b.set_ylim(*lim)
    b.set_aspect("equal")
    b.set_title("one against the other: an oval\narea %.3f, formula %.3f" % (w.linear, wire.truth.expected_linear), fontsize=8)
    b.set_xlabel("the sine", fontsize=8)
    b.set_ylabel("the shifted sine", fontsize=8)
    d.plot(_closed(c.cycle_in), _closed(c.cycle_out), color=BLUE, lw=1.0)
    d.set_xlim(*_symmetric_limits(c.cycle_in))
    d.set_ylim(*_symmetric_limits(c.cycle_out))
    d.set_title("soft clipper, then the same shift:\nbends = clipper, opening = shift", fontsize=8)
    d.set_xlabel("input", fontsize=8)
    d.set_ylabel("output", fontsize=8)
    for ax in (b, d):
        ax.axhline(0, color="0.85", lw=0.5)
        ax.axvline(0, color="0.85", lw=0.5)
    fig.suptitle("Why a time shift draws a loop: a sine against a shifted copy of itself, at E2", fontsize=8)
    fig.savefig(os.path.join(out, "explained-ellipse.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "explained-ellipse.tsv"),
                  ["bin", "sine", "shifted_sine", "clipper_input", "clipper_shifted_output"],
                  [bins, w.cycle_in, w.cycle_out, c.cycle_in, c.cycle_out])


def transfer_figures(manifest_path, out):
    m = tc.load_manifest(manifest_path)
    fig_transfer_cycle(m, out)
    fig_transfer_loop_decomposition(m, out)
    fig_transfer_delay_loop(m, out)
    fig_transfer_compensation(m, out)
    fig_transfer_coupling(m, out)
    fig_explained_ellipse(m, out)


# --- The Chord IMD chapter's figures (imd-*.png) ----------------------------
# Computed from the two-tone reimplementation on the parity cases' own
# inputs (the seeded noise stream is the oracle's, so a figure with noise in
# it is byte-stable), the lattice from the manifest's own search results.
# Every axis is set from what it PLOTS.

IMD_PEAK = 0.5   # the worked example's combined peak (−6 dBFS), the parity cases' own
ROLE_COLOURS = {"thickening": BLUE, "subOctave": GREEN, "addedColour": ORANGE, "clash": RED}
ROLE_LABELS = {"thickening": "Thickening", "subOctave": "Growl (sub-octave)", "addedColour": "Added colour", "clash": "Sourness (clash)"}


def _imd_run(m, source, fs=96_000.0, length=None, peak=IMD_PEAK, noise_db=None, wander=None, legacy=False,
             note1="A2", note2="E3"):
    imd = m["chordIMD"]
    ceiling = int(imd["plan"]["standardFFTLength"]) if length is None else int(length)
    noise = None if noise_db is None else 10 ** (noise_db / 20)
    plan = ci.SynthPlan(source, note1, note2, peak, fs, ceiling, 0, noise, "none" if noise_db is None else "%g" % noise_db,
                        1, wander, legacy)
    return ci.run(plan, m)


def _imd_device(kind, **params):
    base = dict(gain=4.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5)
    base.update(params)
    return ci.Device(kind, base)


def _imd_magnitude(result, m):
    """The analyzer's own spectrum in dBc re the louder tone, over the
    reimplementation's window and scale (`window.scaleRule`)."""
    signal, n = result.signal, result.n
    plan = result.plan
    if isinstance(plan.source, list):
        captured = ci.phantom_capture(signal, plan.source)
    else:
        stimulus = signal.samples() if plan.wander is None else ci.wandering(signal, n, *plan.wander)
        captured = plan.source.render(stimulus, signal.fs)
    if plan.noise_rms is not None:
        increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
        captured = captured + hd.gaussian_noise(len(captured), plan.noise_rms, hd.repeat_seed(plan.seed, 0, increment), increment)
    w = result.window
    segment = np.zeros(n)
    end = min(len(captured), w.end)
    segment[: end - w.start] = captured[w.start:end]
    magnitude = np.abs(np.fft.rfft(segment)) * (2.0 / n)
    return 20 * np.log10(np.maximum(magnitude / result.analysis.tone_reference, 1e-30))


def fig_imd_lattice(m, out):
    """The product lattice: the shipped fifth (g = 22) beside the corpus
    probe (g = 2), every enumerated recipe at its bin and order, and a zoom
    beside the low note showing the detector's offsets, the 12-bin
    neighbourhood and the nearest lattice point."""
    imd = m["chordIMD"]
    shipped = _imd_run(m, _imd_device("identity"))
    corpus = _imd_run(m, _imd_device("identity"), length=1 << 17)
    fig, axes = plt.subplots(1, 3, figsize=(7.6, 2.9), gridspec_kw={"width_ratios": [1.3, 1.0, 1.0]})
    cols = {"lattice": [], "m": [], "n": [], "order": [], "bin": [], "refused": []}
    for a, r, name in ((axes[0], shipped, "shipped 109:163"), (axes[1], corpus, "corpus 75:113")):
        res = r.resolver
        bw = r.signal.fs / r.n
        k1, k2 = res.bin1, res.bin2
        g = ci.gcd(k1, k2)
        for p in r.analysis.products:
            b = res.bin_of(p)
            near = res.inside_neighbourhood(p)
            a.vlines(b, 1.5, p.order, color=RED if near else BLUE, lw=0.9 if near else 0.6, alpha=0.9)
            a.plot([b], [p.order], "o", color=RED if near else BLUE, ms=2.5)
            cols["lattice"].append(name); cols["m"].append(p.m); cols["n"].append(p.n)
            cols["order"].append(p.order); cols["bin"].append(b); cols["refused"].append(near)
        a.vlines([k1, k2], 0.5, 1, color=GREY, lw=1.8)
        a.plot([k1, k2], [1, 1], "s", color=GREY, ms=4)
        a.set_ylim(0.3, 7.7)
        a.set_yticks(range(1, 8))
        a.set_xlim(0, max(res.bin_of(p) for p in r.analysis.products) * 1.03)
        a.set_xlabel("analysis bin", fontsize=8)
        a.set_title("%s: bins %d:%d, g = %d\n2^%d at %g kHz, %.4f Hz per bin"
                    % (name, k1, k2, g, int(round(math.log2(r.n))), r.signal.fs / 1000, bw), fontsize=8)
    axes[0].set_ylabel("order |m| + |n| (1 = the tones)", fontsize=8)
    # The zoom: the low note on the shipped lattice.
    res = shipped.resolver
    k1 = res.bin1
    g = ci.gcd(res.bin1, res.bin2)
    offsets = imd["coherence"]["detectorOffsets"]
    nb = int(imd["resolution"]["playedToneNeighbourhoodBins"])
    z = axes[2]
    z.axvspan(-nb, nb, color="0.92", lw=0)
    z.vlines(0, 0, 1, color=GREY, lw=2.0, label="the played note")
    for d in offsets:
        z.vlines([-d, d], 0, 0.35, color=ORANGE, lw=0.9)
    nearest = [res.bin_of(p) - k1 for p in shipped.analysis.products if abs(res.bin_of(p) - k1) <= 30]
    for d in nearest:
        z.vlines(d, 0, 0.6, color=BLUE, lw=1.2)
    z.set_xlim(-30, 30)
    z.set_ylim(0, 1.1)
    z.set_yticks([])
    z.set_xlabel("bins from the low note", fontsize=8)
    z.set_title("beside the low note (shipped):\ndetector ±1…±%d (orange), %d-bin\nneighbourhood (grey), nearest lattice\npoint %d bins away (blue)"
                % (max(offsets), nb, min(abs(d) for d in nearest) if nearest else g), fontsize=7)
    fig.suptitle("The analysis lattice: every product on a multiple of g (red = refused beside a note)", fontsize=8)
    fig.savefig(os.path.join(out, "imd-lattice.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "imd-lattice.tsv"), list(cols), [cols[c] for c in cols])


def fig_imd_spectrum(m, out):
    """The worked example's analysed spectrum: tanh(2x) at a combined peak
    of 0.5 through −120 dBFS noise on the shipped fifth — the products
    above and below the gate, the capture floor, and a zoom on one product's
    local-floor neighbourhood with its exclusions cut out."""
    imd = m["chordIMD"]
    r = _imd_run(m, _imd_device("tanh", gain=2.0), noise_db=-120)
    res = r.resolver
    mag = _imd_magnitude(r, m)
    bw = r.signal.fs / r.n
    freqs = np.arange(len(mag)) * bw
    v = res.verdict()
    floor = v["floor"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.4, 3.1), gridspec_kw={"width_ratios": [1.6, 1.0]})
    top = 1300.0
    span = freqs <= top
    a.plot(freqs[span], mag[span], color="0.75", lw=0.3)
    cols = {"label": [], "freq_hz": [], "level_dbc": [], "above_floor": [], "reading": []}
    readings = res.resolutions()
    for p, reading in zip(r.analysis.products, readings):
        lv = res.level_dbc(p)
        colour = BLUE if reading.is_present else ("0.5" if reading.is_absent else RED)
        a.plot([p.frequency], [lv if lv is not None else -200], "o", color=colour, ms=3.2)
        cols["label"].append(p.label); cols["freq_hz"].append(p.frequency); cols["level_dbc"].append(lv)
        cols["above_floor"].append(p.above_floor); cols["reading"].append(reading.kind)
    a.plot([r.signal.f1, r.signal.f2], [res.level_dbc(ci.Product(1, 0, 1, r.signal.f1, r.analysis.tone1, True)),
                                        res.level_dbc(ci.Product(0, 1, 1, r.signal.f2, r.analysis.tone2, True))],
           "s", color=GREY, ms=5)
    if floor is not None:
        a.axhline(floor[0], color=RED, lw=0.7, ls="--")
        a.text(top * 0.99, floor[0] + 2, "capture floor %.1f dBc (%d bins)" % (floor[0], floor[1]), ha="right", fontsize=7, color=RED)
    a.set_xlim(0, top)
    a.set_ylim(-180, 5)
    a.set_xlabel("frequency (Hz)")
    a.set_ylabel("level (dBc re the louder tone)")
    a.set_title("tanh(2x), combined peak 0.5, noise −120 dBFS:\n%d present, %d absent, %d refused (%d recipes)"
                % (v["present"], v["absent"], v["unresolved"] + v["out_of_band"], len(r.analysis.products)), fontsize=8)
    # The zoom: the local-floor neighbourhood of 2f1−f2.
    target = next(p for p in r.analysis.products if (p.m, p.n) == (2, -1))
    tb = res.bin_of(target)
    an = imd["analyzer"]
    inner, outer = int(an["localFloorInnerOffsetBins"]), ci.outer_offset_bins(bw, an)
    claimed = {res.bin_of(p) for p in r.analysis.products} | {res.bin1, res.bin2, 0}
    for t in (res.bin1, res.bin2):
        claimed.update(ci.detector_bins(t, len(mag), imd["coherence"]["detectorOffsets"]))
    lo, hi = tb - outer - 5, tb + outer + 5
    idx = np.arange(lo, hi + 1)
    b.plot((idx - tb), mag[idx], color="0.75", lw=0.5)
    b.axvspan(-outer, -inner, color="0.92", lw=0)
    b.axvspan(inner, outer, color="0.92", lw=0)
    excluded = [i - tb for i in idx if i in claimed and inner <= abs(i - tb) <= outer]
    for e in excluded:
        b.axvline(e, color=RED, lw=0.6, ls=":")
    local = ci.local_floor(tb, 10 ** (mag / 20) * r.analysis.tone_reference, bw, claimed, an)
    local_db = 20 * math.log10(local / r.analysis.tone_reference) if local > 0 else -300
    b.axhline(local_db, color=RED, lw=0.7, ls="--")
    b.axhline(local_db + 20 * math.log10(4), color=ORANGE, lw=0.7, ls="--")
    b.plot([0], [mag[tb]], "o", color=BLUE, ms=4)
    b.set_xlim(-outer - 5, outer + 5)
    b.set_ylim(local_db - 25, max(mag[tb], local_db) + 20)
    b.set_xlabel("bins from 2f1−f2", fontsize=8)
    b.set_title("local floor beside 2f1−f2: median of\nthe grey span (±%d…±%d bins = ±%.1f Hz),\nlattice bins cut out (red); floor %.1f dBc,\ngate 4× (orange)"
                % (inner, outer, outer * bw, local_db), fontsize=7)
    fig.savefig(os.path.join(out, "imd-spectrum.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "imd-spectrum.tsv"), list(cols), [cols[c] for c in cols])


def fig_imd_window(m, out):
    """#191: the analysis window inside the stimulus's steady state at 96 and
    48 kHz, and the historical fixed 2^17 window on the 3 s stimulus at
    48 kHz that overran the fade-out by 1472 samples."""
    imd = m["chordIMD"]
    settle, fade = imd["window"]["settleS"], imd["stimulus"]["fadeS"]
    rows = []
    for row in imd["plan"]["standardGrids"]:
        if row["sampleRateHz"] in (96_000, 48_000):
            rows.append((row["label"], row["sampleRateHz"], row["stimulusDurationS"], row["windowStart"],
                         row["windowLength"], row["steadyEnd"], row["fadeOverrun"]))
    historical = ci.Signal(110.0, 165.0, 0.025, 0.025, 48_000.0, 3.0, fade)
    w = ci.window(historical, 0, 1 << 17, settle)
    rows.append(("pre-#191: 48000 Hz, 3 s stimulus, fixed 2^17", 48_000.0, 3.0, w.start, w.length, w.steady_end, w.fade_overrun))
    fig, axes = plt.subplots(len(rows), 1, figsize=(7.2, 4.2))
    for a, (label, fs, duration, start, length, steady_end, overrun) in zip(axes, rows):
        total = duration
        a.barh(0, fade, left=0, color="0.8", height=0.5)
        a.barh(0, total - 2 * fade, left=fade, color="0.9", height=0.5)
        a.barh(0, fade, left=total - fade, color="0.8", height=0.5)
        a.barh(0, settle, left=fade, color=ORANGE, height=0.5, alpha=0.6)
        a.barh(0, length / fs, left=start / fs, color=BLUE, height=0.3)
        if overrun > 0:
            a.barh(0, overrun / fs, left=steady_end / fs, color=RED, height=0.3)
        a.set_xlim(0, total)
        a.set_yticks([])
        a.set_title("%s\nstimulus %.3f s, window %d samples = %.3f s from %.3f s, overrun %d samples (%s)"
                    % (label, total, length, length / fs, start / fs, overrun,
                       "fits" if overrun <= 0 else "OVERRUNS the fade by %.4f s" % (overrun / fs)), fontsize=7)
    axes[-1].set_xlabel("time (s): fade (dark grey), steady state (light), settle (orange), window (blue), overrun (red)", fontsize=8)
    fig.suptitle("The analysis window is a duration inside the steady state; a fixed sample count is not", fontsize=8)
    fig.savefig(os.path.join(out, "imd-window.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "imd-window.tsv"),
                  ["label", "fs", "stimulus_s", "window_start", "window_length", "steady_end", "fade_overrun"],
                  list(zip(*rows)))


def fig_imd_detector(m, out):
    """The coherence detector beside the high note on a clean identity and on
    the wander fixture (both through −110 dBFS noise on the shipped
    lattice), each against its local floor and the 30 dB bar; and the
    per-offset product ceilings with two devices' loudest products."""
    imd = m["chordIMD"]
    co = imd["coherence"]
    clean = _imd_run(m, _imd_device("identity"), peak=0.05, noise_db=-110)
    fault = _imd_run(m, _imd_device("identity"), peak=0.05, noise_db=-110, wander=(6.1e-5, 1.0, False))
    fig, axes = plt.subplots(1, 3, figsize=(7.6, 2.9))
    cols = {"capture": [], "offset": [], "level_dbc": []}
    for a, r, name in ((axes[0], clean, "clean loop"), (axes[1], fault, "wander δ = 6.1e−5, one cycle per window")):
        reading = r.resolver.coherence_reading()
        pair = reading.pair_about("f2")
        offsets = [s[1] for s in pair.sidebands]
        levels = [s[2] for s in pair.sidebands]
        a.bar(offsets, [lv - (-200) for lv in levels], bottom=-200, color=BLUE, width=0.7)
        a.axhline(pair.floor, color=GREY, lw=0.8, ls="--")
        a.axhline(pair.floor + co["thresholdOverFloorDB"], color=RED, lw=0.8, ls="--")
        a.set_xticks([-9, -6, -3, -1, 1, 3, 6, 9])
        a.set_ylim(min(levels + [pair.floor]) - 8, max(levels + [pair.floor + co["thresholdOverFloorDB"]]) + 8)
        a.set_xlabel("bins from the high note", fontsize=8)
        a.set_title("%s\nworst %.1f dBc, %.1f dB over\nthe local floor (bar %.0f): %s"
                    % (name, reading.worst_level, reading.worst_excess_over_floor, co["thresholdOverFloorDB"],
                       "not trustworthy" if reading.exceeds else "premise held"), fontsize=7)
        for o, lv in zip(offsets, levels):
            cols["capture"].append(name); cols["offset"].append(o); cols["level_dbc"].append(lv)
    axes[0].set_ylabel("level (dBc)", fontsize=8)
    c = axes[2]
    d = co["detectorOffsets"]
    ceilings = co["productCeilingsDBcAtStandardSpacing"]
    c.plot(d, ceilings, "o-", color=BLUE, ms=3)
    worked = _imd_run(m, _imd_device("tanh", gain=2.0), noise_db=-120)
    loud = _imd_run(m, _imd_device("poly", a2=40.0), noise_db=-120)
    for r, name, colour in ((worked, "tanh(2x) at 0.5", GREEN), (loud, "x + 40x² at 0.5", RED)):
        lp = r.resolver.loudest_product_dbc()
        c.axhline(lp, color=colour, lw=0.9, ls="--")
        c.text(9.2, lp + 1.5, "%s: loudest product %+.1f dBc" % (name, lp), ha="right", fontsize=6.5, color=colour)
    c.set_xticks(d)
    c.set_xlabel("offset d (bins)", fontsize=8)
    c.set_ylabel("loudest product allowed (dBc)", fontsize=8)
    c.set_title("ceilings at g = 22: a bin reads the tone\nonly while the loudest product's skirt\nsits %.0f dB under the tone's there" % co["productSkirtMarginDB"], fontsize=7)
    fig.suptitle("The coherence detector: the bins beside a note, the local floor, the 30 dB bar, and the level rule", fontsize=8)
    fig.savefig(os.path.join(out, "imd-detector.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "imd-detector.tsv"), list(cols), [cols[c] for c in cols])


def fig_imd_roles(m, out):
    """#259: the harmonic grid of the requested fifth — every enumerated
    recipe placed at m·a + n·b on the 3 : 2 grid, coloured by the role the
    classifier assigns the point, the two played notes marked."""
    imd = m["chordIMD"]
    table = imd["harmonicRoles"]["tables"][0]
    a_, b_ = table["ratioA"], table["ratioB"]
    r = _imd_run(m, _imd_device("identity"))
    placed = {}
    for p in r.analysis.products:
        placed.setdefault(p.m * a_ + p.n * b_, []).append(p.label)
    fig, a = plt.subplots(figsize=(7.2, 3.2))
    cols = {"grid_index": [], "pitch": [], "role": [], "recipes": []}
    top = max(placed)
    points = {pt["index"]: pt for pt in table["points"]}
    names = imd["pitch"]["noteNames"]
    for index in range(min(placed), top + 1):
        labels = placed.get(index, [])
        if index <= 0:
            role = None
        elif index in points:
            role = points[index]["role"]
        else:
            iv = ci.Interval(table["lowerNote"], table["upperNote"], table["lowerNominalHz"], table["upperNominalHz"], a_, b_)
            role = ci.grid_point(index, iv, imd["harmonicRoles"], names)["role"]
        colour = ROLE_COLOURS.get(role, "0.6")
        for i, label in enumerate(labels):
            a.plot([index], [i + 1], "o", color=colour, ms=4)
        if labels:
            a.text(index, len(labels) + 0.5, str(len(labels)), ha="center", fontsize=6, color=colour)
        cols["grid_index"].append(index); cols["role"].append(role or "none"); cols["recipes"].append(";".join(labels))
        cols["pitch"].append(points[index]["pitchName"] if index in points else "")
    a.axvline(a_, color=GREY, lw=1.5)
    a.axvline(b_, color=GREY, lw=1.5)
    a.text(a_, 8.6, table["lowerNote"], ha="center", fontsize=7, color=GREY)
    a.text(b_, 8.6, table["upperNote"], ha="center", fontsize=7, color=GREY)
    for role, colour in ROLE_COLOURS.items():
        a.plot([], [], "o", color=colour, label=ROLE_LABELS[role])
    a.legend(fontsize=7, loc="upper right", ncol=4)
    a.set_xlim(min(placed) - 0.5, top + 0.5)
    a.set_ylim(0, 9.5)
    a.set_xticks(range(0, top + 1, 1))
    a.set_xlabel("grid index k = m·%d + n·%d (%g Hz steps; the low note at %d, the high at %d)" % (a_, b_, table["gridHz"], a_, b_), fontsize=8)
    a.set_ylabel("recipes at the point", fontsize=8)
    a.set_title("The harmonic grid of A2 + E3 at 3 : 2: where each of the %d recipes lands, coloured by role (index ≤ 0 has none)" % len(r.analysis.products), fontsize=8)
    fig.savefig(os.path.join(out, "imd-roles.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "imd-roles.tsv"), list(cols), [cols[c] for c in cols])


def fig_explained_skirt(m, out):
    """The lay companion's concept figure for coherent sampling: the two
    played notes on exact slots of the analysis window (two lines, the floor
    flat), the same two notes with the high one moved a stated fraction of
    a slot off its centre (its skirt spreads across the whole lattice), and
    the slots beside the high note — the coherence detector's — against the
    local floor and the bar. Everything is rendered through the
    reimplementation's own window, scale, analysis and coherence reading
    (never a drawn skirt): the plan's snapped signal at the standard drive
    through seeded noise, and a second signal whose high note is displaced."""
    imd = m["chordIMD"]
    co, wn = imd["coherence"], imd["window"]
    fs = float(imd["plan"]["standardSampleRateHz"])
    ceiling = int(imd["plan"]["standardFFTLength"])
    peak = float(imd["plan"]["defaultPeakAmplitude"])
    signal, _, n = ci.plan_signal(imd["plan"]["defaultNote1"], imd["plan"]["defaultNote2"], peak, fs, ceiling, m)
    bw = fs / n
    fraction = 0.25    # the displacement, in slots — printed in the panel title
    moved = ci.Signal(signal.f1, signal.f2 + fraction * bw, signal.a1, signal.a2, fs, signal.duration, signal.fade)
    noise_db = -110
    increment = int(m["harmonicDistortion"]["synthesis"]["noiseGeneratorIncrement"], 16)
    noise = hd.gaussian_noise(signal.sample_count, 10 ** (noise_db / 20), hd.repeat_seed(1, 0, increment), increment)
    captures = {"exact": signal.samples() + noise, "moved": moved.samples() + noise}
    w = ci.window(signal, 0, n, wn["settleS"])
    spectra, readings = {}, {}
    for name, captured in captures.items():
        # The stored stimulus is the exact one in both cases: the app reads a
        # capture against the signal it asked for, whatever the loop did.
        analysis = ci.analyze(captured, signal, 0, n, m)
        segment = np.zeros(n)
        end = min(len(captured), w.end)
        segment[: end - w.start] = captured[w.start:end]
        magnitude = np.abs(np.fft.rfft(segment)) * (2.0 / min(n, end - w.start))
        spectra[name] = 20 * np.log10(np.maximum(magnitude / analysis.tone_reference, 1e-30))
        readings[name] = ci.Resolver(analysis, n, m).coherence_reading()
    k2 = int(round(signal.f2 / bw))
    top_hz = 350.0
    span = np.arange(int(top_hz / bw) + 1)
    freqs = span * bw
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(7.6, 3.0), gridspec_kw={"width_ratios": [1.15, 1.15, 1.0]})
    for ax, name, title in ((a, "exact", "both notes on exact slots"),
                            (b, "moved", "the high note moved %.2f of a slot\noff its centre" % fraction)):
        ax.plot(freqs, spectra[name][span], color=BLUE, lw=0.4)
        ax.set_xlim(0, top_hz)
        ax.set_ylim(-160, 5)
        ax.set_xlabel("frequency (Hz)", fontsize=8)
        ax.set_title(title, fontsize=8)
    a.set_ylabel("level (dBc re the louder note)", fontsize=8)
    lo, hi = -30, 30
    offsets = np.arange(lo, hi + 1)
    c.plot(offsets, spectra["exact"][k2 + offsets], color=GREY, lw=0.8, label="on its slot")
    c.plot(offsets, spectra["moved"][k2 + offsets], color=BLUE, lw=0.9, label="moved off it")
    for d in co["detectorOffsets"]:
        c.axvline(-d, color=ORANGE, lw=0.5, alpha=0.6)
        c.axvline(d, color=ORANGE, lw=0.5, alpha=0.6)
    pair = readings["moved"].pair_about("f2")
    c.axhline(pair.floor, color=GREY, lw=0.8, ls="--")
    c.axhline(pair.floor + co["thresholdOverFloorDB"], color=RED, lw=0.8, ls="--")
    c.set_xlim(lo, hi)
    c.set_ylim(pair.floor - 12, 5)
    c.set_xlabel("slots from the high note", fontsize=8)
    c.set_title("beside the high note: the detector's\nslots (orange), the local floor and\nthe %.0f dB bar; moved: %.1f dB over"
                % (co["thresholdOverFloorDB"], readings["moved"].worst_excess_over_floor), fontsize=7)
    c.legend(fontsize=6, loc="lower right")
    fig.suptitle("A note that fits the window exactly lights one slot; one a fraction off spills a skirt over every slot",
                 fontsize=8)
    fig.savefig(os.path.join(out, "explained-skirt.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "explained-skirt.tsv"),
                  ["freq_hz", "exact_dbc", "moved_dbc"],
                  [freqs, spectra["exact"][span], spectra["moved"][span]])
    write_sidecar(os.path.join(out, "explained-skirt-zoom.tsv"),
                  ["slots_from_high_note", "exact_dbc", "moved_dbc", "detector_slot"],
                  [offsets, spectra["exact"][k2 + offsets], spectra["moved"][k2 + offsets],
                   [abs(int(o)) in set(co["detectorOffsets"]) for o in offsets]])


def imd_figures(manifest_path, out):
    m = ci.load_manifest(manifest_path)
    fig_imd_lattice(m, out)
    fig_imd_spectrum(m, out)
    fig_imd_window(m, out)
    fig_imd_detector(m, out)
    fig_imd_roles(m, out)
    fig_explained_skirt(m, out)



# --- The Gain Map chapter's figures (#306 chapter four) ----------------------
# Every figure is computed from the Python reimplementation's own runs:
# the worked example (tanh, gain 2, the hardware lattice, noiseless — the
# parity's case a), the identity through seeded noise (case b), the three
# cleanup devices (a, b, d), and the pure phantom (the leakage map).

import gain_map as gmap  # noqa: E402

JOURNEY_NOISE_DB = -100.0


def _journey_plan(m, kind, params=None, noise_db=None, amps=None, plugin=False, gain_db=0.0):
    gm_ = m["gainMap"]
    probe, plan = gm_["probe"], gm_["plan"]
    floor = probe["pluginFloorDBFS"] if plugin else probe["floorDBFS"]
    ceiling = probe["pluginCeilingDBFS"] if plugin else probe["ceilingDBFS"]
    jp = gmap.JourneyPlan(float(plan["startHz"]), float(plan["endHz"]), float(plan["sweepDurationS"]),
                          float(plan["sampleRateHz"]), gmap.levels(floor, ceiling, int(probe["defaultLevels"])),
                          float(plan["prerollS"]), float(plan["tailS"]))
    if kind == "phantom":
        source = gmap.Source("phantom", None, [list(amps)])
    else:
        source = gmap.Source(kind, tc.Device(kind, params or {}, None, None, False), None)
    noise = None if noise_db is None else 10 ** (noise_db / 20)
    return gmap.Plan(source, jp, 0, gain_db, noise, 1, None, float(gm_["floor"]["calibrationLevelDBFS"]))


def _journey_runs(m):
    tanh_params = dict(gain=2.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5)
    hard_params = dict(gain=4.0, threshold=0.002, a2=0.0, a3=0.0, negative_scale=0.5)
    return {
        "tanh": gmap.run(_journey_plan(m, "tanh", tanh_params), m),
        "tanh-noise": gmap.run(_journey_plan(m, "tanh", tanh_params, JOURNEY_NOISE_DB), m),
        "identity": gmap.run(_journey_plan(m, "identity", {}, JOURNEY_NOISE_DB), m),
        "never": gmap.run(_journey_plan(m, "hardclip", hard_params, JOURNEY_NOISE_DB), m),
        "linear": gmap.run(_journey_plan(m, "phantom", amps=[1.0]), m),
    }


def fig_journey_map(runs, m, out):
    """The worked example's THD map: cells as a colour by THD, opacity by the
    composed margin, the masked columns hatched, the corroborated peak and
    the cleanup crossing marked."""
    r = runs["tanh-noise"]
    s, rd = r.summary, r.reading
    levels, freqs = s.levels_db, s.frequencies
    thd = np.array([[np.nan if v is None else 100 * v for v in row] for row in s.thd])
    margins = np.array([[np.nan if v is None else v for v in row] for row in rd.margins])
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    lo = np.nanmin(thd[:, 1:-1]); hi = np.nanmax(thd[:, 1:-1])
    norm = matplotlib.colors.LogNorm(vmin=max(lo, 1e-4), vmax=hi)
    for i in range(len(levels)):
        for j in range(len(freqs)):
            if np.isnan(thd[i, j]):
                continue
            alpha = 1.0 if np.isnan(margins[i, j]) else float(np.clip(margins[i, j] / 6.0, 0.15, 1.0))
            colour = plt.cm.viridis(norm(max(thd[i, j], 1e-4)))
            hatch = "////" if rd.excluded[j] else None
            ax.add_patch(matplotlib.patches.Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=colour, alpha=alpha,
                                                      hatch=hatch, edgecolor="0.7" if hatch else "none", linewidth=0.3))
            if rd.corroborated[i][j] and rd.peak[0] == "peak" and abs(thd[i, j] - rd.peak[1]) < 1e-9:
                ax.plot(j, i, marker="*", color=RED, markersize=12)
    col = rd.tile_column
    if rd.tile[0] == "cleans_up":
        y = np.interp(rd.tile[1], levels, range(len(levels)))
        ax.plot(col, y, marker="v", color=ORANGE, markersize=9)
    ax.set_xlim(-0.5, len(freqs) - 0.5); ax.set_ylim(-0.5, len(levels) - 0.5)
    ax.set_xticks(range(0, len(freqs), 3)); ax.set_xticklabels(["%.0f" % freqs[j] for j in range(0, len(freqs), 3)])
    ax.set_yticks(range(len(levels))); ax.set_yticklabels(["%.1f" % l for l in levels])
    ax.set_xlabel("column fundamental (Hz)"); ax.set_ylabel("drive level (dBFS)")
    sm = plt.cm.ScalarMappable(norm=norm, cmap="viridis"); sm.set_array([])
    fig.colorbar(sm, ax=ax, label="THD (%)")
    ax.set_title("tanh(2x) at −100 dBFS loop noise: colour = THD, opacity = composed margin / 6 dB,\n"
                 "hatched = masked columns; star = corroborated peak %.3f %%, triangle = cleanup crossing %.2f dBFS at %.0f Hz"
                 % (rd.peak[1], rd.tile[1], freqs[col]), fontsize=8)
    fig.savefig(os.path.join(out, "journey-map.png"), **SAVE)
    plt.close(fig)
    rows = [(i, j, freqs[j], levels[i], thd[i, j], margins[i, j], int(rd.excluded[j]), int(rd.clear[i][j]), int(rd.corroborated[i][j]))
            for i in range(len(levels)) for j in range(len(freqs))]
    write_sidecar(os.path.join(out, "journey-map.tsv"),
                  ["level_index", "freq_index", "freq_hz", "level_dbfs", "thd_pct", "margin_db", "masked", "clear", "corroborated"],
                  list(zip(*rows)))


def fig_journey_floor(runs, m, out):
    """One column's floor composition against level, and one level's against
    frequency: the stamp raw and median-read, the drive term with its clamp,
    the residue, and the composed margin."""
    r = runs["tanh-noise"]
    s, rd, cal = r.summary, r.reading, r.cal
    median_points = int(m["gainMap"]["floor"]["stampMedianPoints"])
    j = rd.tile_column
    f = s.frequencies[j]
    stamp_median = gmap.pooled_floor_db(cal.stamp_all, f, median_points)
    stamp_raw = gmap.pooled_floor_db(cal.stamp_all, f, 1)
    cal_abs = cal.delivered_dbfs
    levels = s.levels_db
    delivered = [levels[i] + s.harmonic_db[1][i][j] for i in range(len(levels))]
    drive_term = [max(0.0, cal_abs - d) for d in delivered]
    rig_floor = [stamp_median + t for t in drive_term]
    thd_db = [20 * math.log10(s.thd[i][j]) for i in range(len(levels))]
    residue = rd.residue[j]
    margins = [rd.margins[i][j] for i in range(len(levels))]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 3.6))
    a1.plot(levels, thd_db, "o-", color=BLUE, label="THD cell (dB)")
    a1.plot(levels, rig_floor, "s-", color=ORANGE, label="rig-noise floor: median stamp + drive term")
    a1.axhline(stamp_median, color=ORANGE, linestyle=":", label="stamp (median read) %.1f dB" % stamp_median)
    a1.axhline(stamp_raw, color="0.5", linestyle=":", label="stamp (verbatim) %.1f dB" % stamp_raw)
    a1.axhline(residue, color=RED, linestyle="--", label="analyzer residue %.1f dB" % residue)
    a1.axvline(cal_abs, color="0.3", linestyle="-.", label="calibration delivered %.1f dBFS" % cal_abs)
    a1.set_xlabel("drive level (dBFS)"); a1.set_ylabel("dB re fundamental")
    a1.set_title("column %.0f Hz: the floor's sources vs level" % f, fontsize=8)
    a1.legend(fontsize=5.5, loc="upper left")
    ax2 = a1.twinx()
    ax2.plot(levels, margins, "^-", color=GREEN, label="composed margin (dB)")
    ax2.axhline(float(m["gainMap"]["peak"]["minimumMarginDB"]), color=GREEN, linestyle=":")
    ax2.set_ylabel("composed margin (dB)", color=GREEN)
    i = len(levels) - 1
    freqs = s.frequencies
    thd_f = [20 * math.log10(s.thd[i][jj]) if s.thd[i][jj] else np.nan for jj in range(len(freqs))]
    stamp_f = [gmap.pooled_floor_db(cal.stamp_all, ff, median_points) for ff in freqs]
    raw_f = [gmap.pooled_floor_db(cal.stamp_all, ff, 1) for ff in freqs]
    res_f = rd.residue
    a2.semilogx(freqs, thd_f, "o-", color=BLUE, label="THD cell")
    a2.semilogx(freqs, stamp_f, "s-", color=ORANGE, label="stamp, median read")
    a2.semilogx(freqs, raw_f, ":", color="0.5", label="stamp, verbatim")
    a2.semilogx(freqs, res_f, "--", color=RED, label="analyzer residue (worst over lengths)")
    a2.set_xlabel("column fundamental (Hz)"); a2.set_ylabel("dB re fundamental")
    a2.set_title("loudest level (%.0f dBFS): floor vs frequency" % levels[i], fontsize=8)
    a2.legend(fontsize=6, loc="lower left")
    fig.suptitle("The composed floor: the larger of the rig-noise bound and the analyzer's residue", fontsize=9)
    fig.savefig(os.path.join(out, "journey-floor.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "journey-floor.tsv"),
                  ["level_dbfs", "thd_db", "delivered_dbfs", "drive_term_db", "rig_floor_db", "margin_db"],
                  [levels, thd_db, delivered, drive_term, rig_floor, margins])
    write_sidecar(os.path.join(out, "journey-floor-frequency.tsv"),
                  ["freq_hz", "thd_db", "stamp_median_db", "stamp_raw_db", "residue_db"],
                  [freqs, thd_f, stamp_f, raw_f, res_f])


def fig_journey_residue(runs, m, out):
    """#291's own picture: the analyzer's residue per column at the three
    offered sweep lengths on the shipped grid, and the leakage map."""
    r = runs["identity"]
    s, rd = r.summary, r.reading
    freqs = s.frequencies
    lin = runs["linear"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 3.6))
    for sec, colour in zip(sorted(rd.residue_per_length), (RED, ORANGE, BLUE)):
        vals = [np.nan if v is None else v for v in rd.residue_per_length[sec]]
        a1.semilogx(freqs, vals, "o-", color=colour, label="%g s sweep" % sec, markersize=3)
    worst = [np.nan if v is None else v for v in rd.residue]
    a1.semilogx(freqs, worst, "k--", label="worst (the floor)", linewidth=0.8)
    a1.axvspan(freqs[0] * 0.9, freqs[0] * float(m["gainMap"]["masks"]["bottomEdgeGuardRatio"]), color="0.9")
    a1.set_ylim(-240, 0); a1.set_xlabel("column fundamental (Hz)"); a1.set_ylabel("THD of nothing (dB re fundamental)")
    a1.set_title("the analyzer's residue per column and sweep length\n(first unmasked column: %.1f / %.1f / %.1f dB)"
                 % tuple(rd.residue_per_length[k][1] for k in sorted(rd.residue_per_length)), fontsize=8)
    a1.legend(fontsize=7)
    ls, lrd = lin.summary, lin.reading
    for k in (2, 3, 5, 7, 9):
        vals = []
        for j in range(len(freqs)):
            best = -np.inf
            for i in range(len(ls.levels_db)):
                hk, h1 = ls.harmonic_db[k][i][j], ls.harmonic_db[1][i][j]
                if hk is not None and h1 is not None:
                    best = max(best, hk - h1)
            vals.append(best if np.isfinite(best) else np.nan)
        a2.semilogx(freqs, vals, "o-", markersize=3, label="into H%d's window" % k)
    a2.set_ylim(-240, 0); a2.set_xlabel("column fundamental (Hz)"); a2.set_ylabel("leakage (dB re H1)")
    a2.set_title("the leakage map: a pure fundamental\nread at every other order", fontsize=8)
    a2.legend(fontsize=7)
    fig.savefig(os.path.join(out, "journey-residue.png"), **SAVE)
    plt.close(fig)
    cols = [freqs] + [[np.nan if v is None else v for v in rd.residue_per_length[k]] for k in sorted(rd.residue_per_length)] + [worst]
    write_sidecar(os.path.join(out, "journey-residue.tsv"),
                  ["freq_hz"] + ["residue_%gs_db" % k for k in sorted(rd.residue_per_length)] + ["worst_db"], cols)


def fig_journey_cleanup(runs, m, out):
    """THD against level at the tile's column for the three cleanup states."""
    threshold = float(m["gainMap"]["cleanup"]["threshold"])
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    cols = {}
    for name, colour, label in (("tanh-noise", BLUE, "tanh(2x)"), ("identity", GREEN, "identity"), ("never", RED, "hard clip at 0.002")):
        r = runs[name]
        s, rd = r.summary, r.reading
        j = rd.tile_column
        levels = s.levels_db
        thd = [100 * s.thd[i][j] if s.thd[i][j] else np.nan for i in range(len(levels))]
        state, level = rd.tile
        text = {"cleans_up": "cleans up at %.2f dBFS" % (level or 0), "never_clean": "never clean", "always_clean": "always clean"}[state]
        ax.semilogy(levels, thd, "o-", color=colour, label="%s: %s" % (label, text))
        if state == "cleans_up":
            ax.plot([level], [100 * threshold], marker="v", color=colour, markersize=10)
        cols[name] = thd
    ax.axhline(100 * threshold, color="0.3", linestyle="--", label="threshold %.0f %%" % (100 * threshold))
    ax.set_xlabel("drive level (dBFS)"); ax.set_ylabel("THD (%) at the tile's column")
    ax.set_title("The three cleanup states at %.0f Hz: a genuine crossing, always clean, never clean" % runs["tanh-noise"].summary.frequencies[runs["tanh-noise"].reading.tile_column], fontsize=8)
    ax.legend(fontsize=7)
    fig.savefig(os.path.join(out, "journey-cleanup.png"), **SAVE)
    plt.close(fig)
    levels = runs["tanh-noise"].summary.levels_db
    write_sidecar(os.path.join(out, "journey-cleanup.tsv"), ["level_dbfs", "tanh_thd_pct", "identity_thd_pct", "never_thd_pct"],
                  [levels, cols["tanh-noise"], cols["identity"], cols["never"]])


def fig_journey_peak(runs, m, out):
    """The corroboration rule: the identity-plus-noise map's clearing cells
    against the clipper's shoulder — margins per column at the loudest
    level and at the quietest."""
    minimum = float(m["gainMap"]["peak"]["minimumMarginDB"])
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))
    data = {}
    for ax, name, title in zip(axes, ("identity", "tanh-noise"), ("identity through −100 dBFS noise", "tanh(2x) through the same loop")):
        r = runs[name]
        s, rd = r.summary, r.reading
        freqs = s.frequencies
        for i, colour in ((len(s.levels_db) - 1, BLUE), (0, GREY)):
            margins = [np.nan if rd.margins[i][j] is None else rd.margins[i][j] for j in range(len(freqs))]
            ax.bar([j + (0.2 if i == 0 else -0.2) for j in range(len(freqs))], margins, width=0.4, color=colour,
                   label="level %.0f dBFS" % s.levels_db[i])
            for j in range(len(freqs)):
                if rd.corroborated[i][j]:
                    ax.plot(j + (0.2 if i == 0 else -0.2), margins[j], marker="*", color=RED, markersize=7)
                elif rd.clear[i][j]:
                    ax.plot(j + (0.2 if i == 0 else -0.2), margins[j], marker="x", color=ORANGE, markersize=6)
            data[(name, i)] = margins
        ax.axhline(minimum, color="0.3", linestyle="--")
        ax.set_ylim(-40, max(40, ax.get_ylim()[1]))
        ax.set_xticks(range(0, len(freqs), 4)); ax.set_xticklabels(["%.0f" % freqs[j] for j in range(0, len(freqs), 4)])
        ax.set_xlabel("column fundamental (Hz)"); ax.set_ylabel("composed margin (dB)")
        ax.set_title("%s\npeak tile: %s %s" % (title, rd.peak[0].replace("_", " "), "%.3g %%" % rd.peak[1] if rd.peak[1] else ""), fontsize=8)
        ax.legend(fontsize=7)
    fig.suptitle("Clear (x) is not enough: a peak needs a clear frequency neighbour (star); a lone clearing cell stays a bound", fontsize=8)
    fig.savefig(os.path.join(out, "journey-peak.png"), **SAVE)
    plt.close(fig)
    freqs = runs["identity"].summary.frequencies
    n = len(runs["identity"].summary.levels_db)
    write_sidecar(os.path.join(out, "journey-peak.tsv"),
                  ["freq_hz", "identity_loud_margin_db", "identity_quiet_margin_db", "tanh_loud_margin_db", "tanh_quiet_margin_db"],
                  [freqs, data[("identity", n - 1)], data[("identity", 0)], data[("tanh-noise", n - 1)], data[("tanh-noise", 0)]])


def fig_explained_column(runs, m, out):
    """The lay companion's concept figure for the Gain Map: a MAP is a stack
    of chapter-one measurements. Left: one cell — the harmonic ladder the
    analysis reads at one note and one drive level (the loudest rung of the
    hardware window, the column the cleanup tile reads), with the closed-form
    ladder beside it. Middle: the same note at every rung of the lattice, the
    ladder growing rung by rung. Right: the whole map with that column and
    that cell outlined. Everything is the worked example's own run through
    the reimplementation (tanh(2x) through the seeded loop) and the parity
    code's own truth; nothing is drawn by hand. The chosen drive, note and
    THD are printed in the panel titles."""
    r = runs["tanh-noise"]
    s, rd, t = r.summary, r.reading, r.truth
    levels, freqs, orders = s.levels_db, s.frequencies, s.orders
    j = rd.tile_column
    i_top = len(levels) - 1
    f = freqs[j]

    def re_note(summary, k, i):
        hk, h1 = summary.harmonic_db[k][i][j], summary.harmonic_db[1][i][j]
        return np.nan if hk is None or h1 is None else hk - h1

    odd = [k for k in orders if k % 2 == 1]
    even = [k for k in orders if k % 2 == 0]
    cell_measured = [re_note(s, k, i_top) for k in orders]
    cell_truth = [re_note(t, k, i_top) for k in orders]
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(7.6, 3.3), gridspec_kw={"width_ratios": [1.0, 1.15, 1.35]})
    floor_db = -130.0    # the bars rise from the pane's floor, so a taller bar is a louder harmonic
    a.bar(odd, [cell_measured[k - 1] - floor_db for k in odd], bottom=floor_db, color=BLUE, width=0.7, label="measured, odd")
    a.bar(even, [cell_measured[k - 1] - floor_db for k in even], bottom=floor_db, color=GREY, width=0.7,
          label="measured, even (the loop's noise)")
    a.plot(odd, [cell_truth[k - 1] for k in odd], "x", color="k", markersize=6, label="exact answer")
    a.set_ylim(floor_db, 8)
    a.set_xticks(orders)
    a.set_xlabel("harmonic"); a.set_ylabel("level (dB re the note)")
    a.set_title("one cell: %.1f dBFS, %.1f Hz\nTHD %.2f %%" % (levels[i_top], f, 100 * s.thd[i_top][j]), fontsize=8)
    a.legend(fontsize=5.5, loc="upper right")
    stack_rows = []
    for i, level in enumerate(levels):
        colour = plt.cm.viridis(i / (len(levels) - 1))
        vals = [re_note(s, k, i) for k in odd]
        b.plot(odd, vals, "o-", color=colour, markersize=3, linewidth=1.0,
               label="%.1f dBFS: THD %.2f %%" % (level, 100 * s.thd[i][j]))
        for k in orders:
            stack_rows.append((level, k, re_note(s, k, i), re_note(t, k, i), 100 * s.thd[i][j]))
    b.set_ylim(-130, 8)
    b.set_xticks(odd)
    b.set_xlabel("harmonic (odd only)"); b.set_ylabel("level (dB re the note)")
    b.set_title("the same note at every rung:\n%d cells, quiet (dark) to loud (light)" % len(levels), fontsize=8)
    b.legend(fontsize=5, loc="upper right")
    thd = np.array([[np.nan if v is None else 100 * v for v in row] for row in s.thd])
    lo = np.nanmin(thd[:, 1:-1]); hi = np.nanmax(thd[:, 1:-1])
    norm = matplotlib.colors.LogNorm(vmin=max(lo, 1e-4), vmax=hi)
    for i in range(len(levels)):
        for jj in range(len(freqs)):
            if np.isnan(thd[i, jj]):
                continue
            hatch = "////" if rd.excluded[jj] else None
            c.add_patch(matplotlib.patches.Rectangle((jj - 0.5, i - 0.5), 1, 1,
                                                     facecolor=plt.cm.viridis(norm(max(thd[i, jj], 1e-4))),
                                                     hatch=hatch, edgecolor="0.7" if hatch else "none", linewidth=0.3))
    c.add_patch(matplotlib.patches.Rectangle((j - 0.5, -0.5), 1, len(levels), fill=False, edgecolor=RED, linewidth=1.4))
    c.add_patch(matplotlib.patches.Rectangle((j - 0.5, i_top - 0.5), 1, 1, fill=False, edgecolor="w", linewidth=1.6))
    c.set_xlim(-0.5, len(freqs) - 0.5); c.set_ylim(-0.5, len(levels) - 0.5)
    c.set_xticks(range(0, len(freqs), 4)); c.set_xticklabels(["%.0f" % freqs[jj] for jj in range(0, len(freqs), 4)], fontsize=7)
    c.set_yticks(range(len(levels))); c.set_yticklabels(["%.0f" % l for l in levels], fontsize=7)
    c.set_xlabel("note (Hz)"); c.set_ylabel("drive level (dBFS)")
    c.set_title("the whole map: %d rungs by %d notes\ncolour = THD; column (red), cell (white)" % (len(levels), len(freqs)), fontsize=8)
    fig.suptitle("A cell is one measurement at one loudness; a column is the rungs of one note stacked; a map is the columns side by side",
                 fontsize=8)
    fig.savefig(os.path.join(out, "explained-column.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "explained-column-cell.tsv"),
                  ["order", "measured_db_re_note", "truth_db_re_note"],
                  [orders, cell_measured, cell_truth])
    write_sidecar(os.path.join(out, "explained-column-stack.tsv"),
                  ["level_dbfs", "order", "measured_db_re_note", "truth_db_re_note", "thd_pct"],
                  list(zip(*stack_rows)))
    map_rows = [(levels[i], freqs[jj], thd[i, jj], int(jj == j)) for i in range(len(levels)) for jj in range(len(freqs))]
    write_sidecar(os.path.join(out, "explained-column-map.tsv"),
                  ["level_dbfs", "freq_hz", "thd_pct", "in_column"], list(zip(*map_rows)))


def journey_figures(manifest_path, out):
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)
    runs = _journey_runs(m)
    fig_journey_map(runs, m, out)
    fig_journey_floor(runs, m, out)
    fig_journey_residue(runs, m, out)
    fig_journey_cleanup(runs, m, out)
    fig_journey_peak(runs, m, out)
    fig_explained_column(runs, m, out)


# --- The Compression chapter's figures (#306 chapter five) --------------------
# Every figure is computed from the Python reimplementation's own runs on
# the parity's own cases: the worked example (tanh 8, the hardware grid,
# noiseless — case a), the hard clipper (case c) and the sub-floor clipper
# (case d) for the SSE profiles, the identity through noise with a null run
# through a loop with its own cubic (case b) for the floor picture, the
# three cleanup devices, and the pure phantom for the estimator's error.

import compression_curve as cmp  # noqa: E402

COMPRESSION_NOISE_DB = -100.0


def _compression_plan(m, kind, params=None, noise_db=None, amps=None, null_run=False, loop_a3=None,
                      latency_error=0, plugin=False):
    cm = m["compression"]
    probe = cm["probe"]
    floor = probe["pluginFloorDBFS"] if plugin else probe["floorDBFS"]
    ceiling = probe["pluginCeilingDBFS"] if plugin else probe["ceilingDBFS"]
    steps = probe["pluginSteps"] if plugin else probe["defaultSteps"]
    levels = cmp.levels_db(floor, ceiling, steps, probe["fineStepDB"], probe["maximumFinePoints"])
    if kind == "phantom":
        source = cmp.Source("phantom", None, [list(amps)])
    else:
        source = cmp.Source(kind, tc.Device(kind, params or {}, None, None, False), None)
    noise = None if noise_db is None else 10 ** (noise_db / 20)
    return cmp.Plan(source, levels, float(cm["stimulus"]["frequencyHz"]), float(cm["stimulus"]["sampleRateHz"]),
                    None, None, None, "app", 0, latency_error, 0.0, noise, 1, None, null_run, loop_a3)


def _compression_runs(m):
    tanh8 = dict(gain=8.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5)
    hard = dict(gain=4.0, threshold=0.1, a2=0.0, a3=0.0, negative_scale=0.5)
    under = dict(gain=4.0, threshold=0.0002, a2=0.0, a3=0.0, negative_scale=0.5)
    return {
        "tanh8": cmp.run(_compression_plan(m, "tanh", tanh8), m),
        "hardclip": cmp.run(_compression_plan(m, "hardclip", hard), m),
        "under": cmp.run(_compression_plan(m, "hardclip", under), m),
        "identity-null-loop": cmp.run(_compression_plan(m, "identity", {}, COMPRESSION_NOISE_DB, null_run=True, loop_a3=0.02), m),
        "tanh8-noise": cmp.run(_compression_plan(m, "tanh", tanh8, COMPRESSION_NOISE_DB), m),
        "linear": cmp.run(_compression_plan(m, "phantom", amps=[1.0]), m),
        "linear-miscut": cmp.run(_compression_plan(m, "phantom", amps=[1.0], latency_error=1), m),
    }


def _hinge_profile(curve, m):
    """The hinge fit's (k, SSE) profile and the line's SSE — the chapter's
    own arithmetic, recomputed here for the picture."""
    xs = [p.input_db for p in curve.points]
    ys = [p.output_db for p in curve.points]
    _, _, lin_sse = cmp._line_fit(xs, ys)
    k_lo, k_hi = xs[1], xs[-2]
    ks, sses = [], []
    for i in range(1025):
        k = k_lo + (k_hi - k_lo) * i / 1024
        fit = cmp._hinge_fit(xs, ys, k)
        if fit is not None:
            ks.append(k)
            sses.append(fit[3])
    return np.array(ks), np.array(sses), lin_sse


def fig_compression_curve(runs, m, out):
    """The worked example's output-vs-input curve against unity, the hinge
    fit drawn, the breakpoint and its resolution band, the bound zone."""
    r = runs["tanh8"]
    cm = m["compression"]
    xs = np.array([p.input_db for p in r.curve.points])
    ys = np.array([p.output_db for p in r.curve.points])
    knee = r.reading.knee
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(xs, xs + (ys[0] - xs[0]), "--", color=GREY, label="unity (1 dB in, 1 dB out) through the first point")
    ax.plot(xs, ys, "o-", color=BLUE, markersize=3, label="measured output level (the fundamental)")
    if knee is not None and not knee.is_bound:
        # The fitted hinge through the points.
        k = knee.input_db
        fit = cmp._hinge_fit(list(xs), list(ys), k)
        xx = np.linspace(xs[0], xs[-1], 200)
        ax.plot(xx, fit[0] + fit[1] * xx + fit[2] * np.maximum(0, xx - k), "-", color=ORANGE, linewidth=1.2,
                label="the hinge fit: slopes %.2f and %.2f dB/dB" % (knee.pre_slope, knee.post_slope))
        ax.axvspan(k - knee.resolution_db, k + knee.resolution_db, color=ORANGE, alpha=0.18,
                   label="breakpoint %.2f dBFS, resolution ±%.2f dB" % (k, knee.resolution_db))
        ax.axvline(k, color=ORANGE, linewidth=0.8)
    step = xs[1] - xs[0]
    ax.axvspan(xs[0], xs[0] + step, color=RED, alpha=0.12, hatch="//", label="the floor-bound zone (one probe step above the floor)")
    cl = r.reading.cleanup
    if cl[0] == "cleans_up":
        ax.axvline(cl[1], color=GREEN, linestyle=":", label="cleanup crossing %.2f dBFS (%g %% THD)" % (cl[1], 100 * cm["cleanup"]["threshold"]))
    ax.set_xlabel("input level (dBFS)")
    ax.set_ylabel("output level (dBFS)")
    ax.set_title("The worked example, $y = \\tanh(8x)$ at 220 Hz on the hardware grid", fontsize=9)
    ax.legend(fontsize=7, loc="upper left")
    fig.savefig(os.path.join(out, "compression-curve.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "compression-curve.tsv"), ["input_dbfs", "output_dbfs", "thd_pct"],
                  [xs, ys, [100 * p.thd for p in r.curve.points]])


def fig_compression_knee(runs, m, out):
    """The hinge fit's SSE profile over the candidate breakpoints for a
    point knee (the hard clipper — the 5 % band is a width) and for a
    clipper under the floor (the no-break and unity-guard legs — the
    profile has no minimum to trust and the verdict is a bound)."""
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.4))
    rows = {}
    for ax, name, title in ((axes[0], "hardclip", "hard clip at 0.1: a point"), (axes[1], "under", "hard clip at 0.0002: a bound")):
        r = runs[name]
        ks, sses, lin = _hinge_profile(r.curve, m)
        knee = r.reading.knee
        ax.semilogy(ks, sses, "-", color=BLUE, label="hinge SSE per candidate breakpoint")
        ax.axhline(lin, color=GREY, linestyle="--", label="the single line's SSE")
        ax.axhline(0.5 * lin, color=GREY, linestyle=":", label="½ of it — the no-break bar")
        if knee is not None:
            tol = sses.min() * 1.05 + 1e-12
            band = ks[sses <= tol]
            if not knee.is_bound:
                ax.axvspan(band.min(), band.max(), color=ORANGE, alpha=0.25, label="within 5 %% of the best: the resolution band (±%.3f dB)" % knee.resolution_db)
                ax.axvline(knee.input_db, color=ORANGE, linewidth=0.8)
            text = knee.label + ("; pre slope %.2f" % knee.pre_slope if knee.compressed_throughout(float(m["compression"]["knee"]["preKneeUnitySlopeTolerance"])) else "")
        else:
            text = "no knee"
        ax.set_title("%s\nverdict: %s" % (title, text), fontsize=8)
        ax.set_xlabel("candidate breakpoint (dBFS)")
        ax.set_ylabel("SSE (dB²)")
        ax.legend(fontsize=6)
        rows[name] = (ks, sses)
    fig.savefig(os.path.join(out, "compression-knee.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "compression-knee.tsv"), ["hardclip_k_dbfs", "hardclip_sse", "under_k_dbfs", "under_sse"],
                  [rows["hardclip"][0], rows["hardclip"][1], rows["under"][0], rows["under"][1]])


def fig_compression_floor(runs, m, out):
    """THD against level for the identity through seeded noise and a loop
    with its own cubic, with the √2 noise bound, the shaded noise-dominated
    band, the null-run bound where it governs, and the trace's segments in
    the chart's three styles."""
    r = runs["identity-null-loop"]
    cm = m["compression"]
    margin = float(cm["floor"]["thdNoiseClearMarginDB"])
    pts = r.curve.points
    xs = np.array([p.input_db for p in pts])
    thd = np.array([100 * p.thd for p in pts])
    noise = np.array([100 * (cmp.noise_floor_thd(r.curve, p) or np.nan) for p in pts])
    null = np.array([100 * (cmp.null_run_floor_thd(p, r.reference) or np.nan) for p in pts])
    floor = np.array([100 * (cmp.floor_thd(r.curve, p, r.reference, None) or np.nan) for p in pts])
    classes = [cmp.floor_class(r.curve, p, r.reference, None, float(cm["floor"]["atFloorEpsilonDB"]), margin) for p in pts]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.fill_between(xs, floor, floor * 10 ** (margin / 20), color=GREY, alpha=0.25, label="noise-dominated band (%g dB over the floor)" % margin)
    ax.semilogy(xs, noise, "--", color=GREY, linewidth=0.9, label="the capture's own noise bound, √2·rms / fundamental")
    ax.semilogy(xs, null, "-.", color=GREEN, linewidth=0.9, label="the null run's bound (the loop's own cubic, an absolute contribution)")
    ax.semilogy(xs, floor, "-", color=RED, linewidth=1.0, label="the applied floor: the larger")
    styles = {"clear": ("-", 1.0), "noise_dominated": (":", 1.0), "below_floor": (":", 0.4)}
    for i in range(1, len(xs)):
        cls = classes[i - 1] if cmp.CLASS_RANK[classes[i - 1]] >= cmp.CLASS_RANK[classes[i]] else classes[i]
        ls, alpha = styles[cls]
        ax.semilogy(xs[i - 1:i + 1], thd[i - 1:i + 1], ls, color=BLUE, alpha=alpha, linewidth=1.6)
    ax.plot([], [], "-", color=BLUE, label="THD read: solid clear, dotted noise-dominated, faint at or below the floor")
    ax.axhline(100 * float(cm["cleanup"]["threshold"]), color="0.3", linestyle="--", linewidth=0.7, label="%g %% (the cleanup threshold)" % (100 * cm["cleanup"]["threshold"]))
    source = r.reading.source
    ax.set_title("The identity through −100 dBFS noise and a loop with its own cubic: floor source '%s'" % source, fontsize=9)
    ax.set_xlabel("input level (dBFS)")
    ax.set_ylabel("THD (%)")
    ax.legend(fontsize=6.5, loc="upper right")
    fig.savefig(os.path.join(out, "compression-floor.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "compression-floor.tsv"), ["input_dbfs", "thd_pct", "noise_bound_pct", "null_run_bound_pct", "floor_pct", "class"],
                  [xs, thd, noise, null, floor, classes])


def fig_compression_cleanup(runs, m, out):
    """THD against level for the three cleanup states: a genuine crossing
    (tanh 8), a curve under the threshold throughout (the identity through
    noise), a curve over it throughout (the clipper under the floor)."""
    cm = m["compression"]
    threshold = float(cm["cleanup"]["threshold"])
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    cols = {}
    for name, colour, label in (("tanh8", BLUE, "tanh(8x)"), ("identity-null-loop", GREEN, "identity through noise"), ("under", RED, "hard clip at 0.0002")):
        r = runs[name]
        xs = [p.input_db for p in r.curve.points]
        thd = [100 * p.thd if p.thd > 0 else np.nan for p in r.curve.points]
        state, level = r.reading.cleanup
        text = {"cleans_up": "cleans up at %.2f dBFS" % (level or 0), "never_clean": "never clean", "always_clean": "always clean"}[state]
        ax.semilogy(xs, thd, "o-", color=colour, markersize=2.5, label="%s: %s" % (label, text))
        if state == "cleans_up":
            ax.plot([level], [100 * threshold], marker="v", color=colour, markersize=10)
        cols[name] = (xs, thd)
    ax.axhline(100 * threshold, color="0.3", linestyle="--", label="threshold %g %%" % (100 * threshold))
    ax.set_xlabel("input level (dBFS)")
    ax.set_ylabel("THD (%)")
    ax.set_title("The three cleanup states at 220 Hz: a genuine crossing, always clean, never clean", fontsize=9)
    ax.legend(fontsize=7)
    fig.savefig(os.path.join(out, "compression-cleanup.png"), **SAVE)
    plt.close(fig)
    xs = cols["tanh8"][0]
    write_sidecar(os.path.join(out, "compression-cleanup.tsv"), ["input_dbfs", "tanh8_thd_pct", "identity_thd_pct", "under_thd_pct"],
                  [xs, cols["tanh8"][1], cols["identity-null-loop"][1], cols["under"][1]])


def fig_compression_estimator(runs, m, out):
    """The one-bin Hann estimator's own error on the pure phantom: the
    fundamental's read against its truth per step on the snapped window and
    on a window cut one sample late (left), and the leakage of the
    fundamental into every harmonic bin (right) — the last step, under the
    stimulus's fade, marked."""
    exact = runs["linear"]
    miscut = runs["linear-miscut"]
    xs = np.array([p.input_db for p in exact.curve.points])
    e_exact = np.array([p.output_db - t.output_db for p, t in zip(exact.curve.points, exact.truth_curve.points)])
    e_miscut = np.array([p.output_db - t.output_db for p, t in zip(miscut.curve.points, miscut.truth_curve.points)])
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.4))
    ax = axes[0]
    ax.plot(xs[:-1], e_exact[:-1], "o-", color=BLUE, markersize=3, label="snapped window: |error| ≤ %.1e dB" % np.abs(e_exact[:-1]).max())
    ax.plot(xs[:-1], e_miscut[:-1], "s--", color=ORANGE, markersize=3, label="window cut 1 sample late: |error| ≤ %.1e dB" % np.abs(e_miscut[:-1]).max())
    ax.plot(xs[-1:], e_exact[-1:], "o", color=RED, label="the last step, under the final fade: %.4f dB" % e_exact[-1])
    ax.axhline(0, color=GREY, linewidth=0.6)
    ax.set_xlabel("input level (dBFS)")
    ax.set_ylabel("fundamental read − truth (dB)")
    ax.set_title("The estimator on a pure tone", fontsize=9)
    ax.legend(fontsize=6.5)
    ax = axes[1]
    K = len(exact.truth.harmonic[0])
    leak = np.full((len(xs), K - 1), np.nan)
    for i in range(len(xs)):
        h = exact.harmonics[i]
        if h is None or h[0] is None or h[0] <= 0:
            continue
        for k in range(2, K + 1):
            if h[k - 1] is not None and h[k - 1] > 0:
                leak[i, k - 2] = 20 * np.log10(h[k - 1] / h[0])
    orders = np.arange(2, K + 1)
    ax.plot(orders, np.nanmedian(leak[:-1], axis=0), "o-", color=BLUE, label="every step but the last (the median; all within 0.1 dB)")
    ax.plot(orders, leak[-1], "s--", color=RED, label="the last step, under the final fade")
    ax.set_xlabel("harmonic bin $k$")
    ax.set_ylabel("leakage of the fundamental (dB re H1)")
    ax.set_title("The Hann's leakage into the harmonic bins", fontsize=9)
    ax.legend(fontsize=6.5)
    fig.savefig(os.path.join(out, "compression-estimator.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "compression-estimator.tsv"), ["input_dbfs", "error_exact_db", "error_miscut_db"] + ["leak_h%d_db" % k for k in orders],
                  [xs, e_exact, e_miscut] + [leak[:, k - 2] for k in orders])


def fig_explained_ladder(runs, m, out):
    """The lay companion's concept figure for Compression: one note, a
    ladder of loudnesses, the curve and its corner. Left: the stepped
    tone's level over time — the pre-roll silence where the hiss is
    measured, then the rungs climbing, one rung's settle and measured
    stretch marked. Middle: that one rung close up — the ramp from the
    rung below, the rest of the settle, the measured stretch. Right:
    output level against input level at the rungs for the worked example,
    the one-for-one line, the hinge fit's two straight lines each drawn
    over its own side of the corner and faintly beyond it, and the corner.
    Everything is the reimplementation's own tone, device and hinge fit
    (tanh(8x) at the probe note on the hardware grid, the `tanh8` run);
    nothing is drawn by hand. The device, the note and the fitted knee are
    printed in the panel titles."""
    r = runs["tanh8"]
    cm = m["compression"]
    tone = r.tone
    fs = tone.fs
    preroll_s = float(cm["assembly"]["prerollS"])
    levels = list(r.plan.levels_db)
    n = len(levels)
    marked = n // 2                       # the rung the middle panel opens
    env = tone.envelope()
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(7.6, 3.3), gridspec_kw={"width_ratios": [1.25, 1.0, 1.15]})
    # Left: the ladder in time. Each rung is drawn as its held level from the
    # end of its ramp to its end; the ramps are too short to see at this
    # scale and the middle panel shows one.
    rung_rows = []
    for i, level in enumerate(levels):
        start = preroll_s + i * tone.step_samples / fs
        ramp_end = start + tone.ramp_samples / fs
        measure_start = start + tone.settle_samples / fs
        end = start + tone.step_samples / fs
        a.plot([ramp_end, end], [level, level], "-", color=BLUE, linewidth=1.4)
        if i > 0:
            a.plot([start, ramp_end], [levels[i - 1], level], "-", color=BLUE, linewidth=0.6)
        rung_rows.append((i + 1, level, start, ramp_end, measure_start, end))
    ms = rung_rows[marked]
    a.axvspan(0, preroll_s, color=GREY, alpha=0.3, hatch="////", label="silence: the hiss is measured here")
    a.axvspan(ms[2], ms[4], color=ORANGE, alpha=0.35, label="one rung's settle (not read)")
    a.axvspan(ms[4], ms[5], color=GREEN, alpha=0.35, label="its measured stretch")
    a.set_xlim(0, preroll_s + tone.sample_count / fs)
    a.set_ylim(levels[0] - 4, levels[-1] + 4)
    a.set_xlabel("time (s)")
    a.set_ylabel("input level (dBFS)")
    a.set_title("the ladder: %d rungs, %g to %g dBFS\nat %g Hz, %.1f s in all" % (n, levels[0], levels[-1], tone.frequency, tone.sample_count / fs), fontsize=8)
    a.legend(fontsize=5.5, loc="lower right")
    # Middle: one rung close up, the envelope in linear amplitude, with a
    # little of the rung below in front of it.
    lead = tone.ramp_samples
    base = marked * tone.step_samples
    seg = slice(base - lead, base + tone.step_samples)
    decimate = 8
    t_ms = (np.arange(base - lead, base + tone.step_samples)[::decimate] - base) / fs * 1000
    e = env[seg][::decimate]
    e_db = 20 * np.log10(e)               # the rung's level in dBFS, the left panel's own axis
    ramp_ms = tone.ramp_samples / fs * 1000
    settle_ms = tone.settle_samples / fs * 1000
    step_ms = tone.step_samples / fs * 1000
    b.axvspan(0, ramp_ms, color=RED, alpha=0.25, label="the ramp up from the rung below (%g ms)" % ramp_ms)
    b.axvspan(ramp_ms, settle_ms, color=ORANGE, alpha=0.35, label="the rest of the settle (not read)")
    b.axvspan(settle_ms, step_ms, color=GREEN, alpha=0.35, label="the measured stretch (%g ms, %d cycles)" % (step_ms - settle_ms, tone.measure_samples * tone.frequency / fs + 0.5))
    b.plot(t_ms, e_db, "-", color=BLUE, linewidth=1.4, label="the tone's level")
    b.set_xlim(t_ms[0], t_ms[-1])
    b.set_ylim(levels[marked - 1] - 1.0, levels[marked] + 1.6)
    b.set_xlabel("time within the rung (ms)")
    b.set_ylabel("input level (dBFS)")
    b.set_title("rung %d of %d: %.1f dBFS\nramp, settle, then the stretch that is read" % (marked + 1, n, levels[marked]), fontsize=8)
    b.legend(fontsize=5.5, loc="upper left")
    # Right: the curve and its corner — the hinge fit's two lines.
    xs = np.array([p.input_db for p in r.curve.points])
    ys = np.array([p.output_db for p in r.curve.points])
    knee = r.reading.knee
    assert knee is not None and not knee.is_bound, "the concept figure's worked example must read a point knee"
    k = knee.input_db
    fit = cmp._hinge_fit(list(xs), list(ys), k)
    c0, c1, c2 = fit[0], fit[1], fit[2]
    xx = np.linspace(xs[0], xs[-1], 200)
    lower = c0 + c1 * xx
    upper = c0 + c1 * xx + c2 * (xx - k)
    hinge = c0 + c1 * xx + c2 * np.maximum(0, xx - k)
    c.plot(xx, xx + (ys[0] - xs[0]), "--", color=GREY, linewidth=0.9, label="one-for-one")
    c.plot(xx, lower, ":", color=ORANGE, linewidth=0.8)
    c.plot(xx, upper, ":", color=ORANGE, linewidth=0.8)
    c.plot(xx, hinge, "-", color=ORANGE, linewidth=1.4, label="hinge fit: slopes %.2f, %.2f" % (knee.pre_slope, knee.post_slope))
    c.plot(xs, ys, "o", color=BLUE, markersize=2.6, label="the rungs, measured")
    c.axvline(k, color=ORANGE, linewidth=0.6)
    c.plot([k], [c0 + c1 * k], "o", color=RED, markersize=6, label="the knee, %.2f dBFS" % k)
    c.set_xlabel("input level (dBFS)")
    c.set_ylabel("output level (dBFS)")
    c.set_title("the curve: y = tanh(8x) at %g Hz\nknee %.2f dBFS (±%.2f dB)" % (tone.frequency, k, knee.resolution_db), fontsize=8)
    c.legend(fontsize=5.5, loc="lower right")
    fig.suptitle("One note, a ladder of loudnesses: the curve of output against input, and its corner", fontsize=8)
    fig.savefig(os.path.join(out, "explained-ladder.png"), **SAVE)
    plt.close(fig)
    write_sidecar(os.path.join(out, "explained-ladder-rungs.tsv"),
                  ["rung", "level_dbfs", "start_s", "ramp_end_s", "measure_start_s", "end_s"],
                  list(zip(*rung_rows)))
    write_sidecar(os.path.join(out, "explained-ladder-rung.tsv"), ["t_ms", "level_dbfs"], [t_ms, e_db])
    write_sidecar(os.path.join(out, "explained-ladder-curve.tsv"),
                  ["input_dbfs", "output_dbfs"], [xs, ys])
    write_sidecar(os.path.join(out, "explained-ladder-fit.tsv"),
                  ["input_dbfs", "lower_line_dbfs", "upper_line_dbfs", "hinge_dbfs"], [xx, lower, upper, hinge])


def compression_figures(manifest_path, out):
    m = cmp.load_manifest(manifest_path)
    runs = _compression_runs(m)
    fig_compression_curve(runs, m, out)
    fig_compression_knee(runs, m, out)
    fig_compression_floor(runs, m, out)
    fig_compression_cleanup(runs, m, out)
    fig_compression_estimator(runs, m, out)
    fig_explained_ladder(runs, m, out)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--manifest", default=hd.DEFAULT_MANIFEST)
    p.add_argument("--swift", help="analysisdump synth TSV for the same case (tanh gain 2 seed 1)")
    args = p.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    transfer_figures(args.manifest, args.out)
    imd_figures(args.manifest, args.out)
    journey_figures(args.manifest, args.out)
    compression_figures(args.manifest, args.out)
    m = hd.load_manifest(args.manifest)
    sweep = hd.Sweep.from_manifest(m)
    sweep.check_against(m)
    plan = hd.Plan(kind=CASE["kind"], params=CASE["params"], amps=CASE["amps"], sweep=sweep, seed=1)
    ex = m["extraction"]
    windows = hd.extraction_windows(sweep, int(ex["harmonicCount"]), int(ex["responseFFTLength"]), ex["maxWindowHalfWidthS"])
    capture = hd.clean_capture(sweep, plan.kind, plan.params, plan.amps, m["synthesis"])
    h = hd.deconvolve(sweep, capture, m["deconvolution"])
    analysis = hd.run_analysis(plan, m)
    table = hd.rows(plan, analysis, m)

    fig_sweep(sweep, args.out)
    fig_deconvolved(sweep, h, windows, args.out)
    fig_windows(sweep, h, windows, args.out)
    fig_magnitude(table, sweep, args.out)
    fig_clipping(m, args.out)
    if args.swift:
        buf = io.StringIO()
        hd.write_tsv(plan, analysis, table, "none", buf)
        py = load_tsv_text(buf.getvalue())
        fig_residuals(py, load_tsv(args.swift), sweep, args.out)
    else:
        print("no --swift TSV: hd-residuals.png not produced", file=sys.stderr)
    return 0


def load_tsv_text(text):
    lines = [l for l in text.splitlines(True) if not l.startswith("#")]
    return np.genfromtxt(io.StringIO("".join(lines)), delimiter="\t", names=True, dtype=None, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
