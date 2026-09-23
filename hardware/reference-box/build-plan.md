# Reference Box — build plan
*Addendum E, positions P1–P6. Built and verified one position at a time,
so a disagreement between prediction and measurement always localises to
the circuit you just added.*

> **BUILT — 2026-08-10.** This document is kept as the build narrative
> and repair reference. Predictions inline below have been corrected to
> the as-built, load-included values, and the annotations on the
> generated schematics (`diagram.svg`, `p5-p6-schematic.svg`,
> `board-layout.svg`) carry the same as-built predictions. The bench
> records that measured the box — its expected-values card and the dated
> baseline reports — are private: they are the provenance of the
> published measurement libraries and stay with them. What is published
> is the plan, the two bills of materials, the four schematics and the
> scripts that generate them.
>
> **As-built deltas from the original plan:** P6's load is **1 kΩ**, not
> 10 kΩ. DC probe points are **board nodes**, not the OUT jack (the
> output coupling cap blocks exactly the DC being looked for): P5 at
> pin 7 / col 21 top, P6 at LM358 pin 1 / col 29 bottom. P6's input
> bias offset is **positive** — the PNP input stage sources current out
> of the pin.

---

## The governing idea

Every position has an analytically known answer. That means a mismatch
has exactly two possible causes: the box is miswired, or the app is
wrong. Building incrementally keeps that diagnosis tractable — if P1
through P3 verified and P4 doesn't, the problem is in P4's five
components, not in six circuits and a DSP stack at once.

**Measure each position the moment it exists.** Do not build all six and
then power up.

---

## Stage A — bench characterisation before any soldering

The predictions are only as good as the parts, and you bought spares
precisely so you could select.

- [ ] **Measure all ten 1N4148 forward voltages** at a fixed meter test
      current, written down. Pick the **closest-matched pair for P3** —
      its H2-at-the-floor prediction is a symmetry claim and depends on
      matching. Note the spread; same-batch parts usually land within
      10–20 mV.
- [ ] **Measure the five 10 nF caps.** Use the closest to nominal for
      P2, and record the *measured* value — the f_c prediction becomes
      1/(2πRC) with your number, not the nominal 1.592 kHz.
- [ ] **Measure the 10 k resistors.** Set aside the **four closest-matched
      for P5** (the rectifier's fundamental suppression is a resistor-
      matching claim), and note the actual values for P1's divider pair.
- [ ] Recompute P1's predicted attenuation from measured values —
      **and include the load**. 20·log₁₀(R2/(R1+R2)) is only the
      unloaded answer. As built: 9.052 k / 0.9987 k gives −20.06
      unloaded, but −20.41 dB once the 100 Ω source and the interface's
      ≈30 kΩ input (in parallel with the 1 MΩ bleed) are included. That
      0.35 dB is the whole point of the position.

Write all of this into the pedal's Notes field in the app when you
create it — the predictions are part of the instrument's provenance.

---

## Stage B — enclosure and harness (no circuits yet)

Signal path, common to all positions:

```
IN jack → 10 µF coupling → 1 MΩ to gnd → [rotary pole A wiper]
                                          pole A contacts 1–6 → circuit inputs
          circuit outputs → pole B contacts 1–6
                            [pole B wiper] → 10 µF coupling → 1 MΩ to gnd → OUT jack
```

Both signal legs switched means the CK1459's two poles carry input
distribution and output collection respectively, so an unselected
circuit is disconnected at both ends. Non-shorting contacts (which is
why you chose that part) mean no momentary bridging during rotation.

- [ ] Drill and mount: two ¼″ jacks on the ends, rotary centred, power
      toggle where it won't be knocked.
- [ ] Star ground: one point, everything home-runs to it. Jack sleeves,
      circuit grounds, battery centre tap.
- [ ] Perfboard mounted with the powered stages (P5/P6) physically
      **furthest from the input jack** — they have the most gain and the
      most to leak.
