# Stage 10 UVFITS Visibility Recording Validation

## Objective

Stage 10 records the Stage-9 coherently integrated, fringe-stopped complex visibility to a standard UVFITS file. It is a recording stage only. It does not implement rho, calibration, imaging, gridding, spectral HDF5, multi-B210 operation, or any Stage 11+ behaviour.

## Architecture

The GNU Radio flowgraph taps only the four aligned outputs of `coherent_visibility_integrator`:

- output 0: integrated complex `V_stopped`
- output 1: measured window coherence percent
- output 2: effective integration time, seconds
- output 3: integration sample count

The Stage-10 block enqueues low-rate records from `work()` and returns quickly. A worker thread writes a SQLite recovery journal during the observation. When recording is turned off or the flowgraph stops, the journal is converted to UVFITS using `pyuvdata`, read back, and checked before the observation is reported complete.

The flowgraph does not synchronously connect Stage-5 astronomy or Stage-6 geometry streams to the recorder. Stage 10 recomputes astronomy and UVW metadata independently at the estimated integration-centre UTC using the frozen observation configuration.

## Controls And Status

The GRC file exposes:

- `Observation Name`
- `UVFITS Output Directory`
- `Record UVFITS`

Recording defaults OFF. Switching Record UVFITS ON starts a new observation. Switching it OFF stops intake and finalizes the UVFITS file.

The GRC status sink shows:

- Recording State code: `0=OFF`, `1=RECORDING`, `2=FINALIZING`, `3=COMPLETE`, `4=ERROR`
- Records Captured

The current output filename is printed in the GNU Radio terminal at start/finalize and is stored in the SQLite journal. A standard text-valued dynamic display has not yet been added to the GRC GUI.

## File Design

UVFITS was chosen as the primary scientific visibility format because it preserves complex visibility, time, integration interval, antenna IDs, baseline/UVW geometry, frequency, channel width, flags, and visibility units in a form that `pyuvdata` can read back and later convert toward imaging or MeasurementSet workflows.

UVFITS is not an append-friendly streaming container. Stage 10 therefore writes a `.stage10.sqlite` recovery journal while recording, then creates the final `.uvfits` at observation close. The journal is retained if finalization fails.

Observation files use:

`YYYYMMDDTHHMMSSZ_<observation>_<source>_B01.uvfits`

Existing files are not overwritten; a numeric suffix is added on collision.

## Conventions

Project baseline:

`B01 = r1 - r0`

Project cross-spectrum:

`C01[k] = X0[k] * conj(X1[k])`

pyuvdata mapping:

- `ant1 = 0`
- `ant2 = 1`
- pyuvdata internal baseline is `position(ant2) - position(ant1)`, matching project `B01`

Stage-6/project UVW is supplied to `UVData.uvw_array` directly in metres. Stage 10 does not manually negate UVW before `write_uvfits()`.

The Stage-9 complex visibility is supplied to `UVData.data_array` directly. Stage 10 does not manually conjugate the visibility before `write_uvfits()`.

pyuvdata handles the UVFITS on-disk convention conversion internally. Deterministic write/read tests verify that the pyuvdata readback representation preserves project UVW and complex visibility.

## Time

Stage 10 records the estimated centre of each Stage-9 integration window:

`integration_center = output_utc - effective_integration_s / 2`

`output_utc` is taken from the host UTC clock when the Stage-9 record is emitted. Version 1 does not use B210 PPS sample timestamps, so Stage 10 does not claim hardware-level absolute timestamp accuracy.

## Frequency And Bandwidth

Stage 10 records a single broadband continuum channel:

- `Nfreqs = 1`
- frequency = sky centre frequency, default `4.800e9 Hz`
- channel width = effective Stage-8 retained bandwidth

The bandwidth calculation mirrors the Stage-8 edge exclusion:

- `n_edge = int(fft_size * edge_exclude_pct / 100)`
- `n_used = fft_size - 2*n_edge`
- `effective_bw_hz = n_used * samp_rate / fft_size`

For `fft_size=4096`, `samp_rate=30.72e6`, `edge_exclude_pct=20`, the expected effective bandwidth is `18,435,000 Hz`.

## Source Handling

Manual source mode treats operator RA/Dec as ICRS inputs and computes apparent coordinates and UVW at each integration-centre time.

Sun mode was investigated with `pyuvdata 3.2.7`. The UVFITS writer rejected moving ephemeris phase centres unless `force_phase=True`, which would rephase the data and violate the Stage-10 requirement not to silently alter the visibility/phase centre. Therefore Stage 10 explicitly rejects UVFITS recording in Sun source mode until a scientifically correct Sun file-format path is selected.

