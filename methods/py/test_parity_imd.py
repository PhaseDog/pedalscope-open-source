"""#306 chapter three: the Chord IMD parity guard — the shipped Swift
result against the independent Python reimplementation, and both against
the torus-quadrature truth. Red when the Swift changes and the Python has
not followed, red when either departs from the truth beyond its measured
tolerance. The tolerances and their provenance live in `parity_imd.py`.

Run: `make methods-test` (builds `analysisdump` in release first).
"""
import json
import math
import os

import pytest

import chord_imd as ci
import parity_imd as P


@pytest.fixture(scope="session")
def manifest():
    return ci.load_manifest()


@pytest.fixture(scope="session")
def tool():
    return P.build_tool()


@pytest.fixture(scope="session")
def results(tool, manifest):
    """Every case and every twin run once on both sides."""
    return P.run_all(tool, manifest)


def _report(results, name):
    case, swift, python = results[name]
    return P.compare(case, swift, python)


NAMES = [c.name for c in P.CASES]
DEVICE_NAMES = [c.name for c in P.CASES if c.kind in ("device", "kinked")]
TWIN_NAMES = [c.name + "-twin" for c in P.CASES if c.kind in ("device", "kinked")]


@pytest.mark.parametrize("name", NAMES + TWIN_NAMES)
def test_python_reproduces_swift(results, name):
    r = _report(results, name)
    tol = r.case.swift_tolerance_db
    assert not r.header_field_mismatches, f"{name}: header fields differ: {r.header_field_mismatches[:5]}"
    assert not r.text_mismatches, f"{name}: a sentence differs: {r.text_mismatches[:3]}"
    assert not r.discrete_mismatches, f"{name}: a discrete reading differs: {r.discrete_mismatches[:5]}"
    assert r.swift_header_db <= tol, f"{name}: header |Python − Swift| {r.swift_header_db:.3e} dB"
    assert r.swift_row_db <= tol, f"{name}: row |Python − Swift| {r.swift_row_db:.3e} dB"
    assert r.swift_truth_relative <= P.T_SWIFT_TRUTH_RELATIVE, f"{name}: the two truths differ by {r.swift_truth_relative:.3e}"
    assert r.closed_form_relative <= P.T_CLOSED_FORM_RELATIVE, f"{name}: closed form vs quadrature {r.closed_form_relative:.3e}"
    if not r.case.noisy and r.case.kind != "refusal":
        assert r.empty_worst_dbc <= P.EMPTY_DEPTH_DBC, f"{name}: an empty recipe read {r.empty_worst_dbc:.1f} dBc"


@pytest.mark.parametrize("name", [c.name for c in P.CASES if c.kind == "lattice"])
def test_the_lattice_search_is_the_shipped_choice(results, manifest, name):
    """The snap the oracle played (and the Python reproduced) is the row the
    manifest recorded by RUNNING the shipped search on that grid — bins,
    spacing, reduced ratio, cents, tier and candidate counts."""
    r = _report(results, name)
    lat = r.swift.header["lattice"]
    fs = float(r.swift.header["tones"]["fs"])
    n = int(r.swift.header["tones"]["fft_length"])
    third = "--note2" in r.case.args and r.case.args[r.case.args.index("--note2") + 1] == "C#3"
    octave = "--note2" in r.case.args and r.case.args[r.case.args.index("--note2") + 1] == "A3"
    if octave:
        # The octave is not in the manifest's table: pin its two regimes by
        # the shipped search's own facts — resolved at 2^21, degraded at 2^17.
        assert lat["tier"] == ("standard_resolvable" if n == 1 << 21 else "degraded"), lat["tier"]
        assert int(lat["g"]) >= 13 if n == 1 << 21 else int(lat["g"]) == 2
        return
    rows = manifest["chordIMD"]["lattice"]["snaps"]
    row = next(s for s in rows if s["sampleRateHz"] == fs and s["fftLength"] == n
               and (s["label"].startswith("major third") == third))
    assert int(lat["bin1"]) == row["binIndex1"] and int(lat["bin2"]) == row["binIndex2"], name
    assert int(lat["g"]) == row["spacing"] and int(lat["a"]) == row["reducedA"] and int(lat["b"]) == row["reducedB"]
    assert lat["tier"] == row["tier"]
    assert abs(float(lat["cents1"]) - row["cents1"]) < 1e-9 and abs(float(lat["cents2"]) - row["cents2"]) < 1e-9
    assert int(lat["resolvable_count"]) == row["resolvableCount"]
    assert int(lat["nondegenerate_count"]) == row["nonDegenerateCount"]


def test_a_degenerate_interval_is_refused_with_its_numbers(results):
    r = _report(results, "a-refusal")
    for d in (r.swift, r.python):
        assert d.header["lattice"]["tier"] == "refused"
        assert d.header["lattice"]["a"] == "1" and d.header["lattice"]["b"] == "2" and d.header["lattice"]["g"] == "25"
        assert "cannot be resolved" in d.text["refused"] and "reduced sum 3 is below the 15" in d.text["refused"]
        assert not d.rows


