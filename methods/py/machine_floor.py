"""#306 chapter five, the drift ruling (2026-09-22): a measured deviation
below a stated floor prints as a BOUND, and a plotted sidecar value is
written at a stated number of significant figures.

Why. `make methods-drift` regenerates every committed fragment and sidecar
and diffs them, so a generated file may carry only digits the METHOD
determines. Two files carried the machine's: `figures/compression-floor.tsv`
moved by one ulp of a 19 200-sample rms between the Studio and the
`macos-26` runner (4.4802194391131165 against 4.480219439113117), and
`generated/parity-compression.tex` printed five Swift−Python deviations at
1e−13…1e−12 (5.5e−13 → 7.3e−13, 7.5e−14 → 7.9e−14, 1.5e−12 → 1.9e−12,
5.7e−13 → 7.4e−13, 1.1e−12 → 1.4e−12) — residues of two implementations'
last-bit rounding, which two machines running the same code do not share.
The earlier chapters' fragments print figures at the same scale and were
stable only because the runner's interpreter had not moved.

The floor, DERIVED rather than typed (the ruling's constraints, in order):
  (a) at least two decades above the largest machine-only difference in
      evidence — 4e−13 (the 1.5e−12 → 1.9e−12 row) — so ≥ 4e−11;
  (b) at or below every stated bar it meets, so that "≤ floor" beside a
      bar reads as agreement inside the bar; a bar that sat at or under
      the floor (a claim of more agreement than the machine reproduces)
      was RAISED, with its reason beside it in its parity module —
      `parity_compression.T_LATENCY_DB` 1e−12, `parity_transfer.T_SWIFT`
      1e−10 and `parity_imd.T_CLOSED_FORM_RELATIVE` 1e−10, each to 1e−9;
  (c) under the smallest bar that remains — 1e−9 (the gain and latency
      bars, the transfer shift and truth bars, the corpus bound): one
      decade, which is what the ruling's own arithmetic counted (a bar
      raised to the floor can never sit two decades above it, so the
      kickoff's "two decades" reads as its worked example, 1e−10 under
      1e−9);
  (d) one constant, named, in one place — here — quoted by the generated
      fragment `generated/machine-floor.tex` so the documents print the
      floor they used.
1e−10 is 250× the largest observed difference and a decade under 1e−9.

The guard (`test_machine_floor.py`) is on the FORMATTER, not on CI: the
drift check cannot be run against another machine, so what is pinned is
that a value under the floor prints the bound, a value above keeps its
digits, a stated bar is never bounded and every bar clears the floor, and
a sidecar value is written at the stated figures.
"""
import math

import numpy as np

# The floor: a measured deviation whose magnitude is under it is the
# machine's, and prints as the bound "≤ MACHINE_FLOOR". Derivation above.
MACHINE_FLOOR = 1e-10

# The largest machine-only difference in evidence when the floor was set
# (the 1.5e−12 → 1.9e−12 row of parity-compression.tex, 2026-09-22); the
# guard pins the floor two decades above it.
LARGEST_MACHINE_DIFFERENCE = 4e-13

# Every sidecar value is written at this many significant figures: the
# drifted value's machines differ at the 17th digit, plotting needs six at
# most, and twelve carries five digits of margin.
SIDECAR_SIGNIFICANT_FIGURES = 12


def under_floor(v) -> bool:
    """True for a finite float whose magnitude is under the floor — zero
    included: an exact 0.0 on one machine is a last-bit residue on
    another, and the bound is true of both."""
    if isinstance(v, bool) or not isinstance(v, (float, np.floating)):
        return False
    v = float(v)
    return math.isfinite(v) and abs(v) < MACHINE_FLOOR


def floor_text() -> str:
    """The floor as the fragments print a number (the `num(…, 3)` form)."""
    return f"{MACHINE_FLOOR:.3g}"


# The bound's printed form, in the documents' own register (#157: a bound
# is quoted with ≤). The regex `gen_docs.BOUND_MACRO` reads it back for
# the words form.
BOUND_PREFIX = r"$\le$\,"


def bound_text() -> str:
    return BOUND_PREFIX + floor_text()


def sidecar_value(v) -> str:
    """One writer for every plotted value: a float at
    SIDECAR_SIGNIFICANT_FIGURES significant figures (nan/inf as Python
    spells them), an integer as itself, a bool as 1/0, a string verbatim."""
    if v is None:
        return "nan"
    if isinstance(v, str):
        return v
    if isinstance(v, (bool, np.bool_)):
        return "1" if v else "0"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    return f"{float(v):.{SIDECAR_SIGNIFICANT_FIGURES}g}"
