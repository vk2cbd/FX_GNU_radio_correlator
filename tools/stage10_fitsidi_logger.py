#!/usr/bin/env python3
import argparse
import math
import os
import queue
import socket
import sys
import threading
from dataclasses import dataclass

from astropy.time import Time

from stage10_fitsidi_writer import FitsIdiWriter, source_metadata, uvw_project_m, validate_fitsidi_file
from stage10_protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    bandwidth_metadata,
    decode_line,
    packet_to_writer_config,
    packet_to_writer_record,
    parse_iso_z,
    verify_packet_metadata,
)


STATE_OFF = "OFF"
STATE_RECORDING = "RECORDING"
STATE_FINALIZING = "FINALIZING"
STATE_COMPLETE = "COMPLETE"
STATE_ERROR = "ERROR"
STATE_ERROR_CONFIG_CHANGED = "ERROR_CONFIG_CHANGED"


OBSERVATION_METADATA_FIELDS = (
    "source_mode",
    "source_name",
    "manual_ra_hours",
    "manual_dec_deg",
    "site_lat_deg",
    "site_lon_deg",
    "site_height_m",
    "baseline_e_m",
    "baseline_n_m",
    "baseline_u_m",
    "sky_cf_hz",
    "samp_rate",
    "fft_size",
    "visibility_edge_exclude_pct",
    "retained_fft_bins",
    "effective_correlated_bandwidth_hz",
    "instrument_delay_ns",
    "delay_correction_enable",
    "fringe_stop_enable",
    "fringe_stop_sign",
    "stokes_code",
    "polarization_label",
    "polarization_assumed",
)


@dataclass
class LiveSummary:
    connected: bool = False
    sequence: int = -1
    source: str = ""
    real: float = math.nan
    imag: float = math.nan
    amp: float = math.nan
    phase_deg: float = math.nan
    u_m: float = math.nan
    v_m: float = math.nan
    w_m: float = math.nan
    edge_pct: float = math.nan
    retained_bins: int = 0
    bandwidth_hz: float = math.nan
    integration_s: float = math.nan
    n_int: int = 0
    emitted_utc: str = ""
    center_utc: str = ""


