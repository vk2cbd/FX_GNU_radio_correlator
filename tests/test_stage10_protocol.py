import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import stage10_protocol as protocol


class Stage10ProtocolTests(unittest.TestCase):
    def test_source_names_are_not_silent_fallbacks(self):
        self.assertEqual(protocol.source_name_for_mode(0), "Sun")
        self.assertEqual(protocol.source_name_for_mode(1), "Manual")
        self.assertEqual(protocol.source_name_for_mode(2), "INVALID")
        self.assertEqual(protocol.source_name_for_mode("bad"), "INVALID")

    def test_visibility_packet_schema_and_values(self):
        cfg = {
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
            "visibility_edge_exclude_pct": 20.0,
            "instrument_delay_ns": -1.9,
            "delay_correction_enable": True,
            "fringe_stop_enable": True,
            "fringe_stop_sign": -1,
        }
        packet = protocol.packet_from_visibility(10527, 3 + 4j, 99.5, 1.0, 10, cfg)
        self.assertEqual(packet["schema_version"], 1)
        self.assertEqual(packet["sequence"], 10527)
        self.assertEqual(packet["source_mode"], 1)
        self.assertEqual(packet["source_name"], "Manual")
        self.assertEqual(packet["visibility_real"], 3.0)
        self.assertEqual(packet["visibility_imag"], 4.0)
        self.assertEqual(packet["window_coherence_pct"], 99.5)
        self.assertEqual(packet["effective_integration_s"], 1.0)
        self.assertEqual(packet["n_int"], 10.0)
        decoded = protocol.decode_line(protocol.encode_packet(packet))
        self.assertEqual(decoded["sequence"], packet["sequence"])


if __name__ == "__main__":
    unittest.main()
