import math
import pathlib
import unittest

import numpy as np
import yaml


FFT_SIZE = 4096
SAMP_RATE = 30.72e6


def phase_fit(cross_spectrum, edge_exclude_pct):
    freq_hz = (np.arange(len(cross_spectrum), dtype=np.float64) - len(cross_spectrum) / 2.0) * (
        SAMP_RATE / len(cross_spectrum)
    )
    edge_pct = float(edge_exclude_pct)
    if edge_pct < 0.0:
        edge_pct = 0.0
    elif edge_pct >= 50.0:
        edge_pct = 49.0
    n_edge = int(len(cross_spectrum) * (edge_pct / 100.0))
    if len(cross_spectrum) - 2 * n_edge < 2:
        n_edge = 0
    if n_edge > 0:
        cs_fit = cross_spectrum[n_edge:-n_edge]
        freq_fit = freq_hz[n_edge:-n_edge]
    else:
        cs_fit = cross_spectrum
        freq_fit = freq_hz

    phase = np.unwrap(np.angle(cs_fit)).astype(np.float64)
    slope, intercept = np.polyfit(freq_fit, phase, 1)
    residual = phase - (slope * freq_fit + intercept)
    return {
        "n_edge": n_edge,
        "n_fit": len(cs_fit),
        "slope_deg_per_mhz": slope * (180.0 / np.pi) * 1e6,
        "delay_ns": (slope / (2.0 * np.pi)) * 1e9,
        "rms_deg": np.sqrt(np.mean(residual * residual)) * (180.0 / np.pi),
    }


def synthetic_cross_spectrum(delay_ns=13.795115, edge_phase_error_deg=60.0):
    freq_hz = (np.arange(FFT_SIZE, dtype=np.float64) - FFT_SIZE / 2.0) * (SAMP_RATE / FFT_SIZE)
    tau_s = delay_ns * 1e-9
    phase = 2.0 * np.pi * freq_hz * tau_s
    edge_bins = int(FFT_SIZE * 0.05)
    phase[:edge_bins] += np.deg2rad(edge_phase_error_deg)
    phase[-edge_bins:] -= np.deg2rad(edge_phase_error_deg)
    return np.exp(1j * phase).astype(np.complex64)


class PhaseFitEdgeExclusionTests(unittest.TestCase):
    def test_expected_fit_bin_counts(self):
        cs = np.ones(FFT_SIZE, dtype=np.complex64)
        cases = [
            (0.0, 0, 4096),
            (5.0, 204, 3688),
            (7.5, 307, 3482),
            (10.0, 409, 3278),
        ]
        for pct, expected_edge, expected_fit in cases:
            result = phase_fit(cs, pct)
            self.assertEqual(result["n_edge"], expected_edge)
            self.assertEqual(result["n_fit"], expected_fit)

    def test_delay_sign_and_scaling_are_preserved(self):
        cs = synthetic_cross_spectrum(edge_phase_error_deg=0.0)
        result = phase_fit(cs, 7.5)
        self.assertAlmostEqual(result["slope_deg_per_mhz"], 4.9662414, places=5)
        self.assertAlmostEqual(result["delay_ns"], result["slope_deg_per_mhz"] * 1000.0 / 360.0, places=9)
        self.assertGreater(result["delay_ns"], 0.0)

    def test_edge_cropping_reduces_edge_corruption_rms_without_changing_delay_much(self):
        cs = synthetic_cross_spectrum()
        full = phase_fit(cs, 0.0)
        cropped = phase_fit(cs, 7.5)
        self.assertLess(cropped["rms_deg"], full["rms_deg"])
        self.assertAlmostEqual(cropped["delay_ns"], 13.795115, places=5)

    def test_cropping_occurs_before_unwrap(self):
        freq_hz = (np.arange(FFT_SIZE, dtype=np.float64) - FFT_SIZE / 2.0) * (SAMP_RATE / FFT_SIZE)
        tau_s = 4e-9
        phase = 2.0 * np.pi * freq_hz * tau_s
        edge_bins = int(FFT_SIZE * 0.075)
        phase[:edge_bins] = np.linspace(0.0, 20.0 * np.pi, edge_bins)
        phase[-edge_bins:] = np.linspace(-20.0 * np.pi, 0.0, edge_bins)
        cs = np.exp(1j * phase).astype(np.complex64)

        cropped_first = phase_fit(cs, 7.5)
        phase_full = np.unwrap(np.angle(cs)).astype(np.float64)
        freq_fit_after = freq_hz[edge_bins:-edge_bins]
        phase_fit_after = phase_full[edge_bins:-edge_bins]
        slope_after, intercept_after = np.polyfit(freq_fit_after, phase_fit_after, 1)
        rms_after = (
            np.sqrt(np.mean((phase_fit_after - (slope_after * freq_fit_after + intercept_after)) ** 2))
            * 180.0
            / np.pi
        )

        self.assertLess(cropped_first["rms_deg"], rms_after)

    def test_invalid_percentages_are_handled_safely(self):
        cs = synthetic_cross_spectrum(edge_phase_error_deg=0.0)
        negative = phase_fit(cs, -5.0)
        full = phase_fit(cs, 0.0)
        too_large = phase_fit(cs, 50.0)
        self.assertEqual(negative["n_fit"], full["n_fit"])
        self.assertGreaterEqual(too_large["n_fit"], 2)
        for result in (negative, too_large):
            self.assertTrue(math.isfinite(result["delay_ns"]))
            self.assertTrue(math.isfinite(result["rms_deg"]))

    def test_grc_variable_and_stage4_connections(self):
        graph_path = pathlib.Path(__file__).resolve().parents[1] / "grc" / "fx_interferometer_v1_stage9.grc"
        graph = yaml.safe_load(graph_path.read_text())
        blocks = {block["name"]: block for block in graph["blocks"]}
        self.assertEqual(blocks["phase_fit_edge_exclude_pct"]["parameters"]["value"], "7.5")
        estimator = blocks["phase_slope_delay_estimator"]
        self.assertEqual(estimator["parameters"]["phase_fit_edge_exclude_pct"], "phase_fit_edge_exclude_pct")
        source = estimator["parameters"]["_source_code"]
        self.assertIn("c01_fit, f_fit = self._fit_vectors(c01)", source)
        self.assertLess(source.index("c01_fit, f_fit = self._fit_vectors(c01)"), source.index("phase = np.angle(c01_fit)"))
        self.assertLess(source.index("phase = np.angle(c01_fit)"), source.index("np.unwrap(phase)"))

        connections = {tuple(connection) for connection in graph["connections"]}
        self.assertIn(("cross_accum", "0", "cross_mag", "0"), connections)
        self.assertIn(("cross_accum", "0", "cross_phase_rad", "0"), connections)
        self.assertIn(("cross_accum", "0", "phase_slope_delay_estimator", "0"), connections)


if __name__ == "__main__":
    unittest.main()
