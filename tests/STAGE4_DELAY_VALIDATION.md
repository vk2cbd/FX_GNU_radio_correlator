# Stage 4 Differential Delay Validation

This procedure validates only the Stage 4 phase-slope / differential-delay estimator added after `cross_accum`.

Stage 4 has passed hardware validation on the authoritative Ubuntu GNU Radio 3.10.9.2 / UHD / Ettus B210 system.

## Scope

Stage 4 adds a low-rate Embedded Python estimator fed by the accumulated complex cross-spectrum:

```text
C01[k] = X0[k] * conj(X1[k])
```

No source astronomy, geometric delay, fringe stopping, delay correction, calibration, logging, or imaging is part of this stage.

## Current Accumulation Note

The current working flowgraph uses:

```text
accum_time = 0.01 s
samp_rate = 30.72e6
fft_size = 4096
fft_rate = 7500 FFT vectors/s
accum_frames = round(7500 * 0.01) = 75
```

The existing `accum_frames` comment in the GRC file still refers to the earlier 0.1 s / 750-frame default. That comment is stale, but the Stage 4 implementation does not change `accum_time` or `accum_frames`.

## Estimator Equations

The estimator receives each accumulated complex cross-spectrum vector `C`.

Because both FFT blocks use FFT Shift = True, construct the increasing B210 baseband/IF frequency-offset vector:

```python
f = (np.arange(fft_size) - fft_size/2) * samp_rate / fft_size
```

Fit against this increasing baseband/IF axis, not the displayed astronomical sky-frequency axis. The high-side LNB makes the displayed sky axis run in the opposite direction.

For each vector:

```python
phase = np.angle(C)
phase_unwrapped = np.unwrap(phase)
phase_unwrapped = slope * f + intercept
```

using linear least squares.

Then report:

```python
delay_seconds = slope / (2*pi)
differential_delay_ns = delay_seconds * 1e9
phase_slope_deg_per_MHz = slope * (180/pi) * 1e6
phase_fit = slope*f + intercept
phase_fit_rms_deg = sqrt(mean((phase_unwrapped-phase_fit)**2)) * 180/pi
```

## Hardware Results

The following measurements were made with a common broadband source and the Stage 4 estimator.

### Equal External Cables

```text
Phase slope = -0.031680 deg/MHz
Differential delay = -0.088001 ns
Phase fit RMS = 1.024064 deg
```

### 345 mm Added To RX0

```text
Phase slope = -0.672704 deg/MHz
Differential delay = -1.868621 ns
Phase fit RMS = 1.252698 deg
Delta from baseline = -1.780620 ns
```

### Same 345 mm Cable Added To RX1

```text
Phase slope = +0.593311 deg/MHz
Differential delay = +1.648085 ns
Phase fit RMS = 1.217607 deg
Delta from baseline = +1.736086 ns
```

## Confirmed Sign Convention

For:

```text
C01 = X0 * conj(X1)
```

extra physical/electrical delay in RX1 produces positive phase slope versus increasing IF/baseband frequency and positive reported differential delay.

Extra physical/electrical delay in RX0 produces negative phase slope versus increasing IF/baseband frequency and negative reported differential delay.

Do not silently compensate or invert this sign.

## Hardware Test

### A. Common Broadband Source

Feed one common broadband-noise source through a splitter into RX0 and RX1.

Ensure source level and all attenuation are safe for the B210 inputs.

### B. Baseline Reading

With no added known delay, record:

- differential delay, ns
- phase slope, deg/MHz
- phase-fit RMS, deg

Allow enough time for the number sinks to update and for readings to settle.

### C. Add Known Delay To RX1

Insert a known additional electrical delay into RX1.

Use an independently measured cable or delay line where practical. Record its expected delay in ns.

### D. Delayed Reading

With the added RX1 delay in place, record:

- differential delay, ns
- phase slope, deg/MHz
- phase-fit RMS, deg

### E. Delta Delay

Calculate:

```text
delta_delay = delay_after - delay_before
```

### F. Compare With Known Electrical Delay

Compare `delta_delay` with the independently known electrical delay of the inserted RX1 cable or delay line.

Record:

- expected inserted delay, ns
- measured `delay_before`, ns
- measured `delay_after`, ns
- measured `delta_delay`, ns
- phase-fit RMS before/after
- whether the fit is sufficiently linear for the test bandwidth

### G. Verify RX1 Sign

Verify experimentally whether additional RX1 delay produces positive measured delay, as expected for `C01 = X0 * conj(X1)`.

If the sign disagrees, document the result. Do not change the convention without explicit approval.

### H. Optional RX0 Sign Check

If practical, repeat the test with the same added delay in RX0 instead of RX1.

The expected result is the opposite sign relative to the RX1-added-delay test.

## Pass Criteria

Stage 4 passes when:

- the estimator runs only after `cross_accum`;
- the three number sinks update at low rate;
- common broadband injection produces a stable linear phase slope where SNR is adequate;
- inserted known delay is recovered within the expected measurement tolerance;
- RX1/RX0 sign behavior is experimentally documented.
