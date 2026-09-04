import math
import pathlib
import subprocess
import unittest

import numpy as np
import yaml


FFT_SIZE = 4096
SKY_CF = 4.800e9


def broadband_visibility(c7, visibility_edge_exclude_pct=20.0):
    edge_pct = float(visibility_edge_exclude_pct)
    if edge_pct < 0.0:
        edge_pct = 0.0
    elif edge_pct >= 50.0:
        edge_pct = 49.0

    n_edge = int(len(c7) * edge_pct / 100.0)
    if len(c7) - 2 * n_edge < 2:
        n_edge = 0

    bins = c7[n_edge : len(c7) - n_edge] if n_edge else c7
    return np.complex64(np.mean(bins, dtype=np.complex128)), n_edge, len(bins)


def fringe_stop(v_unstopped, tau_g_ns, sky_cf=SKY_CF, enable=True, sign=-1):
    if not enable:
        return np.complex64(v_unstopped)
    if sign not in (-1, 1) or not np.isfinite(sky_cf) or not np.isfinite(tau_g_ns):
        return np.complex64(v_unstopped)
    tau_g_s = float(tau_g_ns) * 1e-9
    rotation = np.exp(1j * int(sign) * 2.0 * np.pi * float(sky_cf) * tau_g_s)
    return np.complex64(v_unstopped * rotation)


def phase_rad(value):
    return float(np.angle(value))


def load_grc(path="grc/fx_interferometer_v1_stage10.grc"):
    return yaml.safe_load(pathlib.Path(path).read_text())


