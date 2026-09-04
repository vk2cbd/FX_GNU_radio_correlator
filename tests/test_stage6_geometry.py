import math
import pathlib
import unittest
import warnings

import numpy as np
import yaml

from tests.test_stage5_coordinates import SOURCE_MANUAL, compute_coordinates


C_M_S = 299792458.0
BASELINE_E_M = -5.785
BASELINE_N_M = 0.095
BASELINE_U_M = 0.580
SITE_LAT_DEG = -32.724
SKY_CF_HZ = 4.800e9


def uvw_basis(ha_hour, dec_deg, site_lat_deg=SITE_LAT_DEG):
    phi = math.radians(site_lat_deg)
    h = math.radians(ha_hour * 15.0)
    dec = math.radians(dec_deg)
    u_hat = np.array(
        [
            math.cos(h),
            -math.sin(phi) * math.sin(h),
            math.cos(phi) * math.sin(h),
        ]
    )
    v_hat = np.array(
        [
            math.sin(dec) * math.sin(h),
            math.cos(phi) * math.cos(dec)
            + math.sin(phi) * math.sin(dec) * math.cos(h),
            math.sin(phi) * math.cos(dec)
            - math.cos(phi) * math.sin(dec) * math.cos(h),
        ]
    )
    w_hat = np.array(
        [
            -math.cos(dec) * math.sin(h),
            math.sin(dec) * math.cos(phi)
            - math.cos(dec) * math.cos(h) * math.sin(phi),
            math.sin(dec) * math.sin(phi)
            + math.cos(dec) * math.cos(h) * math.cos(phi),
        ]
    )
    return u_hat, v_hat, w_hat


def baseline_vector():
    return np.array([BASELINE_E_M, BASELINE_N_M, BASELINE_U_M], dtype=np.float64)


def geometry_for(ha_hour, dec_deg):
    baseline = baseline_vector()
    u_hat, v_hat, w_hat = uvw_basis(ha_hour, dec_deg)
    u_m = float(np.dot(baseline, u_hat))
    v_m = float(np.dot(baseline, v_hat))
    w_m = float(np.dot(baseline, w_hat))
    tau_s = w_m / C_M_S
    phase_deg = ((360.0 * SKY_CF_HZ * tau_s + 180.0) % 360.0) - 180.0
    return {
        "u_m": u_m,
        "v_m": v_m,
        "w_m": w_m,
        "tau_s": tau_s,
        "tau_ns": tau_s * 1e9,
        "arrival_delay_10_ns": -tau_s * 1e9,
        "phase_deg": phase_deg,
    }


