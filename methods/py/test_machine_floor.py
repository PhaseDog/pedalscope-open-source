"""#306 chapter five, the drift ruling's guard (2026-09-22) — on the
FORMATTER, because the drift check cannot be run against another machine:
a measured deviation under the floor prints the bound, a value at or above
it keeps its digits, a stated bar is never bounded and every bar clears the
floor, a sidecar value is written at the stated figures, the bound has a
words form, and the committed fragments and sidecars carry no digit the
rule forbids (the last two are what would have gone red on the runner's
`make methods-drift` of 2026-09-22 before the rule existed).

Red first: move `machine_floor.MACHINE_FLOOR` in a scratch edit and the
under-floor cases print digits; restore, and the tamper-marker count reads 0.
"""
import glob
import math
import os
import re

import numpy as np

import gen_docs
import machine_floor as mf
import make_figures
import parity_compression
import parity_hd
import parity_imd
import parity_journey
import parity_transfer

HERE = os.path.dirname(os.path.abspath(__file__))
METHODS = os.path.normpath(os.path.join(HERE, ".."))
GENERATED = os.path.join(METHODS, "generated")
FIGURES = os.path.join(METHODS, "figures")

MODULES = (parity_hd, parity_transfer, parity_imd, parity_journey, parity_compression)


def stated_bars():
    """Every `T_*` constant of the five parity modules (a dict's values
    counted one by one), each with the name it is stated under."""
    bars = []
    for module in MODULES:
        for name in sorted(dir(module)):
            if not name.startswith("T_"):
                continue
            value = getattr(module, name)
            if isinstance(value, dict):
                bars.extend((f"{module.__name__}.{name}[{k}]", v) for k, v in value.items())
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                bars.append((f"{module.__name__}.{name}", value))
    assert len(bars) >= 40, f"only {len(bars)} bars found — the scan is not seeing the modules"
    return bars


def test_a_measured_deviation_under_the_floor_prints_the_bound():
    for v in (5.5e-13, 7.3e-13, -3e-11, 0.0, -0.0, 9.9e-11, np.float64(1.4e-13), 1e-300):
        assert gen_docs.dev(v, 2) == mf.bound_text() == r"$\le$\,1e-10", (v, gen_docs.dev(v, 2))


def test_a_measured_deviation_at_or_above_the_floor_keeps_its_digits():
    assert gen_docs.dev(1e-10, 3) == "1e-10"            # AT the floor is not under it
    assert gen_docs.dev(3.1e-8, 2) == "3.1e-08"
    assert gen_docs.dev(-0.0031, 3) == "-0.0031"        # a signed deviation keeps its sign
    assert gen_docs.dev(0.348, 3) == "0.348"
    assert gen_docs.dev(2.6e-10, 2) == "2.6e-10"
    assert not mf.under_floor(float("nan")) and not mf.under_floor(float("inf"))  # not finite: never a bound
    assert gen_docs.dev(12, 3) == "12"                  # an integer is never a deviation
    assert gen_docs.dev("step 34 h9") == "step 34 h9"


def test_the_floor_is_derived_from_the_evidence_and_clears_every_bar():
    # (a) two decades above the largest machine-only difference in evidence.
    assert mf.MACHINE_FLOOR >= 100 * mf.LARGEST_MACHINE_DIFFERENCE
    # (b) under every stated bar — a bar at or below the floor would print
    #     "≤ floor" beside a smaller number and claim nothing.
    bars = stated_bars()
    under = [(n, v) for n, v in bars if v <= mf.MACHINE_FLOOR]
    assert not under, f"bar(s) at or under the floor {mf.MACHINE_FLOOR:g}: {under}"
    # (c) the smallest bar the documents carry sits a decade above it.
    smallest = min(v for _, v in bars)
    assert math.log10(smallest / mf.MACHINE_FLOOR) >= 1 - 1e-9, smallest


def test_a_stated_bar_is_never_bounded():
    """A bar travels through `num`, a measured value through `dev`; the
    bar lists the writers emit are run here, and none prints a bound."""
    emitted = 0
    for bars in (gen_docs.bars_hd(), gen_docs.bars_transfer(), gen_docs.bars_imd(),
                 gen_docs.bars_journey(), gen_docs.bars_compression(), gen_docs.bars_matrix()):
        for macro, value in bars:
            text = gen_docs.num(value, 3)
            assert r"\le" not in text, (macro, text)
            emitted += 1
    assert emitted >= 40, emitted
    # And the committed fragments hold every one of them as digits.
    for fragment, bars in (("parity-hd.tex", gen_docs.bars_hd()), ("parity-transfer.tex", gen_docs.bars_transfer()),
                           ("parity-imd.tex", gen_docs.bars_imd()), ("parity-journey.tex", gen_docs.bars_journey()),
                           ("parity-compression.tex", gen_docs.bars_compression()),
                           ("parity-matrix.tex", gen_docs.bars_matrix())):
        with open(os.path.join(GENERATED, fragment), encoding="utf-8") as f:
            text = f.read()
        for macro, value in bars:
            line = r"\newcommand{\%s}{%s}" % (macro, gen_docs.num(value, 3))
            assert line in text, f"{fragment} does not carry {line}"


