# FX Interferometer

GNU Radio FX radio interferometer for radio astronomy.

## Current target
Stage 10 UVFITS visibility recording for the single-B210 FX interferometer:

- Ubuntu 24.04.4
- GNU Radio 3.10.9.2
- B210 RX0 = 2.4 m dish
- B210 RX1 = 1.7 m dish
- external common 10 MHz reference
- nominal sky CF = 4.800 GHz
- high-side LNB LO = 5.950 GHz
- nominal IF CF = 1.150 GHz
- target sample rate = 30.72 MS/s per channel
- default FFT = 4096
- cross-product convention = X0 * conj(X1)

See `FX_CORRELATOR_SPEC.md` for the authoritative design.

## Development principle
Do high-rate DSP in standard compiled GNU Radio blocks. Only move into custom Python after the FX spectra have been accumulated to roughly 10 updates/s.

## Current flowgraph
The canonical GNU Radio Companion source is:

`grc/fx_interferometer_v1_stage10.grc`

It now contains the staged Version 1 chain:

1. one UHD USRP Source with channels `[0,1]`
2. Stream-to-Vector on each RX
3. 4096-point shifted Blackman-Harris FFT on each RX
4. auto spectra `|X0|^2`, `|X1|^2`
5. complex cross spectrum `X0 * conj(X1)`
6. 0.1 s vector accumulation
7. astronomy coordinates and surveyed-baseline geometry
8. delay-slope correction and fringe stopping
9. coherent visibility integration and phase-stability advisory displays
10. optional Stage-10 UVFITS recording of integrated stopped visibility

Recording defaults OFF. Do not add calibration solving, rho, imaging, multi-B210 support, or Stage 11+ behaviour until Stage 10 is validated.
