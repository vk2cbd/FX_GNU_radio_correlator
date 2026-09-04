import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest

import numpy as np
import yaml
from astropy import units as u
from astropy.io import fits
from astropy.time import Time


ROOT = pathlib.Path(__file__).resolve().parents[1]
C_M_S = 299792458.0


def load_writer():
    path = ROOT / "grc" / "fx_interferometer_v1_stage10_fitsidi_writer.py"
    spec = importlib.util.spec_from_file_location("stage10_writer", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


writer_mod = load_writer()


def raw_primary_header(path):
    text = pathlib.Path(path).read_bytes()[:2880].decode("ascii")
    return {text[idx : idx + 8].strip(): text[idx : idx + 80] for idx in range(0, 2880, 80)}


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


class Stage10FitsIdiTests(unittest.TestCase):
    def test_primary_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            raw = raw_primary_header(final_path)
            self.assertIn("NAXIS", raw["NAXIS"])
            self.assertIn("0", raw["NAXIS"])
            self.assertNotIn("NAXIS1", raw)
            with fits.open(final_path, memmap=False) as hdul:
                hdr = hdul[0].header
                self.assertTrue(hdr["EXTEND"])
                self.assertTrue(hdr["GROUPS"])
                self.assertEqual(hdr["GCOUNT"], 0)
                self.assertEqual(hdr["PCOUNT"], 0)
                self.assertEqual(hdr["CORRELAT"], "FXGNU")
                self.assertNotIn(hdr["CORRELAT"], ("VLBA", "DIFX"))

    def test_table_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 2)
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                names = [hdu.name for hdu in hdul]
                self.assertEqual(names[:4], ["PRIMARY", "ARRAY_GEOMETRY", "FREQUENCY", "SOURCE"])
                self.assertEqual(names[4:], ["UV_DATA"])

    def test_visibility_sign_is_not_conjugated(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                flux = hdul["UV_DATA"].data["FLUX"][0]
                self.assertAlmostEqual(float(flux[0]), 3.0)
                self.assertAlmostEqual(float(flux[1]), 4.0)
                self.assertAlmostEqual(float(flux[2]), 1.0)

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

    def test_baseline_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                self.assertEqual(int(hdul["UV_DATA"].data["BASELINE"][0]), 258)
                self.assertEqual(list(hdul["ARRAY_GEOMETRY"].data["NOSTA"]), [1, 2])

    def test_current_project_baseline_and_array_geometry(self):
        offset = writer_mod.enu_to_ecef_offset(-5.785, 0.095, 0.580, -32.724, 152.130167)
        recovered = writer_mod.ecef_offset_to_enu(*offset, -32.724, 152.130167)
        np.testing.assert_allclose(recovered, np.array([-5.785, 0.095, 0.580]), atol=1e-9)
        self.assertAlmostEqual(float(np.linalg.norm(recovered)), 5.814779, places=6)
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                stab = hdul["ARRAY_GEOMETRY"].data["STABXYZ"]
                recovered = writer_mod.ecef_offset_to_enu(*(stab[1] - stab[0]), -32.724, 152.130167)
                np.testing.assert_allclose(recovered, np.array([-5.785, 0.095, 0.580]), atol=1e-6)

    def test_ideal_east_west_baseline(self):
        u_m, v_m, w_m = writer_mod.uvw_project_m(0.0, -30.0, 6.0, 0.0, 0.0, -32.724)
        self.assertAlmostEqual(u_m, 6.0, places=12)
        self.assertAlmostEqual(v_m, 0.0, places=12)
        self.assertAlmostEqual(w_m, 0.0, places=12)
        self.assertAlmostEqual(-u_m / C_M_S, -6.0 / C_M_S, places=18)

    def test_stage6_cross_check(self):
        sys.path.insert(0, str(ROOT))
        from tests.test_stage6_geometry import geometry_for

        for ha_hour, dec_deg in [(0.0, -30.0), (1.5, -60.0), (-2.0, 15.0)]:
            expected = geometry_for(ha_hour, dec_deg)
            actual = writer_mod.uvw_project_m(ha_hour, dec_deg, -5.785, 0.095, 0.580, -32.724)
            self.assertAlmostEqual(actual[0], expected["u_m"], places=12)
            self.assertAlmostEqual(actual[1], expected["v_m"], places=12)
            self.assertAlmostEqual(actual[2], expected["w_m"], places=12)

    def test_date_time_round_trip_across_midnight(self):
        for isot in ["2026-09-04T23:59:59.5", "2026-09-05T00:00:00.5"]:
            t = Time(isot, scale="utc")
            date_jd, time_days = writer_mod.date_time_from_time(t)
            reconstructed = writer_mod.time_from_date_time(date_jd, time_days)
            self.assertAlmostEqual(reconstructed.jd, t.jd, places=10)

    def test_integration_time_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            for idx, seconds in enumerate([1.0, 5.0, 10.0, 30.0]):
                writer.add_record(
                    {
                        "visibility": 1.0 + 0.0j,
                        "effective_integration_s": seconds,
                        "coherence_pct": 100.0,
                        "n_int": 10,
                        "t_center": Time("2026-09-04T00:00:00", scale="utc") + idx * u.s,
                        "project_uvw_m": (1.0, 2.0, 3.0),
                    }
                )
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                np.testing.assert_allclose(hdul["UV_DATA"].data["INTTIM"], [1.0, 5.0, 10.0, 30.0])

    def test_effective_bandwidth_metadata(self):
        n_edge, n_used, bw = writer_mod.effective_bandwidth_hz(30.72e6, 4096, 20.0)
        self.assertEqual(n_edge, 819)
        self.assertEqual(n_used, 2458)
        self.assertAlmostEqual(bw, 18435000.0)
        with tempfile.TemporaryDirectory() as tmp:
            writer = writer_mod.FitsIdiWriter(base_config(tmp))
            writer.start()
            add_records(writer, 1)
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                self.assertEqual(hdul["FREQUENCY"].header["REF_FREQ"], 4.800e9)
                self.assertEqual(hdul["FREQUENCY"].header["CHAN_BW"], 18435000.0)
                self.assertEqual(hdul["UV_DATA"].header["MAXIS1"], 3)
                self.assertEqual(hdul["UV_DATA"].header["CTYPE1"], "COMPLEX")
                self.assertEqual(hdul["UV_DATA"].header["CTYPE2"], "STOKES")
                self.assertEqual(hdul["UV_DATA"].header["CRVAL2"], -5)

    def test_chunked_uv_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = base_config(tmp)
            cfg["chunk_rows"] = 10
            writer = writer_mod.FitsIdiWriter(cfg)
            writer.start()
            add_records(writer, 27)
            final_path = writer.stop()
            with fits.open(final_path, memmap=False) as hdul:
                uv_hdus = [hdu for hdu in hdul if hdu.name == "UV_DATA"]
                self.assertEqual([len(hdu.data) for hdu in uv_hdus], [10, 10, 7])
                times = []
                for hdu in uv_hdus:
                    times.extend(np.asarray(hdu.data["DATE"]) + np.asarray(hdu.data["TIME"]))
                self.assertTrue(np.all(np.diff(times) > 0))

    def test_partial_file_opens_after_two_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = base_config(tmp)
            cfg["chunk_rows"] = 10
            writer = writer_mod.FitsIdiWriter(cfg)
            writer.start()
            add_records(writer, 20)
            writer.flush()
            summary = writer_mod.validate_fitsidi_file(writer.partial_file, expected_records=20)
            writer.abort_error()
            self.assertEqual(summary["records"], 20)
            self.assertEqual(summary["uv_chunks"], 2)

    def test_queue_overflow_sets_error(self):
        gnuradio = types.ModuleType("gnuradio")

        class FakeSyncBlock:
            def __init__(self, *args, **kwargs):
                pass

        gnuradio.gr = types.SimpleNamespace(sync_block=FakeSyncBlock)
        sys.modules["gnuradio"] = gnuradio
        sys.modules["gnuradio.gr"] = gnuradio.gr
        sys.path.insert(0, str(ROOT / "grc"))
        path = ROOT / "grc" / "fx_interferometer_v1_stage10_fitsidi_recorder.py"
        spec = importlib.util.spec_from_file_location("stage10_recorder", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            block = module.blk(uv_logging_enable=False, output_dir=tmp)
            block.uv_logging_enable = True
            block._state = writer_mod.STATE_RECORDING
            block._queue = types.SimpleNamespace(put_nowait=lambda record: (_ for _ in ()).throw(__import__("queue").Full()))
            inputs = [
                np.array([1.0 + 0.0j], dtype=np.complex64),
                np.array([100.0], dtype=np.float32),
                np.array([1.0], dtype=np.float32),
                np.array([10.0], dtype=np.float32),
                np.array([1.0], dtype=np.float32),
            ]
            outputs = [np.zeros(1, dtype=np.float32) for _ in range(3)]
            block.work(inputs, outputs)
            self.assertEqual(block._state, writer_mod.STATE_ERROR)

    def test_uv_logging_setter_starts_and_stops_writer(self):
        gnuradio = types.ModuleType("gnuradio")

        class FakeSyncBlock:
            def __init__(self, *args, **kwargs):
                pass

        gnuradio.gr = types.SimpleNamespace(sync_block=FakeSyncBlock)
        sys.modules["gnuradio"] = gnuradio
        sys.modules["gnuradio.gr"] = gnuradio.gr
        sys.path.insert(0, str(ROOT / "grc"))
        path = ROOT / "grc" / "fx_interferometer_v1_stage10_fitsidi_recorder.py"
        spec = importlib.util.spec_from_file_location("stage10_recorder_setter", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            block = module.blk(uv_logging_enable="False", output_dir=tmp)
            self.assertEqual(block._state, writer_mod.STATE_OFF)
            block.set_uv_logging_enable("True")
            self.assertEqual(block._state, writer_mod.STATE_RECORDING)
            self.assertTrue(pathlib.Path(block._writer.partial_file).exists())
            block.set_uv_logging_enable("False")
            deadline = Time.now().unix + 5.0
            while block._state == writer_mod.STATE_FINALIZING and Time.now().unix < deadline:
                __import__("time").sleep(0.05)
            self.assertEqual(block._state, writer_mod.STATE_COMPLETE)
            self.assertTrue(pathlib.Path(block._writer.final_file).exists())

    def test_control_stream_starts_recording_from_work(self):
        gnuradio = types.ModuleType("gnuradio")

        class FakeSyncBlock:
            def __init__(self, *args, **kwargs):
                pass

        gnuradio.gr = types.SimpleNamespace(sync_block=FakeSyncBlock)
        sys.modules["gnuradio"] = gnuradio
        sys.modules["gnuradio.gr"] = gnuradio.gr
        sys.path.insert(0, str(ROOT / "grc"))
        path = ROOT / "grc" / "fx_interferometer_v1_stage10_fitsidi_recorder.py"
        spec = importlib.util.spec_from_file_location("stage10_recorder_control_stream", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            block = module.blk(uv_logging_enable=False, output_dir=tmp)
            inputs = [
                np.array([2.0 + 3.0j], dtype=np.complex64),
                np.array([97.0], dtype=np.float32),
                np.array([1.0], dtype=np.float32),
                np.array([10.0], dtype=np.float32),
                np.array([1.0], dtype=np.float32),
            ]
            outputs = [np.zeros(1, dtype=np.float32) for _ in range(3)]
            block.work(inputs, outputs)
            self.assertEqual(block._state, writer_mod.STATE_RECORDING)
            self.assertEqual(outputs[0][0], writer_mod.STATE_RECORDING)
            block.set_uv_logging_enable(False)
            deadline = Time.now().unix + 5.0
            while block._state == writer_mod.STATE_FINALIZING and Time.now().unix < deadline:
                __import__("time").sleep(0.05)
            self.assertEqual(block._state, writer_mod.STATE_COMPLETE)
            self.assertGreaterEqual(block._records_written, 1)

    def test_stage10_grc_derives_from_stage9_without_dsp_regression(self):
        stage9 = yaml.safe_load((ROOT / "grc" / "fx_interferometer_v1_stage9.grc").read_text())
        stage10 = yaml.safe_load((ROOT / "grc" / "fx_interferometer_v1_stage10.grc").read_text())
        self.assertEqual(stage10["options"]["parameters"]["id"], "fx_interferometer_v1_stage10")
        stage9_blocks = {block["name"]: block for block in stage9["blocks"]}
        stage10_blocks = {block["name"]: block for block in stage10["blocks"]}
        for name, block in stage9_blocks.items():
            self.assertIn(name, stage10_blocks)
            self.assertEqual(block["id"], stage10_blocks[name]["id"])
            self.assertEqual(block["states"], stage10_blocks[name]["states"])
        self.assertTrue(set(tuple(c) for c in stage9["connections"]).issubset(set(tuple(c) for c in stage10["connections"])))
        self.assertIn("fitsidi_visibility_recorder", stage10_blocks)
        self.assertIn("stage10_uv_logging_control_source", stage10_blocks)
        connections = {tuple(c) for c in stage10["connections"]}
        self.assertIn(("stage10_uv_logging_control_source", "0", "fitsidi_visibility_recorder", "4"), connections)

    def test_grc_embedded_recorder_fallback_instantiates_after_import_failure(self):
        stage10 = yaml.safe_load((ROOT / "grc" / "fx_interferometer_v1_stage10.grc").read_text())
        block = next(block for block in stage10["blocks"] if block["name"] == "fitsidi_visibility_recorder")
        source = block["parameters"]["_source_code"]

        gnuradio = types.ModuleType("gnuradio")

        class FakeSyncBlock:
            def __init__(self, *args, **kwargs):
                self.init_args = (args, kwargs)

        gnuradio.gr = types.SimpleNamespace(sync_block=FakeSyncBlock)
        sys.modules["gnuradio"] = gnuradio
        sys.modules["gnuradio.gr"] = gnuradio.gr
        original_path = list(sys.path)
        sys.path = [entry for entry in sys.path if str(ROOT / "grc") not in entry]
        try:
            namespace = {"__file__": str(ROOT / "grc" / "fx_interferometer_v1_stage10.py")}
            exec(source, namespace)
            instance = namespace["blk"]()
        finally:
            sys.path = original_path
        self.assertIsInstance(instance, FakeSyncBlock)

    def test_existing_stage9_regression_tests_still_pass_target_files(self):
        output = subprocess.check_output([sys.executable, "-m", "pytest", "tests/test_stage9_integration_stability.py"], cwd=ROOT)
        self.assertIn(b"passed", output)


if __name__ == "__main__":
    unittest.main()
