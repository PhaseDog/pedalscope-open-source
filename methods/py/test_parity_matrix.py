"""#306 chapter six: the Waveform Matrix parity guard — the shipped Swift
result against the independent Python reimplementation, and the stored
tile against its exact truth. Red when the Swift changes and the Python
has not followed, red when a memoryless tile stops being its truth to
Float32 rounding, red when a lattice guarantee no longer holds. Part B —
the lattice guarantees, the refusals, the stamp, the margin and the badge —
is pinned on the oracle's runs and the manifest's delivered lattices. The
tolerances and their provenance live in `parity_matrix.py`.

Run: `make methods-test` (builds `analysisdump` in release first).
"""
import json
import math

import pytest

import parity_matrix as P
import waveform_matrix as wmx


@pytest.fixture(scope="session")
def manifest():
    return wmx.load_manifest()


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
MEMORYLESS = [c.name for c in P.CASES if c.compares_truth_exactly and "--noise-db" not in c.args and c.kind != "miscut"]


@pytest.mark.parametrize("name", NAMES)
def test_python_reproduces_swift(results, name):
    r = _report(results, name)
    filtered = r.case.kind in ("fast", "slow", "rectifier")
    assert len(r.exact_mismatches) == P.T_EXACT_MISMATCHES, f"{name}: {r.exact_mismatches[:5]}"
    assert r.payload_bytes_difference <= P.T_PAYLOAD_BYTES, f"{name}: payload bytes differ by {r.payload_bytes_difference}"
    assert r.worst_relative <= (P.T_SWIFT_RELATIVE_FILTERED if filtered else P.T_SWIFT_RELATIVE), \
        f"{name}: statistic |Python − Swift| {r.worst_relative:.3e} relative at {r.worst_relative_at}"
    assert r.worst_mean_absolute <= P.T_SWIFT_MEAN_ABSOLUTE, f"{name}: a mean differs by {r.worst_mean_absolute:.3e}"
    assert r.worst_error_absolute <= P.T_SWIFT_ERROR_ABSOLUTE, f"{name}: {r.worst_error_absolute:.3e} at {r.worst_error_at}"
    assert r.worst_margin_db <= P.T_SWIFT_MARGIN_DB, f"{name}: a margin differs by {r.worst_margin_db:.3e} dB"
    noisy = "--noise-db" in r.case.args
    assert r.worst_stamp <= (P.T_SWIFT_STAMP_RELATIVE if noisy else P.T_SWIFT_STAMP_ABSOLUTE), f"{name}: the stamp differs by {r.worst_stamp:.3e}"
    assert r.worst_cross <= P.T_SWIFT_CROSS, f"{name}: the cross-check differs by {r.worst_cross:.3e}"


@pytest.mark.parametrize("name", MEMORYLESS)
def test_a_memoryless_tile_is_its_truth_to_float32_rounding(results, name):
    """EQUALITY: on every tile of a memoryless unfiltered device the stored
    tile's departure from the exact truth is exactly its own Float32
    quantization, on both sides."""
    r = _report(results, name)
    assert r.truth_minus_quantization <= P.T_MEMORYLESS_EQUALS_QUANTIZATION, \
        f"{name}: a tile departs from its truth by {r.truth_minus_quantization:.3e} beyond its quantization"
    assert r.quantization_max < 2 ** -23, f"{name}: the quantization {r.quantization_max:.3e} exceeds a Float32 ulp at full scale"
    for row in r.python.rows:
        assert row["truth_max_error"] <= row["float32_error"] + P.T_MEMORYLESS_EQUALS_QUANTIZATION


