# Stage 9 Integration And Stability Validation

## Purpose

Stage 9 adds low-rate processing after Stage-8 fringe stopping:

- selectable non-overlapping coherent temporal integration;
- measured window coherence retained;
- residual phase-rate and rate-based coherence advisor.

The advisor is informational only. It must not change integration time,
fringe-stop sign, baseline ENU, delay correction, or antenna tracking.

## Native Input

The Stage-9 input is native Stage-8 `V_stopped` from:

```text
fringe_stop_corrector output 0
```

Stage 9 does not consume `V_unstopped` and does not integrate before fringe
stopping.

## Integration-Time Selector

Runtime operator control:

```text
Coherent Integration
```

Choices:

```text
0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60 s
```

Default:

```text
integration_time_s = 1.0
```

## Sample Quantisation

Native visibility rate:

```text
visibility_rate = fft_rate / accum_frames
```

Integration sample count:

```text
N_int = max(1, floor(integration_time_s * visibility_rate + 0.5))
```

This is nearest-integer half-up rounding, not Python banker's rounding.

Effective integration:

```text
T_eff = N_int / visibility_rate
```

Requested and effective integration are both displayed. For example, at
`visibility_rate = 10 Hz`, a requested `0.25 s` becomes `N_int = 3` and
`T_eff = 0.3 s`.

## Non-Overlapping Coherent Integration

For native stopped samples `V_s[n]`, Stage 9 outputs:

```text
V_int[m] = (1/N_int) * sum(V_s[n])
```

over complete, non-overlapping windows. Incomplete windows are not emitted.

Runtime integration-time changes reset the current partial window so samples
from different settings are not mixed.

If a native visibility sample is NaN or inf in either I or Q, the current
partial window is reset and no mixed scientific output is emitted.

Integrated output rate:

```text
integrated_visibility_rate = visibility_rate / N_int
```

## Measured Window Coherence

For every completed integration window:

```text
eta_measured = abs(sum(V_s[n])) / sum(abs(V_s[n]))
```

Displayed as:

```text
Window Coherence Retained (%) = 100 * eta_measured
```

This is not `rho`.

## Residual Phase-Rate Fit

The phase-stability advisor consumes native `V_stopped` before integration.

It keeps the most recent:

```text
M = max(3, floor(phase_rate_fit_window_s * visibility_rate + 0.5))
```

samples, unwraps:

```text
phi[n] = unwrap(angle(V_s[n]))
```

and fits:

```text
phi[n] = phi_0 + omega_res * t[n]
```

with centred relative sample times:

```text
t[n] = n / visibility_rate
```

The reported rate is:

```text
residual_phase_rate_deg_s = omega_res * 180/pi
```

The residual fit RMS is displayed in degrees.

Before enough history exists, rate, RMS, rate-based coherence, and recommended
maximum integration are reported as NaN.

## Rate-Based Coherence

For constant residual phase rate:

```text
eta_rate = abs(sin(omega_res*T_eff/2) / (omega_res*T_eff/2))
```

For near-zero argument, `eta_rate = 1`.

Displayed as:

```text
Rate-Based Coherence (%) = 100 * eta_rate
```

This estimate assumes constant phase drift. It does not fully describe
tracking sawtooth, phase jumps, jitter, atmosphere, multipath, or non-linear
phase disturbances.

## Recommended Maximum Integration

Default coherence target:

```text
coherence_target_pct = 95.0
```

For 95% coherence:

```text
sin(x)/x = 0.95
x ~= 0.551910979
```

So the total phase rotation limit is approximately:

```text
2*x ~= 1.103821957 rad ~= 63.25 deg
```

The recommended maximum integration is:

```text
T_max = min(60.0, 2*x/abs(omega_res))
```

For effectively zero residual rate, `T_max = 60.0 s`.

## Tracking Sawtooth Context

Stage-8 Moon/Sun commissioning found a small repetitive stopped-phase
disturbance correlated with piecewise antenna tracking. It disappeared when
tracking was stopped.

Stage 9 measures the effect on coherence. It does not control tracking or
modify geometry to hide the effect.

## Deterministic Tests

Run:

```bash
python -m unittest tests.test_stage9_integration_stability
```

The tests verify:

- constant complex visibility integrates without amplitude/phase loss;
- science windows are non-overlapping;
- integration is a complex mean;
- half-up sample quantisation is used;
- runtime integration changes reset partial windows;
- invalid samples reset partial windows;
- known residual phase rates are estimated correctly;
- phase wrap crossings are unwrapped before fitting;
- rate-based coherence uses the sinc equation;
- 95% recommended-time calculation uses the correct root;
- measured window coherence matches direct calculation;
- unstopped fringes lose amplitude when integrated while stopped constants do
  not;
- advisor startup emits NaN until history is complete;
- Stage 9 consumes native `fringe_stop_corrector` output.

## Ubuntu GRC Validation

On the Ubuntu GNU Radio 3.10.9.2 system:

```bash
cd ~/GNU_Radio/FX_GNU_radio_correlator
git checkout stage1-3-fx-engine
git pull origin stage1-3-fx-engine
gnuradio-companion grc/fx_interferometer_v1_stage9.grc
```

Confirm the flowgraph opens/generates and contains:

- `Coherent Integration` chooser;
- `phase_rate_fit_window_s`;
- `coherence_target_pct`;
- `Coherent Visibility Integrator`;
- `Phase Stability Advisor`;
- `Stage 9 / Integration + Stability` number sink.

Windows-side YAML parsing is not GNU Radio validation.

## Moon/Sun Commissioning

Initial settings:

```text
Delay Correction = Enabled
Fringe Stop = Enabled
Fringe Stop Sign = Normal (-phi_geo)
Coherent Integration = 1 s
Phase Rate Fit Window = 60 s
Coherence Target = 95%
```

Allow the advisor history to fill, then record:

- source, UTC, HA, Az, El;
- Stage-6 fringe rate;
- native stopped phase behaviour;
- residual phase rate and fit RMS;
- requested and effective integration;
- `N_int`;
- integrated amplitude and phase;
- measured window coherence;
- rate-based coherence;
- recommended maximum integration.

## Integration Sweep

On a strong source, test representative values:

```text
0.1, 1, 5, 10, 20, 30, 60 s
```

If stopped phase is stable, integrated amplitude should remain consistent while
noise/scatter reduces. If residual phase varies, measured window coherence
should decrease appropriately.

## Tracking-On / Tracking-Off Diagnostic

Where safe, compare a short interval with tracking active against a short
stationary-tracking interval. Compare:

- residual phase fit RMS;
- measured Window Coherence Retained.

Do not let Stage 9 control tracking.

## Pass / Fail Criteria

Pass requires:

- GRC opens/generates on Ubuntu GNU Radio 3.10.9.2;
- integration happens after Stage-8 `V_stopped`;
- integrated science windows are non-overlapping;
- one output is emitted per complete window;
- requested and effective integration are visible;
- measured coherence and rate-based coherence are distinct;
- phase wrapping is handled correctly;
- advisor remains informational only;
- Stage 8 Normal `(-phi_geo)` sign remains unchanged;
- ENU remains unchanged;
- existing Stage 1-8 paths remain intact;
- existing block coordinate changes are zero;
- no Stage-10 logging, calibration, rho, imaging, OOT migration, or multi-B210
  work has been added.
