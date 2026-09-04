import queue
import threading
import time
from datetime import datetime, timezone

import numpy as np
from gnuradio import gr

from fx_interferometer_v1_stage10_fitsidi_writer import (
    FitsIdiWriter,
    STATE_COMPLETE,
    STATE_ERROR,
    STATE_FINALIZING,
    STATE_OFF,
    STATE_RECORDING,
)


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
    return bool(value)


class blk(gr.sync_block):
    """Stage 10 low-rate FITS-IDI visibility recorder.

    Inputs are the aligned Stage-9 coherent integrator outputs:
    V_stopped, window coherence percent, effective integration seconds, N_int,
    followed by low-rate GUI control streams for UV logging, source mode,
    manual RA hours, and manual Dec degrees.
    Disk I/O is isolated in a worker thread so GNU Radio work() only enqueues
    small visibility records.
    """

    def __init__(
        self,
        uv_logging_enable=False,
        observation_name="obs1",
        output_dir="~/FX_Correlator_Data",
        source_mode=0,
        manual_ra_hours=5.0,
        manual_dec_deg=-30.0,
        site_lat_deg=-32.724,
        site_lon_deg=152.130167,
        site_height_m=70.0,
        baseline_e_m=-5.785,
        baseline_n_m=0.095,
        baseline_u_m=0.580,
        sky_cf_hz=4.800e9,
        samp_rate=30.72e6,
        fft_size=4096,
        visibility_edge_exclude_pct=20.0,
        instrument_delay_ns=0.0,
        delay_correction_enable=True,
        fringe_stop_enable=True,
        fringe_stop_sign=-1,
        integration_time_s=1.0,
        gain0=40.0,
        gain1=40.0,
        stokes_code=-5,
    ):
        self.uv_logging_enable = _as_bool(uv_logging_enable)
        self.observation_name = str(observation_name)
        self.output_dir = str(output_dir)
        self.source_mode = int(source_mode)
        self.manual_ra_hours = float(manual_ra_hours)
        self.manual_dec_deg = float(manual_dec_deg)
        self.site_lat_deg = float(site_lat_deg)
        self.site_lon_deg = float(site_lon_deg)
        self.site_height_m = float(site_height_m)
        self.baseline_e_m = float(baseline_e_m)
        self.baseline_n_m = float(baseline_n_m)
        self.baseline_u_m = float(baseline_u_m)
        self.sky_cf_hz = float(sky_cf_hz)
        self.samp_rate = float(samp_rate)
        self.fft_size = int(fft_size)
        self.visibility_edge_exclude_pct = float(visibility_edge_exclude_pct)
        self.instrument_delay_ns = float(instrument_delay_ns)
        self.delay_correction_enable = _as_bool(delay_correction_enable)
        self.fringe_stop_enable = _as_bool(fringe_stop_enable)
        self.fringe_stop_sign = int(fringe_stop_sign)
        self.integration_time_s = float(integration_time_s)
        self.gain0 = float(gain0)
        self.gain1 = float(gain1)
        self.stokes_code = int(stokes_code)
        self._queue = queue.Queue(maxsize=100)
        self._writer = None
        self._thread = None
        self._stop_requested = False
        self._lock = threading.RLock()
        self._state = STATE_OFF
        self._records_written = 0
        self._chunks_written = 0
        self._last_error = ""
        self._last_file_code = 0.0
        self._control_enabled = False
        self._control_initialized = False
        gr.sync_block.__init__(
            self,
            name="FITS-IDI Visibility Recorder",
            in_sig=[
                np.complex64,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
            ],
            out_sig=[np.float32, np.float32, np.float32],
        )

    def set_uv_logging_enable(self, value):
        with self._lock:
            self.uv_logging_enable = _as_bool(value)

    def set_observation_name(self, value):
        with self._lock:
            self.observation_name = str(value)

    def set_output_dir(self, value):
        with self._lock:
            self.output_dir = str(value)

    def set_source_mode(self, value):
        with self._lock:
            self.source_mode = int(value)

    def set_manual_ra_hours(self, value):
        with self._lock:
            self.manual_ra_hours = float(value)

    def set_manual_dec_deg(self, value):
        with self._lock:
            self.manual_dec_deg = float(value)

    def set_site_lat_deg(self, value):
        with self._lock:
            self.site_lat_deg = float(value)

    def set_site_lon_deg(self, value):
        with self._lock:
            self.site_lon_deg = float(value)

    def set_site_height_m(self, value):
        with self._lock:
            self.site_height_m = float(value)

    def set_baseline_e_m(self, value):
        with self._lock:
            self.baseline_e_m = float(value)

    def set_baseline_n_m(self, value):
        with self._lock:
            self.baseline_n_m = float(value)

    def set_baseline_u_m(self, value):
        with self._lock:
            self.baseline_u_m = float(value)

    def set_sky_cf_hz(self, value):
        with self._lock:
            self.sky_cf_hz = float(value)

    def set_samp_rate(self, value):
        with self._lock:
            self.samp_rate = float(value)

    def set_fft_size(self, value):
        with self._lock:
            self.fft_size = int(value)

    def set_visibility_edge_exclude_pct(self, value):
        with self._lock:
            self.visibility_edge_exclude_pct = float(value)

    def set_instrument_delay_ns(self, value):
        with self._lock:
            self.instrument_delay_ns = float(value)

    def set_delay_correction_enable(self, value):
        with self._lock:
            self.delay_correction_enable = _as_bool(value)

    def set_fringe_stop_enable(self, value):
        with self._lock:
            self.fringe_stop_enable = _as_bool(value)

    def set_fringe_stop_sign(self, value):
        with self._lock:
            self.fringe_stop_sign = int(value)

    def set_integration_time_s(self, value):
        with self._lock:
            if self._state == STATE_RECORDING:
                self._last_error = "integration_time_s changed while recording"
                self._request_stop_locked(error=True)
                return
            self.integration_time_s = float(value)

    def _config_snapshot_locked(self):
        return {
            "observation_name": self.observation_name,
            "output_dir": self.output_dir,
            "source_mode": self.source_mode,
            "manual_ra_hours": self.manual_ra_hours,
            "manual_dec_deg": self.manual_dec_deg,
            "site_lat_deg": self.site_lat_deg,
            "site_lon_deg": self.site_lon_deg,
            "site_height_m": self.site_height_m,
            "baseline_e_m": self.baseline_e_m,
            "baseline_n_m": self.baseline_n_m,
            "baseline_u_m": self.baseline_u_m,
            "sky_cf_hz": self.sky_cf_hz,
            "samp_rate": self.samp_rate,
            "fft_size": self.fft_size,
            "visibility_edge_exclude_pct": self.visibility_edge_exclude_pct,
            "instrument_delay_ns": self.instrument_delay_ns,
            "delay_correction_enable": self.delay_correction_enable,
            "fringe_stop_enable": self.fringe_stop_enable,
            "fringe_stop_sign": self.fringe_stop_sign,
            "integration_time_s": self.integration_time_s,
            "gain0": self.gain0,
            "gain1": self.gain1,
            "stokes_code": self.stokes_code,
        }

    def _start_locked(self):
        if self._state == STATE_RECORDING:
            return
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._stop_requested = False
        self._writer = FitsIdiWriter(self._config_snapshot_locked())
        self._writer.start()
        self._state = STATE_RECORDING
        self._last_file_code += 1.0
        print(f"Stage 10 FITS-IDI recording started: {self._writer.current_file}", flush=True)
        self._thread = threading.Thread(target=self._writer_loop, name="stage10-fitsidi-writer", daemon=True)
        self._thread.start()

    def _request_stop_locked(self, error=False):
        if self._state != STATE_RECORDING:
            return
        self._stop_requested = True
        self._state = STATE_ERROR if error else STATE_FINALIZING

    def _writer_loop(self):
        error = None
        try:
            while True:
                if self._stop_requested and self._queue.empty():
                    break
                try:
                    record = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._writer.add_record(record)
                with self._lock:
                    self._records_written = self._writer.records_written + len(self._writer._chunk)
                    self._chunks_written = self._writer.chunks_written
            self._writer.stop()
        except Exception as exc:
            error = exc
            try:
                if self._writer is not None:
                    self._writer.abort_error()
            except Exception:
                pass
        with self._lock:
            if error is None:
                self._state = STATE_COMPLETE
                self._records_written = self._writer.records_written
                self._chunks_written = self._writer.chunks_written
                self._last_file_code += 1.0
                print(f"Stage 10 FITS-IDI recording complete: {self._writer.current_file}", flush=True)
            else:
                self._state = STATE_ERROR
                self._last_error = str(error)
                print(f"Stage 10 FITS-IDI recorder error: {error}", flush=True)

    def _set_stream_controls_locked(self, source_mode, manual_ra_hours, manual_dec_deg):
        self.source_mode = int(round(float(source_mode)))
        self.manual_ra_hours = float(manual_ra_hours)
        self.manual_dec_deg = float(manual_dec_deg)

    def work(self, input_items, output_items):
        nout = min(*(len(items) for items in input_items), len(output_items[0]))
        for i in range(nout):
            control_enabled = bool(float(input_items[4][i]) >= 0.5)
            with self._lock:
                self._set_stream_controls_locked(input_items[5][i], input_items[6][i], input_items[7][i])
                if not self._control_initialized:
                    self._control_enabled = control_enabled
                    self.uv_logging_enable = control_enabled
                    self._control_initialized = True
                    output_items[0][i] = np.float32(self._state)
                    output_items[1][i] = np.float32(self._records_written)
                    output_items[2][i] = np.float32(self._last_file_code)
                    continue
                previous_control_enabled = self._control_enabled
                self._control_enabled = control_enabled
                self.uv_logging_enable = control_enabled
                if control_enabled and not previous_control_enabled:
                    if self._state in (STATE_OFF, STATE_COMPLETE, STATE_ERROR):
                        try:
                            self._start_locked()
                        except Exception as exc:
                            self._state = STATE_ERROR
                            self._last_error = str(exc)
                            print(f"Stage 10 FITS-IDI recorder start rejected: {exc}", flush=True)
                elif previous_control_enabled and not control_enabled:
                    if self._state == STATE_RECORDING:
                        self._request_stop_locked(error=False)
            with self._lock:
                state = self._state
                writer_active = state == STATE_RECORDING
            if writer_active:
                record = {
                    "visibility": complex(input_items[0][i]),
                    "coherence_pct": float(input_items[1][i]),
                    "effective_integration_s": float(input_items[2][i]),
                    "n_int": float(input_items[3][i]),
                    "t_center": datetime.now(timezone.utc),
                }
                try:
                    self._queue.put_nowait(record)
                except queue.Full:
                    with self._lock:
                        self._last_error = "Stage 10 FITS-IDI queue overflow"
                        self._request_stop_locked(error=True)
                    print("Stage 10 FITS-IDI recorder ERROR: queue overflow; preserving partial file.", flush=True)
            with self._lock:
                output_items[0][i] = np.float32(self._state)
                output_items[1][i] = np.float32(self._records_written)
                output_items[2][i] = np.float32(self._last_file_code)
        return nout
