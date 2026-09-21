"""#306 chapter four: the Gain Map parity guard — the shipped Swift result
against the independent Python reimplementation, and both against the
closed-form ladder. Red when the Swift changes and the Python has not
followed, red when either departs from the truth beyond its measured
tolerance. Part B — the read-time layer — is pinned twice: on the oracle's
synthetic loops (the floor's three sources, the corroboration, the three
cleanup states) and on the kernel test's transcribed corpus grids (the one
stored-input exception). The tolerances and their provenance live in
`parity_journey.py`.

Run: `make methods-test` (builds `analysisdump` in release first).
"""
import json
import math
import os

import pytest

import gain_map as gm
import parity_journey as P


@pytest.fixture(scope="session")
def manifest():
    return gm.load_manifest()


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
NOISELESS = [c.name for c in P.CASES if not c.noisy and c.kind != "linear"] + TWIN_NAMES


@pytest.mark.parametrize("name", NAMES + TWIN_NAMES)
def test_python_reproduces_swift(results, manifest, leakage, name):
    r = _report(results, manifest, leakage, name)
    tol = r.case.swift_tolerance_db
    assert not r.header_field_mismatches, f"{name}: header fields differ: {r.header_field_mismatches[:5]}"
    assert not r.discrete_mismatches, f"{name}: a discrete reading differs: {r.discrete_mismatches[:5]}"
    assert r.swift_header_db <= tol, f"{name}: header |Python − Swift| {r.swift_header_db:.3e} dB"
    assert r.swift_row_db <= tol, f"{name}: row |Python − Swift| {r.swift_row_db:.3e} dB at {r.swift_row_at}"


@pytest.mark.parametrize("name", NOISELESS)
def test_both_match_the_ladder(results, manifest, leakage, name):
    """Every content harmonic cell against the closed-form ladder and every
    THD cell against the definition applied to it, after the analyzer's
    own leakage allowance — the residue is the method's error."""
    r = _report(results, manifest, leakage, name)
    assert r.content_count > 0, f"{name}: no content cell was compared"
    assert r.truth_residue_db <= P.truth_tolerance(r.case), \
        f"{name}: read vs ladder {r.truth_error_db:.4f} dB at {r.truth_error_label} " \
        f"({r.truth_residue_db:.2e} dB beyond the leakage allowance at {r.truth_residue_label})"
    assert r.thd_residue_db <= P.thd_tolerance(r.case), \
        f"{name}: THD vs truth {r.thd_error_db:.4f} dB ({r.thd_residue_db:.2e} beyond the allowance at {r.thd_residue_label})"
    assert r.cleanup_error_db <= P.T_CLEANUP_DB, f"{name}: cleanup crossing vs truth {r.cleanup_error_db:.3f} dB"


def test_the_leakage_map_is_the_analyzers_own(results, manifest, leakage):
    """The pure phantom [1] reads its fundamental at 0 dB inside the band
    (its truth) and every higher order as the analyzer's leakage alone —
    the map the allowance is built from, level-invariant to rounding."""
    r = _report(results, manifest, leakage, "a-linear")
    assert r.truth_error_db <= 1e-3, f"H1 of the pure phantom reads {r.truth_error_db:.2e} dB off"
    d = r.swift
    first = d.lists["masks"]["bottom_edge"].index("0")
    for k, row in leakage.items():
        assert row[first] < -60, f"order {k} leakage at the first unmasked column reads {row[first]:.1f} dB"
        assert row[first + 1] < row[first] - 20, f"order {k}: the leakage does not fall a column up"
    # Level-invariance: the worst and the best level agree within rounding.
    levels = {}
    for row in d.rows:
        if not math.isnan(row["h2_db"]) and not math.isnan(row["h1_db"]):
            levels.setdefault(row["freq_index"], []).append(row["h2_db"] - row["h1_db"])
    spread = max(max(v) - min(v) for j, v in levels.items() if leakage[2][j] > -150)
    assert spread < 0.1, f"the leakage is not level-invariant: spread {spread:.3f} dB"


