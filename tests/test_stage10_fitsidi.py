import pathlib
import sys
import tempfile
import unittest

import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.time import Time


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import stage10_fitsidi_writer as writer_mod


C_M_S = 299792458.0


def base_config(tmpdir):
    cfg = writer_mod.default_config()
    cfg.update(
        {
            "output_dir": str(tmpdir),
            "observation_name": "unit_test",
            "source_mode": 1,
            "manual_ra_hours": 5.0,
            "manual_dec_deg": -30.0,
            "chunk_age_s": 9999.0,
        }
    )
    return cfg


def add_records(writer, count, start="2026-09-04T00:00:00", project_uvw=(1.0, 2.0, 3.0)):
    t0 = Time(start, scale="utc")
    for idx in range(count):
        writer.add_record(
            {
                "visibility": 3.0 + 4.0j,
                "coherence_pct": 98.0,
                "effective_integration_s": 1.0,
                "n_int": 10,
                "t_center": t0 + idx * u.s,
                "project_uvw_m": project_uvw,
            }
        )


def raw_primary_cards(path):
    raw = pathlib.Path(path).read_bytes()[:2880]
    return {raw[idx : idx + 8].decode("ascii").strip(): raw[idx : idx + 80].decode("ascii") for idx in range(0, 2880, 80)}


class Stage10FitsIdiTests(unittest.TestCase):
    def test_primary_table_order_and_visibility_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            raw = raw_primary_cards(final_path)
            self.assertIn("NAXIS", raw["NAXIS"])
            self.assertIn("0", raw["NAXIS"])
            self.assertNotIn("NAXIS1", raw)
            with fits.open(final_path, memmap=False) as hdul:
                self.assertEqual([hdu.name for hdu in hdul], ["PRIMARY", "ARRAY_GEOMETRY", "FREQUENCY", "SOURCE", "UV_DATA"])
                hdr = hdul[0].header
                self.assertEqual(hdr["CORRELAT"], "FXGNU")
                flux = hdul["UV_DATA"].data["FLUX"][0]
                self.assertAlmostEqual(float(flux[0]), 3.0)
                self.assertAlmostEqual(float(flux[1]), 4.0)
                self.assertAlmostEqual(float(flux[2]), 1.0)

    def test_manual_source_metadata_and_filename_are_not_sun(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = base_config(tmp)
            cfg["source_mode"] = 1
            cfg["manual_ra_hours"] = 18.3
            cfg["manual_dec_deg"] = -16.2
            writer = writer_mod.FitsIdiWriter(cfg)
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            self.assertIn("_Manual_B01.fitsidi", pathlib.Path(final_path).name)
            self.assertNotIn("_Sun_B01.fitsidi", pathlib.Path(final_path).name)
            with fits.open(final_path, memmap=False) as hdul:
                source_row = hdul["SOURCE"].data[0]
                self.assertEqual(source_row["SOURCE"].strip(), "Manual")
                self.assertAlmostEqual(float(source_row["RAEPO"]), 18.3 * 15.0, places=8)
                self.assertAlmostEqual(float(source_row["DECEPO"]), -16.2, places=8)

    def test_sun_source_metadata_and_filename_are_not_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = base_config(tmp)
            cfg["source_mode"] = 0
            writer = writer_mod.FitsIdiWriter(cfg)
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            self.assertIn("_Sun_B01.fitsidi", pathlib.Path(final_path).name)
            self.assertNotIn("_Manual_B01.fitsidi", pathlib.Path(final_path).name)
            with fits.open(final_path, memmap=False) as hdul:
                source_row = hdul["SOURCE"].data[0]
                self.assertEqual(source_row["SOURCE"].strip(), "Sun")

    def test_uvw_sign_and_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 1, project_uvw=(4.0, -3.0, 2.0))
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                row = hdul["UV_DATA"].data[0]
                self.assertAlmostEqual(float(row["UU"]), -4.0 / C_M_S, places=18)
                self.assertAlmostEqual(float(row["VV"]), 3.0 / C_M_S, places=18)
                self.assertAlmostEqual(float(row["WW"]), -2.0 / C_M_S, places=18)

    def test_chunked_chronological_uv_data_and_effective_bandwidth(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = base_config(tmp)
            cfg["chunk_rows"] = 10
            writer = writer_mod.FitsIdiWriter(cfg)
            writer.start()
            add_records(writer, 27)
            final_path = writer.stop()
            summary = writer_mod.validate_fitsidi_file(final_path, expected_records=27)
            self.assertEqual(summary["records"], 27)
            self.assertEqual(summary["uv_chunks"], 3)
            with fits.open(final_path, memmap=False) as hdul:
                self.assertEqual(hdul["FREQUENCY"].header["REF_FREQ"], 4.800e9)
                self.assertEqual(hdul["FREQUENCY"].header["CHAN_BW"], 18435000.0)

    def test_current_baseline_and_stage6_cross_check(self):
        offset = writer_mod.enu_to_ecef_offset(-5.785, 0.095, 0.580, -32.724, 152.130167)
        recovered = writer_mod.ecef_offset_to_enu(*offset, -32.724, 152.130167)
        np.testing.assert_allclose(recovered, np.array([-5.785, 0.095, 0.580]), atol=1e-9)
        self.assertAlmostEqual(float(np.linalg.norm(recovered)), 5.814779, places=6)
        sys.path.insert(0, str(ROOT))
        from tests.test_stage6_geometry import geometry_for

        expected = geometry_for(0.0, -30.0)
        actual = writer_mod.uvw_project_m(0.0, -30.0, -5.785, 0.095, 0.580, -32.724)
        self.assertAlmostEqual(actual[0], expected["u_m"], places=12)
        self.assertAlmostEqual(actual[1], expected["v_m"], places=12)
        self.assertAlmostEqual(actual[2], expected["w_m"], places=12)


if __name__ == "__main__":
    unittest.main()