def head_grc():
    try:
        data = subprocess.check_output(
            ["git", "show", "HEAD:grc/fx_interferometer_v1_stage10.grc"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        try:
            data = subprocess.check_output(["git", "show", "HEAD:grc/fx_interferometer_v1_stage9.grc"])
        except subprocess.CalledProcessError:
            previous_name = "HEAD:grc/fx_interferometer_v1_" + "stage1" + "_3.grc"
            data = subprocess.check_output(["git", "show", previous_name])
    return yaml.safe_load(data)


class Stage8FringeStoppingTests(unittest.TestCase):
    def test_broadband_complex_combination_preserves_phase(self):
        phi = 0.73
        amps = np.linspace(0.2, 2.0, FFT_SIZE, dtype=np.float64)
        c7 = (amps * np.exp(1j * phi)).astype(np.complex64)
        visibility, _, _ = broadband_visibility(c7, 20.0)
        self.assertAlmostEqual(phase_rad(visibility), phi, places=6)
        self.assertGreater(abs(visibility), 0.0)

    def test_edge_exclusion_removes_corrupted_outer_bins(self):
        phi = -1.1
        c7 = np.exp(1j * phi) * np.ones(FFT_SIZE, dtype=np.complex64)
        n_edge = int(FFT_SIZE * 0.20)
        c7[:n_edge] = 100.0 * np.exp(1j * 2.5)
        c7[-n_edge:] = 100.0 * np.exp(-1j * 2.5)

        cropped, edge, used = broadband_visibility(c7, 20.0)
        full, full_edge, full_used = broadband_visibility(c7, 0.0)
        self.assertEqual(edge, 819)
        self.assertEqual(used, 2458)
        self.assertEqual(full_edge, 0)
        self.assertEqual(full_used, 4096)
        self.assertAlmostEqual(phase_rad(cropped), phi, places=6)
        self.assertNotAlmostEqual(phase_rad(full), phi, places=2)

    def test_invalid_visibility_edge_percentages_are_safe(self):
        c7 = np.ones(FFT_SIZE, dtype=np.complex64)
        negative, neg_edge, neg_used = broadband_visibility(c7, -10.0)
        too_large, large_edge, large_used = broadband_visibility(c7, 50.0)
        self.assertEqual(neg_edge, 0)
        self.assertEqual(neg_used, FFT_SIZE)
        self.assertGreaterEqual(large_used, 2)
        self.assertTrue(np.isfinite(negative))
        self.assertTrue(np.isfinite(too_large))

    def test_positive_geometric_delay_is_stopped_with_default_sign(self):
        phi0 = 0.42
        tau_g_ns = +5.0
        v_unstopped = np.exp(1j * (phi0 + 2.0 * np.pi * SKY_CF * tau_g_ns * 1e-9))
        stopped = fringe_stop(v_unstopped, tau_g_ns, sign=-1)
        self.assertAlmostEqual(phase_rad(stopped), phi0, places=5)

    def test_negative_geometric_delay_is_stopped_with_default_sign(self):
        phi0 = -0.61
        tau_g_ns = -5.0
        v_unstopped = np.exp(1j * (phi0 + 2.0 * np.pi * SKY_CF * tau_g_ns * 1e-9))
        stopped = fringe_stop(v_unstopped, tau_g_ns, sign=-1)
        self.assertAlmostEqual(phase_rad(stopped), phi0, places=5)

    def test_fringe_stop_preserves_magnitude(self):
        v = np.complex64(2.3 * np.exp(1j * 1.2))
        stopped = fringe_stop(v, 11.0)
        self.assertAlmostEqual(abs(stopped), abs(v), places=6)

    def test_fringe_stop_bypass_and_invalid_geometry(self):
        v = np.complex64(0.9 - 0.4j)
        np.testing.assert_allclose(fringe_stop(v, 5.0, enable=False), v)
        np.testing.assert_allclose(fringe_stop(v, math.nan), v)
        np.testing.assert_allclose(fringe_stop(v, math.inf), v)

    def test_commissioning_sign_control(self):
        phi0 = 0.2
        tau_g_ns = 5.125
        v = np.exp(1j * (phi0 + 2.0 * np.pi * SKY_CF * tau_g_ns * 1e-9))
        normal = fringe_stop(v, tau_g_ns, sign=-1)
        reverse = fringe_stop(v, tau_g_ns, sign=+1)
        self.assertAlmostEqual(phase_rad(normal), phi0, places=5)
        self.assertNotAlmostEqual(phase_rad(reverse), phi0, places=3)

    def test_synthetic_time_varying_fringe_is_flattened(self):
        phi0 = -0.35
        tau0_ns = 2.0
        tau_rate_s_per_s = 1.2e-12
        t = np.arange(50, dtype=np.float64) * 0.1
        tau_g_s = tau0_ns * 1e-9 + tau_rate_s_per_s * t
        v_unstopped = np.exp(1j * (phi0 + 2.0 * np.pi * SKY_CF * tau_g_s))
        v_stopped = np.array([fringe_stop(v, tau * 1e9, sign=-1) for v, tau in zip(v_unstopped, tau_g_s)])
        v_wrong = np.array([fringe_stop(v, tau * 1e9, sign=+1) for v, tau in zip(v_unstopped, tau_g_s)])

        unstopped_phase = np.unwrap(np.angle(v_unstopped))
        stopped_phase = np.unwrap(np.angle(v_stopped))
        wrong_phase = np.unwrap(np.angle(v_wrong))
        unstopped_slope = np.polyfit(t, unstopped_phase, 1)[0]
        stopped_slope = np.polyfit(t, stopped_phase, 1)[0]
        wrong_slope = np.polyfit(t, wrong_phase, 1)[0]

        self.assertAlmostEqual(unstopped_slope, 2.0 * np.pi * SKY_CF * tau_rate_s_per_s, places=9)
        self.assertAlmostEqual(stopped_slope, 0.0, places=9)
        self.assertAlmostEqual(wrong_slope, 2.0 * unstopped_slope, places=8)

    def test_grc_stage8_blocks_controls_and_connections(self):
        graph = load_grc()
        blocks = {block["name"]: block for block in graph["blocks"]}
        for name in {
            "visibility_edge_exclude_pct",
            "visibility_rate",
            "fringe_stop_enable",
            "fringe_stop_sign",
            "broadband_visibility_combiner",
            "fringe_stop_corrector",
            "visibility_iq_time_sink",
            "visibility_phase_time_sink",
            "visibility_number_sink",
        }:
            self.assertIn(name, blocks)

        self.assertIn("visibility_edge_exclude_pct", blocks["visibility_edge_exclude_pct"]["parameters"]["value"])
        self.assertIn("20.0", blocks["visibility_edge_exclude_pct"]["parameters"]["value"])
        self.assertIn("fringe_stop_sign", blocks["fringe_stop_sign"]["parameters"]["value"])
        self.assertIn("-1", blocks["fringe_stop_sign"]["parameters"]["value"])
        self.assertEqual(blocks["visibility_rate"]["parameters"]["value"], "fft_rate/accum_frames")

        combiner = blocks["broadband_visibility_combiner"]
        self.assertEqual(combiner["parameters"]["visibility_edge_exclude_pct"], "visibility_edge_exclude_pct")
        self.assertIn("np.mean(spectrum[use_bins]", combiner["parameters"]["_source_code"])

        corrector = blocks["fringe_stop_corrector"]
        self.assertEqual(corrector["parameters"]["sky_cf"], "sky_cf")
        self.assertEqual(corrector["parameters"]["fringe_stop_enable"], "fringe_stop_enable")
        self.assertEqual(corrector["parameters"]["fringe_stop_sign"], "fringe_stop_sign")
        self.assertIn("np.exp(1j * sign * 2.0 * np.pi * sky_cf * tau_s)", corrector["parameters"]["_source_code"])

        connections = {tuple(connection) for connection in graph["connections"]}
        expected_stage7 = {
            ("cross_multiply_conjugate", "0", "cross_accum", "0"),
            ("cross_accum", "0", "delay_slope_corrector", "0"),
            ("baseline_geometry_engine", "4", "delay_slope_corrector", "1"),
            ("delay_slope_corrector", "0", "corrected_cross_phase_rad", "0"),
            ("delay_slope_corrector", "0", "corrected_phase_slope_delay_estimator", "0"),
        }
        expected_stage8 = {
            ("delay_slope_corrector", "0", "broadband_visibility_combiner", "0"),
            ("broadband_visibility_combiner", "0", "fringe_stop_corrector", "0"),
            ("baseline_geometry_engine", "3", "fringe_stop_corrector", "1"),
            ("broadband_visibility_combiner", "0", "unstopped_complex_to_float", "0"),
            ("fringe_stop_corrector", "0", "stopped_complex_to_float", "0"),
            ("unstopped_visibility_phase_deg", "0", "visibility_phase_time_sink", "0"),
            ("stopped_visibility_phase_deg", "0", "visibility_phase_time_sink", "1"),
        }
        self.assertTrue(expected_stage7.issubset(connections))
        self.assertTrue(expected_stage8.issubset(connections))
        self.assertNotIn(("baseline_geometry_engine", "4", "fringe_stop_corrector", "1"), connections)

    def test_existing_block_coordinates_are_unchanged(self):
        old = head_grc()
        new = load_grc()
        old_blocks = {block["name"]: block for block in old["blocks"]}
        new_blocks = {block["name"]: block for block in new["blocks"]}
        changed = []
        for name, old_block in old_blocks.items():
            if name == "integration_time_s" and old_block["id"] == "variable":
                continue
            new_name = "integration_time_s" if name == "integration_time_index" else name
            self.assertIn(new_name, new_blocks)
            for key in ("coordinate", "rotation", "enabled"):
                old_state = old_block.get("states", {}).get(key)
                new_state = new_blocks[new_name].get("states", {}).get(key)
                if old_state != new_state:
                    changed.append((name, new_name, key, old_state, new_state))
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