## Software Tests

Run:

```bash
python -m unittest discover -s tests
```

The Stage-10 tests cover:

- effective bandwidth
- ideal E-W UVW signs
- UVW baseline norm preservation
- ENU to ECEF antenna metadata round trip
- one-record UVFITS write/read preserving `[+4,-3,+2] m` and `3+4j`
- ten-record UVFITS write/read
- varying integration times
- manual-source integration-centre time metadata
- explicit Sun/ephemeris rejection
- SQLite journal recovery
- recovery CLI
- recorder OFF to RECORDING to COMPLETE state machine
- invalid output directory entering ERROR
- observation-defining configuration changes finalizing the active file
- queue overflow entering ERROR
- GRC Stage-10 controls/connections
- preservation of all existing GRC block coordinates, rotations, bus metadata, and pre-existing connections

This is software validation only. It does not prove B210 hardware or on-sky recording correctness.

## Ubuntu Commissioning

1. Install the Stage-10 dependency in the Python environment used by GNU Radio:

   ```bash
   python3 -m pip install pyuvdata
   python3 - <<'PY'
   import pyuvdata
   print(pyuvdata.__version__)
   PY
   ```

2. Pull the current branch:

   ```bash
   cd ~/GNU_Radio/FX_GNU_radio_correlator
   git checkout stage1-3-fx-engine
   git pull origin stage1-3-fx-engine
   ```

3. Open the authoritative GRC file:

   ```bash
   gnuradio-companion grc/fx_interferometer_v1_stage10.grc
   ```

4. Generate the flowgraph normally in GNU Radio Companion. Confirm the new Stage-10 controls and status sink are visible.

5. Use Manual RA/Dec source mode for the first Stage-10 UVFITS tests. Sun UVFITS recording is intentionally blocked until the ephemeris limitation is resolved.

6. Confirm the science prerequisites before recording:

   - Stage-7 delay correction enabled
   - Stage-8 fringe stop enabled
   - Stage-8 fringe-stop sign Normal `(-phi_geo)`
   - Stage-9 integration selected as desired

7. Set an observation name and output directory. Leave Record UVFITS OFF while checking spectra and visibility.

8. Switch Record UVFITS ON. Confirm the terminal prints the output filename and the status state becomes `1`.

9. Record a short test, then switch Record UVFITS OFF. Confirm:

   - state becomes `3`
   - Records Captured is non-zero
   - `.uvfits` exists
   - diagnostics CSV exists
   - no `.stage10.sqlite` journal remains after successful finalization

10. Inspect the finished file:

    ```bash
    python3 - <<'PY'
    from pyuvdata import UVData
    uv = UVData()
    uv.read_uvfits("path/to/file.uvfits")
    print("Nblts", uv.Nblts)
    print("Nbls", uv.Nbls)
    print("Nfreqs", uv.Nfreqs)
    print("Npols", uv.Npols)
    print("freq Hz", uv.freq_array)
    print("channel width Hz", uv.channel_width)
    print("ant1/ant2", uv.ant_1_array[:5], uv.ant_2_array[:5])
    print("first uvw m", uv.uvw_array[0])
    print("last uvw m", uv.uvw_array[-1])
    print("first visibility", uv.data_array[0, 0, 0])
    print("last visibility", uv.data_array[-1, 0, 0])
    print("vis units", uv.vis_units)
    PY
    ```

11. If finalization fails and a `.stage10.sqlite` journal remains, recover with:

    ```bash
    python3 tools/recover_stage10_uvfits.py path/to/observation.stage10.sqlite
    ```

12. For the first on-sky acceptance run, record 5 to 10 minutes with Manual RA/Dec matching the source. Compare:

    - number of records with expected Stage-9 integration cadence
    - first/last UTC
    - first/last u,v,w
    - first/last U,V,W in wavelengths from diagnostics CSV
    - UV coverage smoothness
    - UVFITS visibility amplitude/phase against the Stage-9 GUI near matching times

## Known Limitations

- Sun source mode cannot yet be claimed as Stage-10 accepted for UVFITS with `pyuvdata 3.2.7`; recording is explicitly rejected rather than written inconsistently.
- Timestamps are host-clock estimates of integration-centre UTC, not PPS/sample-accurate hardware timestamps.
- The current output filename is terminal/journal visible, not dynamically displayed as text in the GRC GUI.
- Visibility units are `uncalib`; the file does not claim Jy or Stokes I.
- No B210 hardware validation is implied by the Windows software tests.
