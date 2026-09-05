import importlib.util
import math
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import stage10_protocol as protocol


class Stage10ProtocolTests(unittest.TestCase):
    def config(self, edge_pct=20.0):
        return {
            "source_mode": 1,
            "manual_ra_hours": 18.3,
            "manual_dec_deg": -16.2,
            "site_lat_deg": -32.724,
            "site_lon_deg": 152.130167,
            "site_height_m": 70.0,
            "baseline_e_m": -5.785,
            "baseline_n_m": 0.095,
            "baseline_u_m": 0.580,
            "sky_cf_hz": 4.8e9,
            "samp_rate": 30.72e6,
            "fft_size": 4096,
            "visibility_edge_exclude_pct": edge_pct,
            "instrument_delay_ns": -1.9,
            "delay_correction_enable": True,
            "fringe_stop_enable": True,
            "fringe_stop_sign": -1,
            "stokes_code": -5,
            "polarization_label": "XX",
            "polarization_assumed": True,
        }

    def test_source_names_are_not_silent_fallbacks(self):
        self.assertEqual(protocol.source_name_for_mode(0), "Sun")
        self.assertEqual(protocol.source_name_for_mode(1), "Manual")
        self.assertEqual(protocol.source_name_for_mode(2), "INVALID")
        self.assertEqual(protocol.source_name_for_mode("bad"), "INVALID")

    def test_visibility_packet_schema_and_values(self):
        packet = protocol.packet_from_visibility(10527, 3 + 4j, 99.5, 1.0, 10, self.config())
        self.assertEqual(packet["schema_version"], 2)
        self.assertEqual(packet["sequence"], 10527)
        self.assertEqual(packet["source_mode"], 1)
        self.assertEqual(packet["source_name"], "Manual")
        self.assertTrue(packet["metadata_valid"])
        self.assertEqual(packet["visibility_real"], 3.0)
        self.assertEqual(packet["visibility_imag"], 4.0)
        self.assertEqual(packet["window_coherence_pct"], 99.5)
        self.assertEqual(packet["effective_integration_s"], 1.0)
        self.assertEqual(packet["n_int"], 10)
        self.assertEqual(packet["retained_fft_bins"], 2458)
        self.assertEqual(packet["effective_correlated_bandwidth_hz"], 18435000.0)
        decoded = protocol.decode_line(protocol.encode_packet(packet))
        self.assertEqual(decoded["sequence"], packet["sequence"])
        emitted = protocol.parse_iso_z(packet["emitted_utc"])
        center = protocol.parse_iso_z(packet["integration_center_utc"])
        self.assertAlmostEqual((emitted - center).total_seconds(), 0.5, places=6)

    def test_bandwidth_metadata_uses_integer_retained_fft_bins(self):
        cases = [
            (5.0, 3688, 27660000.0),
            (20.0, 2458, 18435000.0),
            (12.5, 3072, 23040000.0),
        ]
        for edge_pct, bins, bandwidth_hz in cases:
            with self.subTest(edge_pct=edge_pct):
                packet = protocol.packet_from_visibility(1, 1 + 0j, 99.0, 1.0, 10, self.config(edge_pct))
                self.assertEqual(packet["visibility_edge_exclude_pct"], edge_pct)
                self.assertEqual(packet["retained_fft_bins"], bins)
                self.assertEqual(packet["effective_correlated_bandwidth_hz"], bandwidth_hz)
                protocol.verify_packet_metadata(packet)

    def test_missing_or_mismatched_metadata_is_rejected(self):
        cfg = self.config(5.0)
        del cfg["visibility_edge_exclude_pct"]
        with self.assertRaisesRegex(KeyError, "visibility_edge_exclude_pct"):
            protocol.packet_from_visibility(1, 1 + 0j, 99.0, 1.0, 10, cfg)

        packet = protocol.packet_from_visibility(1, 1 + 0j, 99.0, 1.0, 10, self.config(5.0))
        packet["effective_correlated_bandwidth_hz"] = 18435000.0
        with self.assertRaisesRegex(ValueError, "effective_correlated_bandwidth_hz mismatch"):
            protocol.verify_packet_metadata(packet)

    def test_invalid_edge_exclusion_marks_packet_invalid(self):
        with self.assertRaisesRegex(ValueError, "visibility edge exclusion"):
            protocol.packet_from_visibility(1, 1 + 0j, 99.0, 1.0, 10, self.config(50.0))


if __name__ == "__main__":
    unittest.main()
