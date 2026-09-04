import queue
import threading
from datetime import datetime, timezone

import numpy as np
from gnuradio import gr

from fx_interferometer_v1_stage10_uvfits_writer import (
    STATE_COMPLETE,
    STATE_ERROR,
    STATE_FINALIZING,
    STATE_NAMES,
    STATE_OFF,
    STATE_RECORDING,
    Stage10Config,
    append_record,
    finalize_journal,
    init_journal,
    make_visibility_record,
    pyuvdata_version,
    unique_observation_paths,
)


class blk(gr.sync_block):
    """Stage 10 asynchronous UVFITS visibility recorder."""

    def __init__(
        self,
        record_uvfits=False,
        observation_name="observation",
        uvfits_output_dir="~/FX_Correlator_Data",
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
        lnb_lo_hz=5.950e9,
        samp_rate_hz=30.72e6,
        fft_size=4096,
        visibility_edge_exclude_pct=20.0,
        delay_correction_enabled=True,
        fringe_stop_enabled=True,
        fringe_stop_sign=-1,
        instrument_delay_ns=0.0,
        gain0_db=40.0,
        gain1_db=40.0,
        polarization="xx",
        software_commit="unknown",
        gnuradio_version="3.10.9.2",
        queue_max_records=256,
    ):
        self.record_uvfits = self._as_bool(record_uvfits)
        self._desired_recording = self.record_uvfits
        self.observation_name = str(observation_name)
        self.uvfits_output_dir = str(uvfits_output_dir)
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
        self.lnb_lo_hz = float(lnb_lo_hz)
        self.samp_rate_hz = float(samp_rate_hz)
        self.fft_size = int(fft_size)
        self.visibility_edge_exclude_pct = float(visibility_edge_exclude_pct)
        self.delay_correction_enabled = self._as_bool(delay_correction_enabled)
        self.fringe_stop_enabled = self._as_bool(fringe_stop_enabled)
        self.fringe_stop_sign = int(fringe_stop_sign)
        self.instrument_delay_ns = float(instrument_delay_ns)
        self.gain0_db = float(gain0_db)
        self.gain1_db = float(gain1_db)
        self.polarization = str(polarization)
        self.software_commit = str(software_commit)
        self.gnuradio_version = str(gnuradio_version)
        self.queue_max_records = int(queue_max_records)

        self._lock = threading.RLock()
        self._state = STATE_OFF
        self._records_captured = 0
        self._status_message = "OFF"
        self._current_file = ""
        self._queue = None
        self._worker = None
        self._stop_event = None
        self._journal_conn = None
        self._journal_path = None
        self._outputs = None
        self._config = None

        print(f"Stage 10 UVFITS recorder: pyuvdata version {pyuvdata_version() or 'not installed'}", flush=True)
        gr.sync_block.__init__(
            self,
            name="UVFITS Visibility Recorder",
            in_sig=[np.complex64, np.float32, np.float32, np.float32],
            out_sig=[np.float32, np.float32],
        )

    @staticmethod
    def _as_bool(value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
        return bool(value)

    def _make_config_locked(self):
        return Stage10Config(
            observation_name=self.observation_name,
            output_dir=self.uvfits_output_dir,
            source_mode=self.source_mode,
            manual_ra_hours=self.manual_ra_hours,
            manual_dec_deg=self.manual_dec_deg,
            site_lat_deg=self.site_lat_deg,
            site_lon_deg=self.site_lon_deg,
            site_height_m=self.site_height_m,
            baseline_e_m=self.baseline_e_m,
            baseline_n_m=self.baseline_n_m,
            baseline_u_m=self.baseline_u_m,
            sky_cf_hz=self.sky_cf_hz,
            lnb_lo_hz=self.lnb_lo_hz,
            samp_rate_hz=self.samp_rate_hz,
            fft_size=self.fft_size,
            visibility_edge_exclude_pct=self.visibility_edge_exclude_pct,
            polarization=self.polarization,
            delay_correction_enabled=self.delay_correction_enabled,
            fringe_stop_enabled=self.fringe_stop_enabled,
            fringe_stop_sign=self.fringe_stop_sign,
            instrument_delay_ns=self.instrument_delay_ns,
            gain0_db=self.gain0_db,
            gain1_db=self.gain1_db,
            software_commit=self.software_commit,
            gnuradio_version=self.gnuradio_version,
        )

    def _set_state_locked(self, state, message=None):
        self._state = int(state)
        self._status_message = message or STATE_NAMES.get(self._state, "UNKNOWN")
        if message:
            print(f"Stage 10: {message}", flush=True)

    def _worker_main(self):
        commit_interval = 1.0
        last_commit = datetime.now(timezone.utc).timestamp()
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    self._queue.task_done()
                    break
                append_record(self._journal_conn, item)
                self._records_captured += 1
                now = datetime.now(timezone.utc).timestamp()
                if now - last_commit >= commit_interval:
                    self._journal_conn.commit()
                    last_commit = now
                self._queue.task_done()
            self._journal_conn.commit()
        except Exception as exc:
            with self._lock:
                self._desired_recording = False
                self.record_uvfits = False
                self._set_state_locked(STATE_ERROR, f"UVFITS journal worker failed: {exc}")

    def _start_locked(self):
        try:
            config = self._make_config_locked()
            config.validate_for_science_recording()
            outputs = unique_observation_paths(config)
            self._journal_conn = init_journal(outputs["journal"], config, outputs)
            self._queue = queue.Queue(maxsize=max(1, int(self.queue_max_records)))
            self._stop_event = threading.Event()
            self._outputs = outputs
            self._config = config
            self._journal_path = outputs["journal"]
            self._current_file = str(outputs["uvfits"])
            self._records_captured = 0
            self._worker = threading.Thread(target=self._worker_main, name="stage10-uvfits-writer", daemon=True)
            self._worker.start()
            self._set_state_locked(STATE_RECORDING, f"UVFITS recording started: {self._current_file}")
        except Exception as exc:
            self._desired_recording = False
            self.record_uvfits = False
            self._set_state_locked(STATE_ERROR, str(exc))

    def _finalize_locked(self):
        if self._state != STATE_RECORDING:
            return
        self._set_state_locked(STATE_FINALIZING, "UVFITS recording finalizing.")
        queue_ref = self._queue
        worker_ref = self._worker
        journal_conn = self._journal_conn
        journal_path = self._journal_path
        outputs = self._outputs
        self._desired_recording = False
        self.record_uvfits = False

        if queue_ref is not None:
            queue_ref.put(None)
        if worker_ref is not None:
            worker_ref.join(timeout=30.0)
        try:
            if journal_conn is not None:
                journal_conn.close()
            if journal_path is None or outputs is None:
                raise RuntimeError("Stage 10 finalization missing journal/output paths.")
            finalize_journal(journal_path, outputs["uvfits"], outputs["diagnostics_csv"])
            try:
                import os

                os.remove(journal_path)
            except OSError:
                pass
            self._set_state_locked(STATE_COMPLETE, f"UVFITS recording complete: {outputs['uvfits']}")
        except Exception as exc:
            self._set_state_locked(STATE_ERROR, f"UVFITS finalization failed: {exc}")
        finally:
            self._queue = None
            self._worker = None
            self._journal_conn = None

    def _config_has_changed_locked(self):
        if self._config is None:
            return False
        return self._make_config_locked() != self._config

    def _set_and_stop_if_changed(self, name, value, cast):
        with self._lock:
            old_config = self._config
            setattr(self, name, cast(value))
            if self._state == STATE_RECORDING and old_config is not None and self._config_has_changed_locked():
                print("Stage 10 recording stopped because observation configuration changed.", flush=True)
                self._finalize_locked()

    def set_record_uvfits(self, value):
        with self._lock:
            desired = self._as_bool(value)
            if desired and self._state != STATE_RECORDING:
                self._desired_recording = True
                self.record_uvfits = True
                self._start_locked()
            elif not desired and self._state == STATE_RECORDING:
                self._finalize_locked()
            else:
                self._desired_recording = desired
                self.record_uvfits = desired

    def set_observation_name(self, value):
        self._set_and_stop_if_changed("observation_name", value, str)

    def set_uvfits_output_dir(self, value):
        self._set_and_stop_if_changed("uvfits_output_dir", value, str)

    def set_source_mode(self, value):
        self._set_and_stop_if_changed("source_mode", value, int)

    def set_manual_ra_hours(self, value):
        self._set_and_stop_if_changed("manual_ra_hours", value, float)

    def set_manual_dec_deg(self, value):
        self._set_and_stop_if_changed("manual_dec_deg", value, float)

    def set_sky_cf_hz(self, value):
        self._set_and_stop_if_changed("sky_cf_hz", value, float)

    def set_baseline_e_m(self, value):
        self._set_and_stop_if_changed("baseline_e_m", value, float)

    def set_baseline_n_m(self, value):
        self._set_and_stop_if_changed("baseline_n_m", value, float)

    def set_baseline_u_m(self, value):
        self._set_and_stop_if_changed("baseline_u_m", value, float)

    def work(self, input_items, output_items):
        vis_in, coherence_in, effective_integration_in, samples_in = input_items
        state_out, records_out = output_items
        nout = len(vis_in)
        with self._lock:
            if self.record_uvfits and self._state not in (STATE_RECORDING, STATE_FINALIZING):
                self._start_locked()
            state = self._state
            queue_ref = self._queue
            config = self._config

        for idx in range(nout):
            if state == STATE_RECORDING and queue_ref is not None and config is not None:
                try:
                    record = make_visibility_record(
                        config,
                        vis_in[idx],
                        coherence_in[idx],
                        effective_integration_in[idx],
                        samples_in[idx],
                    )
                    queue_ref.put_nowait(record)
                except queue.Full:
                    with self._lock:
                        self.record_uvfits = False
                        self._desired_recording = False
                        self._set_state_locked(STATE_ERROR, "Stage 10 queue overflow: observation journal retained.")
                    state = STATE_ERROR
                except Exception as exc:
                    with self._lock:
                        self.record_uvfits = False
                        self._desired_recording = False
                        self._set_state_locked(STATE_ERROR, f"Stage 10 recording error: {exc}")
                    state = STATE_ERROR
            with self._lock:
                state_out[idx] = np.float32(self._state)
                records_out[idx] = np.float32(self._records_captured)
        return nout

    def stop(self):
        with self._lock:
            if self._state == STATE_RECORDING:
                self._finalize_locked()
        return True
