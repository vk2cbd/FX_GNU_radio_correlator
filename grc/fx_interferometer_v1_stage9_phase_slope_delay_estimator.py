import numpy as np
from gnuradio import gr


class blk(gr.sync_block):
    """Stage 4 phase-slope / differential-delay estimator.

    Fits unwrapped C01 phase against increasing B210 baseband/IF
    frequency. Cross-spectrum convention is C01 = X0 * conj(X1).
    Provisional sign convention: positive RX1 delay relative to RX0
    should produce positive phase slope versus increasing IF/baseband
    frequency and positive reported differential delay.
    """

    def __init__(self, fft_size=4096, samp_rate=30.72e6, phase_fit_edge_exclude_pct=7.5):
        self.fft_size = int(fft_size)
        self.samp_rate = float(samp_rate)
        self.phase_fit_edge_exclude_pct = float(phase_fit_edge_exclude_pct)
        gr.sync_block.__init__(
            self,
            name='Phase Slope / Delay Estimator',
            in_sig=[(np.complex64, self.fft_size)],
            out_sig=[np.float32, np.float32, np.float32],
        )
        self._f = (
            (np.arange(self.fft_size, dtype=np.float64) - self.fft_size / 2.0)
            * self.samp_rate
            / self.fft_size
        )

    def set_phase_fit_edge_exclude_pct(self, value):
        self.phase_fit_edge_exclude_pct = float(value)

    def _fit_vectors(self, c01):
        edge_pct = float(self.phase_fit_edge_exclude_pct)
        if edge_pct < 0.0:
            print(
                f"Stage 4 phase fit warning: edge exclusion {edge_pct}% is below 0%; using 0%.",
                flush=True,
            )
            edge_pct = 0.0
        elif edge_pct >= 50.0:
            print(
                f"Stage 4 phase fit warning: edge exclusion {edge_pct}% is >= 50%; using 49%.",
                flush=True,
            )
            edge_pct = 49.0

        n_bins = len(c01)
        n_edge = int(n_bins * (edge_pct / 100.0))
        n_fit = n_bins - 2 * n_edge
        if n_fit < 2:
            print(
                f"Stage 4 phase fit warning: edge exclusion leaves {n_fit} bins; using full spectrum.",
                flush=True,
            )
            n_edge = 0

        if n_edge > 0:
            return c01[n_edge:-n_edge], self._f[n_edge:-n_edge]
        return c01, self._f

    def work(self, input_items, output_items):
        spectra = input_items[0]
        delay_ns = output_items[0]
        slope_deg_per_mhz = output_items[1]
        fit_rms_deg = output_items[2]

        for i, c01 in enumerate(spectra):
            c01_fit, f_fit = self._fit_vectors(c01)
            phase = np.angle(c01_fit)
            phase_unwrapped = np.unwrap(phase).astype(np.float64)
            slope, intercept = np.polyfit(f_fit, phase_unwrapped, 1)
            phase_fit = slope * f_fit + intercept
            residual = phase_unwrapped - phase_fit

            delay_ns[i] = np.float32((slope / (2.0 * np.pi)) * 1e9)
            slope_deg_per_mhz[i] = np.float32(slope * (180.0 / np.pi) * 1e6)
            fit_rms_deg[i] = np.float32(
                np.sqrt(np.mean(residual * residual)) * (180.0 / np.pi)
            )

        return len(spectra)
