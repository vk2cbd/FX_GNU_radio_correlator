# FX Interferometer

GNU Radio FX radio interferometer for radio astronomy.

## Current target
Stage 1-3 coherent two-channel FX engine using one Ettus B210:

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

## First milestone
Create `grc/fx_interferometer_v1_stage1_3.grc` containing:

1. one UHD USRP Source with channels `[0,1]`
2. Stream-to-Vector on each RX
3. 4096-point shifted Blackman-Harris FFT on each RX
4. auto spectra `|X0|^2`, `|X1|^2`
5. complex cross spectrum `X0 * conj(X1)`
6. 0.1 s vector accumulation
7. two auto-spectrum display traces
8. cross-spectrum magnitude display
9. cross-spectrum phase display

Do not add astronomy geometry, fringe stopping, calibration or logging until this engine passes coherent-source and known-delay tests.
