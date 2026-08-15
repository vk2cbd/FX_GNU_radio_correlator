import math
import threading

import numpy as np
from gnuradio import gr


class blk(gr.basic_block):
    """Stage 9 non-overlapping coherent visibility integrator.

    Consumes native Stage-8 V_stopped samples and emits one complex mean for
    each complete integration window. Runtime integration changes reset the
    partial window so samples from different integration lengths are not mixed.
    """

    def __init__(self, visibility_rate=10.0, integration_time_s=1.0):
        self.visibility_rate = float(visibility_rate)
        self.integration_time_s = float(integration_time_s)
        self._lock = threading.RLock()
        self._window = []
        self._n_int = self._calc_n_int()
        self._warned_quantization = False
        gr.basic_block.__init__(
            self,
            name='Coherent Visibility Integrator',
            in_sig=[np.complex64],
            out_sig=[np.complex64, np.float32, np.float32, np.float32],
        )

    @staticmethod
    def _finite_complex(value):
        return np.isfinite(value.real) and np.isfinite(value.imag)

    @staticmethod
    def _nearest_int(value):
        return int(math.floor(float(value) + 0.5))

    def _calc_n_int(self):
        rate = float(self.visibility_rate)
        integ = float(self.integration_time_s)
        if not np.isfinite(rate) or rate <= 0.0:
            rate = 1.0
        if not np.isfinite(integ) or integ <= 0.0:
            integ = 0.1
        return max(1, self._nearest_int(integ * rate))

    def _effective_integration_s(self):
        rate = float(self.visibility_rate)
        if not np.isfinite(rate) or rate <= 0.0:
            rate = 1.0
        return float(self._n_int) / rate

    def _reset_locked(self):
        self._window = []
        self._n_int = self._calc_n_int()
        self._warned_quantization = False

    def _warn_quantization_locked(self):
        requested = float(self.integration_time_s)
        effective = self._effective_integration_s()
        if (
            not self._warned_quantization
            and np.isfinite(requested)
            and abs(requested - effective) > 1e-6
        ):
            print(
                f"Stage 9 integration warning: requested {requested:.6g} s, effective {effective:.6g} s "
                f"from {self._n_int} native visibility samples.",
                flush=True,
            )
            self._warned_quantization = True

    def set_visibility_rate(self, value):
        with self._lock:
            self.visibility_rate = float(value)
            self._reset_locked()

    def set_integration_time_s(self, value):
        with self._lock:
            self.integration_time_s = float(value)
            self._reset_locked()

    def forecast(self, noutput_items, ninputs):
        return [1] * ninputs

    def general_work(self, input_items, output_items):
        samples = input_items[0]
        vis_out = output_items[0]
        coherence_out = output_items[1]
        effective_out = output_items[2]
        n_int_out = output_items[3]

        produced = 0
        consumed = 0
        out_capacity = len(vis_out)

        with self._lock:
            n_int = self._calc_n_int()
            if n_int != self._n_int:
                self._reset_locked()
                n_int = self._n_int
            self._warn_quantization_locked()

            for sample in samples:
                if produced >= out_capacity:
                    break

                consumed += 1
                if not self._finite_complex(sample):
                    self._window = []
                    continue

                self._window.append(np.complex64(sample))
                if len(self._window) < n_int:
                    continue

                window = np.asarray(self._window, dtype=np.complex64)
                total = np.sum(window, dtype=np.complex128)
                denom = np.sum(np.abs(window), dtype=np.float64)
                coherence = 100.0 * abs(total) / denom if denom > 0.0 else np.nan

                vis_out[produced] = np.complex64(total / n_int)
                coherence_out[produced] = np.float32(coherence)
                effective_out[produced] = np.float32(self._effective_integration_s())
                n_int_out[produced] = np.float32(n_int)
                produced += 1
                self._window = []

        self.consume(0, consumed)
        return produced
