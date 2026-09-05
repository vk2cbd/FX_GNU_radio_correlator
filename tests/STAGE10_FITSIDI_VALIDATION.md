# Stage 10 FITS-IDI Validation

Stage 10 has been reset into two separate components.

Stage 10A is the GNU Radio visibility publisher in `grc/fx_interferometer_v1_stage10.grc`.
It publishes completed Stage-9 integrated visibility records over localhost TCP JSON lines.
It does not create, open, close, or finalize FITS-IDI files.

Stage 10B is the standalone logger in `tools/stage10_fitsidi_logger.py`.
It owns operator Start/Stop control and FITS-IDI file creation.

## Startup No-Recording Test

1. Start GNU Radio Companion.
2. Open and run `grc/fx_interferometer_v1_stage10.grc`.
3. Wait 30 seconds.
4. Confirm no `.fitsidi` or `.partial.fitsidi` file is created.
5. Start the standalone logger:

   ```bash
   python3 tools/stage10_fitsidi_logger.py
   ```

6. Confirm live data are displayed.
7. Wait 60 seconds.
8. Confirm no FITS-IDI file is created until the logger Start button is pressed.

## Packet Identity Test

With GRC running, use the diagnostic receiver:

```bash
python3 tools/stage10_packet_receiver.py --count 5
```

Verify:

- GRC Source = Sun produces `source_mode: 0` and `source_name: "Sun"`.
- GRC Source = Manual RA/Dec produces `source_mode: 1` and `source_name: "Manual"`.
- Switching back to Sun returns immediately to `source_name: "Sun"`.
- `schema_version` is `2`.
- `metadata_valid` is `true`.
- `integration_center_utc` is `emitted_utc - effective_integration_s/2`.
- `retained_fft_bins` and `effective_correlated_bandwidth_hz` match the live
  `visibility_edge_exclude_pct`, `fft_size`, and `samp_rate`.

Use these edge-exclusion checks:

```text
5.0%  -> retained_fft_bins = 3688, effective_correlated_bandwidth_hz = 27660000
12.5% -> retained_fft_bins = 3072, effective_correlated_bandwidth_hz = 23040000
20.0% -> retained_fft_bins = 2458, effective_correlated_bandwidth_hz = 18435000
```

## Start Test

1. In the standalone logger, verify Publisher Connection is Connected.
2. Verify Live Source is correct.
3. Enter Observation Name and Output Directory.
4. Press Start FITS-IDI Recording.

Expected:

- Recording State becomes RECORDING.
- Exactly one `*.partial.fitsidi` appears.
- The filename source token matches the live packet source.
- No pre-start packets are back-filled.
- If observation-defining metadata changes while recording, the logger finalizes
  the current file and enters `ERROR_CONFIG_CHANGED`.

## Stop Test

1. Record for about 30 seconds.
2. Press Stop FITS-IDI Recording.

Expected:

- State goes through FINALIZING to COMPLETE.
- The partial file is verified and renamed to `*.fitsidi`.
- Live packet display may continue.
- The completed file does not grow after Stop.

## Inspection

Inspect a final or partial file with:

```bash
python3 tools/inspect_stage10_fitsidi.py ~/FX_Correlator_Data/<file>.fitsidi
```

The reported `CHAN_BW` and `TOTAL_BANDWIDTH` are the Stage-8 retained continuum
bandwidth, not the raw B210 sample rate. With the current defaults this is:

```text
sample rate = 30.72 MHz
FFT length = 4096
edge exclusion = 20% per side
retained FFT bins = 2458
effective retained bandwidth = 18.435 MHz
```

Plot U/V coverage with:

```bash
python3 tools/plot_stage10_fitsidi_uv.py ~/FX_Correlator_Data/<file>.fitsidi
```

The FITS sign convention is:

- `UU = -project_u / c`
- `VV = -project_v / c`
- `WW = -project_w / c`

The visibility is written as measured:

- `FLUX[0] = real(V_stopped)`
- `FLUX[1] = imag(V_stopped)`
- `FLUX[2] = 1.0`

No conjugate duplicate baseline is written.