class Stage10LoggerController:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, observation_name="obs1", output_dir="~/FX_Correlator_Data"):
        self.host = host
        self.port = int(port)
        self.observation_name = observation_name
        self.output_dir = output_dir
        self.state = STATE_OFF
        self.records_written = 0
        self.current_file = ""
        self.last_error = ""
        self.last_packet = None
        self.config_snapshot = None
        self.live = LiveSummary()
        self.writer = None
        self._lock = threading.RLock()
        self._events = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._receiver_loop, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()

    def poll_events(self):
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def start_recording(self):
        with self._lock:
            if self.state == STATE_RECORDING:
                return
            if not self.live.connected:
                raise RuntimeError("publisher is not connected")
            if self.last_packet is None:
                raise RuntimeError("no live Stage 10 packet has been received")
            pkt = dict(self.last_packet)
            verify_packet_metadata(pkt)
            if pkt.get("source_name") == "INVALID":
                raise RuntimeError("source_name is INVALID")
            if not bool(pkt.get("delay_correction_enable")):
                raise RuntimeError("delay correction must be enabled")
            if not bool(pkt.get("fringe_stop_enable")):
                raise RuntimeError("fringe stop must be enabled")
            if int(pkt.get("fringe_stop_sign")) != -1:
                raise RuntimeError("fringe stop sign must be Normal (-phi_geo)")
            config = packet_to_writer_config(pkt, self.observation_name, self.output_dir)
            self.writer = FitsIdiWriter(config)
            self.writer.start()
            self.config_snapshot = self._metadata_snapshot(pkt)
            self.current_file = self.writer.current_file
            self.records_written = 0
            self.state = STATE_RECORDING
            self._events.put(("recording", self.current_file))

    def stop_recording(self):
        with self._lock:
            if self.state != STATE_RECORDING:
                return self.current_file
            writer = self.writer
            self.state = STATE_FINALIZING
        final_path = writer.stop()
        validate_fitsidi_file(final_path, expected_records=writer.records_written)
        with self._lock:
            self.current_file = final_path
            self.records_written = writer.records_written
            self.state = STATE_COMPLETE
            self.config_snapshot = None
            self._events.put(("complete", final_path))
        return final_path

    def _receiver_loop(self):
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=2.0) as sock:
                    with self._lock:
                        self.live.connected = True
                    self._events.put(("connected", f"{self.host}:{self.port}"))
                    fileobj = sock.makefile("rb")
                    for raw in fileobj:
                        if self._stop.is_set():
                            break
                        try:
                            packet = decode_line(raw)
                            self._handle_packet(packet)
                        except Exception as exc:
                            with self._lock:
                                self.last_error = str(exc)
                            self._events.put(("error", str(exc)))
            except OSError as exc:
                with self._lock:
                    self.live.connected = False
                self._events.put(("disconnected", str(exc)))
                self._stop.wait(1.0)
            finally:
                with self._lock:
                    self.live.connected = False

    def _handle_packet(self, packet):
        try:
            verify_packet_metadata(packet)
        except Exception as exc:
            with self._lock:
                self.last_error = str(exc)
            self._events.put(("error", str(exc)))
            return
        real = float(packet["visibility_real"])
        imag = float(packet["visibility_imag"])
        amp = math.hypot(real, imag)
        phase = math.degrees(math.atan2(imag, real))
        u_m, v_m, w_m = self._packet_uvw(packet)
        with self._lock:
            self.last_packet = packet
            self.live = LiveSummary(
                connected=True,
                sequence=int(packet["sequence"]),
                source=str(packet["source_name"]),
                real=real,
                imag=imag,
                amp=amp,
                phase_deg=phase,
                u_m=u_m,
                v_m=v_m,
                w_m=w_m,
                edge_pct=float(packet["visibility_edge_exclude_pct"]),
                retained_bins=int(packet["retained_fft_bins"]),
                bandwidth_hz=float(packet["effective_correlated_bandwidth_hz"]),
                integration_s=float(packet["effective_integration_s"]),
                n_int=int(packet["n_int"]),
                emitted_utc=str(packet["emitted_utc"]),
                center_utc=str(packet["integration_center_utc"]),
            )
            recording = self.state == STATE_RECORDING and self.writer is not None
            writer = self.writer
            snapshot = self.config_snapshot
        if recording:
            mismatch = self._metadata_mismatch(snapshot, packet)
            if mismatch is not None:
                final_path = writer.stop()
                with self._lock:
                    self.current_file = final_path
                    self.records_written = writer.records_written
                    self.state = STATE_ERROR_CONFIG_CHANGED
                    self.last_error = f"observation metadata changed during recording: {mismatch}"
                    self.config_snapshot = None
                self._events.put(("error", self.last_error))
                return
            writer.add_record(packet_to_writer_record(packet))
            with self._lock:
                self.records_written = writer.records_written + len(writer._chunk)
                self.current_file = writer.current_file

    def _packet_uvw(self, packet):
        config = packet_to_writer_config(packet, self.observation_name, self.output_dir)
        t = Time(parse_iso_z(packet["integration_center_utc"]), scale="utc")
        meta = source_metadata(config, t)
        return uvw_project_m(
            meta["ha_hour"],
            meta["apparent_dec_deg"],
            float(packet["baseline_e_m"]),
            float(packet["baseline_n_m"]),
            float(packet["baseline_u_m"]),
            float(packet["site_lat_deg"]),
        )

    def _metadata_snapshot(self, packet):
        return {field: packet[field] for field in OBSERVATION_METADATA_FIELDS}

    def _metadata_mismatch(self, snapshot, packet):
        if snapshot is None:
            return None
        for field, old in snapshot.items():
            new = packet.get(field)
            if isinstance(old, float) or isinstance(new, float):
                try:
                    if not math.isclose(float(old), float(new), rel_tol=1e-9, abs_tol=1e-6):
                        return field
                    continue
                except (TypeError, ValueError):
                    pass
            if old != new:
                return field
        return None

    def live_metadata_text(self):
        with self._lock:
            packet = dict(self.last_packet) if self.last_packet else None
        if not packet:
            return "No live Stage 10 packet has been received."
        derived = bandwidth_metadata(packet["samp_rate"], packet["fft_size"], packet["visibility_edge_exclude_pct"])
        lines = [
            f"schema_version: {packet['schema_version']}",
            f"metadata_valid: {packet['metadata_valid']}",
            f"source: {packet['source_name']} ({packet['source_mode']})",
            f"site: lat={packet['site_lat_deg']} lon={packet['site_lon_deg']} height={packet['site_height_m']} m",
            f"baseline ENU: E={packet['baseline_e_m']} N={packet['baseline_n_m']} U={packet['baseline_u_m']} m",
            f"sky_cf_hz: {packet['sky_cf_hz']}",
            f"samp_rate: {packet['samp_rate']}",
            f"fft_size: {packet['fft_size']}",
            f"visibility_edge_exclude_pct: {packet['visibility_edge_exclude_pct']}",
            f"retained_fft_bins: {packet['retained_fft_bins']} (local check {derived['retained_fft_bins']})",
            "effective_correlated_bandwidth_hz: "
            f"{packet['effective_correlated_bandwidth_hz']} (local check {derived['effective_correlated_bandwidth_hz']})",
            f"instrument_delay_ns: {packet['instrument_delay_ns']}",
            f"delay_correction_enable: {packet['delay_correction_enable']}",
            f"fringe_stop_enable: {packet['fringe_stop_enable']}",
            f"fringe_stop_sign: {packet['fringe_stop_sign']}",
            f"stokes_code: {packet['stokes_code']}",
            f"polarization_label: {packet['polarization_label']}",
            f"polarization_assumed: {packet['polarization_assumed']}",
            f"effective_integration_s: {packet['effective_integration_s']}",
            f"n_int: {packet['n_int']}",
            f"emitted_utc: {packet['emitted_utc']}",
            f"integration_center_utc: {packet['integration_center_utc']}",
        ]
        return "\n".join(lines)


