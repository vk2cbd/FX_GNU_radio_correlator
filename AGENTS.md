# AGENTS.md — FX Interferometer Development Rules

## Authoritative specification
Read `FX_CORRELATOR_SPEC.md` before making architectural or DSP changes.

If implementation details conflict with the specification, stop and report the conflict rather than silently changing the design.

## Current milestone
The current task is Stage 1-3 only: prove a stable, coherent two-channel FX engine using one Ettus B210.

Do not implement astronomy geometry, delay correction, fringe stopping, calibration, logging, imaging or OOT modules until Stage 1-3 validation passes.

## Target environment
- Ubuntu 24.04.4
- GNU Radio 3.10.9.2
- Ettus B210 / UHD

Prefer compatibility with the installed local GNU Radio version over assumptions from newer online documentation.

## Core signal conventions
- RX0 = antenna 0 = 2.4 m dish
- RX1 = antenna 1 = 1.7 m dish
- Baseline convention for later stages: B01 = r1 - r0
- Cross-spectrum convention: C01[k] = X0[k] * conj(X1[k])
- Nominal sky centre frequency = 4.800 GHz
- LNB LO = 5.950 GHz, high-side
- Nominal IF centre frequency = 1.150 GHz
- High-side conversion spectrally inverts sky frequency relative to IF/baseband

Do not change these conventions without explicit approval.

## Performance rule
Keep 30.72 MS/s processing in compiled GNU Radio blocks wherever practical.

Do not put per-sample or per-FFT-frame 30.72 MS/s work into Embedded Python.

Only use custom Python after initial FX accumulation has reduced the rate to approximately 10 updates/s, unless profiling demonstrates a safe alternative.

## Stage 1-3 defaults
- samp_rate = 30.72e6
- fft_size = 4096
- accum_time = 0.1
- FFT frame rate = 7500/s
- accum_frames = 750
- non-overlapping FFT frames
- Blackman-Harris window initially
- one UHD Source with stream channels [0,1]
- external 10 MHz clock
- internal time source for one-B210 Version 1

## GRC editing
When creating or modifying `.grc` YAML:
1. Inspect installed GNU Radio/GRC block definitions or a known-good local `.grc` file.
2. Do not guess block IDs or parameter names if they can be checked locally.
3. Run GRC validation / `grcc` after changes where available.
4. Keep the graph visually readable and label major signal paths.
5. Do not edit generated `.py` as the source of truth when a `.grc` file owns that code.

## Verification discipline
For every material DSP change:
- state the expected mathematical result;
- identify the relevant sign/unit convention;
- run a deterministic software test when possible;
- distinguish software validation from B210 hardware validation.

Known-delay phase-slope testing is mandatory before astronomical delay correction is implemented.

## Data safety
Do not commit large IQ captures, observation data or calibration datasets to Git by default.

## Change scope
Prefer small, reviewable commits corresponding to one milestone or one validated fix.
Do not refactor unrelated code while solving a focused problem.
