# PedalScope measurement libraries

Measurement libraries for [PedalScope](https://pedalscope.com), the macOS
instrument that measures how guitar pedals distort. Each library is a real
device, measured under stated conditions and exported from the shipping
build exactly as measured — nothing idealised, nothing cleaned up, no record
re-taken because a nicer one was wanted.

**This repository holds no measurement data in git.** Every library is a
release asset: open the [Releases](../../releases) page, download the zip
for the set you want, unzip it, and double-click the `.pedalscope` file
inside. PedalScope opens it (free tier included — importing needs no
purchase) and reports what arrived. Each release's notes carry the set's
SHA-256, its contents, the rig it was measured on, and how to check the
download.

The index of published sets, with the arithmetic each one was checked
against, is at **https://pedalscope.com/library.html**.

## Naming

- Tag: `library-<set>-<YYYY-MM-DD>` — the set and its capture date.
- Asset: `PedalScope-<Set>-<YYYY-MM-DD>.zip`.

A published set is permanent. A later capture of the same device is
published under a new dated name and arrives in PedalScope as a separate
pedal, so two generations compare cleanly instead of interleaving.

## Licence

The measurement libraries in this repository's releases are licensed under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE):
use them, share them, build on them, with attribution to PedalScope. The
PedalScope name and mark are not part of the grant.
