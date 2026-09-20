#!/usr/bin/env python3
"""The Harmonic Distortion chapter's figures (hd-*.png) and the lay
companion's concept figures (explained-*.png) — generated from the Python
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
import math
import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import harmonic_distortion as hd  # noqa: E402
import transfer_curve as tc  # noqa: E402
import chord_imd as ci  # noqa: E402

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
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for row in zip(*columns):
            f.write("\t".join(hd.fmt(v) for v in row) + "\n")


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


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--manifest", default=hd.DEFAULT_MANIFEST)
    p.add_argument("--swift", help="analysisdump synth TSV for the same case (tanh gain 2 seed 1)")
    args = p.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    transfer_figures(args.manifest, args.out)
    imd_figures(args.manifest, args.out)
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
