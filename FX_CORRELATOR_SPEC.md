# FX Radio Interferometer — Version 1.0 Specification

## 1. Purpose
Implement a two-element radio astronomy FX interferometer using one Ettus B210, with a design that can later scale to multiple antennas and multiple B210 SDRs.

Version 1 shall:
- receive two antenna signals simultaneously;
- display both antenna spectra;
- calculate and display complex cross-spectrum amplitude and phase;
- generate unstopped and fringe-stopped complex interferograms;
- implement frequency-domain geometric/instrumental delay correction;
- support selectable coherent integration;
- calculate normalized complex correlation coefficient rho;
- optionally record visibilities and spectra, both default OFF;
- permit observing without calibration;
- support later instrumental and flux calibration;
- produce data suitable for 1-D imaging first, with 2-D synthesis compatibility retained.

## 2. Platform
- Ubuntu 24.04.4
- GNU Radio 3.10.9.2
- Ettus B210
- One B210, dual receive channels for Version 1

## 3. Antennas and baseline
- Antenna 0: 2.4 m dish, B210 RX0
- Antenna 1: 1.7 m dish, B210 RX1
- Current working baseline B01 = r1 - r0 in ENU metres:
  - E = -5.785 m
  - N = +0.095 m
  - U = +0.580 m
- Antenna 0 is east of antenna 1 and lower than antenna 1.
- E and U are physically measured baseline components.
- N = +0.095 m is the current astronomically refined / working north component derived from Stage-6 validation.
- Baseline magnitude is approximately 5.814779 m.
- Maximum possible absolute geometric delay is approximately 19.396 ns.
- Surveyed baseline shall be represented as E/N/U in metres
- Baseline convention: B01 = r1 - r0

## 4. Frequency plan
- Nominal sky centre frequency: 4.800 GHz
- LNB LO: 5.950 GHz, high-side
- Nominal IF centre frequency: 1.150 GHz
- Relationship: f_IF = f_LO - f_sky
- High-side conversion causes spectral inversion
- Operator-facing plots shall use sky frequency

## 5. Timing and references
- B210 clock source: external 10 MHz GPS-disciplined reference
- LNB local oscillators referenced to common 10 MHz
- No PPS required for one-B210 Version 1
- Future multi-B210 operation should use common 10 MHz + PPS
- Observation timestamps shall be UTC

## 6. Sampling
- Target sample rate: 30.72 MS/s per RX channel
- Both receive channels use identical sample rate and IF centre frequency
- Gains remain independently adjustable
- First acceptance test: continuous dual-channel 30.72 MS/s streaming without UHD overflow

## 7. FX convention
For FFT outputs X0[k], X1[k]:
- P0[k] = |X0[k]|^2
- P1[k] = |X1[k]|^2
- C01[k] = X0[k] * conj(X1[k])

This cross-product sign convention shall be kept fixed through all later processing.

## 8. FFT
Default:
- FFT size: 4096
- Sample rate: 30.72 MS/s
- Bin spacing: 7.5 kHz
- Non-overlapping FFT frames
- Initial window: Blackman-Harris

FFT size shall be selected from a dropdown, not a free-form entry. Initial choices:
- 2048
- 4096
- 8192
- 16384
- 32768

FFT-size changes may require graph restart.

## 9. First-stage accumulation
At 30.72 MS/s and FFT=4096:
- FFT frame rate = 7500 frames/s
- initial accumulation time = 0.1 s
- initial accumulation length = 750 FFT frames
- custom astronomy processing therefore receives approximately 10 updates/s

High-rate DSP shall remain in standard compiled GNU Radio blocks.

## 10. Bandwidth
- Correlated bandwidth is configurable and centred on the IF centre frequency
- Default is maximum available sampled bandwidth
- Initial preset choices may include 5, 10, 15, 20, 25, maximum MHz
- No RFI masking required in Version 1

## 11. Geometry
The astronomy subsystem shall compute from UTC, site coordinates, source RA/Dec and baseline ENU:
- LMST
- hour angle
- azimuth
- elevation
- geometric delay tau_g = (B dot s) / c
- predicted fringe phase/rate/period
- u/v/w

## 12. Delay correction
Frequency-dependent geometric and instrumental delay correction shall occur in the FX domain before broadband summation.

Instrumental delay is maintained separately from geometric delay.

## 13. Unstopped visibility
The displayed unstopped interferogram shall:
- have wideband phase-slope/delay correction applied;
- retain the time-varying centre-frequency astronomical fringe.

It is therefore a coherent wideband visibility, not a naive sum of an uncorrected cross-spectrum.

## 14. Fringe-stopped visibility
After delay-slope correction and coherent channel summation, centre-frequency geometric fringe phase shall be removed.

Both unstopped and fringe-stopped complex visibility streams shall be retained simultaneously.

A commissioning-time sign control may be used until the exact practical sign convention is verified with real data.

## 15. Visibility integration
Initial selectable coherent integration times:
- 0.1 s
- 0.25 s
- 0.5 s
- 1 s
- 2 s
- 5 s
- 10 s
- 20 s
- 30 s
- 60 s

Integration is runtime-selectable.

## 16. Phase stability advisor
Estimate residual phase rate from fringe-stopped visibility where SNR permits.

For constant residual phase rate dphi/dt, coherence estimate:
eta = | sin((dphi/dt) T / 2) / ((dphi/dt) T / 2) |

Display:
- residual phase rate
- current integration
- estimated coherence
- recommended maximum integration

