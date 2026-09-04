import json
import os
from pathlib import Path


SETTINGS_VERSION = 1
ENV_SETTINGS_PATH = "FX_CORRELATOR_SETTINGS_PATH"

DEFAULTS = {
    "site_lat_deg": -32.724,
    "site_lon_deg": 152.130167,
    "site_height_m": 70.0,
    "source_mode": 0,
    "manual_ra_hours": "5.0",
    "manual_dec_deg": "-30.0",
    "baseline_e_m": -5.785,
    "baseline_n_m": 0.095,
    "baseline_u_m": 0.580,
    "sky_cf": 4.800e9,
    "gain0": 40,
    "gain1": 40,
    "fft_size": 4096,
    "accum_time": 0.1,
    "instrument_delay_ns": "0.0",
    "delay_correction_enable": True,
    "fringe_stop_enable": True,
    "fringe_stop_sign": -1,
    "visibility_edge_exclude_pct": 20.0,
    "integration_time_s": "1.0",
    "phase_rate_fit_window_s": 60.0,
    "coherence_target_pct": 95.0,
    "uvfits_output_dir": "~/FX_Correlator_Data",
    "observation_name": "observation",
}


def settings_path():
    override = os.environ.get(ENV_SETTINGS_PATH)
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".config" / "FX_GNU_radio_correlator" / "settings.json"


def _coerce_like(value, default):
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return str(value)
    return value


def load_settings():
    path = settings_path()
    values = dict(DEFAULTS)
    values["settings_version"] = SETTINGS_VERSION
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return values
    if not isinstance(raw, dict):
        return values
    if int(raw.get("settings_version", SETTINGS_VERSION)) > SETTINGS_VERSION:
        return values
    for key, default in DEFAULTS.items():
        if key not in raw:
            continue
        try:
            values[key] = _coerce_like(raw[key], default)
        except Exception:
            values[key] = default
    return values


def load_setting(key, default=None):
    fallback = DEFAULTS.get(key, default)
    return load_settings().get(key, fallback)


def save_settings(**kwargs):
    path = settings_path()
    current = load_settings()
    for key, value in kwargs.items():
        if key in DEFAULTS:
            current[key] = _coerce_like(value, DEFAULTS[key])
    current["settings_version"] = SETTINGS_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return current


def save_setting(key, value):
    return save_settings(**{key: value})


def reset_defaults():
    path = settings_path()
    values = dict(DEFAULTS)
    values["settings_version"] = SETTINGS_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return values
