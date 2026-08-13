# Stage 6 Baseline Geometry Validation

Stage 6 is calculation/display only. It must not correct `C01`, apply delay compensation, fringe stop, calibrate, log, image, or modify the Stage 1-5 science path.

## Working Baseline

Baseline convention:

```text
B01 = r1 - r0
```

Antenna identities:

- antenna 0 = RX0 = 2.4 m dish
- antenna 1 = RX1 = 1.7 m dish

Current working ENU components:

```text
baseline_e_m = -5.785
baseline_n_m = +0.095
baseline_u_m = +0.580
```

ENU convention:

- `+E` = geographic east
- `+N` = geographic north
- `+U` = up

Therefore antenna 1 is 5.785 m west, 0.095 m north and 0.580 m above antenna 0.

E and U are physically measured baseline components.

N = +0.095 m is the current astronomically refined / working north component derived from Stage-6 validation.

Expected baseline magnitude:

```text
|B01| = 5.814779 m
```

Maximum absolute geometric delay:

```text
|B01| / c = 19.396 ns
```

## Delay Conventions

The source unit vector points from the array toward the source.

The Stage 6 geometric delay follows the project specification:

```text
tau_g = dot(B01, s) / c
```

With the Stage 6 uvw convention, this is also:

```text
tau_g = w_m / c
```

The astronomical arrival-time difference is displayed separately:

```text
RX1 minus RX0 arrival delay = -tau_g
```

Do not redefine `tau_g` to match receiver electrical-delay sign.

## UVW Convention

Stage 6 outputs uvw in metres.

- `w` points toward the phase centre/source
- `u` is eastward on the tangent sky plane
- `v` is northward on the tangent sky plane

For local ENU baseline components and Stage 5 apparent hour angle/declination:

```text
H = apparent hour angle, radians
delta = apparent declination, radians
phi = site latitude, radians
```

Unit vectors:

```text
u_hat = [
    cos(H),
    -sin(phi)*sin(H),
    +cos(phi)*sin(H)
]

v_hat = [
    sin(delta)*sin(H),
    cos(phi)*cos(delta) + sin(phi)*sin(delta)*cos(H),
    sin(phi)*cos(delta) - cos(phi)*sin(delta)*cos(H)
]

w_hat = [
    -cos(delta)*sin(H),
    sin(delta)*cos(phi) - cos(delta)*cos(H)*sin(phi),
    sin(delta)*sin(phi) + cos(delta)*cos(H)*cos(phi)
]
```

Then:

```text
u_m = dot(B01, u_hat)
v_m = dot(B01, v_hat)
w_m = dot(B01, w_hat)
```

The basis must be orthonormal and right-handed:

```text
u_hat dot v_hat ~= 0
u_hat dot w_hat ~= 0
v_hat dot w_hat ~= 0
|u_hat| ~= |v_hat| ~= |w_hat| ~= 1
u_hat cross v_hat ~= w_hat
```

And:

```text
u_m^2 + v_m^2 + w_m^2 ~= |B01|^2
```

## Cardinal Direction Sign Tests

For `B01 = (-5.785, +0.095, +0.580) m`:

```text
Source on EAST horizon,  s_ENU = (+1,0,0): tau_g ~= -19.296683 ns
Source on WEST horizon,  s_ENU = (-1,0,0): tau_g ~= +19.296683 ns
Source on NORTH horizon, s_ENU = (0,+1,0): tau_g ~= -0.083391 ns
Source on SOUTH horizon, s_ENU = (0,-1,0): tau_g ~= +0.083391 ns
Source at ZENITH,        s_ENU = (0,0,+1): tau_g ~= +1.934672 ns
```

## Predicted Geometric Phase

For the geometric component of astronomical `C01` at the sky reference frequency:

```text
phi_geo_rad = 2*pi*sky_cf*tau_g_seconds
phi_geo_deg = phi_geo_rad wrapped to -180..+180 deg
```

This is geometric phase only. Absolute measured `C01` phase can include arbitrary instrumental phase offset. Stage 6 must not apply this phase to `C01`.

## Predicted Fringe Rate

The predicted geometric fringe rate is:

```text
f_fringe_hz = sky_cf * d(tau_g)/dt
phase_rate_deg_s = 360 * f_fringe_hz
fringe_period_s = 1 / abs(f_fringe_hz)
```

Stage 6 derives `d(tau_g)/dt` from successive unique low-rate UTC geometry samples so that Sun motion from Stage 5 is naturally included. Repeated cached Stage 5 samples are not differentiated as new geometry observations. The first valid sample may report `NaN` for fringe rate and fringe period until a second unique UTC sample exists.

## Stage 4 / Stage 6 Sign Relation

Stage 4 hardware validation established:

```text
positive measured differential delay = RX1 electrical signal delayed relative to RX0
```

For an astronomical plane wave with Stage 6 conventions:

```text
arrival_delay_RX1_minus_RX0 = -tau_g
```

Therefore, for sky observations after constant instrumental delay cancels:

```text
delta(Stage4 measured delay) ~= -delta(tau_g)
```

Do not force an offset or sign flip in software. This relation must be validated experimentally before Stage 7 correction.

## Deterministic Tests

Run:

```bash
python -m unittest tests.test_stage6_geometry
```

The tests check:

- exact baseline components;
- baseline length and maximum delay;
- cardinal direction sign tests;
- `w/c == tau_g`;
- `arrival_delay_10 == -tau_g`;
- uvw preserves baseline length;
- uvw basis is orthonormal and right-handed;
- transit, east/west hour-angle and negative-declination cases;
- Sun and Manual RA/Dec Stage 5 coordinates feed finite Stage 6 geometry;
- Sun -> Manual -> Sun switching remains finite;
- `abs(tau_g) <= |B|/c` within numerical tolerance;
- Stage 1-5 science connections remain present;
- Stage 4 delay estimator connections remain present.

## Ubuntu Astronomical Validation

1. Point both antennas at the Sun.
2. Record simultaneously at several times:

   - UTC
   - HA
   - Az
   - El
   - Stage 4 measured differential delay
   - Stage 6 `tau_g`
   - Stage 6 predicted fringe rate

3. A constant unknown instrumental delay is allowed.
4. Compare changes rather than absolute offsets:

   ```text
   measured_delay(t2) - measured_delay(t1)
   ```

   against:

   ```text
   -(tau_g(t2) - tau_g(t1))
   ```

5. Magnitude and sign should agree within practical measurement uncertainty.
6. Where SNR permits, compare predicted fringe rate with observed raw `C01` fringe rate. Do not use the observed value to drive Stage 6.

Do not proceed to Stage 7 until this astronomical sign/magnitude relationship has been observed.