Advisory only in Version 1.

## 17. Normalized correlation
Calculate complex normalized correlation coefficient:

rho = <x0 x1*> / sqrt(<|x0|^2><|x1|^2>)

Retain:
- rho_real
- rho_imag
- rho_amplitude
- rho_phase

## 18. Calibration states
Observing shall not require calibration.

Three states:
1. Uncalibrated
2. Instrument calibrated
3. Flux calibrated

Uncalibrated operation still provides spectra, cross-spectrum, geometric correction, fringe stopping and rho.

## 19. Instrument calibration
Preferred future hardware:
- one common broadband noise source
- split into the two low-coupling waveguide injection points

Calibration sequence:
1. Noise OFF
2. Noise ON
3. ON-OFF correlated spectrum
4. fit phase slope
5. estimate instrumental delay
6. determine residual complex bandpass
7. save calibration

Astronomical-source calibration shall also remain possible.

## 20. Absolute calibration
Framework shall support per-antenna:
- Tsys
- aperture efficiency
- effective area
- SEFD

Ultimately provide calibrated complex visibility in Jy while retaining rho.

## 21. Source catalogue
Correlator has its own source selector and does not depend on the antenna-control program in Version 1.

Required catalogue fields:
- source name
- RA decimal hours
- Dec decimal degrees
- nominal flux Jy near 4800 MHz

Existing source catalogue may be read but shall be treated as read-only by the correlator.

## 22. GUI
Initial controls:
- observation name
- source selector
- sky centre frequency
- bandwidth preset
- FFT-size dropdown
- integration dropdown
- history dropdown
- unstopped/stopped display selector
- fringe-stop enable
- delay-correction enable
- visibility recording enable
- spectrum recording enable
- calibration status
- start/stop recording

Recording defaults OFF.

Displays:
- two auto-spectra, relative dB, sky-frequency axis
- cross-spectrum magnitude versus sky frequency
- cross-spectrum phase versus sky frequency
- selectable complex interferogram (unstopped/stopped), I and Q
- numerical amplitude and phase

History choices:
- 1, 5, 15, 30 min
- 1, 2, 4 h

## 23. Logging
Visibility logging:
- optional, default OFF
- FITS-IDI primary scientific visibility recording
- one row per integrated Stage-9 fringe-stopped visibility

Fields shall include at least:
- UTC
- observation
- source
- RA/Dec
- Az/El
- hour angle / LMST
- RF centre frequency
- bandwidth
- FFT size
- integration
- antenna IDs
- baseline ENU
- u/v/w
- broadband powers
- unstopped complex visibility
- stopped complex visibility
- rho
- Jy visibility where calibrated
- calibration state
- residual phase rate where available

CSV visibility output is not the primary scientific archive for Stage 10.
CSV may be produced only as an optional diagnostic sidecar for human inspection
and validation.

Spectral logging:
- optional, default OFF
- HDF5 preferred
- independent cadence: 1, 5, 10, 30, 60 s
- store frequency axis, P0, P1, raw cross-spectrum, corrected cross-spectrum and timestamps

## 24. Implementation rule
Keep high-rate processing in standard compiled GNU Radio blocks:
- UHD source
- stream-to-vector
- FFT
- magnitude-squared
- multiply-conjugate
- first-stage accumulation

Only after rate reduction to roughly 10 updates/s should astronomy-specific Python blocks be used.

## 25. Initial custom blocks (later stages)
Likely Embedded Python blocks:
- astronomy geometry / visibility corrector
- runtime visibility integrator
- phase-stability monitor
- FITS-IDI visibility recorder with optional diagnostic CSV sidecar
- spectral HDF5 logger

Migrate to an OOT module only after behaviour is stable and tested.

## 26. First build milestone: Stage 1-3 coherent FX engine
Build only:
- one dual-channel UHD USRP Source
- two Stream-to-Vector blocks
- two FFT blocks
- two auto-power paths
- one X0*conj(X1) cross-product path
- 0.1 s accumulation
- auto-spectrum display
- cross-spectrum magnitude display
- cross-spectrum phase display

Do NOT initially add:
- catalogue
- geometry
- delay correction
- fringe stopping
- rho
- logging
- calibration
- imaging

## 27. Stage 1-3 default values
- samp_rate = 30.72e6
- fft_size = 4096
- accum_time = 0.1
- fft_rate = samp_rate / fft_size = 7500
- accum_frames = 750
- sky_cf = 4.800e9
- lnb_lo = 5.950e9
- if_cf = 1.150e9
- initial gain0/gain1 = conservative commissioning values, adjustable
- UHD stream channels = [0,1]
- clock source = external
- time source = internal

## 28. Stage 1-3 validation
1. Confirm dual-channel continuous streaming with no UHD overflows.
2. Confirm sensible auto-spectra on both channels.
3. Confirm correct sky-frequency orientation accounting for high-side spectral inversion.
4. Feed a common coherent/test source into both chains.
5. Confirm strong cross-spectrum magnitude and stable relative phase.
6. Introduce a known differential electrical delay.
7. Confirm resulting cross-spectrum phase slope and recover delay from dphi/df.

Only after these tests pass should astronomical geometry and fringe stopping be added.

## 29. Future scalability
Use antenna IDs rather than permanent East/West naming.

For future four-antenna operation, data model shall support six baselines and common 10 MHz + PPS synchronisation.

Sequential-baseline observations may also be combined later if calibration and metadata are sufficient.
