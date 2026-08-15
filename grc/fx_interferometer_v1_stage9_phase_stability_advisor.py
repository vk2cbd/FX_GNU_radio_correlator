import math
import threading

import numpy as np
from gnuradio import gr


MAX_INTEGRATION_S = 60.0


class blk(gr.sync_block):
    """Stage 9 residual phase-rate and coherence advisor.

    Measures native Stage-8 V_stopped phase history. Outputs are advisory only
    and must not control integration time, fringe-stop sign, geometry, or
    antenna tracking.
    """

    def __init__(
        self,
        visibility_rate=10.0,
        integration_time_s=1.0,
        phase_rate_fit_window_s=60.0,
        coherence_target_pct=95.0,
    ):
        self.visibility_rate = float(visibility_rate)
        self.integration_time_s = float(integration_time_s)
        self.phase_rate_fit_window_s = float(phase_rate_fit_window_s)
        self.coherence_target_pct = float(coherence_target_pct)
        self._history = []
        self._warned_quantization = False
        self._lock = threading.RLock()
        gr.sync_block.__init__(
            self,
            name='Phase Stability Advisor',
            in_sig=[np.complex64],
            out_sig=[
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
            ],
        )

    @staticmethod
    def _finite_complex(value):
        return np.isfinite(value.real) and np.isfinite(value.imag)

    @staticmethod
    def _nearest_int(value):
        return int(math.floor(float(value) + 0.5))

    def _visibility_rate(self):
        rate = float(self.visibility_rate)
        return rate if np.isfinite(rate) and rate > 0.0 else 1.0

    def _n_int(self):
        integ = float(self.integration_time_s)
        if not np.isfinite(integ) or integ <= 0.0:
            integ = 0.1
        return max(1, self._nearest_int(integ * self._visibility_rate()))

    def _effective_integration_s(self):
        return float(self._n_int()) / self._visibility_rate()

    def _history_len(self):
        fit_window = float(self.phase_rate_fit_window_s)
        if not np.isfinite(fit_window) or fit_window <= 0.0:
            fit_window = 60.0
        return max(3, self._nearest_int(fit_window * self._visibility_rate()))

    def _coherence_for_rate(self, omega_rad_s, integration_s):
        x = abs(float(omega_rad_s) * float(integration_s) / 2.0)
        if x < 1e-9:
            return 1.0
        return abs(math.sin(x) / x)

    def _solve_coherence_x(self, target_fraction):
        target = min(max(float(target_fraction), 1e-6), 0.999999)
        lo = 0.0
        hi = math.pi
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            value = math.sin(mid) / mid if mid != 0.0 else 1.0
            if value > target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _recommended_max_s(self, omega_rad_s):
        omega = abs(float(omega_rad_s))
        if omega < 1e-12:
            return MAX_INTEGRATION_S
        target = float(self.coherence_target_pct) / 100.0
        x = self._solve_coherence_x(target)
        return min(MAX_INTEGRATION_S, 2.0 * x / omega)

    def set_visibility_rate(self, value):
        with self._lock:
            self.visibility_rate = float(value)
            self._history = []
            self._warned_quantization = False

    def set_integration_time_s(self, value):
        with self._lock:
            self.integration_time_s = float(value)
            self._warned_quantization = False

    def set_phase_rate_fit_window_s(self, value):
        with self._lock:
            self.phase_rate_fit_window_s = float(value)
            self._history = []

    def set_coherence_target_pct(self, value):
        with self._lock:
            self.coherence_target_pct = float(value)

    def _estimate_locked(self):
        m = self._history_len()
        if len(self._history) < m:
            return (np.nan, np.nan, np.nan, np.nan)

        values = np.asarray(self._history[-m:], dtype=np.complex64)
        phase = np.unwrap(np.angle(values)).astype(np.float64)
        t = np.arange(m, dtype=np.float64) / self._visibility_rate()
        t -= np.mean(t)
        omega, intercept = np.polyfit(t, phase, 1)
        residual = phase - (omega * t + intercept)
        rms_deg = np.sqrt(np.mean(residual * residual)) * 180.0 / np.pi
        rate_deg_s = omega * 180.0 / np.pi
        rate_coherence_pct = 100.0 * self._coherence_for_rate(omega, self._effective_integration_s())
        recommended_s = self._recommended_max_s(omega)
        return (rate_deg_s, rms_deg, rate_coherence_pct, recommended_s)

    def _warn_quantization_locked(self):
        requested = float(self.integration_time_s)
        effective = self._effective_integration_s()
        if (
            not self._warned_quantization
            and np.isfinite(requested)
            and abs(requested - effective) > 1e-6
        ):
            print(
                f"Stage 9 advisor warning: requested {requested:.6g} s, effective {effective:.6g} s "
                f"from {self._n_int()} native visibility samples.",
                flush=True,
            )
            self._warned_quantization = True

    def work(self, input_items, output_items):
        samples = input_items[0]
        rate_out = output_items[0]
        rms_out = output_items[1]
        rate_coherence_out = output_items[2]
        recommended_out = output_items[3]
        requested_out = output_items[4]
        effective_out = output_items[5]
        n_int_out = output_items[6]

        with self._lock:
            self._warn_quantization_locked()
            for i, sample in enumerate(samples):
                if self._finite_complex(sample) and abs(sample) > 0.0:
                    self._history.append(np.complex64(sample))
                    m = self._history_len()
                    if len(self._history) > m:
                        self._history = self._history[-m:]
                else:
                    self._history = []

                rate_deg_s, rms_deg, rate_coherence_pct, recommended_s = self._estimate_locked()
                rate_out[i] = np.float32(rate_deg_s)
                rms_out[i] = np.float32(rms_deg)
                rate_coherence_out[i] = np.float32(rate_coherence_pct)
                recommended_out[i] = np.float32(recommended_s)
                requested_out[i] = np.float32(self.integration_time_s)
                effective_out[i] = np.float32(self._effective_integration_s())
                n_int_out[i] = np.float32(self._n_int())

        return len(samples)
