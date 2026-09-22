"""#306 chapter five: the Compression parity guard — the shipped Swift result
against the independent Python reimplementation, and both against the
closed-form ladder. Red when the Swift changes and the Python has not
followed, red when either departs from the truth beyond its measured
tolerance. Part B — the read-time layer ruled from measurement — is
pinned on the oracle's synthetic loops: the hinge fit's four verdict legs,
the three-state cleanup, the three-source floor with its label, the
presence verdict. The tolerances and their provenance live in
`parity_compression.py`.

Run: `make methods-test` (builds `analysisdump` in release first).
"""
import json
import math

import pytest

import compression_curve as cp
import parity_compression as P


@pytest.fixture(scope="session")
def manifest():
    return cp.load_manifest()


@pytest.fixture(scope="session")
def tool():
    return P.build_tool()


@pytest.fixture(scope="session")
def results(tool, manifest):
    """Every case and every twin run once on both sides."""
    return P.run_all(tool, manifest)


@pytest.fixture(scope="session")
def leakage(results):
    return P.leakage_from(results)


def _report(results, manifest, leakage, name):
    case, swift, python = results[name]
    return P.compare(case, swift, python, manifest, leakage)


NAMES = [c.name for c in P.CASES]
TWIN_NAMES = [n + "-twin" for n in P.TWIN_OF]
TRUTH_NAMES = [c.name for c in P.CASES if c.compares_truth] + TWIN_NAMES
KNEE = "knee"
TRUTH_KNEE = "truth knee"
CLEANUP = "cleanup"
TRUTH_CLEANUP = "truth cleanup"


@pytest.mark.parametrize("name", NAMES + TWIN_NAMES)
def test_python_reproduces_swift(results, manifest, leakage, name):
    r = _report(results, manifest, leakage, name)
    tol = r.case.swift_tolerance_db
    assert not r.header_field_mismatches, f"{name}: header fields differ: {r.header_field_mismatches[:5]}"
    assert not r.discrete_mismatches, f"{name}: a discrete reading differs: {r.discrete_mismatches[:5]}"
    assert r.swift_header_db <= tol, f"{name}: header |Python − Swift| {r.swift_header_db:.3e} dB"
    assert r.swift_row_db <= tol, f"{name}: row |Python − Swift| {r.swift_row_db:.3e} dB at {r.swift_row_at}"
    assert r.swift_truth_db <= P.T_SWIFT_TRUTH_DB, f"{name}: truth |Python − Swift| {r.swift_truth_db:.3e} at {r.swift_truth_at}"


@pytest.mark.parametrize("name", TRUTH_NAMES)
def test_both_match_the_ladder(results, manifest, leakage, name):
    """The fundamental and every content harmonic per step against the
    closed-form ladder after the estimator's leakage allowance, the THD
    against the definition on it, the last step under the fade, and the
    knee and cleanup against the truth curve's own."""
    r = _report(results, manifest, leakage, name)
    assert r.content_count > 0, f"{name}: no content harmonic was compared"
    assert r.h1_error_db <= P.T_H1_DB, f"{name}: the fundamental reads {r.h1_error_db:.3e} dB from its truth"
    assert r.harmonic_residue_db <= P.truth_tolerance(r.case), \
        f"{name}: read vs ladder {r.harmonic_error_db:.4f} dB at {r.harmonic_error_at} " \
        f"({r.harmonic_residue_db:.2e} dB beyond the leakage allowance at {r.harmonic_residue_at})"
    assert r.thd_residue_db <= P.T_THD_DB, f"{name}: THD vs truth {r.thd_error_db:.4f} dB ({r.thd_residue_db:.2e} beyond the allowance)"
    assert -P.T_FADE_DB < r.fade_error_db < 0, f"{name}: the last step reads {r.fade_error_db:.4f} dB from its truth (the fade)"
    if not math.isnan(r.knee_error_db):
        assert r.knee_error_db <= P.T_KNEE_DB, f"{name}: knee {r.knee_error_db:.4f} dB from the truth curve's"
    if not math.isnan(r.cleanup_error_db):
        assert r.cleanup_error_db <= P.T_CLEANUP_DB, f"{name}: cleanup crossing {r.cleanup_error_db:.2e} dB from the truth curve's"