def run_console(args):
    controller = Stage10LoggerController(args.host, args.port, args.observation, args.output_dir)
    print("Stage 10 FITS-IDI logger started. Commands: start, stop, status, quit")
    try:
        while True:
            command = input("> ").strip().lower()
            try:
                if command == "start":
                    controller.start_recording()
                elif command == "stop":
                    controller.stop_recording()
                elif command in ("quit", "exit"):
                    if controller.state == STATE_RECORDING:
                        controller.stop_recording()
                    return
                elif command == "status":
                    pass
                elif command in ("metadata", "meta"):
                    print(controller.live_metadata_text())
                    continue
                else:
                    print("Commands: start, stop, status, metadata, quit")
                    continue
            except Exception as exc:
                controller.last_error = str(exc)
                print(f"ERROR: {exc}")
            with controller._lock:
                live = controller.live
                print(
                    f"connected={live.connected} state={controller.state} "
                    f"seq={live.sequence} source={live.source} "
                    f"vis={live.real:.6g}+j{live.imag:.6g} amp={live.amp:.6g} "
                    f"phase={live.phase_deg:.3f} u/v/w={live.u_m:.3f},{live.v_m:.3f},{live.w_m:.3f} "
                    f"records={controller.records_written} file={controller.current_file}"
                )
    finally:
        controller.close()


