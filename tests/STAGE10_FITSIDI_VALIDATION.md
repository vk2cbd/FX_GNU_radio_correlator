# Stage 10 FITS-IDI Validation

Stage 10 records the Stage-9 coherently integrated fringe-stopped visibility
to FITS-IDI. It is a low-rate sink only and does not alter the validated
Stage 1-9 DSP path.

## Software Checks

1. Open `grc/fx_interferometer_v1_stage10.grc` in GNU Radio Companion 3.10.9.2.
2. Confirm the Stage-10 controls are present:
   Observation Name, FITS-IDI Output Directory, UV Logging, Recording State,
   Records Written, and Current File Code.
3. Confirm UV Logging defaults to Start/Off.
4. Generate the flowgraph on Ubuntu and confirm no GRC block errors.
5. Run the Python test suite from the repository root:

   ```sh
   python3 -m pytest tests
   ```

6. Confirm `tests/test_stage10_fitsidi.py` passes the synthetic FITS-IDI tests:
   primary signature, table order, visibility sign, UVW sign/units,
   baseline number, effective bandwidth, chunking, partial-file recovery, and
   queue-overflow failure handling.

## First Recording Test

1. Use the known-good Stage-9 observing setup.
2. Set Delay Correction to Enabled.
3. Set Fringe Stop to Enabled.
4. Set Fringe Stop Sign to Normal (-phi_geo).
5. Set Coherent Integration to `1.0`.
6. Set FITS-IDI Output Directory to `~/FX_Correlator_Data`.
7. Set Observation Name to a short descriptive name.
8. Start the flowgraph.
9. Set UV Logging to Stop UV Logging / Enabled to begin recording.
10. Observe for roughly five minutes on a strong source.
11. Set UV Logging back to Start UV Logging / Disabled to stop and finalize.
12. Confirm the console reports the final `*.fitsidi` path and no ERROR state.

## File Inspection

Use:

```sh
python3 tools/inspect_stage10_fitsidi.py ~/FX_Correlator_Data/<file>.fitsidi
```

Confirm:

- HDU order is `PRIMARY`, `ARRAY_GEOMETRY`, `FREQUENCY`, `SOURCE`, then one or
  more chronological `UV_DATA` chunks.
- `BASELINE` is 258.
- `REF_FREQ` is the sky frequency, nominally 4.800e9 Hz.
- `CHAN_BW` is the Stage-8 retained effective bandwidth.
- FITS `UU/VV/WW` are seconds.
- Converted project `u/v/w` match the Stage-6/UV-coverage expectation.
- `FLUX[0] + j*FLUX[1]` matches the Stage-9 integrated stopped visibility to
  expected display/timestamp precision.

## Partial-File Recovery

If the flowgraph exits unexpectedly, keep the resulting `*.partial.fitsidi`.
Inspect it with:

```sh
python3 tools/inspect_stage10_fitsidi.py ~/FX_Correlator_Data/<file>.partial.fitsidi
```

If it verifies and contains the expected completed chunks, it can be finalized:

```sh
python3 tools/inspect_stage10_fitsidi.py --finalize ~/FX_Correlator_Data/<file>.partial.fitsidi
```

## Known Limitations

- Timestamps are derived from host UTC at Stage-9 output time, with the
  integration center estimated as `t_received - effective_integration_s/2`.
  No PPS/sample timestamp is available in this one-B210 Stage-10 version.
- Sun observations use SOURCE table coordinates as reference coordinates only;
  per-record apparent coordinates are retained in the diagnostic CSV sidecar.
- The repository does not yet confirm the physical feed polarization. Stage 10
  writes `STK_1 = -5` (XX) as an explicit metadata assumption, not as Stokes I.
- This validation is software/GRC commissioning only until Ubuntu/B210 on-sky
  tests are performed.
