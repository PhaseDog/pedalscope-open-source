"""#305: the Harmonic Distortion parity guard — the shipped Swift result
against the independent Python reimplementation, and both against
analytic ground truth. Red when the Swift changes and the Python has not
followed, red when either departs from the truth beyond its measured
tolerance. The tolerances and their provenance live in `parity_hd.py`.

Run: `make methods-test` (builds `analysisdump` in release first).
"""
import json
import os

import numpy as np
import pytest

import parity_hd as P
import harmonic_distortion as hd


@pytest.fixture(scope="session")
def tool():
    return P.build_tool()


@pytest.fixture(scope="session")
def manifest():
    with open(hd.DEFAULT_MANIFEST, encoding="utf-8") as f:
        return json.load(f)["harmonicDistortion"]


@pytest.fixture(scope="session")
def results(tool, manifest):
    """Every case run once on both sides (the Swift release build takes a
    second or two per case; the Python about as long)."""
    out = {}
    for case in P.CASES:
        swift = P.run_swift(tool, case)
        out[case.name] = (case, swift, P.run_python(case))
        if case.source != "phantom":
            twin = P.phantom_twin(case, swift)
            out[twin.name] = (twin, P.run_swift(tool, twin), P.run_python(twin))
    for case in (P.NOISY, P.NOISY_SINGLE):
        out[case.name] = (case, P.run_swift(tool, case), P.run_python(case))
    return out


def _report(results, manifest, name):
    case, swift, python = results[name]
    return P.compare(case, swift, python, manifest)


@pytest.mark.parametrize("name", [c.name for c in P.CASES])
def test_python_reproduces_swift(results, manifest, name):
    report = _report(results, manifest, name)
    assert report.content_orders(), f"{name}: no order carries content"
    for o in report.content_orders():
        assert o.max_swift_vs_python <= P.T_SWIFT, \
            f"{name} H{o.order}: |Python − Swift| max {o.max_swift_vs_python:.3e} dB > {P.T_SWIFT}"


@pytest.mark.parametrize("name", [c.name for c in P.CASES])
def test_both_match_analytic_truth(results, manifest, name):
    case, swift, python = results[name]
    report = P.compare(case, swift, python, manifest)
    tolerance = P.T_ANALYTIC_ALIAS_FREE if case.source == "phantom" else P.T_ANALYTIC_PER_SAMPLE[case.source]
    for o in report.content_orders():
        assert o.band_points > 0
        assert o.max_swift_vs_analytic_band <= tolerance, \
            f"{name} H{o.order}: |Swift − analytic| max {o.max_swift_vs_analytic_band:.4f} dB > {tolerance}"
        assert o.max_python_vs_analytic_band <= tolerance, \
            f"{name} H{o.order}: |Python − analytic| max {o.max_python_vs_analytic_band:.4f} dB > {tolerance}"


@pytest.mark.parametrize("name", [c.name + "-phantom-twin" for c in P.CASES if c.source != "phantom"])
def test_phantom_twin_is_exact_over_the_whole_band(results, manifest, name):
    """The alias-free control: the same amplitudes as the per-sample case,
    as a phantom, must match analytic truth to the alias-free tolerance
    over the WHOLE excited valid band — that is what shows the per-sample
    cases' full-band excess is the synthesis aliasing, not the method."""
    report = _report(results, manifest, name)
    for o in report.content_orders():
        assert o.max_swift_vs_analytic_full <= P.T_ANALYTIC_ALIAS_FREE, \
            f"{name} H{o.order}: |Swift − analytic| full band {o.max_swift_vs_analytic_full:.4f} dB"
        assert o.max_swift_vs_python <= P.T_SWIFT


@pytest.mark.parametrize("name", [c.name for c in P.CASES])
def test_empty_orders_stay_empty_on_both_sides(results, manifest, name):
    case, swift, python = results[name]
    report = P.compare(case, swift, python, manifest)
    ceilings = P.empty_order_ceiling(case, swift, python, manifest)
    loudest = P.loudest_expected_db(swift)
    for o in report.empty_orders():
        assert ceilings[o.order] <= loudest - P.EMPTY_ORDER_DEPTH_DB, \
            f"{name} H{o.order}: an analytically empty order reads {ceilings[o.order]:.1f} dB, only {loudest - ceilings[o.order]:.1f} dB under the loudest order"
        assert o.max_swift_vs_python <= P.T_SWIFT_EMPTY, \
            f"{name} H{o.order}: residue differs by {o.max_swift_vs_python:.3e} dB"


def test_noisy_averaged_case(results, manifest):
    """Seeded noise, four repeats through the shipped combine: the Python
    reproduces the Swift's noise stream and combine to T_SWIFT, and on the
    points both predicates call shaped the error against truth sits inside
    three times the read's own stated scatter. Averaging must also LOWER
    the empty orders' noise floor against the single-sweep run."""
    report = _report(results, manifest, P.NOISY.name)
    for o in report.content_orders():
        assert o.max_swift_vs_python <= P.T_SWIFT, \
            f"noisy H{o.order}: |Python − Swift| {o.max_swift_vs_python:.3e} dB"
        if o.shaped_both:
            assert o.max_scatter_normalized <= 1.0, \
                f"noisy H{o.order}: error exceeds {P.NOISY_SCATTER_MULTIPLE}× the stated scatter (ratio {o.max_scatter_normalized:.2f})"
    single = results[P.NOISY_SINGLE.name]
    averaged = results[P.NOISY.name]
    floor_single = P.empty_order_ceiling(single[0], single[1], single[2], manifest)
    floor_averaged = P.empty_order_ceiling(averaged[0], averaged[1], averaged[2], manifest)
    lowered = [k for k in floor_single if floor_averaged[k] < floor_single[k]]
    assert len(lowered) >= len(floor_single) - 1, \
        f"averaging did not lower the empty orders' floor: single {floor_single}, averaged {floor_averaged}"


def test_the_python_reads_the_manifest_not_its_own_constants(results, manifest, tmp_path):
    """The red-first check: a manifest with a tampered window cap must
    move the Python's result away from the Swift's — proof the Python is
    driven by the manifest and the parity test can see a change."""
    case = P.CASES[1]  # tanh
    tampered = dict(manifest)
    tampered = json.loads(json.dumps({"harmonicDistortion": manifest}))
    tampered["harmonicDistortion"]["extraction"]["maxWindowHalfWidthS"] = 0.1
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered))
    swift = results[case.name][1]
    python = P.run_python(case, manifest=str(path))
    report = P.compare(case, swift, python, manifest)
    worst = max(o.max_swift_vs_python for o in report.content_orders())
    assert worst > P.T_SWIFT, f"a tampered window cap left parity at {worst:.3e} dB — the Python is not reading the manifest"