def run_qt(args):
    try:
        from PyQt5 import QtCore, QtWidgets
    except Exception:
        run_console(args)
        return

    app = QtWidgets.QApplication(sys.argv)
    controller = Stage10LoggerController(args.host, args.port, args.observation, args.output_dir)
    window = QtWidgets.QWidget()
    window.setWindowTitle("Stage 10 FITS-IDI Logger")
    form = QtWidgets.QFormLayout(window)
    fields = {}
    for name in [
        "Publisher Connection",
        "Live Source",
        "Live Sequence",
        "Live Visibility Real",
        "Live Visibility Imag",
        "Live Visibility Amplitude",
        "Live Visibility Phase",
        "Live u",
        "Live v",
        "Live w",
        "Edge Exclusion",
        "Retained FFT Bins",
        "Effective Correlated BW",
        "Effective Integration",
        "N_int",
        "Emitted UTC",
        "Integration Centre UTC",
        "Recording State",
        "Records Written",
        "Current File",
        "Last Error",
    ]:
        label = QtWidgets.QLabel("")
        fields[name] = label
        form.addRow(name + ":", label)
    obs = QtWidgets.QLineEdit(args.observation)
    out = QtWidgets.QLineEdit(os.path.expanduser(args.output_dir))
    form.addRow("Observation Name:", obs)
    form.addRow("Output Directory:", out)
    button = QtWidgets.QPushButton("Start FITS-IDI Recording")
    form.addRow(button)
    metadata_button = QtWidgets.QPushButton("Print Live Metadata")
    form.addRow(metadata_button)

    def on_button():
        controller.observation_name = obs.text().strip() or "obs1"
        controller.output_dir = out.text().strip() or "~/FX_Correlator_Data"
        try:
            if controller.state == STATE_RECORDING:
                controller.stop_recording()
            else:
                controller.start_recording()
        except Exception as exc:
            controller.last_error = str(exc)

    button.clicked.connect(on_button)

    def on_metadata():
        print(controller.live_metadata_text(), flush=True)

    metadata_button.clicked.connect(on_metadata)

    def update():
        with controller._lock:
            live = controller.live
            fields["Publisher Connection"].setText("Connected" if live.connected else "Disconnected")
            fields["Live Source"].setText(live.source)
            fields["Live Sequence"].setText(str(live.sequence))
            fields["Live Visibility Real"].setText(f"{live.real:.9g}")
            fields["Live Visibility Imag"].setText(f"{live.imag:.9g}")
            fields["Live Visibility Amplitude"].setText(f"{live.amp:.9g}")
            fields["Live Visibility Phase"].setText(f"{live.phase_deg:.6f} deg")
            fields["Live u"].setText(f"{live.u_m:.6f} m")
            fields["Live v"].setText(f"{live.v_m:.6f} m")
            fields["Live w"].setText(f"{live.w_m:.6f} m")
            fields["Edge Exclusion"].setText(f"{live.edge_pct:.6g} %")
            fields["Retained FFT Bins"].setText(str(live.retained_bins))
            fields["Effective Correlated BW"].setText(f"{live.bandwidth_hz / 1e6:.6f} MHz")
            fields["Effective Integration"].setText(f"{live.integration_s:.6g} s")
            fields["N_int"].setText(str(live.n_int))
            fields["Emitted UTC"].setText(live.emitted_utc)
            fields["Integration Centre UTC"].setText(live.center_utc)
            fields["Recording State"].setText(controller.state)
            fields["Records Written"].setText(str(controller.records_written))
            fields["Current File"].setText(controller.current_file)
            fields["Last Error"].setText(controller.last_error)
            button.setText("Stop FITS-IDI Recording" if controller.state == STATE_RECORDING else "Start FITS-IDI Recording")

    timer = QtCore.QTimer()
    timer.timeout.connect(update)
    timer.start(250)
    window.resize(720, 420)
    window.show()
    rc = app.exec_()
    if controller.state == STATE_RECORDING:
        controller.stop_recording()
    controller.close()
    sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Standalone Stage 10 FITS-IDI logger.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--observation", default="obs1")
    parser.add_argument("--output-dir", default="~/FX_Correlator_Data")
    parser.add_argument("--console", action="store_true")
    args = parser.parse_args()
    if args.console:
        run_console(args)
    else:
        run_qt(args)


if __name__ == "__main__":
    main()