def test_the_leakage_map_is_the_estimators_own(results, manifest, leakage):
    """The pure phantom [1] reads its fundamental exactly and every harmonic
    bin as the symmetric Hann's leakage alone — falling with bin distance,
    level-invariant to rounding — the map the allowance is built from."""
    r = _report(results, manifest, leakage, "a-linear")
    d = r.swift
    for row in d.rows:
        assert not row["dropped"] and not row["skipped"]
        if row["index"] < max(x["index"] for x in d.rows):
            assert abs(row["output_db"] - row["truth_output_db"]) <= P.T_H1_DB
    for k in sorted(leakage):
        levels = [v for v in leakage[k].values()]
        assert max(levels) < -150, f"order {k} leaks {max(levels):.1f} dB"
        # Level-invariant to rounding: the spread at 200 dB down is the
        # rounding of a read that small (measured 0.023 dB at order 8).
        assert max(levels) - min(levels) < 0.1, f"order {k}: the leakage is not level-invariant ({max(levels) - min(levels):.3f} dB)"
        if k > 2:
            assert max(leakage[k].values()) < max(leakage[k - 1].values()), f"order {k}: the leakage does not fall with distance"
    assert d.header[KNEE].get("state") == "none" and d.header[CLEANUP]["state"] == "always_clean"


def test_the_stamp_reads_the_injected_noise_and_the_classes_read_the_bathtub(results, manifest, leakage):
    """The identity through seeded noise: the pre-roll stamp against the
    injected rms, no knee, always clean, the capture-noise source, and every
    point at or under the √2 bound (the identity adds nothing — the read is
    the rig), on both sides."""
    r = _report(results, manifest, leakage, "b-identity-noise")
    for d in (r.swift, r.python):
        assert abs(P._num(d.header["noise stamp"]["error_db"])) <= P.T_STAMP_DB
        assert d.header[KNEE].get("state") == "none"
        assert d.header[CLEANUP]["state"] == "always_clean"
        assert d.header["floor runs"]["runs"] == "below_floor:%d" % len(d.rows)
        for row in d.rows:
            assert row["floor_class"] == "below_floor"
            bound = math.sqrt(2) * P._num(d.header["noise stamp"]["measured_rms"]) / (10 ** (row["output_db"] / 20))
            assert abs(20 * math.log10(row["noise_floor_thd"] / bound)) < 1e-9
    assert r.swift.header["floor source"] and "capture_noise" in results["b-identity-noise"][1].split("# floor source: ")[1].split("\n")[0]


def test_the_null_run_is_an_absolute_contribution_and_labels_only_where_it_sets_the_floor(results, manifest, leakage):
    """#129: through a LINEAR loop the null run's bound sits under this
    capture's own stamp everywhere and the label stays capture_noise;
    through a loop with its own cubic the null run's absolute contribution
    sets the floor on the identity (the label fires) and the clipper's own
    products stand over it where they exist; outside the null run's probed
    span the bound is nil — on both sides."""
    for name, expected in (("b-identity-null", "capture_noise"), ("b-identity-null-loop", "null_run"), ("b-tanh8-null-loop", "null_run")):
        case, swift, python = results[name]
        for text in (swift, python):
            d = P.parse(text)
            assert text.split("# floor source: ")[1].split(" ")[0] == expected, name
            assert d.header["floor source"]["without_null_run"] in ("capture_noise",)
            inside = [row for row in d.rows if not math.isnan(row["null_run_floor_thd"])]
            assert inside, f"{name}: no point inside the null run's span"
            for row in d.rows:
                if math.isnan(row["null_run_floor_thd"]):
                    continue
                assert row["floor_thd"] >= row["noise_floor_thd"] - 1e-15 and row["floor_thd"] >= row["null_run_floor_thd"] - 1e-15
    loop = P.parse(results["b-tanh8-null-loop"][1])
    assert loop.header[KNEE].get("state") == "fitted" and loop.header[CLEANUP]["state"] == "cleans_up"
    assert "clear" in loop.header["floor runs"]["runs"]