@pytest.mark.parametrize("name", DEVICE_NAMES + TWIN_NAMES + ["d-phantom"])
def test_both_match_the_truth(results, name):
    r = _report(results, name)
    assert r.content_count > 0, f"{name}: no content recipe was compared"
    tol = P.truth_tolerance(r.case)
    assert r.truth_residue_db <= tol, \
        f"{name}: read vs truth {r.truth_error_db:.4f} dB at {r.truth_error_label} " \
        f"({r.truth_residue_db:.2e} dB beyond the noise allowance at {r.truth_residue_label}) > {tol}"


def test_the_phantom_reads_back_exactly(results, manifest):
    """Every enumerated recipe planted at a chosen level comes back at that
    level on both sides — and every recipe INSIDE the integration band reads
    present. The one recipe the shipped fifth puts under the band's low edge
    (3f1−2f2, about 1 Hz) reads out-of-band by the band rule, which outranks
    presence: its level still reads back exactly, its reading is a refusal
    on frequency, never a verdict — the first draft of this test asserted 54
    present and was red against the predicate, not the phantom."""
    r = _report(results, "d-phantom")
    low_edge = float(manifest["chordIMD"]["audibleBand"]["lowHz"])
    assert len(r.swift.rows) == 54 and len(r.python.rows) == 54
    for d in (r.swift, r.python):
        under = [row for row in d.rows if row["freq_hz"] < low_edge]
        assert len(under) == 1 and under[0]["label"] == "3f1−2f2", under
        v = d.header["shipped verdict"]
        assert int(v["out_of_band"]) == len(under) and int(v["present"]) == 54 - len(under), v
        assert all(row["reading"] == ("out_of_band" if row["freq_hz"] < low_edge else "present") for row in d.rows)
        assert max(abs(row["err_db"]) for row in d.rows) <= P.T_TRUTH_PHANTOM_DB


@pytest.mark.parametrize("name", [c.name for c in P.CASES if c.kind == "noise"])
def test_the_noise_floor_is_the_analytic_median(results, name):
    """The identity through seeded noise: every product absent, the capture
    floor at the noise's analytic per-bin median, the coherence check
    interpreting on both registers under the bar at about the clean-noise
    reference."""
    r = _report(results, name)
    corpus = "--length" in r.case.args  # the 2^17 fallback lattice, g = 2
    for d in (r.swift, r.python):
        v = d.header["shipped verdict"]
        assert int(v["present"]) == 0, v
        # On the corpus lattice the five recipes beside the notes and DC are
        # refused on position (#245/#251) whatever the capture holds; on the
        # shipped lattice nothing is refused and the one sub-band recipe
        # reads out of band. Neither is a resolved product.
        refused = {row["label"] for row in d.rows if row["reading"] == "near_played_tone"}
        assert refused == ({"−2f1+2f2", "4f1−2f2", "3f1−f2", "−3f1+3f2", "−3f1+2f2"} if corpus else set()), refused
        assert int(v["unresolved"]) == len(refused), v
        floor = float(v["floor_dbc"])
        expected = float(d.header["noise"]["expected_median_dbc"])
        assert abs(floor - expected) <= P.T_FLOOR_VS_EXPECTED_DB, f"{name}: floor {floor:.2f} vs analytic median {expected:.2f}"
        c = d.header["coherence (IMDAnalysis.coherenceReading)"]
        assert c["exceeds"] == "0" and c["interprets_loop_only"] == "1", c
        assert c["readable_offsets"] == "1..9" and c["read_bin_count"] == "36"
        excess = float(c["excess_over_floor_db"])
        assert abs(excess - float(c["expected_noise_excess_db"])) <= P.T_COHERENCE_EXCESS_VS_NOISE_DB, excess
        assert "premise held" in d.text["coherence line, loop-only register"]
        if corpus:
            # g = 2: a lattice point sits inside the detector's span, so the
            # device register cannot attribute the bins and says so.
            assert c["lattice_clear"] == "0" and c["interprets_device"] == "0", c
            assert "not attributable" in d.text["coherence line, device register"]
        else:
            assert c["lattice_clear"] == "1" and c["interprets_device"] == "1", c
            assert "premise held" in d.text["coherence line, device register"]


def test_the_per_bin_noise_read_falls_with_the_window(results):
    """The per-bin median of white noise sits 10·log10(N / 4 ln 2) below its
    broadband rms — 12.04 dB deeper at 2^21 than at 2^17 — which is why a
    broadband floor cannot bound a bin without a spread assumption."""
    long = _report(results, "e-identity-80").swift.header["noise"]
    short = _report(results, "e-identity-corpus-80").swift.header["noise"]
    gap = float(long["per_bin_below_broadband_db"]) - float(short["per_bin_below_broadband_db"])
    assert abs(gap - 10 * math.log10(16)) < 1e-9, gap


