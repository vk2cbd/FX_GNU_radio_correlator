import numpy as np
from gnuradio import gr


class blk(gr.sync_block):
    """Stage 8 broadband complex visibility combiner.

    Operates on Stage-7 delay-corrected C01 spectra and outputs one complex
    unstopped visibility per accumulated spectrum. The combiner performs a
    coherent complex mean over the retained FFT bins.
    """

    def __init__(self, fft_size=4096, visibility_edge_exclude_pct=20.0):
        self.fft_size = int(fft_size)
        self.visibility_edge_exclude_pct = float(visibility_edge_exclude_pct)
        gr.sync_block.__init__(
            self,
            name='Broadband Visibility Combiner',
            in_sig=[(np.complex64, self.fft_size)],
            out_sig=[np.complex64],
        )

    def set_visibility_edge_exclude_pct(self, value):
        self.visibility_edge_exclude_pct = float(value)

    def _fit_slice(self):
        edge_pct = float(self.visibility_edge_exclude_pct)
        if edge_pct < 0.0:
            print(
                f"Stage 8 visibility warning: edge exclusion {edge_pct}% is below 0%; using 0%.",
                flush=True,
            )
            edge_pct = 0.0
        elif edge_pct >= 50.0:
            print(
                f"Stage 8 visibility warning: edge exclusion {edge_pct}% is >= 50%; using 49%.",
                flush=True,
            )
            edge_pct = 49.0

        n_edge = int(self.fft_size * (edge_pct / 100.0))
        n_used = self.fft_size - 2 * n_edge
        if n_used < 2:
            print(
                f"Stage 8 visibility warning: edge exclusion leaves {n_used} bins; using full spectrum.",
                flush=True,
            )
            n_edge = 0

        if n_edge > 0:
            return slice(n_edge, self.fft_size - n_edge)
        return slice(None)

    def work(self, input_items, output_items):
        spectra = input_items[0]
        visibility = output_items[0]
        use_bins = self._fit_slice()

        for i, spectrum in enumerate(spectra):
            visibility[i] = np.complex64(np.mean(spectrum[use_bins], dtype=np.complex128))

        return len(spectra)