def test_the_four_knee_legs_and_the_three_cleanup_states(results, manifest, leakage):
    """Part B on the oracle's loops: a point knee (tanh 8, the hard clipper),
    the never-compresses leg (tanh 2: a break, post slope over the
    threshold, no knee), #53's unity guard (an exact sub-unity line with a
    break: a bound at the floor, compressed throughout), the floor-bound
    zone and the sub-floor clipper (bounds at the floor), the plugin
    window's ceiling at 0 dBFS; and the cleanup's three states — a genuine
    crossing, always clean, never clean — on both sides, the truth curve
    agreeing in kind."""
    def both(name):
        case, swift, python = results[name]
        return P.parse(swift), P.parse(python)

    for name in ("a-tanh8", "c-hardclip", "e-fine", "f-plugin"):
        for d in both(name):
            assert d.header[KNEE]["state"] == "fitted" and d.header[KNEE]["bound"] == "0", name
            assert d.header[TRUTH_KNEE]["state"] == "fitted" and d.header[TRUTH_KNEE]["bound"] == "0", name
            assert d.header[CLEANUP]["state"] == "cleans_up" and d.header[TRUTH_CLEANUP]["state"] == "cleans_up", name
    for d in both("a-tanh2"):
        assert d.header[KNEE].get("state") == "none" and d.header[TRUTH_KNEE].get("state") == "none"
    for name in ("d-subunity-break", "d-hardclip-zone", "d-hardclip-under"):
        for d in both(name):
            assert d.header[KNEE]["state"] == "fitted" and d.header[KNEE]["bound"] == "1", name
            assert d.header[KNEE]["label"].startswith("≤ "), name
            assert d.header[KNEE]["compressed_throughout"] == "1", name
            assert abs(P._num(d.header[KNEE]["input_dbfs"]) - manifest["compression"]["probe"]["floorDBFS"]) < 1e-9, name
            assert abs(P._num(d.header[KNEE]["resolution_db"]) - manifest["compression"]["probe"]["hardwareStepDB"]) < 1e-9, name
    for d in both("d-subunity-break"):
        assert abs(P._num(d.header[KNEE]["pre_knee_slope"]) - 0.85) < 1e-3
    for d in both("d-hardclip-under"):
        assert d.header[CLEANUP]["state"] == "never_clean" and d.header[TRUTH_CLEANUP]["state"] == "never_clean"
    for d in both("f-plugin"):
        levels = [float(x) for x in d.lists["plan"]["level_dbfs"]]
        assert levels[0] == manifest["compression"]["probe"]["pluginFloorDBFS"] and levels[-1] == 0.0
    for d in both("b-identity-noise"):
        assert d.header[CLEANUP]["state"] == "always_clean" and d.header[TRUTH_CLEANUP]["state"] == "always_clean"


def test_an_exact_sub_unity_line_is_lost_to_the_fade(results, manifest, leakage):
    """The finding, pinned as measured: #53's second leg — one sub-unity line,
    no break — is decided by a RATIO of residuals with no absolute scale,
    and the measured curve's one bent point (the last step, under the
    stimulus's final fade) lets the hinge beat the line by that ratio, so
    the measured side reads no knee while the truth curve — the same exact
    line with no fade — reads the bound at the floor. Both sides agree with
    each other; the chapter's limits state it."""
    case, swift, python = results["d-subunity-line"]
    for text in (swift, python):
        d = P.parse(text)
        assert d.header[KNEE].get("state") == "none", "the measured line read a knee — the fade finding has moved"
        assert d.header[TRUTH_KNEE]["state"] == "fitted" and d.header[TRUTH_KNEE]["bound"] == "1"
        assert d.header[TRUTH_KNEE]["compressed_throughout"] == "1"
        assert abs(P._num(d.header[TRUTH_KNEE]["pre_knee_slope"]) - 0.85) < 1e-3


