"""#306 chapter two: the Transfer Curve parity guard — the shipped Swift
result against the independent Python reimplementation, and both against
closed-form truth. Red when the Swift changes and the Python has not
followed, red when either departs from the truth beyond its measured
tolerance. The tolerances and their provenance live in `parity_transfer.py`.

Run: `make methods-test` (builds `analysisdump` in release first).
"""
import json
import math
import os

import pytest

import parity_transfer as P
import transfer_curve as tc


@pytest.fixture(scope="session")
def tool():
    return P.build_tool()


@pytest.fixture(scope="session")
def results(tool):
    """Every case run once on both sides."""
    return P.run_all(tool)


def _report(results, name):
    case, swift, python = results[name]
    return P.compare(case, swift, python)


NAMES = [c.name for c in P.CASES]


@pytest.mark.parametrize("name", NAMES)
def test_python_reproduces_swift(results, name):
    r = _report(results, name)
    assert r.discrete_match, f"{name}: a discrete reading (class, flip, polarity, tile, verdict, presence) differs"
    assert r.swift_cycle <= P.T_SWIFT, f"{name}: displayed cycle |Python − Swift| {r.swift_cycle:.3e}"
    assert r.swift_static <= P.T_SWIFT, f"{name}: static curve |Python − Swift| {r.swift_static:.3e}"
    assert r.swift_areas <= P.T_SWIFT, f"{name}: areas |Python − Swift| {r.swift_areas:.3e}"
    assert r.swift_psi1 <= P.T_SWIFT, f"{name}: ψ1 |Python − Swift| {r.swift_psi1:.3e}"
    assert r.swift_truth <= P.T_SWIFT_TRUTH, f"{name}: the two truths differ by {r.swift_truth:.3e}"
    if r.has_compensated:
        assert r.swift_compensated <= P.T_SWIFT, f"{name}: compensated cycle |Python − Swift| {r.swift_compensated:.3e}"
    if math.isfinite(r.swift_shift):
        assert r.swift_shift <= P.T_SWIFT_SHIFT, f"{name}: frame shift |Python − Swift| {r.swift_shift:.3e}"
        assert r.swift_residual <= P.T_SWIFT, f"{name}: residual |Python − Swift| {r.swift_residual:.3e}"
        assert r.swift_terms <= P.T_SWIFT, f"{name}: fit terms |Python − Swift| {r.swift_terms:.3e}"


@pytest.mark.parametrize("name", [c.name for c in P.CASES if c.kind in ("ellipse", "ellipse-long")])
def test_the_ellipse_reads_its_closed_form(results, name):
    """#352's synthetic check: the shipped linearLoopArea against
    (π/4)·|sin φ| for a linear device — the low-pass at three notes and a
    pure alignment error at three notes, at the plan's tone and at ten
    times its length."""
    r = _report(results, name)
    tol = P.ellipse_tolerance(r.case)
    assert abs(r.ellipse_ratio - 1) <= tol, \
        f"{name}: linear {r.linear:.6f} vs closed form {r.expected_linear:.6f} (ratio {r.ellipse_ratio:.5f}, bar {tol})"
    assert r.nonlinear <= P.T_MEMORYLESS_NONLINEAR, f"{name}: a linear device read nonlinear {r.nonlinear:.5f}"


@pytest.mark.parametrize("name", NAMES)
def test_both_match_the_truth(results, name):
    r = _report(results, name)
    tol = P.raw_static_tolerance(r.case)
    assert r.raw_static_truth <= tol, f"{name}: raw static curve vs truth {r.raw_static_truth:.4f} of peak > {tol}"
    assert r.python_raw_static_truth <= tol, f"{name}: Python raw static curve vs truth {r.python_raw_static_truth:.4f}"
    cycle_tol = P.T_RAW_CYCLE_TRUTH * (1.5 if r.case.kind == "hardclip" else 1.0)
    assert r.raw_cycle_truth <= cycle_tol, f"{name}: raw cycle vs truth {r.raw_cycle_truth:.4f} of peak"
    if r.case.kind in ("memoryless", "hardclip", "paired-noop") and not r.case.paired:
        assert r.nonlinear <= P.T_MEMORYLESS_NONLINEAR, f"{name}: memoryless device read nonlinear {r.nonlinear:.5f}"


@pytest.mark.parametrize("name", [c.name for c in P.CASES if c.kind == "paired"])
def test_the_removal_recovers_the_memoryless_truth(results, name):
    """Part B: a memoryless device behind a filter, paired with its own
    Harmonic Distortion analysis, must compensate, find the planted frame
    shift, keep its residual well under the accept bar, recover the
    memoryless-lattice truth, and read both compensated areas near zero."""
    r = _report(results, name)
    assert r.figure_class == "compensated", f"{name}: class {r.figure_class}"
    assert r.expected_class == "compensated"
    assert abs(r.frame_shift - r.expected_shift) <= P.T_FRAME_SHIFT_SAMPLES, \
        f"{name}: frame shift {r.frame_shift:.3f} vs planted {r.expected_shift:.3f}"
    assert r.residual_rms <= P.T_RESIDUAL_RMS, f"{name}: residual {r.residual_rms:.4f} rad"
    assert r.comp_static_truth <= P.T_COMP_STATIC_TRUTH, f"{name}: compensated static vs truth {r.comp_static_truth:.4f}"
    assert r.python_comp_static_truth <= P.T_COMP_STATIC_TRUTH
    assert r.comp_cycle_truth <= P.T_COMP_CYCLE_TRUTH, f"{name}: compensated cycle vs truth {r.comp_cycle_truth:.4f}"
    assert r.comp_linear <= P.T_COMP_AREA and r.comp_nonlinear <= P.T_COMP_AREA, \
        f"{name}: compensated areas {r.comp_linear:.4f} / {r.comp_nonlinear:.4f}"
    assert r.voting >= 3


def test_orientation_and_polarity(results):
    """The half-cycle lock is undone (flipped, the figure restored to the
    no-op class), the inverted device reads inverting on the tile, the
    non-inverted ones non-inverting, and the paired memoryless device is
    the no-op class."""
    shift = _report(results, "g-tanh-shift")
    assert shift.flipped and shift.figure_class == "negligible_raw_loop"
    assert shift.polarity_inverting is False
    inverted = _report(results, "g-tanh-inv-lp")
    assert inverted.polarity_inverting is True and inverted.figure_class == "compensated" and not inverted.flipped
    plain = _report(results, "g-tanh-paired")
    assert plain.figure_class == "negligible_raw_loop" and plain.expected_class == "negligible_raw_loop"
    assert plain.polarity_inverting is False
    for name in ("d-tanh-lp", "d-tanh-hp", "e-tanh-prehp", "f-asym-hp"):
        assert _report(results, name).polarity_inverting is False, name


def test_the_python_reads_the_manifest_not_its_own_constants(results, tmp_path):
    """The red-first check: a manifest with a tampered bin count must move
    the Python's result away from the Swift's — proof the Python is driven
    by the manifest and the parity test can see a change."""
    m = tc.load_manifest()
    m["transferCurve"]["binning"]["phaseBins"] = 128
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(m))
    case, swift, _ = results["a-tanh"]
    python = P.run_python(case, manifest=str(path))
    with pytest.raises(AssertionError):
        P.compare(case, swift, python)