- [ ] Label positions on the panel: P1 Divider · P2 RC · P3 Sym ·
      P4 Asym · P5 Rectifier · P6 Crossover.

**Harness verification — do this before any circuit exists.**
Temporarily jumper position 1 as a straight wire (contact A1 to B1).
Calibrate, then measure the box.

> **Expect:** flat within the interface's own flatness, THD at the
> interface floor, essentially unity gain minus coupling-cap loss at the
> bottom of the range. The box's own contribution is now bounded and
> documented. Anything else is a wiring or grounding problem — fix it
> here, where there are five components to check.

Remove the jumper when it passes.

---

## Stage C — passive positions

Build P1 and P2 first: no power, no semiconductors, exact predictions.
These two are also the positions that would have caught the calibration
problems from last week.

### P1 — Reference divider
9.09 k series / 1.01 k shunt (or 9.1 k/1 k).

> **Predicts:** H1 flat at your computed *loaded* value
> (**−20.41 dB** as built) ±0.2 dB, 20 Hz–20 kHz. Every harmonic at the
> measurement floor. THD equal to the interface's own floor.
> **Validates:** absolute gain through the whole calibration chain, and
> what your real THD floor actually is — noting that P1's floor is
> pessimistic by 20 dB, since the position throws away 20 dB of signal.
> **Also the directional gate:** reversed cables read ≈ −3.2 dB here.

### P2 — Single-pole RC low-pass
10 k series, measured-value cap to ground.

