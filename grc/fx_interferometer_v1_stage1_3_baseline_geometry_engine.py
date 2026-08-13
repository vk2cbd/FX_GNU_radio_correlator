import math

import numpy as np
from gnuradio import gr


C_M_S = 299792458.0


class blk(gr.sync_block):
    """Stage 6 baseline geometry and predicted geometric quantities."""

    def __init__(
        self,
        site_lat_deg=-32.724,
        baseline_e_m=-5.785,
        baseline_n_m=0.095,
        baseline_u_m=0.580,
        sky_cf=4.800e9,
    ):
        self.site_lat_deg = float(site_lat_deg)
        self.baseline_e_m = float(baseline_e_m)
        self.baseline_n_m = float(baseline_n_m)
        self.baseline_u_m = float(baseline_u_m)
        self.sky_cf = float(sky_cf)
        self._last_utc_hour = None
        self._last_tau_s = None
        self._last_fringe_hz = np.nan
        self._last_period_s = np.nan
        gr.sync_block.__init__(
            self,
            name='Baseline Geometry Engine',
            in_sig=[np.float32, np.float32, np.float32],
            out_sig=[
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
            ],
        )

    def set_site_lat_deg(self, value):
        self.site_lat_deg = float(value)

    def set_baseline_e_m(self, value):
        self.baseline_e_m = float(value)

    def set_baseline_n_m(self, value):
        self.baseline_n_m = float(value)

    def set_baseline_u_m(self, value):
        self.baseline_u_m = float(value)

    def set_sky_cf(self, value):
        self.sky_cf = float(value)

    @staticmethod
    def _wrap_deg_pm180(angle_deg):
        return ((angle_deg + 180.0) % 360.0) - 180.0

    @staticmethod
    def _delta_utc_seconds(utc_hour, prev_utc_hour):
        delta_h = utc_hour - prev_utc_hour
        if delta_h <= -12.0:
            delta_h += 24.0
        elif delta_h > 12.0:
            delta_h -= 24.0
        return delta_h * 3600.0

    def _compute_geometry(self, utc_hour, ha_hour, apparent_dec_deg):
        site_lat_deg = float(self.site_lat_deg)
        baseline = np.array(
            [
                float(self.baseline_e_m),
                float(self.baseline_n_m),
                float(self.baseline_u_m),
            ],
            dtype=np.float64,
        )
        sky_cf = float(self.sky_cf)

        phi = math.radians(site_lat_deg)
        h = math.radians(float(ha_hour) * 15.0)
        dec = math.radians(float(apparent_dec_deg))

        u_hat = np.array(
            [
                math.cos(h),
                -math.sin(phi) * math.sin(h),
                math.cos(phi) * math.sin(h),
            ],
            dtype=np.float64,
        )
        v_hat = np.array(
            [
                math.sin(dec) * math.sin(h),
                math.cos(phi) * math.cos(dec)
                + math.sin(phi) * math.sin(dec) * math.cos(h),
                math.sin(phi) * math.cos(dec)
                - math.cos(phi) * math.sin(dec) * math.cos(h),
            ],
            dtype=np.float64,
        )
        w_hat = np.array(
            [
                -math.cos(dec) * math.sin(h),
                math.sin(dec) * math.cos(phi)
                - math.cos(dec) * math.cos(h) * math.sin(phi),
                math.sin(dec) * math.sin(phi)
                + math.cos(dec) * math.cos(h) * math.cos(phi),
            ],
            dtype=np.float64,
        )

        u_m = float(np.dot(baseline, u_hat))
        v_m = float(np.dot(baseline, v_hat))
        w_m = float(np.dot(baseline, w_hat))
        tau_s = w_m / C_M_S
        tau_ns = tau_s * 1e9
        arrival_delay_10_ns = -tau_ns
        phase_deg = self._wrap_deg_pm180(360.0 * sky_cf * tau_s)

        fringe_hz = self._last_fringe_hz
        period_s = self._last_period_s
        if self._last_utc_hour is not None and self._last_tau_s is not None:
            dt_s = self._delta_utc_seconds(float(utc_hour), self._last_utc_hour)
            if dt_s > 1e-6:
                fringe_hz = sky_cf * (tau_s - self._last_tau_s) / dt_s
                if abs(fringe_hz) > 1e-12:
                    period_s = 1.0 / abs(fringe_hz)
                else:
                    period_s = math.inf
                self._last_fringe_hz = fringe_hz
                self._last_period_s = period_s

        if self._last_utc_hour is None or abs(self._delta_utc_seconds(float(utc_hour), self._last_utc_hour)) > 1e-6:
            self._last_utc_hour = float(utc_hour)
            self._last_tau_s = tau_s

        return np.array(
            [
                u_m,
                v_m,
                w_m,
                tau_ns,
                arrival_delay_10_ns,
                phase_deg,
                fringe_hz,
                period_s,
            ],
            dtype=np.float32,
        )

    def work(self, input_items, output_items):
        nout = len(input_items[0])
        for i in range(nout):
            try:
                values = self._compute_geometry(
                    float(input_items[0][i]),
                    float(input_items[1][i]),
                    float(input_items[2][i]),
                )
            except Exception as exc:
                print(f"Stage 6 baseline geometry error: {exc}", flush=True)
                values = np.full(8, np.nan, dtype=np.float32)

            for out_idx, value in enumerate(values):
                output_items[out_idx][i] = value

        return nout
