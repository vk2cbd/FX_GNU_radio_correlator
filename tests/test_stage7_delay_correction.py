import math
import pathlib
import subprocess
import unittest

import numpy as np
import yaml


FFT_SIZE = 4096
SAMP_RATE = 30.72e6


def f_bb(fft_size=FFT_SIZE, samp_rate=SAMP_RATE):
    return (np.arange(fft_size, dtype=np.float64) - fft_size / 2.0) * samp_rate / fft_size


def synthetic_cross_spectrum(delay_ns, phi0_rad=0.37):
    freq = f_bb()
    tau_s = delay_ns * 1e-9
    return np.exp(1j * (phi0_rad + 2.0 * np.pi * freq * tau_s)).astype(np.complex64)


def delay_correct(c01, tau_geo_ns, instrument_delay_ns=0.0, enable=True):
    if not enable:
        return np.array(c01, copy=True)
    if not np.isfinite(tau_geo_ns) or not np.isfinite(instrument_delay_ns):
        return np.array(c01, copy=True)
    tau_apply_s = (float(tau_geo_ns) + float(instrument_delay_ns)) * 1e-9
    rotation = np.exp(-1j * 2.0 * np.pi * f_bb(len(c01), SAMP_RATE) * tau_apply_s).astype(np.complex64)
    return c01 * rotation


def estimate_delay_ns(c01):
    phase = np.unwrap(np.angle(c01)).astype(np.float64)
    slope, _ = np.polyfit(f_bb(len(c01), SAMP_RATE), phase, 1)
    return (slope / (2.0 * np.pi)) * 1e9


def load_grc(path="grc/fx_interferometer_v1_stage1_3.grc"):
    return yaml.safe_load(pathlib.Path(path).read_text())


def head_grc():
    data = subprocess.check_output(["git", "show", "HEAD:grc/fx_interferometer_v1_stage1_3.grc"])
    return yaml.safe_load(data)