def test_the_settle_window_absorbs_a_fast_filters_transient_and_not_a_slow_ones(results):
    """Case (d): behind a fast filter the tile reaches the steady-state
    series to rounding; behind a slow output coupling capacitor a residue
    the size of the transient the settle window left remains — the
    chapter's settle-sufficiency number, measured, never assumed."""
    for name in ("d-tanh8-prehp", "d-tanh8-postlp"):
        r = _report(results, name)
        assert r.truth_relative_max <= P.T_FAST_FILTER_RELATIVE, f"{name}: residue {r.truth_relative_max:.3e} re the truth peak"
        assert r.truth_minus_quantization <= P.T_FAST_FILTER_BEYOND_QUANTIZATION, f"{name}: {r.truth_minus_quantization:.3e} beyond the quantization"
    slow2, slow05 = _report(results, "d-tanh8-posthp2"), _report(results, "d-tanh8-posthp05")
    for r in (slow2, slow05):
        assert r.truth_minus_quantization > 100 * r.quantization_max, f"{r.case.name}: the transient did not stand above the quantization"
        assert r.truth_relative_max <= P.T_SLOW_FILTER_CEILING_RELATIVE, f"{r.case.name}: residue {r.truth_relative_max:.3e}"
    assert slow05.truth_relative_max > slow2.truth_relative_max, "a slower capacitor leaves less transient?"


def test_the_dc_tail_reproduces_under_carried_state_and_not_under_independent_rows(results):
    """#267, measured: a rectifier behind an output coupling capacitor
    leaves the previous row's step decaying into the next row's pre-roll —
    rows 2…N's stamps stand tens of dB over the injected noise under
    carried state and read the noise's own scatter under independent rows;
    the quiet tiles' residue against the steady state is larger on the
    carried rows (the tail reaches them). On both sides."""
    for corner in ("hp05", "hp2"):
        carried = _report(results, f"i-asym-{corner}")
        fresh = _report(results, f"i-asym-{corner}-indep")
        for r in (carried, fresh):
            for d in (r.swift, r.python):
                excess = [float(x) for x in d.lists["stamps"]["excess_db"]]
                assert abs(excess[0]) <= P.T_STAMP_DB, f"{r.case.name}: row 1 reads {excess[0]:+.3f} dB over the noise"
                later = excess[1:]
                if r is carried:
                    assert all(e > P.T_DC_TAIL_EXCESS_DB for e in later), f"{r.case.name}: carried rows read {later}"
                else:
                    assert all(abs(e) <= P.T_STAMP_DB for e in later), f"{r.case.name}: independent rows read {later}"
        for f in range(1, len(carried.truth_relative_per_row)):
            assert carried.truth_relative_per_row[f] >= fresh.truth_relative_per_row[f], \
                f"{corner}: row {f + 1} carried {carried.truth_relative_per_row[f]:.3e} < independent {fresh.truth_relative_per_row[f]:.3e}"


def test_the_crossover_device_shows_its_dead_zone_at_the_quiet_end(results):
    """Case (c): the kernel's requirement through the oracle — the quietest
    tile entirely inside the dead zone, the loudest mostly outside, the
    fraction monotone down the amplitude axis, on every row, equal to the
    truth's fractions, on both sides."""
    r = _report(results, "c-crossover")
    for d in (r.swift, r.python):
        rows = {}
        for row in d.rows:
            rows.setdefault(row["freq_index"], []).append(row)
        for f, tiles in rows.items():
            fractions = [t["dead_fraction"] for t in tiles]
            assert fractions[0] == 1.0 and fractions[-1] < 0.15, f"row {f}: {fractions}"
            assert fractions == sorted(fractions, reverse=True)
            assert fractions == [t["truth_dead_fraction"] for t in tiles]


