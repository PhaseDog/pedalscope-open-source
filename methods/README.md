# Docs/Methods — the methods-document pipeline (#305)

Two open-source documents that must stay true to the app as its methods
change: `methods.pdf` (the technical reference) and `explained.pdf` (its
plain-language companion). **Propagation is
enforced by CI, not remembered.** Nothing here is bundled into the app.

## The four mechanisms

1. **The manifest.** `analysisdump manifest` (a package tool on the app's own
   measurement kernel — no app launch, no build coupling) writes
   `generated/manifest.json`: every parameter that determines a result, each
   obtained by CALLING the shipped function that owns it. `ManifestGuardTests`
   pins the key list and scans the method's source files so a named constant
   cannot join the method without an entry.
2. **The Python reimplementation.** `py/harmonic_distortion.py` is the method
   written again from the manifest and the published definition, not from the
   Swift. It emits the same TSV `analysisdump synth` emits.
3. **The parity test.** `py/test_parity_hd.py` runs both on identical
   synthetic devices and holds them to each other and to analytic truth at
   tolerances SET FROM MEASUREMENT (`py/parity_hd.py` quotes each one's
   provenance).
4. **The drift check.** `make methods-drift` regenerates `generated/` and
   `figures/` and fails on any diff; CI runs it beside the parity test.

Plus the **terms source** `terms.yaml`: both documents' glossaries are
generated from it and `py/test_terms.py` fails on an undefined `\term{}`
reference, an unused entry, or a sentence that says what something sounds
like.

## Make

| target | does |
|---|---|
| `make methods-venv` | Python venv under `.venv/` from `requirements.txt` (pinned) |
| `make methods-manifest` | builds `analysisdump` (release) and writes the manifest |
| `make methods-figures` | the chapter figures from the Python (seeded, byte-stable, TSV sidecars) |
| `make methods-generated` | the LaTeX fragments: parameter tables, glossary, the parity run's numbers |
| `make methods-docs` | all of the above, then `latexmk` (pdflatex, pinned in `tex/latexmkrc`) → `tex/build/*.pdf` |
| `make methods-test` | the parity test and the terms guard |
| `make methods-drift` | regenerate and `git diff --exit-code` on `generated/` and `figures/` |

| `make methods-pdf` | both PDFs from the COMMITTED inputs only (no Swift, no Python), `SOURCE_DATE_EPOCH` = HEAD's commit time; output `tex/build/`, gitignored |

LaTeX is expected at `/Library/TeX/texbin` locally (`TEXBIN=` overrides).

## The review route (ruled 2026-09-17)

The reader of record reviews the built PDFs and the review lands in the
`.tex` sources only: a prose edit the reader is sure of goes straight into
the `.tex`; where the session that acts on the review should decide, a
`%% RICK: …` comment on the line above the sentence says what to decide,
and the session resolves it and removes the tag. Never `generated/` or
`figures/` — those are regenerated, and an edit there is drift. A
comments-only push may carry `[skip ci]`; a prose edit pushes normally so
the terms and names scans run over it.

## CI and publication (ruled 2026-09-08)

**The PDFs are never committed** — a committed PDF is either an unchecked
drift hole or a cross-install byte mismatch. `.github/workflows/methods-docs.yml`
(path-filtered to `Docs/Methods/**`, `Tools/analysisdump/**`,
`Packages/MeasureKit/**`) runs two jobs: `parity` on macOS (the Swift tool
needs Accelerate: `methods-test` + `methods-drift`) and `pdf` on Ubuntu
(minimal TeX via `Tools/ci-texlive.sh`, cached on `tex/texlive-packages.txt`;
`make methods-pdf`; link/citation census; PDFs uploaded as the
`pedalscope-methods-pdfs` artifact). The Pages deploy runs the same TeX
recipe and `Site/build.sh` publishes the PDFs at `/methods/`.
`SOURCE_DATE_EPOCH` makes builds reproducible run to run on one install;
nothing is gated on the bytes.