class Stage6GeometryTests(unittest.TestCase):
    def test_baseline_length_and_max_delay(self):
        length = float(np.linalg.norm(baseline_vector()))
        self.assertAlmostEqual(length, 5.814779, places=6)
        self.assertAlmostEqual(length / C_M_S * 1e9, 19.396014, places=6)

    def test_cardinal_source_delays(self):
        baseline = baseline_vector()
        cases = [
            (np.array([1.0, 0.0, 0.0]), -19.296683),
            (np.array([-1.0, 0.0, 0.0]), 19.296683),
            (np.array([0.0, 1.0, 0.0]), 0.316886),
            (np.array([0.0, -1.0, 0.0]), -0.316886),
            (np.array([0.0, 0.0, 1.0]), 1.934672),
        ]
        for s_enu, expected_ns in cases:
            tau_ns = float(np.dot(baseline, s_enu)) / C_M_S * 1e9
            self.assertAlmostEqual(tau_ns, expected_ns, places=6)

    def test_uvw_basis_is_orthonormal_and_right_handed(self):
        for ha_hour, dec_deg in [(-4.0, -30.0), (0.0, -30.0), (3.0, 20.0)]:
            u_hat, v_hat, w_hat = uvw_basis(ha_hour, dec_deg)
            self.assertAlmostEqual(float(np.dot(u_hat, v_hat)), 0.0, places=12)
            self.assertAlmostEqual(float(np.dot(u_hat, w_hat)), 0.0, places=12)
            self.assertAlmostEqual(float(np.dot(v_hat, w_hat)), 0.0, places=12)
            self.assertAlmostEqual(float(np.linalg.norm(u_hat)), 1.0, places=12)
            self.assertAlmostEqual(float(np.linalg.norm(v_hat)), 1.0, places=12)
            self.assertAlmostEqual(float(np.linalg.norm(w_hat)), 1.0, places=12)
            np.testing.assert_allclose(np.cross(u_hat, v_hat), w_hat, atol=1e-12)

    def test_uvw_preserves_baseline_length_and_tau_relation(self):
        baseline_len2 = float(np.dot(baseline_vector(), baseline_vector()))
        for ha_hour, dec_deg in [(-6.0, -45.0), (-1.0, -10.0), (0.0, -32.724), (5.0, 15.0)]:
            geom = geometry_for(ha_hour, dec_deg)
            uvw_len2 = geom["u_m"] ** 2 + geom["v_m"] ** 2 + geom["w_m"] ** 2
            self.assertAlmostEqual(uvw_len2, baseline_len2, places=10)
            self.assertAlmostEqual(geom["w_m"] / C_M_S, geom["tau_s"], places=18)
            self.assertAlmostEqual(geom["arrival_delay_10_ns"], -geom["tau_ns"], places=12)
            self.assertLessEqual(abs(geom["tau_ns"]), 19.396013576960943 + 1e-9)

    def test_transit_symmetry_and_signs(self):
        geom = geometry_for(0.0, -30.0)
        self.assertAlmostEqual(geom["u_m"], BASELINE_E_M, places=12)
        self.assertAlmostEqual(geom["tau_ns"], geom["w_m"] / C_M_S * 1e9, places=12)

    def test_east_and_west_hour_angles_are_finite(self):
        east = geometry_for(-2.0, -30.0)
        west = geometry_for(2.0, -30.0)
        for geom in (east, west):
            for value in geom.values():
                self.assertTrue(math.isfinite(value))
            self.assertGreaterEqual(geom["phase_deg"], -180.0)
            self.assertLess(geom["phase_deg"], 180.0)

    def test_negative_declination(self):
        geom = geometry_for(1.5, -60.0)
        self.assertTrue(math.isfinite(geom["tau_ns"]))
        self.assertLessEqual(abs(geom["tau_ns"]), 19.396013576960943 + 1e-9)

    def test_sun_and_manual_stage5_coordinates_supply_finite_stage6_geometry(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sun = compute_coordinates(0)
            manual = compute_coordinates(SOURCE_MANUAL, manual_ra_hours="5.25", manual_dec_deg="-30.5")
            sun_again = compute_coordinates(0)
        for coords in (sun, manual, sun_again):
            geom = geometry_for(coords["ha_hour"], coords["apparent_dec_deg"])
            for value in geom.values():
                self.assertTrue(math.isfinite(value))

    def test_graph_preserves_stage1_to_stage5_connections_and_stage4_estimator(self):
        graph_path = pathlib.Path(__file__).resolve().parents[1] / "grc" / "fx_interferometer_v1_stage10.grc"
        graph = yaml.safe_load(graph_path.read_text())
        blocks = {block["name"]: block for block in graph["blocks"]}
        self.assertIn("-5.785", str(blocks["baseline_e_m"]["parameters"]["value"]))
        self.assertIn("0.095", str(blocks["baseline_n_m"]["parameters"]["value"]))
        self.assertIn("0.580", str(blocks["baseline_u_m"]["parameters"]["value"]))
        connections = {tuple(connection) for connection in graph["connections"]}
        required = {
            ("cross_multiply_conjugate", "0", "cross_accum", "0"),
            ("cross_accum", "0", "cross_mag", "0"),
            ("cross_accum", "0", "cross_phase_rad", "0"),
            ("cross_accum", "0", "phase_slope_delay_estimator", "0"),
            ("phase_slope_delay_estimator", "0", "delay_number_sink", "0"),
            ("phase_slope_delay_estimator", "1", "phase_slope_number_sink", "0"),
            ("phase_slope_delay_estimator", "2", "phase_fit_rms_number_sink", "0"),
            ("cross_accum", "0", "astronomy_coordinate_engine", "0"),
            ("astronomy_coordinate_engine", "0", "astronomy_number_sink", "0"),
            ("astronomy_coordinate_engine", "2", "astronomy_number_sink", "2"),
            ("astronomy_coordinate_engine", "6", "astronomy_number_sink", "6"),
        }
        self.assertTrue(required.issubset(connections))


if __name__ == "__main__":
    unittest.main()
