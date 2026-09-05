import os
import queue
import socket
import sys
import threading
import inspect
import weakref

import numpy as np
from gnuradio import gr


for _path in [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools")) if "__file__" in globals() else "",
    os.path.abspath("tools"),
    os.path.abspath(os.path.join(os.getcwd(), "tools")),
]:
    if _path and os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

from stage10_protocol import DEFAULT_HOST, DEFAULT_PORT, encode_packet, packet_from_visibility


GRC_PARAMETER_NAMES = (
    "source_mode",
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
    "instrument_delay_ns",
    "delay_correction_enable",
    "fringe_stop_enable",
    "fringe_stop_sign",
    "stokes_code",
    "polarization_label",
    "polarization_assumed",
)


class blk(gr.sync_block):
    """Stage 10A localhost JSON visibility publisher.

    This block never opens a FITS file and never owns observation state.
    """

    def __init__(
        self,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
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
        stokes_code=-5,
        polarization_label="XX",
        polarization_assumed=True,
    ):
        gr.sync_block.__init__(
            self,
            name="Stage 10 Visibility Publisher",
            in_sig=[np.complex64, np.float32, np.float32, np.float32],
            out_sig=[np.float32],
        )
        self.host = str(host)
        self.port = int(port)
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=256)
        self._sequence = 0
        self._connected = False
        self._stopping = False
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
        self.delay_correction_enable = self._as_bool(delay_correction_enable)
        self.fringe_stop_enable = self._as_bool(fringe_stop_enable)
        self.fringe_stop_sign = int(fringe_stop_sign)
        self.stokes_code = int(stokes_code)
        self.polarization_label = str(polarization_label)
        self.polarization_assumed = self._as_bool(polarization_assumed)
        self._grc_owner_ref = self._capture_grc_owner()
        self._refresh_from_grc_owner_locked()
        self._thread = threading.Thread(target=self._server_loop, name="stage10-publisher", daemon=True)
        self._thread.start()

    def stop(self):
        self._stopping = True

    def _as_bool(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
        return bool(value)

    def _capture_grc_owner(self):
        frame = inspect.currentframe()
        if frame is None:
            return None
        try:
            caller = frame.f_back
            while caller is not None:
                owner = caller.f_locals.get("self")
                if owner is not None and owner is not self and any(
                    hasattr(owner, name) for name in GRC_PARAMETER_NAMES
                ):
                    try:
                        return weakref.ref(owner)
                    except TypeError:
                        return None
                caller = caller.f_back
        finally:
            del frame
        return None

    def _owner_value(self, owner, name):
        if name == "sky_cf_hz" and not hasattr(owner, "sky_cf_hz") and hasattr(owner, "sky_cf"):
            return getattr(owner, "sky_cf")
        return getattr(owner, name)

    def _refresh_from_grc_owner_locked(self):
        owner = self._grc_owner_ref() if self._grc_owner_ref is not None else None
        if owner is None:
            return
        for name in GRC_PARAMETER_NAMES:
            attr_name = "sky_cf_hz" if name == "sky_cf_hz" else name
            if name == "sky_cf_hz" and not hasattr(owner, "sky_cf_hz") and not hasattr(owner, "sky_cf"):
                continue
            if name != "sky_cf_hz" and not hasattr(owner, name):
                continue
            value = self._owner_value(owner, name)
            if name in ("source_mode", "fft_size", "fringe_stop_sign", "stokes_code"):
                setattr(self, attr_name, int(value))
            elif name in ("delay_correction_enable", "fringe_stop_enable", "polarization_assumed"):
                setattr(self, attr_name, self._as_bool(value))
            elif name == "polarization_label":
                setattr(self, attr_name, str(value))
            else:
                setattr(self, attr_name, float(value))

    def _config_snapshot(self):
        with self._lock:
            self._refresh_from_grc_owner_locked()
            return {
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
                "stokes_code": self.stokes_code,
                "polarization_label": self.polarization_label,
                "polarization_assumed": self.polarization_assumed,
            }

    def _server_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(1)
        server.settimeout(0.5)
        print(f"Stage 10 visibility publisher listening on {self.host}:{self.port}", flush=True)
        try:
            while not self._stopping:
                try:
                    client, addr = server.accept()
                except socket.timeout:
                    continue
                print(f"Stage 10 logger connected from {addr[0]}:{addr[1]}", flush=True)
                with self._lock:
                    self._connected = True
                client.settimeout(0.5)
                try:
                    while not self._stopping:
                        try:
                            packet = self._queue.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        client.sendall(encode_packet(packet))
                except OSError:
                    pass
                finally:
                    with self._lock:
                        self._connected = False
                    try:
                        client.close()
                    except OSError:
                        pass
                    while not self._queue.empty():
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
                    print("Stage 10 logger disconnected", flush=True)
        finally:
            server.close()

    def work(self, input_items, output_items):
        nout = min(len(input_items[0]), len(output_items[0]))
        for idx in range(nout):
            with self._lock:
                sequence = self._sequence
                self._sequence += 1
                connected = self._connected
            if connected:
                packet = packet_from_visibility(
                    sequence,
                    complex(input_items[0][idx]),
                    float(input_items[1][idx]),
                    float(input_items[2][idx]),
                    float(input_items[3][idx]),
                    self._config_snapshot(),
                )
                try:
                    self._queue.put_nowait(packet)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(packet)
                    except queue.Empty:
                        pass
            output_items[0][idx] = np.float32(1.0 if connected else 0.0)
        return nout

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
            self.delay_correction_enable = self._as_bool(value)

    def set_fringe_stop_enable(self, value):
        with self._lock:
            self.fringe_stop_enable = self._as_bool(value)

    def set_fringe_stop_sign(self, value):
        with self._lock:
            self.fringe_stop_sign = int(value)

    def set_stokes_code(self, value):
        with self._lock:
            self.stokes_code = int(value)

    def set_polarization_label(self, value):
        with self._lock:
            self.polarization_label = str(value)

    def set_polarization_assumed(self, value):
        with self._lock:
            self.polarization_assumed = self._as_bool(value)
