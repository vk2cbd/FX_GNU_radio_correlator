# Stage 1-3 Ubuntu Validation Procedure

This checklist is for the authoritative target system:

- Ubuntu 24.04.4
- GNU Radio 3.10.9.2
- UHD
- Ettus B210
- external 10 MHz reference
- one B210 with RX channels `[0,1]`

The Windows development checkout is not proof of GNU Radio, UHD, or B210 validity.

## Scope

Validate only the Stage 1-3 coherent FX engine in:

`grc/fx_interferometer_v1_stage10.grc`

Do not add geometry, delay correction, fringe stopping, rho, calibration, logging, imaging, or OOT modules during this validation.

## Fixed Conventions

- RX0 = antenna 0 = 2.4 m dish
- RX1 = antenna 1 = 1.7 m dish
- Cross-spectrum convention: `C01[k] = X0[k] * conj(X1[k])`
- Sky centre frequency: `sky_cf = 4.800e9 Hz`
- High-side LNB LO: `lnb_lo = 5.950e9 Hz`
- IF centre frequency: `if_cf = lnb_lo - sky_cf = 1.150e9 Hz`
- Sample rate: `samp_rate = 30.72e6 samples/s/channel`
- FFT size: `fft_size = 4096`
- FFT bin width: `samp_rate / fft_size = 7500 Hz`
- FFT vector rate: `samp_rate / fft_size = 7500 vectors/s`
- Accumulation: `accum_frames = 750`, approximately `0.1 s`
- Clock source: external 10 MHz
- Time source: internal for one-B210 Version 1

## A. Open Or Generate The GRC File

1. Copy or pull the repository onto the Ubuntu GNU Radio machine.
2. From the repository root, inspect the GRC file:

   ```bash
   sed -n '1,240p' grc/fx_interferometer_v1_stage10.grc
   ```

3. Open it in GNU Radio Companion:

   ```bash
   gnuradio-companion grc/fx_interferometer_v1_stage10.grc
   ```

4. Confirm the graph opens without missing-block errors.
5. Confirm the generated top block is named `fx_interferometer_v1_stage10`.

## B. Check GRC Compatibility

1. Confirm every block ID resolves in GNU Radio 3.10.9.2.
2. Pay special attention to these candidate block IDs and parameters:

   - `uhd_usrp_source`
   - `fft_vxx`
   - `blocks_stream_to_vector`
   - `blocks_complex_to_mag_squared`
   - `blocks_multiply_conjugate_cc`
   - `blocks_integrate_xx`
   - `blocks_complex_to_mag`
   - `blocks_complex_to_arg`
   - `blocks_nlog10_ff`
   - `blocks_multiply_const_vxx`
   - `qtgui_vector_sink_f`

3. If GRC reports renamed or invalid parameters, update the `.grc` file using the local GNU Radio 3.10.9.2 block definitions as the authority.
4. Generate Python from the flowgraph:

   ```bash
   grcc grc/fx_interferometer_v1_stage10.grc
   ```

5. Record whether `grcc` succeeds and keep any warnings/errors.

## C. Verify External 10 MHz Reference

1. Connect the GPS-disciplined or lab 10 MHz reference to the B210 reference input.
2. Confirm UHD detects and locks to the external reference, using whichever commands are available locally. Examples:

   ```bash
   uhd_find_devices
   uhd_usrp_probe
   ```

3. In the probe output, verify the B210 is present and look for reference/clock-source information.
4. If UHD does not lock to the external 10 MHz source, do not proceed to coherence tests.

## D. Test Dual-Channel 30.72 MS/s Streaming

1. Confirm the flowgraph uses one UHD Source with stream channels `[0,1]`.
2. Confirm both RX channels use:

   - sample rate `30.72e6`
   - centre frequency `1.150e9`
   - complex float host samples
   - `sc16` over-the-wire samples if supported
   - independent gains `gain0` and `gain1`

3. Start the generated flowgraph from GRC or the generated Python script.
4. Let it run for at least several minutes with both channels active.

## E. Monitor UHD Overflow Messages

1. Watch the terminal that launched the graph.
2. Look for UHD overflow indicators such as `O`, `overflow`, `D`, late packets, or streamer warnings.
3. Pass condition: sustained dual-channel streaming at `30.72 MS/s` per channel with no recurring UHD overflow messages.
4. If overflows occur, record:

   - host CPU
   - USB controller and negotiated speed
   - B210 firmware/FPGA versions
   - whether overflows begin immediately or after runtime
   - actual sample rate if it was reduced for diagnosis

## F. Check Both Auto-Spectra

1. Confirm the auto-spectrum display shows two traces:

   - RX0 / antenna 0 / 2.4 m
   - RX1 / antenna 1 / 1.7 m

2. Confirm the traces update at roughly 10 Hz.
3. Confirm each trace responds to its own gain setting.
4. Confirm no absolute calibration is implied; the display is relative dB only.
5. Confirm the x-axis represents sky frequency, with high-side inversion:

   ```text
   f_sky = f_LO - f_IF
   ```

   With the shifted FFT, the left side of the plot should correspond to higher sky frequency and the right side to lower sky frequency unless a display-only reversal is later added.

## G. Inject A Common Signal Into Both Receiver Paths

1. Inject a common coherent tone or broadband test source into both RX chains through appropriate attenuation/splitting.
2. Ensure the signal level is safe for the B210 inputs.
3. Confirm the tone or band feature appears in both auto-spectra at the expected sky-frequency label.
4. Confirm changing one channel gain affects that channel auto-spectrum without changing the other channel gain setting.

## H. Check Cross-Spectrum Magnitude And Phase Stability

1. With the common coherent signal connected to both chains, inspect the cross-spectrum magnitude display.
2. Pass condition: a strong cross-spectrum magnitude appears where the common signal is present.
3. Inspect the cross-spectrum phase display.
4. Pass condition: phase is stable over time for the common coherent signal, allowing for static instrumental phase offset.
5. Preserve the sign convention while interpreting results:

   ```text
   C01[k] = X0[k] * conj(X1[k])
   ```

6. If phase sign appears opposite to expectation, document it. Do not change the convention without explicit approval.

## I. Later Known Differential-Delay Test

This test is mandatory before later astronomy delay correction is implemented.

1. Insert a known additional electrical delay into one receiver path.
2. Use a coherent broadband or multi-tone source spanning enough bandwidth to measure phase slope.
3. Measure cross-spectrum phase versus sky frequency.
4. Fit the phase slope and recover the delay from `dphi/df`.
5. Record:

   - which physical path received the added delay
   - expected delay in seconds
   - measured phase slope
   - recovered delay
   - whether the sign agrees with `C01[k] = X0[k] * conj(X1[k])`
   - how high-side sky-frequency inversion affects the plotted slope

Do not proceed to astronomical delay correction, geometry, or fringe stopping until this test passes and the sign convention is understood.
