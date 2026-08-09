# Stage 5 Coordinate Validation

Stage 5 adds only the source/site/time coordinate subsystem.

Do not apply geometric delay correction, uvw correction, fringe stopping, calibration, logging, imaging, or any correction to `C01` during this stage.

## Implemented Scope

The GNU Radio flowgraph adds a low-rate Astropy-backed Embedded Python coordinate engine as a side branch from `cross_accum`.

The engine uses `cross_accum` only as a low-rate timing input. It does not modify the accumulated complex cross-spectrum and is not inserted into the existing science path.

## Configurable Inputs

GRC variables:

- `site_lat_deg = -32.724`
- `site_lon_deg = +152.130167`
- `site_height_m = 0.0`

Longitude is east-positive.

GUI controls:

- `source_mode`: Sun or Manual RA/Dec
- `manual_ra_hours`: manual ICRS right ascension in decimal hours
- `manual_dec_deg`: manual ICRS declination in decimal degrees

No online source-name resolution is used.

## Numerical Outputs

The Stage 5 number sink displays:

- UTC decimal hour, hours
- LMST, hours
- Hour Angle, hours
- Azimuth, degrees
- Elevation, degrees
- Apparent RA, hours
- Apparent Dec, degrees

## Astronomy Conventions

- Astropy is used for solar position, time, coordinate transforms and Earth-orientation handling.
- LMST uses local apparent sidereal time.
- Hour angle is wrapped to approximately `-12..+12 h`.
- Negative HA means the source is east of the meridian.
- Positive HA means the source is west of the meridian.
- Azimuth uses north `0 deg`, east `90 deg`, south `180 deg`, west `270 deg`.
- Elevation is `-90..+90 deg`.
- AltAz transforms use `pressure=0` so atmospheric refraction is not introduced into the geometric direction.
- Manual RA/Dec are ICRS and are transformed at the current observation time/location.
- Apparent RA/Dec use Astropy `TETE`, an apparent-of-date frame suitable for relating apparent RA to local apparent sidereal time.

## IERS / Earth Orientation

Astropy's standard Earth-orientation machinery is used. No manual UT1 or polar-motion correction is implemented.

The Stage 5 block sets:

```python
iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"
```

This avoids relying on live internet during an observation and allows Astropy to use bundled or cached IERS data, but precise observing should use current IERS tables installed or cached before the observing session. If IERS data are stale or outside range, Astropy may warn and coordinate accuracy may degrade.

## Deterministic Tests

Run from the repository root:

```bash
python -m unittest tests.test_stage5_coordinates
```

The tests check:

- longitude convention is east-positive;
- LMST is in `0..24 h`;
- HA uses the stated east/west sign;
- azimuth uses north `0 deg`, east `90 deg`;
- elevation is within `-90..+90 deg`;
- Sun coordinates are finite and time-varying;
- Manual RA/Dec transforms successfully;
- Stage 4 delay estimator connections remain present;
- Stage 5 does not replace the existing Stage 1-4 science path connections.

## Ubuntu GRC Validation

On the authoritative Ubuntu GNU Radio 3.10.9.2 system:

```bash
cd /home/astro/GNU_Radio/FX_GNU_radio_correlator
git checkout stage1-3-fx-engine
git pull
gnuradio-companion grc/fx_interferometer_v1_stage1_3.grc
```

Confirm:

- the flowgraph opens without missing block errors;
- the Source selector, Manual RA and Manual Dec controls are visible;
- the Astronomy / Source Coordinates number sink is visible;
- changing Manual RA/Dec in Manual mode changes apparent RA/Dec, HA, Az and El;
- selecting Sun produces finite, time-varying apparent RA/Dec, HA, Az and El;
- existing spectra, cross-spectrum, phase-slope and delay-estimator displays still work.

## Independent Sun Az/El Check

For a chosen UTC on the Ubuntu observing system:

1. Record site coordinates:

   ```text
   lat = -32.724 deg
   lon = +152.130167 deg
   height = 0.0 m initially
   ```

2. Select Sun mode in the flowgraph.
3. Record UTC, Azimuth and Elevation from the Stage 5 display.
4. Compare against an independent known-good pointing program or astronomy reference using the same UTC and site coordinates.
5. Ensure the comparison uses:

   - east-positive longitude;
   - azimuth north `0 deg`, east `90 deg`;
   - geometric/no-refraction coordinates where the independent tool supports that choice.

Do not claim Stage 5 coordinate validation complete until the Ubuntu/B210-side GRC runtime and independent Sun Az/El comparison have been performed.