class Stage7DelayCorrectionTests(unittest.TestCase):
    def test_positive_delay_is_removed(self):
        raw = synthetic_cross_spectrum(+5.0)
        corrected = delay_correct(raw, +5.0)
        self.assertAlmostEqual(estimate_delay_ns(corrected), 0.0, places=5)

    def test_negative_delay_is_removed(self):
        raw = synthetic_cross_spectrum(-5.0)
        corrected = delay_correct(raw, -5.0)
        self.assertAlmostEqual(estimate_delay_ns(corrected), 0.0, places=5)

    def test_geometric_plus_instrument_delay_is_removed(self):
        raw = synthetic_cross_spectrum(+2.0)
        corrected = delay_correct(raw, tau_geo_ns=+3.0, instrument_delay_ns=-1.0)
        self.assertAlmostEqual(estimate_delay_ns(corrected), 0.0, places=5)

    def test_magnitude_is_preserved(self):
        raw = synthetic_cross_spectrum(+7.25)
        corrected = delay_correct(raw, +7.25)
        np.testing.assert_allclose(np.abs(corrected), np.abs(raw), rtol=1e-6, atol=1e-6)

    def test_centre_bin_is_not_rotated(self):
        raw = synthetic_cross_spectrum(-13.0)
        corrected = delay_correct(raw, -13.0)
        centre = FFT_SIZE // 2
        self.assertEqual(f_bb()[centre], 0.0)
        self.assertAlmostEqual(corrected[centre].real, raw[centre].real, places=7)
        self.assertAlmostEqual(corrected[centre].imag, raw[centre].imag, places=7)

    def test_bypass_returns_input(self):
        raw = synthetic_cross_spectrum(+4.0)
        corrected = delay_correct(raw, +4.0, enable=False)
        np.testing.assert_array_equal(corrected, raw)

    def test_invalid_geometry_bypasses_without_nans(self):
        raw = synthetic_cross_spectrum(+4.0)
        corrected = delay_correct(raw, math.nan)
        np.testing.assert_array_equal(corrected, raw)
        self.assertFalse(np.isnan(corrected).any())

    def test_correction_sign_is_negative_exponential(self):
        raw = synthetic_cross_spectrum(+5.0)
        correct_sign = delay_correct(raw, +5.0)
        wrong_sign = raw * np.exp(+1j * 2.0 * np.pi * f_bb() * 5.0e-9).astype(np.complex64)
        self.assertAlmostEqual(estimate_delay_ns(correct_sign), 0.0, places=5)
        self.assertAlmostEqual(estimate_delay_ns(wrong_sign), 10.0, places=4)

    def test_grc_stage7_blocks_and_connections(self):
        graph = load_grc()
        blocks = {block["name"]: block for block in graph["blocks"]}
        for name in {
            "delay_correction_enable",
            "instrument_delay_ns",
            "delay_slope_corrector",
            "corrected_cross_phase_rad",
            "corrected_cross_phase_deg",
            "corrected_cross_phase_sink",
            "corrected_phase_slope_delay_estimator",
            "corrected_delay_number_sink",
            "corrected_phase_slope_number_sink",
            "corrected_phase_fit_rms_number_sink",
        }:
            self.assertIn(name, blocks)

        corrector = blocks["delay_slope_corrector"]
        self.assertEqual(corrector["parameters"]["fft_size"], "fft_size")
        self.assertEqual(corrector["parameters"]["samp_rate"], "samp_rate")
        self.assertEqual(corrector["parameters"]["instrument_delay_ns"], "instrument_delay_ns")
        self.assertEqual(corrector["parameters"]["delay_correction_enable"], "delay_correction_enable")
        self.assertIn("exp((-1j * 2.0 * np.pi * self._f_bb * tau_apply_s))", corrector["parameters"]["_source_code"])

        corrected_sink = blocks["corrected_cross_phase_sink"]
        self.assertEqual(corrected_sink["parameters"]["x_start"], "sky_axis_start/1e9")
        self.assertEqual(corrected_sink["parameters"]["x_step"], "sky_axis_step/1e9")
        self.assertEqual(corrected_sink["parameters"]["x_axis_label"], "Sky frequency (GHz)")

        connections = {tuple(connection) for connection in graph["connections"]}
        expected = {
            ("cross_multiply_conjugate", "0", "cross_accum", "0"),
            ("cross_accum", "0", "cross_mag", "0"),
            ("cross_accum", "0", "cross_phase_rad", "0"),
            ("cross_accum", "0", "phase_slope_delay_estimator", "0"),
            ("cross_accum", "0", "astronomy_coordinate_engine", "0"),
            ("astronomy_coordinate_engine", "0", "baseline_geometry_engine", "0"),
            ("baseline_geometry_engine", "4", "delay_slope_corrector", "1"),
            ("cross_accum", "0", "delay_slope_corrector", "0"),
            ("delay_slope_corrector", "0", "corrected_cross_phase_rad", "0"),
            ("delay_slope_corrector", "0", "corrected_phase_slope_delay_estimator", "0"),
            ("corrected_cross_phase_rad", "0", "corrected_cross_phase_deg", "0"),
            ("corrected_cross_phase_deg", "0", "corrected_cross_phase_sink", "0"),
            ("corrected_phase_slope_delay_estimator", "0", "corrected_delay_number_sink", "0"),
            ("corrected_phase_slope_delay_estimator", "1", "corrected_phase_slope_number_sink", "0"),
            ("corrected_phase_slope_delay_estimator", "2", "corrected_phase_fit_rms_number_sink", "0"),
        }
        self.assertTrue(expected.issubset(connections))

    def test_existing_block_coordinates_are_unchanged_except_baseline_value_update(self):
        old = head_grc()
        new = load_grc()
        old_blocks = {block["name"]: block for block in old["blocks"]}
        new_blocks = {block["name"]: block for block in new["blocks"]}
        state_keys = ("coordinate", "rotation", "enabled")
        changed = []
        for name, old_block in old_blocks.items():
            self.assertIn(name, new_blocks)
            for key in state_keys:
                old_state = old_block.get("states", {}).get(key)
                new_state = new_blocks[name].get("states", {}).get(key)
                if old_state != new_state:
                    changed.append((name, key, old_state, new_state))
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