@pytest.mark.parametrize("name", [c.name for c in P.CASES if c.kind == "corpus"])
def test_the_corpus_lattice_refuses_by_position(results, name):
    """On the corpus probe (g = 2) the five recipes beside the notes and DC
    are refused by position on both sides, products refused beside a
    louder neighbour exist, and the floor excludes them."""
    r = _report(results, name)
    for d in (r.swift, r.python):
        near = {row["label"] for row in d.rows if row["reading"] == "near_played_tone"}
        assert near == {"−2f1+2f2", "4f1−2f2", "3f1−f2", "−3f1+3f2", "−3f1+2f2"}, near
        assert any(row["reading"] == "near_louder_product" for row in d.rows)
        assert d.header["floor line"]["absence"] == "none"
        assert int(d.header["floor line"]["noise_reads"]) < 54 - 5
        assert int(d.header["near louder product"].get("refused", "0") or 0) >= 0
        assert d.header["coherence (IMDAnalysis.coherenceReading)"]["lattice_clear"] == "0"
        assert d.header["coherence (IMDAnalysis.coherenceReading)"]["interprets_device"] == "0"
        assert "not attributable" in d.text["coherence line, device register"]


def test_the_wander_fixture_is_read_in_both_registers(results):
    """The validated wander generator: through the legacy path on the corpus
    lattice it is the loop-only register's fault and the device register's
    'not attributable'; on the shipped lattice the detector reads it over
    the bar in both registers, with the pair difference near the shared
    frequency wander's signature."""
    legacy = _report(results, "h-wander-legacy")
    for d in (legacy.swift, legacy.python):
        c = d.header["coherence (IMDAnalysis.coherenceReading)"]
        assert c["source"] == "stored_products" and c["max_offset_bins"] == "2"
        assert c["not_trustworthy_loop_only"] == "1" and c["interprets_device"] == "0", c
        assert float(c["excess_over_bar_db"]) > 0
        assert "not trustworthy" in d.text["coherence line, loop-only register"]
        assert "not attributable" in d.text["coherence line, device register"]
    shipped = _report(results, "h-wander-shipped")
    for d in (shipped.swift, shipped.python):
        c = d.header["coherence (IMDAnalysis.coherenceReading)"]
        assert c["source"] == "detector" and c["not_trustworthy_device"] == "1" and c["not_trustworthy_loop_only"] == "1"
        assert float(c["worst_dbc"]) > -40, c["worst_dbc"]
        assert abs(float(c["pair_difference_db"]) - float(c["expected_difference_db"])) < 1.0, c["pair_difference_db"]
        assert "not trustworthy" in d.text["coherence line, device register"]


def test_a_loud_device_is_not_interpreted(results):
    """A device whose loudest product stands above the played tones: no
    detector offset passes the level rule, the reading does not interpret,
    the loudest-skirt rule marks products unread, and the sentence names
    the signal that would have been read."""
    r = _report(results, "i-loud-squarer")
    for d in (r.swift, r.python):
        c = d.header["coherence (IMDAnalysis.coherenceReading)"]
        assert float(c["loudest_product_dbc"]) > 0
        assert c["readable_offsets"] == "none" and c["level_limited"] == "1" and c["interprets_device"] == "0"
        assert d.header["loudest skirt"].get("loudest") is not None and int(d.header["loudest skirt"]["under_skirt"]) > 0
        assert "does not interpret" in d.text["coherence line, device register"]
        assert any(row["reading"] == "under_loudest_skirt" for row in d.rows)


def test_a_latency_error_moves_the_window_and_no_magnitude(results):
    """The worked example analyzed 100 samples late: the segment moves, the
    overrun is unchanged, every content product's level is unchanged."""
    zero = _report(results, "c-tanh").swift
    late = _report(results, "j-latency").swift
    assert int(late.header["window"]["start"]) == int(zero.header["window"]["start"]) + 100
    assert late.header["window"]["fade_overrun"] == zero.header["window"]["fade_overrun"]
    by = {(r["m"], r["n"]): r for r in zero.rows}
    for row in late.rows:
        if math.isfinite(row["truth_dbc"]) and row["truth_dbc"] > -120:
            shift = abs(row["level_dbc"] - by[(row["m"], row["n"])]["level_dbc"])
            assert shift <= P.T_LATENCY_SHIFT_DB, f"{row['label']}: {shift:.3e} dB"


def test_the_python_reads_the_manifest_not_its_own_constants(results, manifest, tmp_path):
    """The red-first check: a manifest with a tampered neighbourhood width
    must move the Python's readings away from the Swift's on the corpus
    lattice — proof the Python is driven by the manifest and the parity
    test can see a change."""
    m = json.loads(json.dumps(manifest))
    m["chordIMD"]["resolution"]["playedToneNeighbourhoodBins"] = 0
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(m))
    case, swift, _ = results["g-corpus-squarer"]
    python = P.run_python(P.resolved_args(case, manifest), manifest=str(path))
    r = P.compare(case, swift, python)
    assert r.discrete_mismatches, "a tampered manifest produced no visible difference"
