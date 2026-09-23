# Reference Box — Abra Electronics shopping list
*(Addendum E build, positions P1–P6; optional P7/P8 items separate.
"✔" = confirmed in Abra catalog; "☎" = call ahead / verify in store.)*

## Enclosure & hardware
- [ ] ✔ Hammond 1590B diecast enclosure, unpainted — **prefer 1590BB if stocked** (more room for rotary + 2×9V + perfboard)
- [ ] 2× 1/4" mono phone jacks, panel mount (Switchcraft-style, open frame)
- [ ] ☎ **2P6T rotary switch** (2-pole, 6-position; 2P8T also fine → enables P7/P8)
      — THE critical part; if absent: Digi-Key (e.g. Electroswitch C4D0806N-A) and buy everything else anyway
- [ ] 1× knob for rotary (any, but a pointer knob helps position labeling)
- [ ] Perfboard, ~5×7 cm
- [ ] Hookup wire (if low at home), heat-shrink assortment

## Resistors (1/4W metal film 1%, Abra SKU series `R1/4-<value>-1`)
- [ ] 10× 10k  (P2/P3/P4 series ×3; P5 ×6 — four hand-matched plus a parallel pair for the
      half-value leg; one spare. The P6 load is NOT one of these — see the 1k line)
- [ ] 2× 9.09k (fallback 9.1k — fine per spec)
- [ ] 2× 1k    (both used as built: P1 shunt 0.9987 kΩ, P6 load 0.9976 kΩ — the P6 load was
      originally specified as 10k; at 1k the crossover handover sits inside the drive range)
- [ ] 4× 1M   (bias/bleed)
- [ ] (optional P7): 2× 10k, 1× 1k, 1× 4.7k

## Capacitors
- [ ] 5× 10nF film (P2) — buy several, DMM-measure, use closest to nominal;
      record measured value for the f_c prediction
- [ ] 4× 10µF film or bipolar electrolytic (AC coupling; film preferred if size allows)
- [ ] 4× 100nF ceramic (op-amp supply bypass)

## Semiconductors
- [ ] ✔ 10× 1N4148 (need 7: P3 ×2, P4 ×3, P5 loops ×2 + spares)
- [ ] ☎ 1× TL072 DIP-8 (P5) — **substitute: 2× TL071** (confirmed carried), electrically identical, one extra socket
- [ ] ☎ 1× LM358 DIP-8 (P6 — must be LM358 specifically; its class-B output IS the crossover test)
- [ ] 3× DIP-8 IC sockets

## Power
- [ ] 2× 9V battery snap connectors
- [ ] 2× 9V batteries (if not on hand)
- [ ] 1× DPDT toggle (battery on/off; or switch power on the rotary's spare deck if 2P8T)
- [ ] Battery holder/clips or adhesive foam pad

## Notes
- P1 divider: 9.09k/1k nominal; as built 9.052 k / 0.9987 k → −20.06 dB unloaded,
  **−20.41 dB** loaded by the reference rig's ≈30 kΩ input (100 Ω source, 1 MΩ
  bleed in parallel). The loaded figure is the prediction; ratios are the contract.
- P2 corner: 1.59 kHz is the UNLOADED f_c of 10k + 10nF and is retired. Loaded by the
  reference rig's ≈30 kΩ input the cap sees (100 Ω + 10.013 k) ∥ 29.13 k = 7.51 k, so
  the as-built corner is **2121 Hz**; compute it from measured R, C and the load.
- Rotary must switch BOTH signal legs (both decks) so unselected circuits are
  fully out of path.
- Label panel positions P1–P6 (short names) — ControlLayout mirrors the panel.
