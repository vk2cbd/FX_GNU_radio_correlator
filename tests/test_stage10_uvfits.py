import importlib.util
import math
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest

import numpy as np
import yaml
from astropy import units as u
from astropy.time import Time


ROOT = pathlib.Path(__file__).resolve().parents[1]
GRC_DIR = ROOT / "grc"
if str(GRC_DIR) not in sys.path:
    sys.path.insert(0, str(GRC_DIR))


class _FakeSyncBlock:
    def __init__(self, *args, **kwargs):
        pass


def install_gnuradio_stub():
    gnuradio = types.ModuleType("gnuradio")
    gr = types.SimpleNamespace(sync_block=_FakeSyncBlock)
    gnuradio.gr = gr
    sys.modules["gnuradio"] = gnuradio
    sys.modules["gnuradio.gr"] = gr


def load_module(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


writer = load_module("stage10_writer", "grc/fx_interferometer_v1_stage10_uvfits_writer.py")
install_gnuradio_stub()
recorder = load_module("stage10_recorder", "grc/fx_interferometer_v1_stage10_uvfits_recorder.py")
settings = load_module("stage10_settings", "grc/fx_interferometer_v1_stage10_settings.py")
settings_persistence = load_module(
    "stage10_settings_persistence", "grc/fx_interferometer_v1_stage10_settings_persistence.py"
)


def pyuvdata_available():
    try:
        import pyuvdata  # noqa: F401

        return True
    except Exception:
        return False


def manual_config(**kwargs):
    values = {
        "source_mode": writer.SOURCE_MANUAL,
        "manual_ra_hours": 5.0,
        "manual_dec_deg": -30.0,
        "delay_correction_enabled": True,
        "fringe_stop_enabled": True,
        "fringe_stop_sign": -1,
    }
    values.update(kwargs)
    return writer.Stage10Config(**values)


def synthetic_record(uvw=(4.0, -3.0, 2.0), vis=3.0 + 4.0j, jd=None, integration=1.0):
    time = Time("2026-09-04T00:00:00.500", scale="utc") if jd is None else Time(jd, format="jd", scale="utc")
    return writer.VisibilityRecord(
        output_utc_iso=(time + integration * 0.5 * u.s).utc.isot,
        integration_center_utc_iso=time.utc.isot,
        integration_center_jd=float(time.jd),
        vis_real=float(complex(vis).real),
        vis_imag=float(complex(vis).imag),
        window_coherence_pct=99.0,
        effective_integration_s=float(integration),
        integration_samples=10.0 * float(integration),
        apparent_ra_h=5.0,
        apparent_dec_deg=-30.0,
        lmst_h=7.0,
        ha_h=2.0,
        az_deg=120.0,
        el_deg=45.0,
        u_m=float(uvw[0]),
        v_m=float(uvw[1]),
        w_m=float(uvw[2]),
        u_lambda=0.0,
        v_lambda=0.0,
        w_lambda=0.0,
    )


@unittest.skipUnless(pyuvdata_available(), "pyuvdata is required for Stage 10 UVFITS tests")
class Stage10UVFITSTests(unittest.TestCase):
    def test_effective_bandwidth_matches_stage8_edge_exclusion(self):
        n_edge, n_used, delta_f, effective_bw = writer.effective_bandwidth_hz(4096, 30.72e6, 20.0)
        self.assertEqual(n_edge, 819)
        self.assertEqual(n_used, 2458)
        self.assertEqual(delta_f, 7500.0)
        self.assertEqual(effective_bw, 18435000.0)

    def test_ideal_east_west_baseline_signs(self):
        np.testing.assert_allclose(writer.uvw_from_enu((6, 0, 0), 0, 0, 0), [6, 0, 0], atol=1e-12)
        np.testing.assert_allclose(writer.uvw_from_enu((6, 0, 0), 0, -6, 0), [0, 0, 6], atol=1e-12)
        np.testing.assert_allclose(writer.uvw_from_enu((6, 0, 0), 0, 6, 0), [0, 0, -6], atol=1e-12)

    def test_baseline_norm_is_preserved(self):
        baseline = np.array([-5.785, 0.095, 0.580], dtype=np.float64)
        expected = np.dot(baseline, baseline)
        for ha in (-5.0, -1.0, 0.0, 3.5, 5.9):
            for dec in (-60.0, -10.0, 25.0):
                uvw = writer.uvw_from_enu(baseline, -32.724, ha, dec)
                self.assertAlmostEqual(float(np.dot(uvw, uvw)), expected, places=10)

    def test_antenna_ecef_offsets_roundtrip_to_project_enu_baseline(self):
        config = manual_config()
        offsets = writer.antenna_positions_ecef_offsets(config)
        enu = writer.antenna_offsets_to_enu(config, offsets)
        np.testing.assert_allclose(enu[1] - enu[0], [-5.785, 0.095, 0.580], atol=1e-3)

    def test_one_record_roundtrip_preserves_uvw_and_complex_visibility(self):
        from pyuvdata import UVData

        with tempfile.TemporaryDirectory() as tmp:
            config = manual_config()
            path = pathlib.Path(tmp) / "one.uvfits"
            original = writer.write_uvfits(config, [synthetic_record()], path)
            readback = UVData()
            readback.read_uvfits(str(path))
            writer.validate_roundtrip(original, readback)
            np.testing.assert_allclose(readback.uvw_array, [[4.0, -3.0, 2.0]], atol=1e-5)
            np.testing.assert_allclose(readback.data_array[:, 0, 0], [3.0 + 4.0j], atol=1e-5)
            np.testing.assert_array_equal(readback.ant_1_array, [0])
            np.testing.assert_array_equal(readback.ant_2_array, [1])
            self.assertEqual(readback.vis_units, "uncalib")

    def test_multi_record_and_varying_integration_roundtrip(self):
        from pyuvdata import UVData

        with tempfile.TemporaryDirectory() as tmp:
            config = manual_config()
            t0 = Time("2026-09-04T00:00:00.500", scale="utc")
            integrations = [1.0, 5.0, 10.0] + [1.0] * 7
            records = [
                synthetic_record(
                    uvw=(4.0 + i, -3.0 + 0.1 * i, 2.0 - 0.2 * i),
                    vis=(3.0 + i) + (4.0 - i) * 1j,
                    jd=float((t0 + i * u.s).jd),
                    integration=integrations[i],
                )
                for i in range(10)
            ]
            path = pathlib.Path(tmp) / "multi.uvfits"
            original = writer.write_uvfits(config, records, path)
            readback = UVData()
            readback.read_uvfits(str(path))
            writer.validate_roundtrip(original, readback)
            self.assertEqual(readback.Nblts, 10)
            self.assertEqual(readback.Nbls, 1)
            self.assertEqual(readback.Nfreqs, 1)
            self.assertEqual(readback.Npols, 1)
            np.testing.assert_allclose(readback.integration_time[:3], integrations[:3])
            self.assertAlmostEqual(readback.freq_array[0], 4.800e9, delta=1e-3)
            self.assertAlmostEqual(readback.channel_width[0], 18435000.0, delta=1e-3)

    def test_manual_source_record_uses_integration_center_time(self):
        config = manual_config(manual_ra_hours=6.25, manual_dec_deg=-22.5)
        output_time = Time("2026-09-04T00:00:10", scale="utc")
        record = writer.make_visibility_record(config, 1 + 0.5j, 98.0, 10.0, 100.0, output_time=output_time)
        self.assertAlmostEqual(record.integration_center_jd, (output_time - 5.0 * u.s).jd)
        self.assertAlmostEqual(record.effective_integration_s, 10.0)
        self.assertTrue(math.isfinite(record.u_m))
        self.assertTrue(math.isfinite(record.v_m))
        self.assertTrue(math.isfinite(record.w_m))

    def test_sun_uvfits_recording_is_explicitly_rejected_until_ephem_path_is_resolved(self):
        config = writer.Stage10Config(source_mode=writer.SOURCE_SUN)
        with self.assertRaisesRegex(ValueError, "moving Sun ephemeris"):
            config.validate_for_science_recording()

    def test_moon_uvfits_recording_is_explicitly_rejected_until_ephem_path_is_resolved(self):
        config = writer.Stage10Config(source_mode=writer.SOURCE_MOON)
        with self.assertRaisesRegex(ValueError, "moving Moon ephemeris"):
            config.validate_for_science_recording()

    def test_moon_metadata_is_time_varying_and_identified_as_moon(self):
        config = writer.Stage10Config(source_mode=writer.SOURCE_MOON)
        t0 = Time("2026-09-04T00:00:00", scale="utc")
        t1 = Time("2026-09-04T01:00:00", scale="utc")
        m0 = writer.source_metadata(config, t0)
        m1 = writer.source_metadata(config, t1)
        self.assertEqual(m0["cat_name"], "Moon")
        self.assertEqual(m0["cat_type"], "ephem")
        for meta in (m0, m1):
            for key in ("apparent_ra_h", "apparent_dec_deg", "lmst_h", "ha_h", "az_deg", "el_deg"):
                self.assertTrue(math.isfinite(float(meta[key])))
            self.assertTrue(np.all(np.isfinite(meta["uvw_m"])))
        self.assertNotAlmostEqual(m0["apparent_ra_h"], m1["apparent_ra_h"], places=3)
        self.assertNotAlmostEqual(m0["az_deg"], m1["az_deg"], places=3)

    def test_journal_recovery_writes_readable_uvfits_and_diagnostics(self):
        from pyuvdata import UVData

        with tempfile.TemporaryDirectory() as tmp:
            config = manual_config()
            journal = pathlib.Path(tmp) / "recover.stage10.sqlite"
            uvfits = pathlib.Path(tmp) / "recovered.uvfits"
            diagnostics = pathlib.Path(tmp) / "recovered_diagnostics.csv"
            records = [synthetic_record(vis=1 + 2j), synthetic_record(vis=3 + 4j, jd=Time("2026-09-04T00:00:01.5", scale="utc").jd)]
            writer.write_synthetic_journal(
                journal,
                config,
                records,
                {"uvfits": str(uvfits), "partial_uvfits": str(pathlib.Path(tmp) / "recovered.partial.uvfits"), "journal": str(journal), "diagnostics_csv": str(diagnostics)},
            )
            out, diag, _ = writer.finalize_journal(journal)
            self.assertTrue(out.exists())
            self.assertTrue(diag.exists())
            readback = UVData()
            readback.read_uvfits(str(out))
            np.testing.assert_allclose(readback.data_array[:, 0, 0], [1 + 2j, 3 + 4j], atol=1e-5)

    def test_recovery_script_uses_common_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = manual_config()
            journal = pathlib.Path(tmp) / "recover_cli.stage10.sqlite"
            uvfits = pathlib.Path(tmp) / "cli.uvfits"
            diagnostics = pathlib.Path(tmp) / "cli_diagnostics.csv"
            writer.write_synthetic_journal(
                journal,
                config,
                [synthetic_record()],
                {"uvfits": str(uvfits), "partial_uvfits": str(pathlib.Path(tmp) / "cli.partial.uvfits"), "journal": str(journal), "diagnostics_csv": str(diagnostics)},
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/recover_stage10_uvfits.py"), str(journal)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("Recovered UVFITS", result.stdout)
            self.assertTrue(uvfits.exists())

    def test_recorder_state_machine_start_stop_creates_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            block = recorder.blk(
                source_mode=writer.SOURCE_MANUAL,
                uvfits_output_dir=tmp,
                observation_name="state_machine",
                record_uvfits=False,
            )
            self.assertEqual(block._state, writer.STATE_OFF)
            block.set_record_uvfits(True)
            self.assertEqual(block._state, writer.STATE_RECORDING)
            inputs = [
                np.array([1 + 2j, 3 + 4j], dtype=np.complex64),
                np.array([99, 98], dtype=np.float32),
                np.array([1, 1], dtype=np.float32),
                np.array([10, 10], dtype=np.float32),
            ]
            outputs = [np.zeros(2, dtype=np.float32), np.zeros(2, dtype=np.float32)]
            produced = block.work(inputs, outputs)
            self.assertEqual(produced, 2)
            block.set_record_uvfits(False)
            self.assertEqual(block._state, writer.STATE_COMPLETE)
            self.assertEqual(len(list(pathlib.Path(tmp).glob("*.uvfits"))), 1)
            block.set_record_uvfits(True)
            block.work([arr[:1] for arr in inputs], [np.zeros(1, dtype=np.float32), np.zeros(1, dtype=np.float32)])
            block.set_record_uvfits(False)
            self.assertEqual(len(list(pathlib.Path(tmp).glob("*.uvfits"))), 2)

    def test_invalid_output_directory_enters_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            not_dir = pathlib.Path(tmp) / "not_a_dir"
            not_dir.write_text("not a directory")
            block = recorder.blk(
                source_mode=writer.SOURCE_MANUAL,
                uvfits_output_dir=str(not_dir),
                record_uvfits=False,
            )
            block.set_record_uvfits(True)
            self.assertEqual(block._state, writer.STATE_ERROR)

    def test_configuration_change_while_recording_finalizes_current_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            block = recorder.blk(
                source_mode=writer.SOURCE_MANUAL,
                uvfits_output_dir=tmp,
                observation_name="config_change",
                record_uvfits=False,
            )
            block.set_record_uvfits(True)
            inputs = [
                np.array([1 + 2j], dtype=np.complex64),
                np.array([99], dtype=np.float32),
                np.array([1], dtype=np.float32),
                np.array([10], dtype=np.float32),
            ]
            block.work(inputs, [np.zeros(1, dtype=np.float32), np.zeros(1, dtype=np.float32)])
            block.set_sky_cf_hz(4.801e9)
            self.assertEqual(block._state, writer.STATE_COMPLETE)
            self.assertEqual(len(list(pathlib.Path(tmp).glob("*.uvfits"))), 1)

    def test_grc_recorder_fallback_instantiates_when_module_import_fails(self):
        graph = yaml.safe_load((ROOT / "grc/fx_interferometer_v1_stage10.grc").read_text())
        code = next(
            block for block in graph["blocks"] if block["name"] == "uvfits_visibility_recorder"
        )["parameters"]["_source_code"]
        old_path = list(sys.path)
        old_cwd = pathlib.Path.cwd()
        old_gnuradio = sys.modules.get("gnuradio")
        old_gr = sys.modules.get("gnuradio.gr")
        with tempfile.TemporaryDirectory() as tmp:
            try:
                import os

                sys.path = [path for path in sys.path if str(ROOT) not in path]
                install_gnuradio_stub()
                os.chdir(tmp)
                namespace = {"__file__": str(pathlib.Path(tmp) / "dummy_generated.py")}
                exec(code, namespace)
                block = namespace["blk"]()
                self.assertIn("fx_interferometer_v1_stage10_uvfits_recorder", block._error)
            finally:
                os.chdir(old_cwd)
                sys.path = old_path
                if old_gnuradio is None:
                    sys.modules.pop("gnuradio", None)
                else:
                    sys.modules["gnuradio"] = old_gnuradio
                if old_gr is None:
                    sys.modules.pop("gnuradio.gr", None)
                else:
                    sys.modules["gnuradio.gr"] = old_gr

    def test_queue_overflow_enters_error(self):
        class FullQueue:
            def put_nowait(self, _item):
                raise recorder.queue.Full

        block = recorder.blk(source_mode=writer.SOURCE_MANUAL, record_uvfits=False)
        block._state = writer.STATE_RECORDING
        block._queue = FullQueue()
        block._config = manual_config()
        inputs = [
            np.array([1 + 2j], dtype=np.complex64),
            np.array([99], dtype=np.float32),
            np.array([1], dtype=np.float32),
            np.array([10], dtype=np.float32),
        ]
        block.work(inputs, [np.zeros(1, dtype=np.float32), np.zeros(1, dtype=np.float32)])
        self.assertEqual(block._state, writer.STATE_ERROR)

    def test_grc_stage10_controls_blocks_and_connections(self):
        graph = yaml.safe_load((ROOT / "grc/fx_interferometer_v1_stage10.grc").read_text())
        blocks = {block["name"]: block for block in graph["blocks"]}
        for name in {
            "observation_name",
            "uvfits_output_dir",
            "record_uvfits",
            "stage10_settings_import",
            "stage10_settings_persistence",
            "stage10_polarization",
            "stage10_queue_max_records",
            "uvfits_visibility_recorder",
            "stage10_recording_status_sink",
        }:
            self.assertIn(name, blocks)
        self.assertEqual(blocks["record_uvfits"]["id"], "variable_qtgui_toggle_button_msg")
        self.assertEqual(blocks["record_uvfits"]["parameters"]["value"], "False")
        self.assertNotIn("fx_settings_load", blocks["record_uvfits"]["parameters"]["value"])
        self.assertEqual(blocks["source_mode"]["parameters"]["options"], "[0, 1, 2]")
        self.assertEqual(blocks["source_mode"]["parameters"]["label0"], "Sun")
        self.assertEqual(blocks["source_mode"]["parameters"]["label1"], "Moon")
        self.assertEqual(blocks["source_mode"]["parameters"]["label2"], "Manual RA/Dec")
        self.assertEqual(blocks["stage10_polarization"]["parameters"]["value"], '"xx"')
        self.assertEqual(blocks["stage10_recording_status_sink"]["parameters"]["nconnections"], "2")
        recorder_code = blocks["uvfits_visibility_recorder"]["parameters"]["_source_code"]
        self.assertIn("_add_stage10_module_paths()", recorder_code)
        self.assertIn("from fx_interferometer_v1_stage10_uvfits_recorder import blk", recorder_code)
        self.assertIn("except Exception as _stage10_import_error", recorder_code)
        astronomy_code = blocks["astronomy_coordinate_engine"]["parameters"]["_source_code"]
        self.assertIn("from fx_interferometer_v1_stage9_astronomy_coordinate_engine import blk", astronomy_code)
        self.assertIn("except Exception as _stage5_import_error", astronomy_code)

        connections = {tuple(connection) for connection in graph["connections"]}
        expected = {
            ("coherent_visibility_integrator", "0", "uvfits_visibility_recorder", "0"),
            ("coherent_visibility_integrator", "1", "uvfits_visibility_recorder", "1"),
            ("coherent_visibility_integrator", "2", "uvfits_visibility_recorder", "2"),
            ("coherent_visibility_integrator", "3", "uvfits_visibility_recorder", "3"),
            ("uvfits_visibility_recorder", "0", "stage10_recording_status_sink", "0"),
            ("uvfits_visibility_recorder", "1", "stage10_recording_status_sink", "1"),
        }
        self.assertTrue(expected.issubset(connections))
        self.assertFalse(any(c[2] == "uvfits_visibility_recorder" and c[0] in {"astronomy_coordinate_engine", "baseline_geometry_engine"} for c in connections))

    def test_settings_json_tolerates_missing_corrupt_and_persists_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get(settings.ENV_SETTINGS_PATH)
            os.environ[settings.ENV_SETTINGS_PATH] = str(pathlib.Path(tmp) / "settings.json")
            try:
                self.assertEqual(settings.load_setting("source_mode", None), writer.SOURCE_SUN)
                settings.settings_path().write_text("{corrupt", encoding="utf-8")
                self.assertEqual(settings.load_setting("source_mode", None), writer.SOURCE_SUN)
                settings.save_settings(source_mode=writer.SOURCE_MOON, observation_name="test_moon")
                loaded = settings.load_settings()
                self.assertEqual(loaded["settings_version"], 1)
                self.assertEqual(loaded["source_mode"], writer.SOURCE_MOON)
                self.assertEqual(loaded["observation_name"], "test_moon")
                settings.save_settings(record_uvfits=True)
                raw = settings.settings_path().read_text(encoding="utf-8")
                self.assertNotIn("record_uvfits", raw)
            finally:
                if old_env is None:
                    os.environ.pop(settings.ENV_SETTINGS_PATH, None)
                else:
                    os.environ[settings.ENV_SETTINGS_PATH] = old_env

    def test_settings_persistence_block_saves_on_variable_setters(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get(settings.ENV_SETTINGS_PATH)
            os.environ[settings.ENV_SETTINGS_PATH] = str(pathlib.Path(tmp) / "settings.json")
            try:
                block = settings_persistence.blk(source_mode=writer.SOURCE_MOON, observation_name="moon_test")
                self.assertEqual(settings.load_setting("source_mode"), writer.SOURCE_MOON)
                self.assertEqual(settings.load_setting("observation_name"), "moon_test")
                block.set_integration_time_s("5.0")
                block.set_uvfits_output_dir("~/FX_Correlator_Data/Test")
                loaded = settings.load_settings()
                self.assertEqual(loaded["integration_time_s"], "5.0")
                self.assertEqual(loaded["uvfits_output_dir"], "~/FX_Correlator_Data/Test")
            finally:
                if old_env is None:
                    os.environ.pop(settings.ENV_SETTINGS_PATH, None)
                else:
                    os.environ[settings.ENV_SETTINGS_PATH] = old_env

    def test_existing_grc_block_layout_and_connections_are_preserved(self):
        try:
            old_bytes = subprocess.check_output(
                ["git", "show", "HEAD:grc/fx_interferometer_v1_stage10.grc"],
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            old_bytes = subprocess.check_output(["git", "show", "HEAD:grc/fx_interferometer_v1_stage9.grc"])
        old = yaml.safe_load(old_bytes)
        new = yaml.safe_load((ROOT / "grc/fx_interferometer_v1_stage10.grc").read_text())
        old_blocks = {block["name"]: block for block in old["blocks"]}
        new_blocks = {block["name"]: block for block in new["blocks"]}
        changed = []
        for name, old_block in old_blocks.items():
            self.assertIn(name, new_blocks)
            for key in ("coordinate", "rotation", "bus_sink", "bus_source", "bus_structure"):
                old_state = old_block.get("states", {}).get(key)
                new_state = new_blocks[name].get("states", {}).get(key)
                if old_state != new_state:
                    changed.append((name, key, old_state, new_state))
        self.assertEqual(changed, [])
        self.assertTrue({tuple(c) for c in old["connections"]}.issubset({tuple(c) for c in new["connections"]}))


if __name__ == "__main__":
    unittest.main()