**Publication (ruled 2026-09-20, #309).** The documents publish into
`methods/` of the ONE public repository, `PhaseDog/pedalscope-open-source`
(the library releases' repository, renamed that day), by
`make publish-methods` — `Tools/publish-methods.sh`, run once per landed
chapter, no second CI. It is a SNAPSHOT COPY, not a subtree split: this
directory minus `.venv/`, `py/__pycache__/`, `py/.pytest_cache/` and
`tex/build/`, plus `methods/pdf/methods.pdf` and `methods/pdf/explained.pdf`
from `make methods-pdf`, copied with `rsync --delete` scoped to `methods/`,
committed as `methods: Docs/Methods at <private short SHA> (<date>)`. It
refuses unless this tree is clean on `main` and `make methods-test` and
`make methods-drift` are green, and it STOPS before the push
(`PUBLISH_METHODS_PUSH=1` pushes). The public copy's PDFs are a published
artefact named by the SHA they were built at — the never-committed rule
above is about this tree, which has a drift check; the site's `/methods/`
and the repo's `methods/pdf/` both regenerate from one commit, the site on
push and the repo at the landing session's publish, so the two copies follow
one SHA by procedure. Nothing in the public copy is edited by hand: a fix
lands here and is re-published. The parity tests travel as the record of
what is asserted and at what tolerance — they call `analysisdump`, which is
private, so they cannot run there; the public README says what can.

## Layout

```
generated/   manifest.json + the .tex fragments (plain-<kind>.tex holds the lay
             chapter's macros and the parity words forms) — COMMITTED, drift-checked
figures/     hd-*.png, transfer-*.png, imd-*.png, journey-*.png, explained-*.png + .tsv sidecars — COMMITTED, drift-checked
py/          harmonic_distortion.py  the reimplementation
             parity_hd.py           the comparison + tolerances (shared by test and generator)
             test_parity_hd.py      the CI parity test
             transfer_curve.py      the Transfer Curve reimplementation (#306 chapter two)
             parity_transfer.py     its comparison + tolerances
             test_parity_transfer.py  its CI parity test
             chord_imd.py           the Chord IMD reimplementation (#306 chapter three)
             parity_imd.py          its comparison + tolerances
             test_parity_imd.py     its CI parity test
             gain_map.py            the Gain Map reimplementation (#306 chapter four; imports harmonic_distortion.py)
             parity_journey.py      its comparison + tolerances
             test_parity_journey.py its CI parity test
             make_figures.py        the figures
             gen_docs.py            the fragments (both registers)
             test_terms.py          the terms guard
tex/         methods.tex explained.tex preamble.tex references.bib latexmkrc
             build/                 latexmk products — ignored
terms.yaml   the terms source
requirements.txt
```

## Licences (ruled 2026-09-08)

| paths | licence |
|---|---|
| `py/`, `make_figures.py`, `gen_docs.py`, the `methods-*` Makefile targets and `tex/latexmkrc` — the code | MIT — `LICENSE` |
| `tex/`, `terms.yaml`, `figures/`, `generated/`, and the built PDFs — the documents | CC BY 4.0 — `LICENSE-DOCS` (the legal code, verbatim) |

Holder: **Richard Hoge** (the string the app's About view carries). Both
documents print the same line in their front matter, and the site's
`/methods/` index repeats it under the two PDF links.

**Trademark exclusion.** "PedalScope" and its mark are not part of either
grant: the licences cover the code and the text, not the name. This section
travels with the directory into `methods/` of the public
`pedalscope-open-source` repository at every `make publish-methods` (#309);
the hardware's licence (CERN-OHL-P-2.0) lands with `Bench/` under #308, not
here.

## The recipe for the next chapter

Chapters two through N are mechanical. For a measurement kind X:

1. **Oracle.** If no `analysisdump` subcommand runs a KNOWN input through
   X's shipped analyze path with the truth beside it, add one on `synth`'s
   shape (a `*Dump.swift` in `AnalysisDumpKit`, a `run…` in `main.swift`, a
   Help entry, a guard that RUNS it). The oracle's TSV is the parity target;
   real stored records are not (they hold results, not raw captures).
2. **Manifest.** Add an `X` object beside `harmonicDistortion` in
   `ManifestDump.swift`: every parameter by a shipped call; functions as
   name + defining constants + a one-line rule; a `shippedConstants` map.
   Extend `ManifestGuardTests`: the key pin, and X's source files in the
   census list (allowlist non-X statics with a reason). Regenerate the
   manifest.
3. **Python.** `py/x.py` from the manifest and the published definition,
   emitting the oracle's exact column set. Establish parity BEFORE writing
   the test: run both, tabulate `|Swift − Python|` and `|Swift − truth|` per
   order/point, and only then set tolerances just above the measured maxima
   (the way `parity_hd.py` documents each of its own). Show the test red
   (a deliberate one-sample error), then green.
4. **Figures.** `py/make_figures.py` gains X's figures (seeded, `SAVE`
   metadata stripped, a TSV sidecar per figure).
5. **Terms.** Add X's terms to `terms.yaml`; the guard names what is
   missing or unused.
6. **Chapter.** A `\section` in `methods.tex` in the HD chapter's order
   (purpose and what it cannot tell you; stimulus; pipeline as numbered
   steps; the generated parameter table; figures; the worked example with
   the parity numbers; limits), a stub section in `explained.tex`, and
   `gen_docs.py` writers for X's fragments. No third-party name in a
   finding; nothing "sounds" like anything (the terms guard scans both).
7. `make methods-docs`, `make methods-test`, `make methods-drift`, commit
   the regenerated `generated/` and `figures/`.

## The recipe for a lay chapter (explained.tex)

The lay counterpart to a technical chapter, written in the same or an
adjacent session (one chapter per code session, ruled 2026-09-16). For a
measurement kind X whose technical chapter exists:

1. **Mirror the headings.** The same order as the technical chapter, in
   plainer words, each subsection answering the question its technical
   twin answers, so the two documents read side by side. No equation in
   the prose; a symbol appears only inside a generated table.
2. **Numbers through fragments only.** `gen_docs.py`'s `gen_plain` writes
   `generated/plain-<kind>.tex`: one macro per value the prose quotes
   (`\hdStartHz`, `\hdDelayTwoS`, …) and a per-harmonic table in plain
   column headings, all read from the manifest; the parity macros in
   `parity-<kind>.tex` serve both registers. A number the fragments do
   not carry is a new macro, never a typed digit. A note name beside a
   frequency is the nearest equal-tempered note (A4 = 440 Hz), a naming
   aid computed by the writer. **Tolerances in words:** a parity macro
   prints `1e-10`-style figures, so the plain writer emits a words form
   beside every scalar the parity fragment carries (`\tparitySwiftWords`
   = "a ten-billionth", from the same literal, through `in_words` in
   `gen_docs.py`: an exact power of ten is named, anything else reads
   "about N ×10^k" in words, and a value with no name comes back as the
   number). The lay prose quotes the words form with the number beside
   it; the plain writers therefore run AFTER the parity writers in
   `gen_docs.py` so the words never lag the numbers.
3. **Concept figures.** `make_figures.py` gains `explained-*.png` figures
   computed from the reimplementation's own devices and the truth function
   the parity code uses (`fig_clipping` is the model), seeded or
   deterministic, a TSV sidecar per plotted set, byte-stable across two
   runs (`make methods-figures` twice, hash the directory).
4. **Groundwork inline.** A concept the reader may lack (what a harmonic
   is, what clipping does, what "at the floor" means, what a loop in an
   output-against-input picture means) is explained where the chapter
   first needs it; if the inline groundwork for one idea runs past about
   a page, lift it into a short section placed before the chapter and say
   so in the handoff, which names the concept chapters the paragraphs
   seed (chapter three lifted *Slots: how a spectrum is read* ahead of
   Chord IMD — the seed of the "what a spectrum's slots are" concept
   chapter). A concept figure carries the groundwork where a picture is
   the explanation (`explained-ellipse.png`: a sine against a shifted copy
   of itself is the loop; `explained-skirt.png`: a note off its slot
   spills a skirt). The chosen value a concept figure is built on (the
   shift, the fractional offset) is PRINTED in the panel title, so the
   caption is checkable against the figure. **View every PNG once after
   `make methods-figures`** — a title that fits in the code can run off
   the pane at 110 dpi.
5. **Terms.** `\term{key}` at first use; improve a `plain` definition the
   chapter shows to be too technical (that field exists for this
   document); a new term needs `technical` and `plain` and a chapter that
   uses it. A `plain` body carries no typed number — no macro can reach
   a term body, so a duration or a count there goes stale silently; say
   "the long middle stretch" and let the chapter quote the figure through
   its macro. A `\term{}` (a `\hyperlink`) cannot sit inside a `\caption`;
   the term goes in the body text at first use and the caption says the
   plain word.
6. **Guards.** `test_terms.py` scans both documents: undefined or unused
   terms, a sentence that says what something sounds like (the exact-
   phrase disclaimer allowlist, every entry used), and a third-party
   product name (the app's pinned list, by repo path). Show a new
   allowlist entry or scratch line red before relying on the guard. The
   app's own chart in the chapter is described from the guide's rendered
   PNG and nothing else: a chart element the renderer does not draw, or a
   rule the code does not carry (the static curve is dashed on EVERY
   loop, open or closed — read in the view, 2026-09-17), is an unpinned
   claim.
7. `make methods-test`, `make methods-drift`, `make methods-pdf`; read the
   built chapter through once as its reader; quote its page range in the
   handoff with the reader-of-record request.
