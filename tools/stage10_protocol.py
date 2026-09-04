import json
import math
from datetime import datetime, timezone


SCHEMA_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48710


def source_name_for_mode(source_mode):
    try:
        mode = int(source_mode)
    except (TypeError, ValueError):
        return "INVALID"
    if mode == 0:
        return "Sun"
    if mode == 1:
        return "Manual"
    return "INVALID"


def bool_value(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
    return bool(value)


def finite_float(value, default=math.nan):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def packet_from_visibility(sequence, visibility, window_coherence_pct, effective_integration_s, n_int, config):
    vis = complex(visibility)
    source_mode = int(config.get("source_mode", -1))
    return {
        "schema_version": SCHEMA_VERSION,
        "sequence": int(sequence),
        "emitted_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_mode": source_mode,
        "source_name": source_name_for_mode(source_mode),
        "manual_ra_hours": finite_float(config.get("manual_ra_hours")),
        "manual_dec_deg": finite_float(config.get("manual_dec_deg")),
        "site_lat_deg": finite_float(config.get("site_lat_deg")),
        "site_lon_deg": finite_float(config.get("site_lon_deg")),
        "site_height_m": finite_float(config.get("site_height_m")),
        "baseline_e_m": finite_float(config.get("baseline_e_m")),
        "baseline_n_m": finite_float(config.get("baseline_n_m")),
        "baseline_u_m": finite_float(config.get("baseline_u_m")),
        "sky_cf_hz": finite_float(config.get("sky_cf_hz")),
        "samp_rate": finite_float(config.get("samp_rate")),
        "fft_size": int(config.get("fft_size")),
        "visibility_edge_exclude_pct": finite_float(config.get("visibility_edge_exclude_pct")),
        "instrument_delay_ns": finite_float(config.get("instrument_delay_ns")),
        "delay_correction_enable": bool_value(config.get("delay_correction_enable")),
        "fringe_stop_enable": bool_value(config.get("fringe_stop_enable")),
        "fringe_stop_sign": int(config.get("fringe_stop_sign")),
        "visibility_real": float(vis.real),
        "visibility_imag": float(vis.imag),
        "window_coherence_pct": finite_float(window_coherence_pct),
        "effective_integration_s": finite_float(effective_integration_s),
        "n_int": finite_float(n_int),
    }


def encode_packet(packet):
    return (json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def decode_line(line):
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    packet = json.loads(line)
    if int(packet.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError(f"unsupported Stage 10 schema_version {packet.get('schema_version')}")
    return packet


def packet_to_writer_config(packet, observation_name, output_dir):
    return {
        "observation_name": observation_name,
        "output_dir": output_dir,
        "source_mode": int(packet["source_mode"]),
        "manual_ra_hours": float(packet["manual_ra_hours"]),
        "manual_dec_deg": float(packet["manual_dec_deg"]),
        "site_lat_deg": float(packet["site_lat_deg"]),
        "site_lon_deg": float(packet["site_lon_deg"]),
        "site_height_m": float(packet["site_height_m"]),
        "baseline_e_m": float(packet["baseline_e_m"]),
        "baseline_n_m": float(packet["baseline_n_m"]),
        "baseline_u_m": float(packet["baseline_u_m"]),
        "sky_cf_hz": float(packet["sky_cf_hz"]),
        "samp_rate": float(packet["samp_rate"]),
        "fft_size": int(packet["fft_size"]),
        "visibility_edge_exclude_pct": float(packet["visibility_edge_exclude_pct"]),
        "instrument_delay_ns": float(packet["instrument_delay_ns"]),
        "delay_correction_enable": bool(packet["delay_correction_enable"]),
        "fringe_stop_enable": bool(packet["fringe_stop_enable"]),
        "fringe_stop_sign": int(packet["fringe_stop_sign"]),
        "integration_time_s": float(packet["effective_integration_s"]),
    }


def packet_to_writer_record(packet):
    from astropy.time import Time

    return {
        "visibility": complex(float(packet["visibility_real"]), float(packet["visibility_imag"])),
        "coherence_pct": float(packet["window_coherence_pct"]),
        "effective_integration_s": float(packet["effective_integration_s"]),
        "n_int": float(packet["n_int"]),
        "t_center": Time(datetime.fromisoformat(str(packet["emitted_utc"]).replace("Z", "+00:00")), scale="utc"),
    }
