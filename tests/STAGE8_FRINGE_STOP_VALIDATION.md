# Stage 8 Fringe Stop Validation

## Purpose

Stage 8 takes the Stage-7 delay-slope-corrected complex spectrum and creates
two simultaneous scalar complex visibility streams:

- `V_unstopped`
- `V_stopped`

Stage 8 may combine frequency channels. It must not implement selectable
temporal coherent integration, logging, calibration, rho, or imaging.

## Relation To Stage 7

Stage 7 outputs:

```text
C7[k] = delay-corrected C01[k]
```

Stage 7 removes frequency-dependent phase slope and preserves the centre-bin
phase. Stage 8 begins after `delay_slope_corrector` and does not change the
Stage-7 equation.

## Broadband Visibility

The broadband unstopped visibility is a coherent complex mean:

```text
V_unstopped = (1/N_used) * sum(C7[k] for k in usable bins)
```

Do not average magnitudes or phases separately.

## Visibility Edge Exclusion

Stage 8 uses a separate parameter:

```text
visibility_edge_exclude_pct = 20.0
```

At `fft_size = 4096`, this excludes:

```text
n_edge = int(4096 * 20.0 / 100.0) = 819 bins from each end
N_used = 4096 - 2*819 = 2458 bins
```

This parameter is independent of `phase_fit_edge_exclude_pct`, which belongs
to the delay-estimator diagnostics.

## Geometry Convention

Stage 6 defines:

```text
tau_g = dot(B01, s) / c
phi_geo = 2*pi*sky_cf*tau_g
```

Stage 8 uses Stage-6 output 3, the geometric delay `tau_g` in ns.

Stage 8 does not use output 4, `RX1-RX0 Arrival`. Output 4 is used by Stage 7
for delay-slope correction.

## Fringe Stop Equation

Default sign:

```text
fringe_stop_sign = -1
```

General rotation:

```text
rotation = exp(j * fringe_stop_sign * 2*pi * sky_cf * tau_g_s)
```

Default operational equation:

```text
V_stopped = V_unstopped * exp(-j * 2*pi * sky_cf * tau_g_s)
```

The reverse sign option `+1` is present only as a commissioning check.

## Bypass Behaviour

When `fringe_stop_enable = False`:

```text
V_stopped = V_unstopped
```

If `tau_g` is NaN or inf, the block safely bypasses fringe stopping for that
sample rather than emitting invalid complex values.

## Absolute Phase

Do not expect stopped phase to be zero.

Even with correct fringe stopping, stopped phase may contain receiver phase,
source phase, residual bandpass phase, baseline errors, atmosphere, multipath,
or other calibration terms.

Stage 8 success is primarily reduced phase rate, not zero absolute phase.

## Geometry Cadence Caveat

Stage 5 currently refreshes astronomy coordinates approximately once per
second, so Stage 6 `tau_g` may update at that cadence while visibility samples
arrive faster.

This can leave a small piecewise-constant residual phase. Do not redesign the
astronomy engine in Stage 8 solely to address this. Faster interpolation or
prediction is a separate reviewed refinement.

## Deterministic Tests

Run:

```bash
python -m unittest tests.test_stage8_fringe_stopping
```

The tests verify:

- complex broadband mean preserves phase;
- edge exclusion removes deliberately corrupted band edges;
- invalid visibility edge percentages are handled safely;
- positive and negative `tau_g` stop correctly with default sign;
- fringe stopping preserves magnitude;
- bypass and invalid geometry are safe;
- reverse sign does not flatten the normal convention;
- synthetic time-varying fringes are flattened by the default sign;
- Stage 8 uses `baseline_geometry_engine` output 3, not output 4;
- existing pre-Stage-8 block coordinates are unchanged.

## Ubuntu GRC Validation

On the Ubuntu GNU Radio 3.10.9.2 system:

```bash
cd ~/GNU_Radio/FX_GNU_radio_correlator
git checkout stage1-3-fx-engine
git pull origin stage1-3-fx-engine
gnuradio-companion grc/fx_interferometer_v1_stage9.grc
```

Confirm the flowgraph opens without GRC errors and contains:

- `visibility_edge_exclude_pct`
- `visibility_rate`
- `Fringe Stop`
- `Fringe Stop Sign`
- `Broadband Visibility Combiner`
- `Fringe Stop Corrector`
- `Stage 8 - Visibility I/Q`
- `Stage 8 - Visibility Phase`
- `Stage 8 / Visibility Scalars`

Generate/run the flowgraph in GNU Radio Companion on Ubuntu. Windows-side YAML
parsing is not GNU Radio validation.

## Astronomical Commissioning

Initial settings:

```text
Delay Correction = Enabled
Instrument Delay = current measured value, or 0.0 for geometric-only testing
Fringe Stop = Enabled
Fringe Stop Sign = Normal (-phi_geo)
visibility_edge_exclude_pct = 20.0
```

Observe a strong unobstructed source, initially the Sun.

Record simultaneously:

- UTC, HA, Az, El
- Stage-6 `tau_g`
- Stage-6 geometric phase
- Stage-6 fringe rate and period
- raw Stage-4 delay
- Stage-7 corrected delay
- `V_unstopped` I/Q, amplitude, phase
- `V_stopped` I/Q, amplitude, phase

Expected behaviour:

- unstopped phase rotates at approximately `360 * fringe_rate_hz` deg/s;
- stopped phase changes much more slowly;
- `abs(V_stopped) ~= abs(V_unstopped)`;
- reverse sign generally makes phase motion worse or about doubles the
  geometric phase rate.

## Pass / Fail Criteria

Pass requires:

- GRC opens/generates on Ubuntu GNU Radio 3.10.9.2;
- all Stage 1-7 paths remain present;
- `V_unstopped` and `V_stopped` are simultaneous separate streams;
- Stage 8 uses Stage-6 `tau_g` output 3;
- default sign is Normal `(-phi_geo)`;
- stopped phase rate is substantially reduced relative to unstopped phase;
- fringe stopping does not change amplitude except for floating-point error;
- no Stage-9 temporal integration, stability advisor, logging, calibration,
  rho, imaging, or OOT migration has been added.

## Real-System Acceptance Note

Stage 8 primary fringe-stop acceptance passed on a Moon observation.

The commissioning A/B/C test showed:

- Normal `(-phi_geo)`: stopped phase became nearly stationary while the
  unstopped visibility continued to fringe.
- Reverse `(+phi_geo)`: stopped phase rotated substantially faster, matching
  the expected wrong-sign behaviour.
- Bypass: stopped and unstopped phase traces coincided.

Amplitude preservation was also observed. Example commissioning values showed
`abs(V_unstopped)` and `abs(V_stopped)` equal within numerical precision.

A small repetitive sawtooth-like stopped-phase structure was observed while
piecewise antenna tracking was active. The structure disappeared when tracking
was stopped, so it is currently treated as tracking/mount/pointing related
rather than a Stage-8 fringe-stop sign error.