> **Predicts:** plateau −2.59 dB (the 10 k series resistor into the
> interface's input is itself a divider), then −3.0 dB relative to that
> at the **loaded** f_c — 2121 Hz as built, not the 1590 Hz the
> unloaded R alone would give, because the cap sees
> (100 Ω + 10.013 k) ∥ 29.13 k = 7.51 k. −20 dB/decade asymptote above
> it; harmonics at the floor. Discriminate by hovering A6 and A7.
> **Validates:** H1 magnitude against closed form — and, critically,
> **the transfer-curve loop should collapse to a dead straight line.**
> This is the direct test of the phase-compensation path. A compensated
> linear filter with a nonzero nonlinear residual means the
> compensation is leaving something behind. Run it with "remove filter
> phase rotation" both on and off and record both.

Do not proceed until both verify. If P1's level is off by a fixed
amount, that's calibration; if P2's shape is off, that's the cap or the
resistor; if P2's loop doesn't close, that's the app.

---

## Stage D — passive clipping positions

### P3 — Symmetric Si clipper
10 k series → matched antiparallel 1N4148 pair to ground.

> **Predicts:** odd-dominant, H3 ≫ H5, decaying monotonically.
> **H2 low but NOT zero** — as built it lands ≈20 dB below H3 and
> ≈11 dB above the rig's even-order floor, i.e. real residual
> asymmetry from sub-0.1 mV diode mismatch or layout. The original
> "symmetry zero" prediction was wrong. Clipping knee below ±0.6 V and
> soft (conduction is at tens of µA in circuit, not the meter's ~1 mA);
> the knee is an **empirical** reference, not an analytic one.
> Cleans up at low drive (a measurable cleanup point). XY curve a
> symmetric soft knee.
> **Validates:** even/odd separation, deep-negative even-to-odd ratio,
> knee detection, cleanup, and every summary claim the lexicon makes
> about symmetric circuits.

This position is the middle rung of the **even-order sensitivity
ladder** that settles the open even-order distance question — P2 at
≤ −96 dB re H1 (the floor), P3 at −85 (real but tiny), P4 at −65.5
(designed). That ladder, not a predicted zero, is what lets an
even-order claim on a real pedal be judged.

### P4 — Asymmetric Si clipper
As P3, but one diode up, two in series down (≈0.6 V vs ≈1.2 V).

> **Predicts:** H2 rises ~20 dB relative to P3 and overtakes H3 (the
> H2−H3 relationship swings ~25 dB). XY clip levels asymmetric with
> ratio ≈ 2:1 (±15%) — **not yet testable**, the transfer curve is
> hard-coded to E2 below the knee. Odd content still present but
> *weaker* than P3 at the same drive. Expect **no knee** alongside a
> valid cleanup point: asymmetric clipping compresses far less than
> symmetric clipping at matched THD.
> **Validates:** the asymmetry features, H2 bloom, the lexicon's
> asymmetric vocabulary, the even-harmonic audio illustrations.

P3 and P4 together are the cleanest possible A/B for the app's
asymmetry machinery — same topology, one diode different, one known
answer each.

---

## Stage E — power subsystem

Before either op-amp position.

- [ ] Two 9 V batteries in series. Junction = **ground / centre tap**.
      Free end of one = +9 V, free end of the other = −9 V.
- [ ] DPDT toggle breaking **both** rails.
- [ ] 100 nF from each rail to ground **at each IC socket**, short leads.
- [ ] Verify ±9 V at the sockets with the meter before inserting chips.
      Sockets are why you bought them — never solder these ICs in.

---

## Stage F — active positions

### P5 — Full-wave rectifier (the analytic gem)
TL072, standard two-op-amp precision absolute-value topology, your four
matched 10 k resistors plus two 1N4148 in the loops, ±9 V. Build from a
published reference schematic; the resistor *ratios* set the accuracy,
which is why they were selected.

> **Predicts:** output ≈ |x|. Fundamental strongly suppressed (limited
> by resistor matching; expect ≤ −35 dB re H2). **Even harmonics in
> ratios fixed by the |sin| Fourier series: H4/H2 = 1/5 (−14.0 dB),
> H6/H2 = 3/35 (−21.34 dB)** — essentially independent of diode
> parameters at moderate drive. Odd harmonics near the floor.
> **Expected app behaviour:** with the fundamental suppressed, THD
> "relative to H1" will be enormous and quality flags may fire. That is
> the honest reading of a frequency doubler and itself validates the
> flags. **Judge this position on H4/H2, H6/H2 AND THD** — the full
> even ladder predicts the reported THD to within the readout's own
> resolution, which makes P5 a validation of the THD summation itself.
> (An earlier version of this plan said to ignore THD here. Wrong.)
> **Validates:** harmonic-ratio accuracy — the hardware analogue of the
> Tier-1 polynomial exactness test.

### P6 — Crossover distortion
LM358 unity follower, ±9 V, output loaded **1 k** to ground to force
the class-B output stage into crossover. (The plan originally specified
10 k; at that value the handover sits at −1.2 V ≈ −15.7 dBFS and less
than 4 dB of the drive range lies above it. 1 k moves the handover to
−120 mV ≈ −35.7 dBFS and opens ~24 dB.)

> **Predicts — qualitatively only.** THD **rising as level falls** in
> the low-level region — the inverse of every clipper — with
> odd-dominant residue. Near-clean at high level. Everything numeric
> about this position is set by the LM358's internal output sink
> current, which TI's SLOA277 calls unreliable and which measured
> ≈120 µA against a 50 µA nominal. **P6 numbers are chip-specific
> empirical values, not box ground truth.** Handover is at
> V_out = −I_sink × R_L — note that this is *not* the zero crossing
> unless R_L is chosen to make it so.
> **Validates:** the distortion-vs-level machinery on a non-monotonic
> case, and pre-validates Addendum C's amp-mode crossover signature
> years before an amp exists.

P6 is also a live test of the **knee bound-guard issue** just filed: a
device that gets *cleaner* as you dig in has no conventional knee at
all, and the app should say so rather than fitting one.

---

## Stage G — app setup and the reference sweep

- [ ] Create pedal **"Reference Box v2"**. ControlLayout: one discrete
      control `CIRCUIT` with positions P1…P6 (use the panel names).
      Put the measured component values and each position's prediction
      in the pedal notes.
- [ ] Clean bare-cable loopback calibration; confirm the sanity check
      passes and the stamps read cable-shaped.
- [ ] Run a **full-suite sweep across all six positions** at the standard
      drive level, plus a gain journey at P3 and P6 (the level-dependent
      ones).
- [ ] Check each position against its prediction above. The sweep's
      pivot figure *is* the validation report.
- [ ] Name the sweep **"Reference 2026-08"** and keep it. (The library
      has no sweep-level title or notes field yet — issue filed. Until
      it does, the string goes in the *pedal's* Notes, phrased to name
      its target rather than to claim to be it.) This becomes
      the physical regression rig: after any DSP-affecting change,
      re-measure and compare via Compare distance. Expect ~1 dB for
      passive positions, ~2 dB for diode/op-amp ones (temperature moves
      junctions). Structural invariants — P3's H2 zero, P5's ratios,
      P6's inverse slope — must hold exactly regardless of drift.

Temperature note: diode thresholds move ≈ −2 mV/°C. Measure at
consistent room temperature (±5 °C) and don't chase fractional-dB drift
in P3–P5 absolute levels. **The ratios and zeros are the contract.**

---

## Stage H — play through it

The last stage of validation, not a distraction from it.

**Two things stand between a guitar and a usable signal through the
box.** P1–P4 present
~10 kΩ input impedance (the series resistor *is* the input impedance),
which is a brutal load for a pickup; and the diodes need ≈0.6 V to
clip, which a pickup rarely reaches. Fix both **outside the box** —
never add a buffer inside. Its electrical purity is the whole reason it
can validate anything.

- [ ] **Buffer + modest boost in front.** A buffered boost with its
      clipping diodes switched out is both at once: its input buffer
      gives the box a low-impedance source (the same source condition
      the interface provides, so the box is driven the way it was
      measured), and its gain stage supplies the level.
      - Keep the gain **low**. With the diodes switched out there is
        nothing left to clip but the supply rails, and a hard-clipped
        source contaminates every comparison downstream. Verify rather
        than assume: measure the boost with its diodes out and find the
        gain setting that keeps THD under ~1% at your playing level.
      - The tone stack is still in circuit, so it's a mid-voiced boost,
        not a flat one. Fine for listening; record it as part of the
        fixture if anything quantitative depends on it.
- [ ] **P6 needs no help** — its signal goes straight to the LM358's
      non-inverting input, so it's already megohms.

**What each position is, at the amp:** P1 an attenuator · P2 a dark
tone control · P3 the classic hard clipper (a series resistor into
antiparallel diodes to ground is the textbook clipping section of many
pedals) · P4 the same circuit with the common asymmetric modification ·
P5 an octave-up (rectification is the octave-fuzz principle, though this
one is glassier: an octave fuzz distorts *before* rectifying) · P6 a
badly biased class-B output stage, at its worst on note decays.

**Why this matters.** P3 versus P4 is a controlled A/B in which the only
difference is one diode, and the even-harmonic content is a *computed*
quantity rather than an estimate. Every adjective in the lexicon — warm,
aggressive, spitty, thick — can be tested against a device whose answer
was known before you plugged in. Real pedals can only calibrate words
against another measurement; this calibrates them against ground truth.
This is the stimulus the parked listening-study calibration has been
waiting for.

---

## What the box settles that nothing else can

| Open question | Position |
|---|---|
| Does phase compensation fully collapse a linear filter? | P2 |
| Is the even-order distance metric reporting noise? | P2 + P3 + P4 (the sensitivity ladder) |
| Does the asymmetry vocabulary track real asymmetry? | P3 vs P4 |
| Are harmonic ratios accurate in absolute terms? | P5 |
| Does the knee machinery handle inverse-slope devices? | P6 |
| What is the real THD floor of this rig? | P1 |
| Do the lexicon's adjectives track ground truth? | P3 vs P4, by ear |
