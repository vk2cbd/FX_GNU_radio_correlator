# Stage 7 Delay-Slope Correction Validation

## Purpose

Stage 7 adds a parallel frequency-domain correction branch after `cross_accum`.
It removes the wideband phase slope caused by geometric delay and an optional
static instrumental delay.

Stage 7 does not fringe-stop. It must preserve the centre-frequency
astronomical fringe.

## Fixed Conventions

- RX0 = antenna 0 = 2.4 m dish.
- RX1 = antenna 1 = 1.7 m dish.
- Baseline convention: `B01 = r1 - r0`.
- Cross-spectrum convention: `C01[k] = X0[k] * conj(X1[k])`.
- Positive measured differential delay means RX1 is delayed relative to RX0.
- Positive RX1 delay produces positive phase slope versus increasing B210
  baseband/IF frequency.

## Stage 6 Arrival-Delay Input

Stage 6 computes:

```text
tau_g = dot(B01, s) / c
```

The literal astronomical arrival delay is:

```text
RX1-RX0 Arrival = -tau_g
```

Stage 7 uses the existing Stage 6 `RX1-RX0 Arrival` output directly.

## Frequency Vector

The correction uses increasing shifted B210 baseband/IF offset frequency:

```text
f_bb[k] = (k - fft_size/2) * samp_rate / fft_size
```

It does not use the operator-facing descending sky-frequency axis. The sky
axis is reversed by the high-side LNB and is for display only.

## Correction Equation

The total delay applied is:

```text
tau_apply_ns = RX1_minus_RX0_arrival_ns + instrument_delay_ns
tau_apply_s  = tau_apply_ns * 1e-9
```

The Stage 7 corrected cross-spectrum is:

```text
C01_corrected[k] =
    C01_raw[k] * exp(-j * 2*pi * f_bb[k] * tau_apply_s)
```

The negative exponential sign removes the positive phase slope produced by a
positive RX1-relative delay.

## Centre-Bin Preservation

At the centre FFT bin:

```text
f_bb[fft_size/2] = 0
rotation = 1
C01_corrected[centre] = C01_raw[centre]
```

This is the key check that Stage 7 has not become fringe stopping.

## Deterministic Software Tests

Run on the development machine:

```bash
python -m unittest tests.test_stage7_delay_correction
```

The tests verify:

- positive synthetic delay is removed;
- negative synthetic delay is removed;
- geometric plus instrumental delay are summed with the documented sign;
- magnitude is preserved;
- the centre FFT bin is unchanged;
- bypass mode returns the raw input;
- invalid geometry delay safely bypasses;
- the implemented sign is `exp(-j*2*pi*f_bb*tau)`;
- Stage 1-6 raw paths remain present in the canonical GRC.

## Ubuntu GRC Validation

On the Ubuntu GNU Radio 3.10.9.2 system:

```bash
cd ~/GNU_Radio/FX_GNU_radio_correlator
git checkout stage1-3-fx-engine
git pull origin stage1-3-fx-engine
gnuradio-companion grc/fx_interferometer_v1_stage9.grc
```

Confirm the flowgraph opens without GRC errors and contains:

- `Delay Correction` runtime enable/bypass control;
- `Instrument Delay (ns)` operator entry;
- `Delay Slope Corrector`;
- `Stage 7 - Delay-Corrected Cross Phase` display;
- corrected differential delay, phase slope, and phase-fit RMS number sinks.

Generate the flowgraph in GRC or run the local project generation workflow.
Do not treat Windows-side parsing as GNU Radio validation.

## Astronomical Commissioning

Initial settings:

```text
delay_correction_enable = True
instrument_delay_ns = 0.0
```

Observe the Sun and compare simultaneously:

- raw Stage 4 delay;
- Stage 6 `RX1-RX0 Arrival`;
- Stage 7 corrected delay;
- raw cross-phase spectrum;
- corrected cross-phase spectrum;
- corrected phase-fit RMS.

Expected first-order relationship:

```text
Stage7_corrected_delay ~= raw_Stage4_delay - Stage6_arrival_delay
```

Example:

```text
raw delay     = -12.242200 ns
arrival delay = -10.442077 ns

corrected delay ~= -1.800123 ns
```

The corrected phase spectrum should be flatter than the raw phase spectrum.
The cross-spectrum magnitude should remain unchanged.
The centre-frequency phase should remain unchanged and continue to fringe
with time.

## Instrumental Delay Commissioning

After the zero-instrument-delay test passes, enter a contemporaneously measured
instrument delay.

For example, if measurements indicate:

```text
instrument_delay_ns = -1.8
```

then the corrected Stage-4-style delay should move closer to zero.

Do not assume `-1.8 ns` permanently.

## Pass / Fail Criteria

Pass requires:

- GRC opens/generates on Ubuntu GNU Radio 3.10.9.2;
- raw Stage 1-6 displays and estimators still operate;
- delay correction can be enabled and bypassed at runtime;
- corrected phase display is available simultaneously with raw phase display;
- corrected delay diagnostic is available simultaneously with raw delay;
- corrected delay follows the expected sign and magnitude relationship;
- centre-frequency phase is not removed;
- no Stage 8 fringe stopping, channel summation, long integration, logging,
  calibration, or imaging has been introduced.
