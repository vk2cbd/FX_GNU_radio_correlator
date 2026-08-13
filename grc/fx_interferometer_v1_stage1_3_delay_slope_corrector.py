import numpy as np
from gnuradio import gr


class blk(gr.sync_block):
    """Stage 7 frequency-domain delay-slope corrector.

    Input C01 uses the fixed convention C01 = X0 * conj(X1).
    Positive delay means RX1 is delayed relative to RX0 and produces a
    positive phase slope versus increasing B210 baseband/IF frequency.
    This block removes that slope using exp(-j*2*pi*f_bb*tau).
    The centre FFT bin is not rotated because f_bb[centre] = 0.
    """

    def __init__(
        self,
        fft_size=4096,
        samp_rate=30.72e6,
        instrument_delay_ns=0.0,
        delay_correction_enable=True,
    ):
        self.fft_size = int(fft_size)
        self.samp_rate = float(samp_rate)
        self.instrument_delay_ns = float(instrument_delay_ns)
        self.delay_correction_enable = self._as_bool(delay_correction_enable)
        gr.sync_block.__init__(
            self,
            name='Delay Slope Corrector',
            in_sig=[(np.complex64, self.fft_size), np.float32],
            out_sig=[(np.complex64, self.fft_size)],
        )
        self._f_bb = (
            (np.arange(self.fft_size, dtype=np.float64) - self.fft_size / 2.0)
            * self.samp_rate
            / self.fft_size
        )

    @staticmethod
    def _as_bool(value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "enable", "enabled")
        return bool(value)

    def set_instrument_delay_ns(self, value):
        self.instrument_delay_ns = float(value)

    def set_delay_correction_enable(self, value):
        self.delay_correction_enable = self._as_bool(value)

    def work(self, input_items, output_items):
        spectra = input_items[0]
        geo_arrival_ns = input_items[1]
        corrected = output_items[0]
        nout = len(spectra)

        if not self.delay_correction_enable:
            corrected[:nout] = spectra
            return nout

        instrument_delay_ns = float(self.instrument_delay_ns)
        if not np.isfinite(instrument_delay_ns):
            corrected[:nout] = spectra
            return nout

        for i in range(nout):
            tau_geo_ns = float(geo_arrival_ns[i])
            if not np.isfinite(tau_geo_ns):
                corrected[i] = spectra[i]
                continue

            tau_apply_s = (tau_geo_ns + instrument_delay_ns) * 1e-9
            rotation = np.exp((-1j * 2.0 * np.pi * self._f_bb * tau_apply_s)).astype(np.complex64)
            corrected[i] = spectra[i] * rotation

        return nout
