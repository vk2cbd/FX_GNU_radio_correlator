import numpy as np
from gnuradio import gr


class blk(gr.sync_block):
    """Stage 8 centre-frequency geometric fringe-stop corrector.

    Uses Stage-6 tau_g, not RX1-RX0 arrival delay. The default sign is
    exp(-j*2*pi*sky_cf*tau_g), matching the project geometric phase convention.
    """

    def __init__(self, sky_cf=4.800e9, fringe_stop_enable=True, fringe_stop_sign=-1):
        self.sky_cf = float(sky_cf)
        self.fringe_stop_enable = self._as_bool(fringe_stop_enable)
        self.fringe_stop_sign = int(fringe_stop_sign)
        gr.sync_block.__init__(
            self,
            name='Fringe Stop Corrector',
            in_sig=[np.complex64, np.float32],
            out_sig=[np.complex64],
        )

    @staticmethod
    def _as_bool(value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "enable", "enabled")
        return bool(value)

    def set_sky_cf(self, value):
        self.sky_cf = float(value)

    def set_fringe_stop_enable(self, value):
        self.fringe_stop_enable = self._as_bool(value)

    def set_fringe_stop_sign(self, value):
        self.fringe_stop_sign = int(value)

    def work(self, input_items, output_items):
        unstopped = input_items[0]
        tau_g_ns = input_items[1]
        stopped = output_items[0]
        nout = len(unstopped)

        if not self.fringe_stop_enable:
            stopped[:nout] = unstopped
            return nout

        sky_cf = float(self.sky_cf)
        sign = int(self.fringe_stop_sign)
        if sign not in (-1, 1) or not np.isfinite(sky_cf):
            stopped[:nout] = unstopped
            return nout

        for i in range(nout):
            tau_ns = float(tau_g_ns[i])
            if not np.isfinite(tau_ns):
                stopped[i] = unstopped[i]
                continue

            tau_s = tau_ns * 1e-9
            rotation = np.exp(1j * sign * 2.0 * np.pi * sky_cf * tau_s)
            stopped[i] = np.complex64(unstopped[i] * rotation)

        return nout