def test_the_lattices_are_the_shipped_generators_and_nest(results, manifest):
    """Case (e): every delivered lattice on both sides equals the manifest's
    delivered lattice at that (dimension, factor); 3 ⊂ 5 ⊂ 7 by VALUE on
    both axes at every factor; the anchor at the centre index; E2 on the
    note lattice; the #372 tie reproduced — four of seven quiet-side levels
    differ between 4.827 and 4.828 at 7 and none at 5."""
    delivered = manifest["waveformMatrix"]["lattice"]["delivered"]

    def entry(dimension, volts):
        return next(e for e in delivered if e["dimension"] == dimension and e.get("voltsAtFullScale") == volts)

    lattices = {}
    for name, dimension, volts in (("e-3-none", 3, None), ("a-identity", 5, None), ("e-7-none", 7, None),
                                    ("e-5-335", 5, 3.35), ("e-7-335", 7, 3.35), ("e-7-4827", 7, 4.827),
                                    ("e-7-4828", 7, 4.828), ("e-5-4828", 5, 4.828)):
        case, swift, python = results[name]
        e = entry(dimension, volts)
        for text in (swift, python):
            hz, names, amps = P.lattice_of(P.parse(text))
            assert hz == e["notesHz"] and names == e["noteNames"] and amps == e["amplitudesDBFS"], name
            assert abs(amps[dimension // 2] - e["anchorDBFS"]) < 1e-12 and amps[0] == e["floorDBFS"]
            assert hz[0] == manifest["waveformMatrix"]["lattice"]["noteAnchorHz"]
            assert names[dimension // 2] == "E4"
        lattices[name] = (set(hz), set(amps))
    assert lattices["e-3-none"][0] <= lattices["a-identity"][0] <= lattices["e-7-none"][0]
    assert lattices["e-3-none"][1] <= lattices["a-identity"][1] <= lattices["e-7-none"][1]
    assert lattices["e-5-335"][1] <= lattices["e-7-335"][1] and lattices["e-5-4828"][1] <= lattices["e-7-4828"][1]
    a7, b7 = P.lattice_of(P.parse(results["e-7-4827"][1]))[2], P.lattice_of(P.parse(results["e-7-4828"][1]))[2]
    assert sum(abs(x - y) > 0.5 for x, y in zip(a7, b7)) == P.TIE_DIFFERING_LEVELS_AT_SEVEN, (a7, b7)
    # The Python's OWN generators, unaided by the oracle, deliver the manifest's lattices at 1…9.
    wm = manifest["waveformMatrix"]
    for e in delivered:
        anchor = wmx.anchor_dbfs(e.get("voltsAtFullScale"), wm)
        assert wmx.note_frequencies(e["dimension"], wm["lattice"]["defaultLowFrequencyHz"], wm["lattice"]["defaultHighFrequencyHz"],
                                    wm["lattice"]["noteAnchorHz"], wm) == e["notesHz"]
        assert wmx.amplitudes_dbfs(e["dimension"], wmx.default_floor_dbfs(anchor, wm), wm["lattice"]["defaultCeilingDBFS"], anchor) == e["amplitudesDBFS"]
    previous = (set(), set())
    for n in range(1, 10):
        hz = set(wmx.note_frequencies(n, wm["lattice"]["defaultLowFrequencyHz"], wm["lattice"]["defaultHighFrequencyHz"], wm["lattice"]["noteAnchorHz"], wm))
        amps = set(wmx.amplitudes_dbfs(n, wm["lattice"]["defaultFloorDBFS"], wm["lattice"]["defaultCeilingDBFS"], wm["lattice"]["noVoltsAnchorDBFS"]))
        if n >= 3 and n % 2 == 1:
            assert previous[0] <= hz and previous[1] <= amps, n
            previous = (hz, amps)


def test_the_noise_stamp_reads_the_injected_noise_and_badges_nothing_on_the_identity(results):
    r = _report(results, "h-identity-noise")
    for d in (r.swift, r.python):
        excess = [float(x) for x in d.lists["stamps"]["excess_db"]]
        assert all(abs(e) <= P.T_STAMP_DB for e in excess), excess
        assert all(row["noise_badge"] == 0 for row in d.rows)
        assert all(row["noise_margin_db"] > 40 for row in d.rows)


def test_the_gain_is_input_referred_and_the_latency_cut_is_exact(results):
    g0, g12 = P.parse(results["f-hardclip-noise"][1]), P.parse(results["f-hardclip-gain12"][1])
    assert g0.lists["grid"] == g12.lists["grid"]
    for a, b in zip(g0.rows, g12.rows):
        assert a["input_start"] == b["input_start"] and a["captured_start"] == b["captured_start"]
        assert a["noise_badge"] == b["noise_badge"]
        assert abs(20 * math.log10(b["output_rms"] / a["output_rms"]) - 12) <= P.T_GAIN_DB
        assert abs(b["noise_margin_db"] - a["noise_margin_db"]) <= P.T_GAIN_DB
    for x, y in zip(g0.lists["stamps"]["row_noise_rms"], g12.lists["stamps"]["row_noise_rms"]):
        assert abs(20 * math.log10(float(y) / float(x)) - 12) <= P.T_GAIN_DB
    zero, late = P.parse(results["b-tanh8"][1]), P.parse(results["g-latency100"][1])
    for a, b in zip(zero.rows, late.rows):
        assert b["captured_start"] == a["captured_start"] + 100
        for k in ("output_rms", "output_peak", "output_mean", "truth_max_error"):
            assert P._diff(a[k], b[k]) <= P.T_LATENCY, k


def test_a_one_sample_mis_cut_grows_with_the_note(results):
    """A stated figure, pinned in ORDER only: the residue grows with the
    note (the same one sample is a larger phase error at a higher note)."""
    r = _report(results, "g-miscut1")
    per_row = r.truth_relative_per_row
    assert per_row == sorted(per_row) and per_row[0] > 1e-3 and per_row[-1] < 0.5, per_row


def test_the_cross_check_reads_the_frame_on_the_identity(results):
    """(j): the identity control's difference from the transfer cycle is
    the frame's own — under the stated ceiling — and the input-cycle
    deficit is negative (the end fade inside the average), on both sides."""
    for text in (results["a-identity"][1], results["a-identity"][2]):
        d = P.parse(text)
        c = d.header["cross-check"]
        assert int(c["bins_filled"]) == int(c["bins"])
        assert float(c["max_difference"]) / float(c["cycle_peak"]) <= P.T_CROSS_CHECK_CONTROL_RE_PEAK
        assert -0.1 < float(c["input_deficit_db"]) < 0
        assert abs(float(c["amplitude_ratio_db"]) - 20 * math.log10(10 ** (-26 / 20) / 0.05)) < 1e-12


def test_the_plugin_ceiling_and_a_user_floor_are_honoured(results, manifest):
    lat = manifest["waveformMatrix"]["lattice"]
    for text in results["k-plugin"][1:]:
        amps = P.lattice_of(P.parse(text))[2]
        assert amps[-1] == lat["pluginCeilingDBFS"] == 0.0 and amps[0] == lat["defaultFloorDBFS"]
    for text in results["k-floor40"][1:]:
        amps = P.lattice_of(P.parse(text))[2]
        assert amps[0] == -40.0 and amps[-1] == lat["defaultCeilingDBFS"] and amps[2] == lat["noVoltsAnchorDBFS"]


def test_the_four_refusals_agree(results):
    d, p = P.parse(results["l-refusals"][1]), P.parse(results["l-refusals"][2])
    assert d.header["refusal unknown_encoding"]["decodes"] == p.header["refusal unknown_encoding"]["decodes"] == "0"
    assert d.header["refusal count_mismatch"]["decodes"] == p.header["refusal count_mismatch"]["decodes"] == "0"
    for key in ("refusal short_capture", "refusal window"):
        assert d.header[key]["threw"] == p.header[key]["threw"] == "1"
        assert d.header[key]["message"] == p.header[key]["message"], key


def test_the_payload_size_is_the_kernels_own_bound(results):
    seven = P.parse(results["e-7-none"][1])
    five = P.parse(results["a-identity"][1])
    assert int(five.header["stamps"]["payload_bytes"]) < 800_000
    assert 400_000 < int(seven.header["stamps"]["payload_bytes"]) < 800_000


def test_the_python_reads_the_manifest_not_its_own_constants(results, manifest, tmp_path):
    """The red-first check: a manifest with a tampered floor span must
    move the Python's lattice away from the Swift's."""
    m = json.loads(json.dumps(manifest))
    m["waveformMatrix"]["lattice"]["defaultFloorSpanBelowAnchorDB"] = 20.0
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(m))
    case, swift, _ = results["a-identity"]
    python = P.run_python(case.args, manifest=str(path))
    r = P.compare(case, swift, python)
    assert r.exact_mismatches, "a tampered manifest produced no visible difference"