def test_the_fine_window_keeps_the_local_probe_step_and_interleaves(results, manifest, leakage):
    """#119: the fine window's points interleave the lattice in ascending
    order, the coarse rung at the floor is unchanged, the knee stays a point
    inside the window on both sides, and the fit's resolution is the
    candidate spacing on both grids (measured 2026-09-21: identical — the
    5 % band is narrower than one candidate step on either grid)."""
    coarse = P.parse(results["c-hardclip"][1])
    for text in (results["e-fine"][1], results["e-fine"][2]):
        fine = P.parse(text)
        levels = [float(x) for x in fine.lists["plan"]["level_dbfs"]]
        assert levels == sorted(levels) and len(levels) > len(coarse.lists["plan"]["level_dbfs"])
        assert abs((levels[1] - levels[0]) - manifest["compression"]["probe"]["hardwareStepDB"]) < 1e-9
        assert fine.header[KNEE]["bound"] == "0"
        assert -24 <= P._num(fine.header[KNEE]["input_dbfs"]) <= -16
        assert abs(P._num(fine.header[KNEE]["input_dbfs"]) - P._num(coarse.header[KNEE]["input_dbfs"])) < manifest["compression"]["probe"]["hardwareStepDB"]


def test_the_input_referred_quantities_are_invariant_to_the_chain_gain(results, manifest, leakage):
    g0 = P.parse(results["g-gain0"][1])
    g12 = P.parse(results["g-gain12"][1])
    assert g0.header[KNEE]["input_dbfs"] == g12.header[KNEE]["input_dbfs"]
    assert abs(P._num(g0.header[CLEANUP]["level_dbfs"]) - P._num(g12.header[CLEANUP]["level_dbfs"])) <= P.T_GAIN_DB
    assert abs((P._num(g12.header["noise stamp"]["measured_dbfs"]) - P._num(g0.header["noise stamp"]["measured_dbfs"])) - 12) <= P.T_GAIN_DB
    for a, b in zip(g0.rows, g12.rows):
        assert a["floor_class"] == b["floor_class"]
        assert abs((b["output_db"] - a["output_db"]) - 12) <= P.T_GAIN_DB
        assert abs(b["gain_db"] - a["gain_db"] - 12) <= P.T_GAIN_DB


def test_the_latency_cut_is_exact_and_a_one_sample_mis_cut_is_invisible(results, manifest, leakage):
    zero = P.parse(results["a-tanh8"][1])
    late = P.parse(results["h-latency"][1])
    assert late.header["loop"]["analyzed_latency_samples"] == str(int(zero.header["loop"]["analyzed_latency_samples"]) + 100)
    for a, b in zip(zero.rows, late.rows):
        for k in range(1, 10):
            assert P._diff(a["h%d" % k], b["h%d" % k]) <= P.T_LATENCY_DB
    mc = P.parse(results["h-miscut"][1])
    assert mc.header["loop"]["latency_error_samples"] == str(P.MISCUT_SAMPLES)
    last = max(r["index"] for r in mc.rows)
    worst = max(abs(r["output_db"] - r["truth_output_db"]) for r in mc.rows if r["index"] < last)
    assert worst <= P.T_MISCUT_DB, f"a one-sample mis-cut moved the fundamental by {worst:.2e} dB"


def test_the_stated_floor_governs_on_a_plugin_record(results, manifest, leakage):
    for text in (results["i-operative"][1], results["i-operative"][2]):
        d = P.parse(text)
        assert text.split("# floor source: ")[1].split(" ")[0] == "stated_floor"
        rms = P._num(d.header["precheck"]["operative_rms"])
        for row in d.rows:
            expected = math.sqrt(2) * rms / (10 ** (row["output_db"] / 20))
            assert abs(20 * math.log10(row["stated_floor_thd"] / expected)) < 1e-9
            assert row["floor_thd"] >= row["stated_floor_thd"] - 1e-15


def test_a_device_with_no_fundamental_is_refused_and_the_estimator_separates_far_beyond_the_bar(results, manifest, leakage):
    for text in (results["j-absent"][1], results["j-absent"][2]):
        d = P.parse(text)
        assert d.header["fundamental verdict"]["absent"] == "1"
        assert d.header[KNEE].get("state") == "not_stated" and d.header[CLEANUP]["state"] == "none"
        assert d.header["summaries (FeatureExtractor.extract(compression:))"]["fundamental_absent"] == "1"
        assert text.split("# floor source: ")[1].split(" ")[0] == "none"
    sep = P.parse(results["j-separation"][1])
    bar = float(manifest["harmonicDistortion"]["fundamentalPresence"]["analyzerSeparationDB"])
    depth = P._num(sep.header["fundamental verdict"]["median_depth_db"])
    assert sep.header["fundamental verdict"]["absent"] == "1"
    assert depth > bar + P.T_SEPARATION_OVER_BAR_DB, f"the one-bin estimator separates {depth:.1f} dB against the borrowed {bar} dB bar"