@pytest.mark.parametrize("name", [c.name for c in P.CASES if c.kind == "noise"])
def test_the_residue_reads_the_law_and_the_identity_reads_a_bound(results, manifest, leakage, name):
    """The identity through seeded noise: the residue at the first unmasked
    column reads #291's three numbers from BOTH implementations' own
    analyses, every cell's fundamental is present, the peak tile is a bound,
    the cleanup tile is always clean, and no cell in the loudest row is
    quoted clear (the drive term is never extrapolated past the calibration)."""
    r = _report(results, manifest, leakage, name)
    for d in (r.swift, r.python):
        first = d.lists["masks"]["bottom_edge"].index("0")
        for seconds, law in P.RESIDUE_LAW_DB.items():
            read = float(d.series["residue length_s=%s" % gm.fmt(float(seconds))][first])
            assert abs(read - law) <= P.T_RESIDUE_VS_LAW_DB, f"{name}: residue at {seconds} s reads {read:.3f} against {law}"
        assert d.header["fundamental verdict"]["absent"] == "0"
        assert d.header["peak tile"]["state"] == "at_floor", d.header["peak tile"]
        assert d.header["cleanup tile (nearest column to 220.0 Hz)"]["state"] == "always_clean"
        loudest = max(row["level_index"] for row in d.rows)
        for row in d.rows:
            assert row["presence"] == "present", f"{name}: cell ({row['level_index']},{row['freq_index']}) reads {row['presence']}"
            if row["level_index"] == loudest and row["bottom_edge"] == 0 and row["top_edge"] == 0:
                assert row["corroborated"] == 0, f"{name}: a loudest-row cell was quoted clear"


def test_a_device_with_no_fundamental_is_refused_everywhere(results, manifest, leakage):
    r = _report(results, manifest, leakage, "c-absent")
    for d in (r.swift, r.python):
        assert d.header["fundamental verdict"]["absent"] == "1"
        assert d.header["peak tile"]["state"] == "fundamental_absent"
        assert d.header["cleanup tile (nearest column to 220.0 Hz)"]["state"] == "none"
        assert d.header["summaries cleanup (FeatureExtractor.extract(journey:))"]["state"] == "none"
        # Per cell the read is honest about what it holds: at the quietest
        # levels the fundamental's bin holds the loop's noise, and at the
        # two columns beside the low edge it holds the second harmonic's own
        # leakage into the fundamental's window (−50 / −73 dB, inside the
        # separation bound), so those cells read present — the majority
        # verdict exists for exactly this (measured: 79 % of the cells
        # absent); at the loudest level every cell from the third column to
        # the top edge is absent.
        assert float(d.header["fundamental verdict"]["absent_fraction"]) > 0.5
        loudest = max(row["level_index"] for row in d.rows)
        assert all(row["presence"] == "absent" for row in d.rows
                   if row["level_index"] == loudest and row["freq_index"] >= 3 and row["top_edge"] == 0)


def test_the_three_cleanup_states(results, manifest, leakage):
    """A genuine crossing (tanh, against the truth curve's crossing), a
    column under the threshold throughout (the identity), a column over it
    throughout (a hard clipper whose threshold sits under the lattice's
    floor) — on both sides, and the truth's reading agrees in kind."""
    cleans = _report(results, manifest, leakage, "a-tanh")
    tile = "cleanup tile (nearest column to 220.0 Hz)"
    for d in (cleans.swift, cleans.python):
        assert d.header[tile]["state"] == "cleans_up"
        assert abs(float(d.header[tile]["level_dbfs"]) - float(d.header["truth " + tile]["level_dbfs"])) <= P.T_CLEANUP_DB
        assert d.header["summaries cleanup (FeatureExtractor.extract(journey:))"]["state"] == "cleans_up"
    always = _report(results, manifest, leakage, "b-identity-5s")
    never = _report(results, manifest, leakage, "d-never-clean")
    for d in (always.swift, always.python):
        assert d.header[tile]["state"] == "always_clean" and d.header["truth " + tile]["state"] == "always_clean"
    for d in (never.swift, never.python):
        assert d.header[tile]["state"] == "never_clean" and d.header["truth " + tile]["state"] == "never_clean"
        assert d.header["peak tile"]["state"] == "peak"


def test_the_margins_are_invariant_to_the_chain_gain(results, manifest, leakage):
    """The #100 term: 12 dB more loop gain moves H1 by 12 dB, the stamp's
    chain gain to 12, and no composed margin."""
    g0 = _report(results, manifest, leakage, "e-tanh-gain0")
    g12 = _report(results, manifest, leakage, "e-tanh-gain12")
    for a, b in ((g0.swift, g12.swift), (g0.python, g12.python)):
        # The stamp's gain is a median of interpolated |H1| reads on a noisy
        # loop: measured 12.0000016 dB (2026-09-20).
        assert abs(float(b.header["calibration"]["chain_gain_db"]) - 12) < 1e-5
        worst = 0.0
        for ra, rb in zip(a.rows, b.rows):
            assert abs((rb["h1_db"] - ra["h1_db"]) - 12) < 1e-6
            worst = max(worst, P._diff(ra["margin_db"], rb["margin_db"]), P._diff(ra["rig_margin_db"], rb["rig_margin_db"]))
        assert worst <= P.T_GAIN_INVARIANCE_DB, f"a margin moved by {worst:.2e} dB with the gain"


