import importlib.util
import inspect
import ast
import pathlib
import queue
import sys
import types
import unittest

import numpy as np
import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]


def normalize_io_cache(cache):
    if isinstance(cache, str):
        cache = ast.literal_eval(cache)
    return cache


def load_publisher():
    gnuradio = types.ModuleType("gnuradio")

    class FakeSyncBlock:
        def __init__(self, *args, **kwargs):
            self.init_args = (args, kwargs)

    gnuradio.gr = types.SimpleNamespace(sync_block=FakeSyncBlock)
    sys.modules["gnuradio"] = gnuradio
    sys.modules["gnuradio.gr"] = gnuradio.gr
    sys.path.insert(0, str(ROOT / "tools"))
    path = ROOT / "grc" / "fx_interferometer_v1_stage10_visibility_publisher.py"
    spec = importlib.util.spec_from_file_location("stage10_visibility_publisher_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Stage10PublisherTests(unittest.TestCase):
    def test_grc_is_stage9_plus_publisher_only(self):
        stage9 = yaml.safe_load((ROOT / "grc" / "fx_interferometer_v1_stage9.grc").read_text())
        stage10 = yaml.safe_load((ROOT / "grc" / "fx_interferometer_v1_stage10.grc").read_text())
        self.assertEqual(stage10["options"]["parameters"]["id"], "fx_interferometer_v1_stage10")
        stage9_blocks = {block["name"]: block for block in stage9["blocks"]}
        stage10_blocks = {block["name"]: block for block in stage10["blocks"]}
        for name, block in stage9_blocks.items():
            self.assertIn(name, stage10_blocks)
            self.assertEqual(block["id"], stage10_blocks[name]["id"])
            self.assertEqual(block["states"], stage10_blocks[name]["states"])
        self.assertIn("stage10_visibility_publisher", stage10_blocks)
        self.assertIn("stage10_publisher_status_sink", stage10_blocks)
        for removed in [
            "fitsidi_visibility_recorder",
            "stage10_uv_logging_control_source",
            "stage10_source_mode_control_source",
            "stage10_manual_ra_control_source",
            "stage10_manual_dec_control_source",
            "uv_logging_enable",
            "stage10_number_sink",
            "stage10_observation_name",
            "stage10_output_dir",
        ]:
            self.assertNotIn(removed, stage10_blocks)
        publisher = stage10_blocks["stage10_visibility_publisher"]
        combiner = stage10_blocks["broadband_visibility_combiner"]
        self.assertEqual(combiner["parameters"]["visibility_edge_exclude_pct"], "visibility_edge_exclude_pct")
        self.assertEqual(publisher["parameters"]["visibility_edge_exclude_pct"], "visibility_edge_exclude_pct")
        io_cache = normalize_io_cache(publisher["states"]["_io_cache"])
        params = {name for name, _default in io_cache[2]}
        self.assertIn("visibility_edge_exclude_pct", params)
        self.assertIn("source_mode", params)
        inputs = [list(item) for item in io_cache[3]]
        outputs = [list(item) for item in io_cache[4]]
        self.assertEqual(inputs, [["0", "complex", 1], ["1", "float", 1], ["2", "float", 1], ["3", "float", 1]])
        self.assertEqual(outputs, [["0", "float", 1]])
        connections = {tuple(c) for c in stage10["connections"]}
        self.assertIn(("coherent_visibility_integrator", "0", "stage10_visibility_publisher", "0"), connections)
        self.assertIn(("coherent_visibility_integrator", "1", "stage10_visibility_publisher", "1"), connections)
        self.assertIn(("coherent_visibility_integrator", "2", "stage10_visibility_publisher", "2"), connections)
        self.assertIn(("coherent_visibility_integrator", "3", "stage10_visibility_publisher", "3"), connections)

    def test_grc_embedded_wrapper_exposes_constructor_metadata_params(self):
        stage10 = yaml.safe_load((ROOT / "grc" / "fx_interferometer_v1_stage10.grc").read_text())
        blocks = {block["name"]: block for block in stage10["blocks"]}
        source = blocks["stage10_visibility_publisher"]["parameters"]["_source_code"]
        gnuradio = types.ModuleType("gnuradio")

        class FakeSyncBlock:
            def __init__(self, *args, **kwargs):
                self.init_args = (args, kwargs)

        class FakePublisher(FakeSyncBlock):
            pass

        gnuradio.gr = types.SimpleNamespace(sync_block=FakeSyncBlock)
        fake_module = types.ModuleType("fx_interferometer_v1_stage10_visibility_publisher")
        fake_module.blk = FakePublisher
        old_modules = {name: sys.modules.get(name) for name in ["gnuradio", "gnuradio.gr", fake_module.__name__]}
        sys.modules["gnuradio"] = gnuradio
        sys.modules["gnuradio.gr"] = gnuradio.gr
        sys.modules[fake_module.__name__] = fake_module
        namespace = {}
        try:
            exec(source, namespace)
        finally:
            for name, old in old_modules.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old
        params = inspect.signature(namespace["blk"].__init__).parameters
        for required in [
            "source_mode",
            "manual_ra_hours",
            "manual_dec_deg",
            "site_lat_deg",
            "site_lon_deg",
            "site_height_m",
            "baseline_e_m",
            "baseline_n_m",
            "baseline_u_m",
            "sky_cf_hz",
            "samp_rate",
            "fft_size",
            "visibility_edge_exclude_pct",
            "instrument_delay_ns",
            "delay_correction_enable",
            "fringe_stop_enable",
            "fringe_stop_sign",
        ]:
            self.assertIn(required, params)
        instance = namespace["blk"](visibility_edge_exclude_pct=5.0, source_mode=1)
        self.assertEqual(instance.init_args[1]["visibility_edge_exclude_pct"], 5.0)
        self.assertEqual(instance.init_args[1]["source_mode"], 1)

    def test_publisher_packets_have_source_and_science_values(self):
        module = load_publisher()
        block = module.blk(port=0)
        block._connected = True
        block._queue = queue.Queue(maxsize=10)
        block.set_source_mode(0)
        inputs = [
            np.array([3 + 4j], dtype=np.complex64),
            np.array([99.5], dtype=np.float32),
            np.array([1.0], dtype=np.float32),
            np.array([10.0], dtype=np.float32),
        ]
        outputs = [np.zeros(1, dtype=np.float32)]
        block.work(inputs, outputs)
        sun = block._queue.get_nowait()
        self.assertEqual(sun["source_mode"], 0)
        self.assertEqual(sun["source_name"], "Sun")
        self.assertEqual(sun["visibility_real"], 3.0)
        self.assertEqual(sun["visibility_imag"], 4.0)
        self.assertEqual(sun["sequence"], 0)
        block.set_source_mode(1)
        block.work(inputs, outputs)
        manual = block._queue.get_nowait()
        self.assertEqual(manual["source_mode"], 1)
        self.assertEqual(manual["source_name"], "Manual")
        self.assertEqual(manual["sequence"], 1)
        block.set_visibility_edge_exclude_pct(5.0)
        block.work(inputs, outputs)
        edge_5 = block._queue.get_nowait()
        self.assertEqual(edge_5["visibility_edge_exclude_pct"], 5.0)
        self.assertEqual(edge_5["retained_fft_bins"], 3688)
        self.assertEqual(edge_5["effective_correlated_bandwidth_hz"], 27660000.0)
        block.set_visibility_edge_exclude_pct(12.5)
        block.work(inputs, outputs)
        edge_12_5 = block._queue.get_nowait()
        self.assertEqual(edge_12_5["visibility_edge_exclude_pct"], 12.5)
        self.assertEqual(edge_12_5["retained_fft_bins"], 3072)
        self.assertEqual(edge_12_5["effective_correlated_bandwidth_hz"], 23040000.0)

    def test_publisher_reads_live_grc_owner_values_when_generated_without_args(self):
        module = load_publisher()

        class GeneratedTopBlock:
            source_mode = 1
            manual_ra_hours = 18.3
            manual_dec_deg = -16.2
            site_lat_deg = -32.724
            site_lon_deg = 152.130167
            site_height_m = 70.0
            baseline_e_m = -5.785
            baseline_n_m = 0.095
            baseline_u_m = 0.580
            sky_cf = 4.8e9
            samp_rate = 30.72e6
            fft_size = 4096
            visibility_edge_exclude_pct = 5.0
            instrument_delay_ns = -1.9
            delay_correction_enable = True
            fringe_stop_enable = True
            fringe_stop_sign = -1
            stokes_code = -5
            polarization_label = "XX"
            polarization_assumed = True

            def __init__(self):
                self.stage10_visibility_publisher = module.blk(port=0)

        top_block = GeneratedTopBlock()
        block = top_block.stage10_visibility_publisher
        block._connected = True
        block._queue = queue.Queue(maxsize=10)
        inputs = [
            np.array([3 + 4j], dtype=np.complex64),
            np.array([99.5], dtype=np.float32),
            np.array([1.0], dtype=np.float32),
            np.array([10.0], dtype=np.float32),
        ]
        outputs = [np.zeros(1, dtype=np.float32)]
        block.work(inputs, outputs)
        packet = block._queue.get_nowait()
        self.assertEqual(packet["source_mode"], 1)
        self.assertEqual(packet["source_name"], "Manual")
        self.assertEqual(packet["manual_ra_hours"], 18.3)
        self.assertEqual(packet["manual_dec_deg"], -16.2)
        self.assertEqual(packet["visibility_edge_exclude_pct"], 5.0)
        self.assertEqual(packet["retained_fft_bins"], 3688)
        self.assertEqual(packet["effective_correlated_bandwidth_hz"], 27660000.0)

        top_block.source_mode = 0
        top_block.visibility_edge_exclude_pct = 12.5
        block.work(inputs, outputs)
        updated = block._queue.get_nowait()
        self.assertEqual(updated["source_name"], "Sun")
        self.assertEqual(updated["visibility_edge_exclude_pct"], 12.5)
        self.assertEqual(updated["retained_fft_bins"], 3072)
        self.assertEqual(updated["effective_correlated_bandwidth_hz"], 23040000.0)


if __name__ == "__main__":
    unittest.main()
