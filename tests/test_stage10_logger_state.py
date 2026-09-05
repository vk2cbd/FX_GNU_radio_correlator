import pathlib
import sys
import tempfile
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stage10_fitsidi_logger import (
    STATE_COMPLETE,
    STATE_ERROR_CONFIG_CHANGED,
    STATE_OFF,
    STATE_RECORDING,
    Stage10LoggerController,
)
from stage10_protocol import packet_from_visibility


def packet(source_mode=1, sequence=1, edge_pct=20.0):
    return packet_from_visibility(
        sequence,
        3 + 4j,
        99.5,
        1.0,
        10,
        {
            "source_mode": source_mode,
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
        },
    )


class Stage10LoggerStateTests(unittest.TestCase):
    def test_connection_and_packets_do_not_create_file_until_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = Stage10LoggerController(port=1, observation_name="state_test", output_dir=tmp)
            try:
                logger.live.connected = True
                logger._handle_packet(packet(edge_pct=5.0))
                self.assertEqual(logger.state, STATE_OFF)
                self.assertEqual(list(pathlib.Path(tmp).glob("*")), [])
                self.assertEqual(logger.live.edge_pct, 5.0)
                self.assertEqual(logger.live.retained_bins, 3688)
                self.assertEqual(logger.live.bandwidth_hz, 27660000.0)
                logger.start_recording()
                self.assertEqual(logger.state, STATE_RECORDING)
                partial = pathlib.Path(logger.current_file)
                self.assertTrue(partial.name.endswith(".partial.fitsidi"))
                logger._handle_packet(packet(sequence=2, edge_pct=5.0))
                logger.stop_recording()
                self.assertEqual(logger.state, STATE_COMPLETE)
                first_final = pathlib.Path(logger.current_file)
                self.assertTrue(first_final.name.endswith(".fitsidi"))
                size_after_stop = first_final.stat().st_size
                logger._handle_packet(packet(sequence=3))
                time.sleep(0.05)
                self.assertEqual(first_final.stat().st_size, size_after_stop)
                logger.start_recording()
                second_partial = pathlib.Path(logger.current_file)
                self.assertNotEqual(second_partial, first_final)
                self.assertTrue(second_partial.name.endswith(".partial.fitsidi"))
            finally:
                if logger.state == STATE_RECORDING:
                    logger.stop_recording()
                logger.close()

    def test_config_change_during_recording_stops_with_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = Stage10LoggerController(port=1, observation_name="state_test", output_dir=tmp)
            try:
                logger.live.connected = True
                logger._handle_packet(packet(edge_pct=5.0))
                logger.start_recording()
                logger._handle_packet(packet(sequence=2, edge_pct=20.0))
                self.assertEqual(logger.state, STATE_ERROR_CONFIG_CHANGED)
                self.assertIn("visibility_edge_exclude_pct", logger.last_error)
                self.assertTrue(pathlib.Path(logger.current_file).name.endswith(".fitsidi"))
            finally:
                logger.close()

    def test_start_requires_connected_valid_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = Stage10LoggerController(port=1, output_dir=tmp)
            try:
                with self.assertRaisesRegex(RuntimeError, "publisher is not connected"):
                    logger.start_recording()
                logger.live.connected = True
                with self.assertRaisesRegex(RuntimeError, "no live Stage 10 packet"):
                    logger.start_recording()
                logger.last_packet = packet(source_mode=2)
                with self.assertRaisesRegex(ValueError, "source mode"):
                    logger.start_recording()
            finally:
                logger.close()


if __name__ == "__main__":
    unittest.main()
