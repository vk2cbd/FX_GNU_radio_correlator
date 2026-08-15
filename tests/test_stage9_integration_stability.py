import importlib.util
import math
import pathlib
import subprocess
import sys
import types
import unittest

import numpy as np
import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]


class _FakeBasicBlock:
    def __init__(self, *args, **kwargs):
        self.consumed = []

    def consume(self, port, count):
        self.consumed.append((port, count))


class _FakeSyncBlock(_FakeBasicBlock):
    pass


def install_gnuradio_stub():
    gnuradio = types.ModuleType("gnuradio")
    gr = types.SimpleNamespace(basic_block=_FakeBasicBlock, sync_block=_FakeSyncBlock)
    gnuradio.gr = gr
    sys.modules["gnuradio"] = gnuradio
    sys.modules["gnuradio.gr"] = gr


def load_block_module(module_name, relative_path):
    install_gnuradio_stub()
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


integrator_module = load_block_module(
    "stage9_integrator", "grc/fx_interferometer_v1_stage9_coherent_visibility_integrator.py"
)
advisor_module = load_block_module(
    "stage9_advisor", "grc/fx_interferometer_v1_stage9_phase_stability_advisor.py"
)


def head_grc():
    try:
        data = subprocess.check_output(
            ["git", "show", "HEAD:grc/fx_interferometer_v1_stage9.grc"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        previous_name = "HEAD:grc/fx_interferometer_v1_" + "stage1" + "_3.grc"
        data = subprocess.check_output(["git", "show", previous_name])
    return yaml.safe_load(data)


def run_integrator(block, samples, out_capacity=None):
    samples = np.asarray(samples, dtype=np.complex64)
    capacity = out_capacity if out_capacity is not None else max(1, len(samples))
    outputs = [
        np.zeros(capacity, dtype=np.complex64),
        np.zeros(capacity, dtype=np.float32),
        np.zeros(capacity, dtype=np.float32),
        np.zeros(capacity, dtype=np.float32),
    ]
    produced = block.general_work([samples], outputs)
    return tuple(out[:produced].copy() for out in outputs), produced


def run_advisor(block, samples):
    samples = np.asarray(samples, dtype=np.complex64)
    outputs = [np.zeros(len(samples), dtype=np.float32) for _ in range(7)]
    produced = block.work([samples], outputs)
    return tuple(out[:produced].copy() for out in outputs)


def measured_coherence_pct(samples):
    samples = np.asarray(samples, dtype=np.complex64)
    denom = np.sum(np.abs(samples), dtype=np.float64)
    return 100.0 * abs(np.sum(samples, dtype=np.complex128)) / denom


class Stage9IntegrationStabilityTests(unittest.TestCase):
    def test_constant_complex_visibility_integrates_without_loss(self):
        for phase in (0.6, -1.2):
            block = integrator_module.blk(visibility_rate=10.0, integration_time_s=1.0)
            value = np.complex64(3.5 * np.exp(1j * phase))
            outputs, produced = run_integrator(block, [value] * 30)
            vis, coherence, effective, n_int = outputs
            self.assertEqual(produced, 3)
            np.testing.assert_allclose(vis, value, rtol=1e-6, atol=1e-6)
            np.testing.assert_allclose(coherence, 100.0, rtol=1e-6, atol=1e-5)
            np.testing.assert_allclose(effective, 1.0)
            np.testing.assert_allclose(n_int, 10.0)

    def test_non_overlapping_windows(self):
        block = integrator_module.blk(visibility_rate=10.0, integration_time_s=0.3)
        samples = np.array([1, 2, 3, 10, 20, 30, -1, -2, -3], dtype=np.float32).astype(np.complex64)
        outputs, produced = run_integrator(block, samples)
        vis = outputs[0]
        self.assertEqual(produced, 3)
        np.testing.assert_allclose(vis, np.array([2, 20, -2], dtype=np.complex64))

    def test_complex_mean_not_magnitude_or_wrapped_phase(self):
        block = integrator_module.blk(visibility_rate=10.0, integration_time_s=0.2)
        samples = np.array([1 + 2j, -3 + 4j, 5 - 6j, 7 + 8j], dtype=np.complex64)
        outputs, produced = run_integrator(block, samples)
        self.assertEqual(produced, 2)
        np.testing.assert_allclose(outputs[0], np.array([np.mean(samples[:2]), np.mean(samples[2:])]))

    def test_sample_quantisation_uses_half_up_rounding(self):
        cases = [
            (0.1, 1, 0.1),
            (0.25, 3, 0.3),
            (0.5, 5, 0.5),
            (1.0, 10, 1.0),
        ]
        for requested, expected_n, expected_eff in cases:
            block = integrator_module.blk(visibility_rate=10.0, integration_time_s=requested)
            self.assertEqual(block._n_int, expected_n)
            self.assertAlmostEqual(block._effective_integration_s(), expected_eff)

    def test_integrator_forecast_uses_gnuradio_310_return_style(self):
        block = integrator_module.blk(visibility_rate=10.0, integration_time_s=1.0)
        self.assertEqual(block.forecast(4, 1), [1])

    def test_runtime_integration_change_resets_partial_window(self):
        block = integrator_module.blk(visibility_rate=10.0, integration_time_s=1.0)
        outputs, produced = run_integrator(block, [1 + 0j] * 5)
        self.assertEqual(produced, 0)
        block.set_integration_time_s(0.2)
        outputs, produced = run_integrator(block, [2 + 0j, 4 + 0j])
        self.assertEqual(produced, 1)
        self.assertAlmostEqual(outputs[0][0].real, 3.0)

    def test_invalid_visibility_resets_partial_window(self):
        block = integrator_module.blk(visibility_rate=10.0, integration_time_s=0.3)
        samples = [1 + 0j, 2 + 0j, np.nan + 0j, 10 + 0j, 20 + 0j, 30 + 0j]
        outputs, produced = run_integrator(block, samples)
        self.assertEqual(produced, 1)
        self.assertAlmostEqual(outputs[0][0].real, 20.0)

    def test_known_linear_phase_rate(self):
        rate = 10.0
        omega = 0.07
        block = advisor_module.blk(
            visibility_rate=rate,
            integration_time_s=1.0,
            phase_rate_fit_window_s=2.0,
            coherence_target_pct=95.0,
        )
        t = np.arange(20, dtype=np.float64) / rate
        samples = np.exp(1j * (0.4 + omega * t)).astype(np.complex64)
        outputs = run_advisor(block, samples)
        self.assertAlmostEqual(outputs[0][-1], omega * 180.0 / np.pi, places=4)
        self.assertLess(outputs[1][-1], 1e-3)

    def test_phase_wrap_crossing_is_unwrapped(self):
        rate = 10.0
        omega = math.radians(220.0)
        block = advisor_module.blk(
            visibility_rate=rate,
            integration_time_s=1.0,
            phase_rate_fit_window_s=1.0,
            coherence_target_pct=95.0,
        )
        t = np.arange(10, dtype=np.float64) / rate
        samples = np.exp(1j * (math.radians(170.0) + omega * t)).astype(np.complex64)
        outputs = run_advisor(block, samples)
        self.assertAlmostEqual(outputs[0][-1], 220.0, places=3)

    def test_rate_based_coherence_formula(self):
        block = advisor_module.blk(visibility_rate=10.0, integration_time_s=1.0, phase_rate_fit_window_s=1.0)
        self.assertAlmostEqual(block._coherence_for_rate(0.0, 10.0), 1.0)
        omega = 0.4
        t_eff = 2.5
        expected = abs(math.sin(omega * t_eff / 2.0) / (omega * t_eff / 2.0))
        self.assertAlmostEqual(block._coherence_for_rate(omega, t_eff), expected)

    def test_95_percent_recommended_time(self):
        block = advisor_module.blk(coherence_target_pct=95.0)
        x = block._solve_coherence_x(0.95)
        self.assertAlmostEqual(x, 0.551910979, places=6)
        omega = 0.2
        self.assertAlmostEqual(block._recommended_max_s(omega), 1.103821958 / omega, places=5)
        self.assertEqual(block._recommended_max_s(0.0), 60.0)

    def test_measured_window_coherence(self):
        block = integrator_module.blk(visibility_rate=10.0, integration_time_s=0.5)
        phases = np.linspace(-0.4, 0.4, 5)
        samples = np.exp(1j * phases).astype(np.complex64)
        outputs, produced = run_integrator(block, samples)
        self.assertEqual(produced, 1)
        self.assertAlmostEqual(outputs[1][0], measured_coherence_pct(samples), places=5)

        jittered = np.exp(1j * np.array([0.0, math.pi, 0.0, math.pi, 0.0])).astype(np.complex64)
        outputs, produced = run_integrator(block, jittered)
        self.assertLess(outputs[1][0], 25.0)

    def test_integration_amplitude_loss_from_unstopped_fringe(self):
        rate = 10.0
        n_int = 10
        omega = 1.0
        t = np.arange(n_int, dtype=np.float64) / rate
        unstopped = np.exp(1j * omega * t).astype(np.complex64)
        stopped = np.ones(n_int, dtype=np.complex64)
        eta_expected = abs(np.sum(unstopped)) / np.sum(np.abs(unstopped))

        block = integrator_module.blk(visibility_rate=rate, integration_time_s=1.0)
        outputs, _ = run_integrator(block, unstopped)
        self.assertAlmostEqual(abs(outputs[0][0]), eta_expected, places=6)

        block = integrator_module.blk(visibility_rate=rate, integration_time_s=1.0)
        outputs, _ = run_integrator(block, stopped)
        self.assertAlmostEqual(abs(outputs[0][0]), 1.0, places=6)

    def test_advisor_startup_outputs_nan_until_history_full(self):
        block = advisor_module.blk(visibility_rate=10.0, integration_time_s=1.0, phase_rate_fit_window_s=1.0)
        outputs = run_advisor(block, np.ones(9, dtype=np.complex64))
        self.assertTrue(np.isnan(outputs[0][-1]))
        self.assertTrue(np.isnan(outputs[1][-1]))
        outputs = run_advisor(block, np.ones(1, dtype=np.complex64))
        self.assertTrue(np.isfinite(outputs[0][-1]))
        self.assertTrue(np.isfinite(outputs[1][-1]))

    def test_grc_stage9_controls_blocks_and_connections(self):
        graph = yaml.safe_load((ROOT / "grc/fx_interferometer_v1_stage9.grc").read_text())
        blocks = {block["name"]: block for block in graph["blocks"]}
        for name in {
            "integration_time_s",
            "phase_rate_fit_window_s",
            "coherence_target_pct",
            "coherent_visibility_integrator",
            "phase_stability_advisor",
            "stage9_number_sink",
        }:
            self.assertIn(name, blocks)

        self.assertEqual(blocks["integration_time_s"]["id"], "variable_qtgui_entry")
        self.assertEqual(blocks["integration_time_s"]["parameters"]["value"], "1.0")
        self.assertEqual(blocks["integration_time_s"]["parameters"]["type"], "string")
        self.assertEqual(blocks["integration_time_s"]["parameters"]["entry_signal"], "editingFinished")
        self.assertEqual(blocks["phase_rate_fit_window_s"]["parameters"]["value"], "60.0")
        self.assertEqual(blocks["coherence_target_pct"]["parameters"]["value"], "95.0")
        self.assertIn("general_work", blocks["coherent_visibility_integrator"]["parameters"]["_source_code"])
        self.assertIn("np.unwrap(np.angle(values))", blocks["phase_stability_advisor"]["parameters"]["_source_code"])
        self.assertEqual(blocks["phase_stability_effective_integration_null"]["id"], "blocks_null_sink")
        self.assertEqual(blocks["phase_stability_n_int_null"]["id"], "blocks_null_sink")

        connections = {tuple(connection) for connection in graph["connections"]}
        expected = {
            ("delay_slope_corrector", "0", "broadband_visibility_combiner", "0"),
            ("broadband_visibility_combiner", "0", "fringe_stop_corrector", "0"),
            ("fringe_stop_corrector", "0", "coherent_visibility_integrator", "0"),
            ("fringe_stop_corrector", "0", "phase_stability_advisor", "0"),
            ("coherent_visibility_integrator", "0", "integrated_visibility_mag", "0"),
            ("coherent_visibility_integrator", "1", "stage9_number_sink", "5"),
            ("phase_stability_advisor", "0", "stage9_number_sink", "6"),
            ("phase_stability_advisor", "5", "phase_stability_effective_integration_null", "0"),
            ("phase_stability_advisor", "6", "phase_stability_n_int_null", "0"),
        }
        self.assertTrue(expected.issubset(connections))
        self.assertNotIn(("broadband_visibility_combiner", "0", "coherent_visibility_integrator", "0"), connections)

    def test_existing_block_coordinates_are_unchanged(self):
        old = head_grc()
        new = yaml.safe_load((ROOT / "grc/fx_interferometer_v1_stage9.grc").read_text())
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
