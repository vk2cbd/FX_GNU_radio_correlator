# Codex Task — Build Stage 1-3 Coherent FX Engine

Historical note: this file records the original Stage 1-3 build task. The current canonical GRC file has since advanced and is named `grc/fx_interferometer_v1_stage10.grc`.

## Goal
Create and validate the first GNU Radio Companion flowgraph for the FX interferometer described in `FX_CORRELATOR_SPEC.md`.

Target file:

`grc/fx_interferometer_v1_stage10.grc`

## Environment
- Ubuntu 24.04.4
- GNU Radio 3.10.9.2
- UHD / Ettus B210

Before editing, inspect the installed GNU Radio block definitions or existing local `.grc` files as needed so the generated YAML matches GNU Radio 3.10.9.2 exactly. Do not guess GRC block parameter names when they can be verified locally.

## Required variables
- `samp_rate = 30.72e6`
- `fft_size = 4096`
- `accum_time = 0.1`
- `fft_rate = samp_rate/fft_size`
- `accum_frames = int(round(fft_rate*accum_time))`
- `sky_cf = 4.800e9`
- `lnb_lo = 5.950e9`
- `if_cf = lnb_lo-sky_cf`
- `gain0`, `gain1` as conservative adjustable commissioning values

At defaults, verify:
- IF CF = 1.150 GHz
- FFT bin width = 7.5 kHz
- FFT rate = 7500 vectors/s
- `accum_frames = 750`

## UHD source
Use ONE UHD USRP Source with two receive stream channels `[0,1]`.

Requirements:
- complex float host samples
- wire format appropriate for B210, preferably `sc16`
- sample rate `samp_rate`
- both centre frequencies `if_cf`
- RX0 and RX1 gains separately adjustable
- external 10 MHz clock source
- internal time source for this one-B210 version
- RX0 represents antenna 0 / 2.4 m
- RX1 represents antenna 1 / 1.7 m

## Per-channel FFT paths
For each RX:

`UHD -> Stream to Vector(fft_size) -> forward FFT(fft_size, shifted, Blackman-Harris)`

Use identical processing on both channels.

## Auto spectra
For each FFT output:

`FFT -> Complex to Mag^2(vlen=fft_size) -> Integrate(decim=accum_frames, vlen=fft_size)`

Display the two auto spectra together in relative dB.

Do not perform absolute calibration yet.

## Cross spectrum
Build:

`C01[k] = X0[k] * conj(X1[k])`

Use the GNU Radio vector-capable Multiply Conjugate block if available in this installed version.

Then:

`cross -> Integrate(decim=accum_frames, vlen=fft_size)`

Branch the accumulated complex cross spectrum to:

1. magnitude -> relative dB -> QT vector display
2. phase/arg -> degrees -> QT vector display with roughly -180..+180 deg range

## Frequency axis
All user-facing displays should represent sky frequency.

High-side LNB mapping:

`f_sky = f_LO - f_IF`

Because this reverses frequency orientation, first make the frequency labels mathematically correct. Do not alter the coherent science path solely to make the display ascend left-to-right. A display-only reversal may be added later.

## Explicit exclusions
Do NOT add yet:
- source catalogue
- RA/Dec
- Az/El
- geometric delay
- delay correction
- fringe stopping
- rho
- CSV/HDF5 logging
- calibration
- imaging
- custom OOT modules

## Validation
Run GRC validation and `grcc` if available.

If hardware is present, run the generated graph and check for UHD overflow messages.

Report:
1. exact block IDs/classes used
2. any GNU Radio 3.10.9.2 compatibility changes made
3. whether `grcc` succeeds
4. whether the graph starts with the B210
5. any UHD overflows at 30.72 MS/s per channel
6. any assumptions still requiring hardware verification

Do not proceed into astronomy geometry or fringe stopping until the Stage 1-3 graph is validated.
