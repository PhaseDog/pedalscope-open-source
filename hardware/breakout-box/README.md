# PedalScope Breakout Box — hardware plans

A small passive box for the measurement loop between an audio interface
and a guitar pedal: three TS jacks, three 4 mm posts, one 10 kΩ resistor,
and wire. It is the bench fixture used with
[PedalScope](https://pedalscope.com), a macOS app that measures how
guitar pedals distort. The user guide describes it, and the Reference
Box's null runs and level readings were taken through it. It is not a pedal and not a product, and the project
built it by hand for the bench.

It does three jobs:

| connector | job |
|---|---|
| **TIP** / **SLEEVE** posts | a probe point on the loop: a meter or scope reads the signal with both plugs seated |
| **OUT 10k**, with **TIP +10k** after the resistor | the pedal driven through a 10 kΩ series source, on demand |
| **OUT** | a straight pass-through (IN → OUT), for null runs with no pedal in the chain |

## What is here

- `build-plan.md`: what the box is for, the layout as built, the wiring
  and the meter check before first use. Read it first.
- `bom.md`: the parts, and what the parts list does not record.
- `schematic.svg`: the circuit.
- `schematic.gen.py`: the script the schematic is generated from.
- `photos/`: `breakout-box-top.jpg` (the posts and the OUT / OUT 10k
  side) and `breakout-box-inside.jpg` (opened: the wiring and the
  lid-bond lug).

No drilling template is given: no hole position has been measured.

## Regenerating the schematic

The schematic is generated, never hand-edited. The script writes its SVG
beside itself and needs only a stock Python 3:

```
python3 schematic.gen.py
```

A change to the schematic is a change to its script, followed by a rerun.

## Licence

Everything in this directory is licensed under the
[CERN Open Hardware Licence Version 2 - Permissive](LICENSE)
(CERN-OHL-P-2.0): the plan, the bill of materials, the schematic, the
script that generates it, and the two photographs, which are covered as
documentation. Use it, share it, build on it, sell what you build, with
attribution. See `NOTICE` for the copyright line.

The PedalScope name and mark are not part of the grant: a box built
from these plans is not a PedalScope product.
