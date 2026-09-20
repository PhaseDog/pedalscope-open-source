# PedalScope open source

The open-source side of [PedalScope](https://pedalscope.com), the macOS
instrument that measures how guitar pedals distort: the measurement
libraries, the methods documents with the code that reproduces them, and —
forthcoming — the hardware plans for the project's reference fixtures. One
repository, three kinds of thing, each under its own licence (see
[Licences](#licences) at the end).

## Measurement libraries

Each library is a real device, measured under stated conditions and exported
from the shipping build exactly as measured — nothing idealised, nothing
cleaned up, no record re-taken because a nicer one was wanted.

**This repository holds no measurement data in git.** Every library is a
release asset: open the [Releases](../../releases) page, download the zip
for the set you want, unzip it, and double-click the `.pedalscope` file
inside. PedalScope opens it (free tier included — importing needs no
purchase) and reports what arrived. Each release's notes carry the set's
SHA-256, its contents, the rig it was measured on, and how to check the
download.

The index of published sets, with the arithmetic each one was checked
against, is at **https://pedalscope.com/library.html**.

### Naming

- Tag: `library-<set>-<YYYY-MM-DD>` — the set and its capture date.
- Asset: `PedalScope-<Set>-<YYYY-MM-DD>.zip`.

A published set is permanent. A later capture of the same device is
published under a new dated name and arrives in PedalScope as a separate
pedal, so two generations compare cleanly instead of interleaving.

## Methods documents

`methods/` holds the two documents that describe how PedalScope measures,
and everything they are built from:

- **`methods/pdf/methods.pdf`** — the technical document: for each
  measurement kind, the stimulus, the analysis pipeline step by step, every
  parameter with its value, the figures, a worked example with the parity
  numbers, and the limits.
- **`methods/pdf/explained.pdf`** — the plain-language companion, chapter
  for chapter, for a reader who plays and wants to know what the charts mean.
- `methods/tex/` — the LaTeX sources of both (`methods.tex`,
  `explained.tex`, `preamble.tex`, `references.bib`) and the pinned
  `latexmkrc`.
- `methods/py/` — the Python reimplementations of the methods
  (`harmonic_distortion.py`, `transfer_curve.py`, `chord_imd.py`), written
  from the manifest and the published definitions, not from the app's Swift;
  the figure generator (`make_figures.py`); the fragment generator
  (`gen_docs.py`); the terms guard (`test_terms.py`); and the parity tests
  (`test_parity_*.py`, `parity_*.py`).
- `methods/generated/manifest.json` — **every number the documents quote
  comes from here.** The manifest is emitted by the shipped app's own
  measurement code: each parameter is obtained by calling the function that
  owns it, and a guard in the private repository fails when a constant joins
  a method without an entry. Beside it, the generated LaTeX fragments
  (parameter tables, glossaries, the parity numbers, the lay chapters'
  macros).
- `methods/figures/` — every figure in the documents as PNG, each with a
  `.tsv` sidecar of the values it plots; plus the four charts the documents
  reproduce from PedalScope's user guide (`*--sim*.png`), rendered by the
  app itself.
- `methods/terms.yaml` — the terms source both glossaries are generated
  from, with a technical and a plain definition per term.

The documents are also served at https://pedalscope.com/methods/.

### Where it comes from

`methods/` is a snapshot of the private repository's `Docs/Methods` at one
commit, named in the commit message (`methods: Docs/Methods at <sha>
(<date>)`), with the PDFs built from those inputs. It is refreshed when a
chapter lands. Nothing here is edited by hand: a correction is made at the
source and republished.

### Building the PDFs

You need `pdflatex`, `bibtex` and `latexmk` (on Debian or Ubuntu, the
packages in `methods/tex/texlive-packages.txt`; on a Mac, a TeX Live
install). Then:

```
cd methods/tex
latexmk -r latexmkrc methods.tex explained.tex
```

Output lands in `methods/tex/build/`. Both documents build from the
committed inputs alone — no Swift, no Python.

### What runs here, and what cannot

Everything below was run in a fresh checkout of this repository and is
stated as found:

- **The terms guard** — `python -m pytest test_terms.py -k "not
  third_party"` in `methods/py/`, with the packages in
  `methods/requirements.txt` installed: four checks pass (every term a
  chapter uses is defined, every defined term is used, every entry is
  complete, and the chapters state what was measured and never what is
  heard). The fifth, `test_no_third_party_names`, reads the app's pinned
  product-name list by a private path and cannot run here; it is
  deselected by the `-k` above.
- **The generated fragments** — `python gen_docs.py --no-parity` in
  `methods/py/` regenerates `methods/generated/*.tex` from the manifest and
  `terms.yaml`, byte-identical to what is committed. The parity fragments
  (`parity-*.tex`) are left as committed, because producing them needs the
  Swift oracle.
- **The figures** — `python make_figures.py` in `methods/py/` regenerates
  every figure in `methods/figures/` byte-identical to what is committed,
  except `hd-residuals.png`, which needs the Swift oracle's output for the
  same case (`--swift`) and is left as committed.
- **The PDFs** — `latexmk` as above: 49 and 42 pages, the same page counts
  as the committed PDFs.
- **The parity tests cannot run here.** `test_parity_hd.py`,
  `test_parity_transfer.py` and `test_parity_imd.py` call the private
  Swift tool (`analysisdump synth`, `transfer-synth`, `imd-synth`), which
  runs the app's own analysis code on a synthetic device beside the Python's
  and holds the two to each other and to the analytic truth. Those tests
  run in the private repository's CI on every change; they are published
  here as the record of **what is asserted and at what tolerance** — read
  `parity_hd.py`, `parity_transfer.py` and `parity_imd.py`, where each
  tolerance is quoted with the measurement it was set from — and the
  numbers they produced are in the documents' worked examples.

## Hardware plans

Forthcoming: `hardware/` will hold the build plans for the project's
reference fixtures — the **Reference Box** first (six known-answer
circuits whose distortion was computed from resistor arithmetic and Fourier
theory before anything was plugged in; the measurement library above was
made with it), then the **Breakout Box**. Plans, bills of materials and
generated schematics; not the bench records, which are the libraries'
provenance and stay with them. No date is promised.

## Licences

| what | licence | holder |
|---|---|---|
| the measurement libraries (release assets) | [CC BY 4.0](LICENSE) | Richard Hoge |
| `methods/` — the code (`py/`, the `latexmkrc`) | [MIT](methods/LICENSE) | Richard Hoge |
| `methods/` — the documents (`tex/`, `terms.yaml`, `figures/`, `generated/`, `pdf/`) | [CC BY 4.0](methods/LICENSE-DOCS) | Richard Hoge |
| `hardware/` — when it lands | CERN-OHL-P-2.0 | Richard Hoge |

Use them, share them, build on them, with attribution to PedalScope. The
PedalScope name and mark are not part of the grant.