def test_simulation_modes_assembly_reads_the_same_kind_of_knee(results, manifest, leakage):
    """The interactive assembly (no pre-roll, no stamp, 24 steps at 48 kHz,
    shorter windows): a point knee on the same device, no floor overlay,
    and a stated distance from the app assembly's knee (measured
    2026-09-21: 1.28 dB, quoted in the chapter, not a bar)."""
    for text in (results["k-simulation"][1], results["k-simulation"][2]):
        d = P.parse(text)
        assert d.header["plan"]["assembly"] == "simulation" and d.header["plan"]["preroll_samples"] == "0"
        assert d.header["noise stamp"]["measured_rms"] == "nan" and d.header["noise stamp"]["dropped"] == "nan"
        assert d.header[KNEE]["state"] == "fitted" and d.header[KNEE]["bound"] == "0"
        assert d.header["floor runs"]["runs"] == "none"


def test_the_grid_generators_are_the_shipped_ones(manifest):
    probe = manifest["compression"]["probe"]
    assert cp.levels_db(probe["floorDBFS"], probe["ceilingDBFS"], probe["defaultSteps"], probe["fineStepDB"], probe["maximumFinePoints"]) == probe["hardwareLevelsDBFS"]
    assert cp.levels_db(probe["pluginFloorDBFS"], probe["pluginCeilingDBFS"], probe["pluginSteps"], probe["fineStepDB"], probe["maximumFinePoints"]) == probe["pluginLevelsDBFS"]
    lo, hi = probe["fineExampleRangeDBFS"]
    assert cp.levels_db(probe["floorDBFS"], probe["ceilingDBFS"], probe["defaultSteps"], probe["fineStepDB"], probe["maximumFinePoints"], (lo, hi)) == probe["fineExampleLevelsDBFS"]
    # The cap: a wide window widens its spacing rather than growing the run.
    wide = cp.levels_db(probe["floorDBFS"], probe["ceilingDBFS"], probe["defaultSteps"], probe["fineStepDB"], probe["maximumFinePoints"], (-60, -20))
    assert len(wide) <= probe["defaultSteps"] + probe["maximumFinePoints"]
    # The clamp: a window past the ceiling stops at it.
    clamped = cp.levels_db(probe["floorDBFS"], probe["ceilingDBFS"], probe["defaultSteps"], probe["fineStepDB"], probe["maximumFinePoints"], (-14, 0))
    assert max(clamped) == probe["ceilingDBFS"]
    st = manifest["compression"]["stimulus"]
    for fs, f0, settle, measure, ramp in st["deliveredPerRate"]:
        tone = cp.SteppedTone.build(f0, fs, [1], st["settleS"], cp.default_measure_s(manifest["compression"]), st["rampS"])
        assert (tone.settle_samples, tone.measure_samples, tone.ramp_samples) == (settle, measure, ramp), fs
        assert tone.measure_range(2) == (2 * tone.step_samples + tone.settle_samples, 2 * tone.step_samples + tone.settle_samples + tone.measure_samples)


def test_the_python_reads_the_manifest_not_its_own_constants(results, manifest, leakage, tmp_path):
    """The red-first check: a manifest with a tampered slope threshold must
    move the Python's knee verdict away from the Swift's — proof the Python
    is driven by the manifest and the parity test can see a change."""
    m = json.loads(json.dumps(manifest))
    m["compression"]["knee"]["slopeThreshold"] = 0.5
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(m))
    case, swift, _ = results["a-tanh8"]
    python = P.run_python(case.args, manifest=str(path))
    r = P.compare(case, swift, python, manifest, leakage)
    assert r.header_field_mismatches, "a tampered manifest produced no visible difference"