NUMERAL = re.compile(r"(?<![A-Za-z\\{}])(-?[0-9]+(?:\.[0-9]+)?(?:e-?[0-9]+)?)(?![A-Za-z])")


def test_the_committed_fragments_carry_no_digit_under_the_floor():
    """What the runner's drift check saw on 2026-09-22 — five figures at
    1e−13…1e−12 — can no longer be printed: every numeral in a parity
    fragment is zero, or at least the floor in magnitude."""
    fragments = sorted(glob.glob(os.path.join(GENERATED, "parity-*.tex")))
    assert len(fragments) == 6, fragments
    offenders = []
    for path in fragments:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                for token in NUMERAL.findall(line.replace(r"\,", " ")):
                    try:
                        x = float(token)
                    except ValueError:
                        continue
                    if 0 < abs(x) < mf.MACHINE_FLOOR:
                        offenders.append((os.path.basename(path), n, token))
    assert not offenders, offenders


def test_the_bound_prints_in_every_fragment_that_measured_under_the_floor():
    """The rule is one rule across the six fragments: on the run that
    built the committed fragments every chapter measured at least one
    Swift−Python deviation under the floor, so every fragment prints the
    bound at least once (a fragment with none would mean the rule was
    applied to five writers and not the sixth)."""
    for path in sorted(glob.glob(os.path.join(GENERATED, "parity-*.tex"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert mf.bound_text() in text, os.path.basename(path)


def test_the_bound_has_a_words_form(tmp_path):
    fragment = tmp_path / "parity-scratch.tex"
    fragment.write_text("\\newcommand{\\xWorst}{%s}\n\\newcommand{\\xBar}{1e-09}\n\\newcommand{\\xTable}{\n1 & 2 \\\\\n}\n"
                        % mf.bound_text(), encoding="utf-8")
    words = "".join(gen_docs.parity_words_macros(str(fragment)))
    assert r"\newcommand{\xWorstWords}{under a ten-billionth}" in words, words
    assert r"\newcommand{\xBarWords}{a billionth}" in words, words
    assert "xTable" not in words


def test_the_fragment_quotes_the_floor(tmp_path):
    written = gen_docs.gen_machine_floor(str(tmp_path))
    with open(written, encoding="utf-8") as f:
        fresh = f.read()
    with open(os.path.join(GENERATED, "machine-floor.tex"), encoding="utf-8") as f:
        committed = f.read()
    assert fresh == committed, "generated/machine-floor.tex is not what the generator writes — regenerate and git add"
    assert r"\newcommand{\machineFloor}{1e-10}" in committed
    assert r"\newcommand{\machineFloorWords}{a ten-billionth}" in committed
    assert r"\newcommand{\sidecarFigures}{12}" in committed


def test_a_sidecar_value_is_written_at_the_stated_figures():
    studio, runner = 4.4802194391131165, 4.480219439113117
    assert studio != runner                                     # the one-ulp pair of 2026-09-22
    assert mf.sidecar_value(studio) == mf.sidecar_value(runner) == "4.48021943911"
    digits = mf.sidecar_value(studio).replace(".", "").lstrip("0")
    assert len(digits) == mf.SIDECAR_SIGNIFICANT_FIGURES == 12
    assert mf.sidecar_value(np.float64(1.00085713477824e-05)) == "1.00085713478e-05"
    assert mf.sidecar_value(30.0) == "30" and mf.sidecar_value(30.000000000000004) == "30"
    assert mf.sidecar_value(3) == "3" and mf.sidecar_value(np.int64(-7)) == "-7"
    assert mf.sidecar_value(True) == "1" and mf.sidecar_value(np.bool_(False)) == "0"
    assert mf.sidecar_value("below_floor") == "below_floor"
    assert mf.sidecar_value(float("nan")) == "nan" and mf.sidecar_value(None) == "nan"
    assert mf.sidecar_value(float("-inf")) == "-inf"


def test_the_sidecar_writer_uses_the_one_formatter(tmp_path):
    path = str(tmp_path / "scratch.tsv")
    make_figures.write_sidecar(path, ["a", "b", "c"], [[4.4802194391131165, 2], [np.float64(0.1), "x"], [1, True]])
    with open(path, encoding="utf-8") as f:
        assert f.read() == "a\tb\tc\n4.48021943911\t0.1\t1\n2\tx\t1\n"


SIDECAR_NUMERAL = re.compile(r"^-?(?:[0-9]+(?:\.[0-9]+)?)(?:e[-+]?[0-9]+)?$")


def test_the_committed_sidecars_carry_no_more_than_the_stated_figures():
    """The committed sidecars are the writer's own output: no numeric cell
    carries more significant digits than the stated count (the drifted
    column carried seventeen)."""
    files = sorted(glob.glob(os.path.join(FIGURES, "*.tsv")))
    assert len(files) >= 30, len(files)
    offenders = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            next(f)  # the header
            for n, line in enumerate(f, 2):
                for cell in line.rstrip("\n").split("\t"):
                    if not SIDECAR_NUMERAL.match(cell):
                        continue
                    mantissa = cell.split("e")[0].lstrip("-").replace(".", "").lstrip("0")
                    if len(mantissa) > mf.SIDECAR_SIGNIFICANT_FIGURES:
                        offenders.append((os.path.basename(path), n, cell))
    assert not offenders, offenders[:10]
