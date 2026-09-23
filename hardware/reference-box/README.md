# PedalScope Reference Box — hardware plans

Six small circuits in one box, chosen because their distortion can be
computed from resistor arithmetic and Fourier theory before anything is
plugged in. It exists to check a measurement instrument —
[PedalScope](https://pedalscope.com), a macOS app that measures how
guitar pedals distort — against answers that were known in advance. It is
not a pedal and not a product: nothing about it was chosen for how it
plays, and it was built on perfboard by the project for the bench.

The published **Reference Box measurement library** was made with this
box: https://pedalscope.com/library.html. Beside each measurement on
that page is the number that was computed first. Build the box, measure
it, and compare your library against the published one — the check
stays checkable.

## The six positions

A two-pole rotary switch selects one circuit at a time and disconnects
the other five at both ends.

| position | circuit | what it checks |
|---|---|---|
| P1 | resistive divider | absolute gain through the whole calibration chain, and the rig's own distortion floor |
| P2 | one-pole RC low-pass | a linear filter's magnitude against closed form, and that phase compensation leaves nothing behind |
| P3 | symmetric diode clipper (matched pair) | odd-harmonic distortion; the even orders are a small matching residue, not zero |
| P4 | asymmetric diode clipper (one up, two down) | even-harmonic distortion: the same circuit as P3 with one diode changed |
| P5 | precision full-wave rectifier | harmonic ratios fixed by the Fourier series of \|sin\|: H4/H2 = −13.98 dB, H6/H2 = −21.34 dB |
| P6 | unity follower forced into class-B crossover | distortion that rises as the level falls — a non-monotonic case |

## What is here

- `build-plan.md` — the build narrative, position by position, with the
  as-built predictions and what each one validates. Read it first.
- `bom-abra.md` and `bom-mouser.csv` — two bills of materials, one as a
  shopping list and one in a distributor-import shape.
- `diagram.svg` — the signal path and the six positions, annotated with
  each position's as-built prediction.
- `p5-p6-schematic.svg` — the two op-amp positions in full, with the
  measured part tags and the meter checks.
- `board-layout.svg` — the perfboard placement, both sides, the harness
  table and the meter pre-checks.
- `power-wiring.svg` — the split-rail battery supply.
- `*.gen.py` — the four scripts the schematics are generated from.

## Regenerating the schematics

The schematics are generated, never hand-edited. Each script writes its
SVG beside itself and needs only a stock Python 3:

```
python3 diagram.gen.py
python3 p5-p6-schematic.gen.py
python3 board-layout.gen.py
python3 power-wiring.gen.py
```

A change to a schematic is a change to its script, followed by a rerun.

## As built

The box that made the published library differs from its first plan in
one part: the P6 load is **1 kΩ**, not the 10 kΩ first specified (at
10 kΩ the crossover handover sat too close to the top of the drive
range). The plan's header lists the as-built deltas, and every number
on the schematics is the as-built prediction. The bench records that
measured the box are not published here; they are the provenance of
the measurement library and travel with it.

## Licence

Everything in this directory — the plan, the bills of materials, the
schematics and the scripts that generate them — is licensed under the
[CERN Open Hardware Licence Version 2 - Permissive](LICENSE)
(CERN-OHL-P-2.0). Use it, share it, build on it, sell what you build,
with attribution. See `NOTICE` for the copyright line.

The PedalScope name and mark are not part of the grant: a box built
from these plans is not a PedalScope product.