def test_the_operative_floor_governs_on_a_silent_stamp(results, manifest, leakage):
    """The #150 path: the render-path stamp is numerically silent, so the
    rig-noise margin is the operative bound's alone — thd − (absolute −
    delivered), no chain-gain term."""
    r = _report(results, manifest, leakage, "f-operative")
    for d in (r.swift, r.python):
        pre = d.header["precheck"]
        absolute = float(pre["absolute_dbfs"])
        assert abs(absolute - 20 * math.log10(math.sqrt(2) * 1e-4)) < 1e-9
        for row in d.rows:
            if math.isnan(row["rig_margin_db"]) or math.isnan(row["h1_db"]) or row["thd"] <= 0:
                continue
            expected = 20 * math.log10(row["thd"]) - (absolute - (row["level_dbfs"] + row["h1_db"]))
            assert abs(row["rig_margin_db"] - expected) < 1e-9, f"({row['level_index']},{row['freq_index']}): {row['rig_margin_db']} vs {expected}"


def test_the_plugin_window_reaches_full_scale(results, manifest, leakage):
    r = _report(results, manifest, leakage, "g-plugin-hardclip")
    for d in (r.swift, r.python):
        levels = [float(x) for x in d.lists["plan"]["level_dbfs"]]
        assert levels[0] == manifest["gainMap"]["probe"]["pluginFloorDBFS"] and levels[-1] == 0.0
        assert d.header["peak tile"]["state"] == "peak"
        assert d.header["cleanup tile (nearest column to 220.0 Hz)"]["state"] == "cleans_up"


def test_a_late_capture_reads_the_same_cells(results, manifest, leakage):
    """The calibrator finds the loop's 100 samples and the aligned cut removes
    them: every harmonic cell equals the zero-latency capture's, and the
    residue — a property of the plan's geometry — is identical."""
    zero = _report(results, manifest, leakage, "a-tanh").swift
    late = _report(results, manifest, leakage, "j-latency").swift
    assert late.header["calibration"]["latency_samples"] == "100"
    orders = zero.orders
    for a, b in zip(zero.rows, late.rows):
        for k in orders:
            assert P._diff(a[f"h{k}_db"], b[f"h{k}_db"]) <= P.T_LATENCY_DB, f"H{k} ({a['level_index']},{a['freq_index']})"
    assert zero.series["analyzer residue (dB re fundamental, worst over sweep lengths 2.0/5.0/10.0 s; stamp median 7 points)"] == \
        late.series["analyzer residue (dB re fundamental, worst over sweep lengths 2.0/5.0/10.0 s; stamp median 7 points)"]


def test_the_lattices_and_the_grid_are_the_shipped_ones(manifest):
    plan = manifest["gainMap"]["plan"]
    probe = manifest["gainMap"]["probe"]
    assert gm.levels(probe["floorDBFS"], probe["ceilingDBFS"], probe["defaultLevels"]) == plan["hardwareLevelsDBFS"]
    assert gm.levels(probe["pluginFloorDBFS"], probe["pluginCeilingDBFS"], probe["defaultLevels"]) == plan["pluginLevelsDBFS"]
    assert gm.export_grid(plan["startHz"], plan["endHz"], plan["exportFrequencyCount"]) == plan["exportGridHz"]
    assert gm.levels(-48, -12, 1) == [-12]


def test_part_b_reproduces_the_corpus_tiles(manifest):
    """The read-time half on the kernel test's own transcribed grids: the
    Python's tiles equal the kernel's pinned figures — the two clippers'
    peaks to the kernel's 0.1 dB and the seven bounds to the digit."""
    records = {r.pk: r for r in P.corpus_records()}
    assert set(records) == set(P.CORPUS_PINNED)
    for pk, (state, value) in P.CORPUS_PINNED.items():
        reading = P.corpus_reading(records[pk], manifest)
        assert reading.peak[0] == state, f"record {pk}: {reading.peak} against {state}"
        if state == "peak":
            assert abs(20 * math.log10(reading.peak[1] / value)) < P.T_CORPUS_PEAK_DB, f"record {pk}: {reading.peak[1]} vs {value}"
        else:
            assert abs(reading.peak[1] - value) <= P.T_CORPUS_BOUND_RELATIVE * value, f"record {pk}: {reading.peak[1]} vs {value}"
        assert reading.verdict.absent is False


def test_the_python_reads_the_manifest_not_its_own_constants(results, manifest, leakage, tmp_path):
    """The red-first check: a manifest with a tampered minimum margin must
    move the Python's tile flags away from the Swift's — proof the Python is
    driven by the manifest and the parity test can see a change."""
    m = json.loads(json.dumps(manifest))
    m["gainMap"]["peak"]["minimumMarginDB"] = -1000.0
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(m))
    case, swift, _ = results["e-tanh-gain0"]
    python = P.run_python(case.args, manifest=str(path))
    r = P.compare(case, swift, python, manifest, leakage)
    assert r.discrete_mismatches, "a tampered manifest produced no visible difference"
