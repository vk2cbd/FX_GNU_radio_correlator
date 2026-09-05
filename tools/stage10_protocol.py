import json
import math
from datetime import datetime, timedelta, timezone


SCHEMA_VERSION = 2
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48710


REQUIRED_CONFIG_FIELDS = (
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
    "stokes_code",
    "polarization_label",
    "polarization_assumed",
)


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


def required_value(mapping, field):
    if field not in mapping:
        raise KeyError(f"missing required Stage 10 metadata field: {field}")
    value = mapping[field]
    if value is None:
        raise ValueError(f"required Stage 10 metadata field is None: {field}")
    return value


def required_float(mapping, field):
    value = float(required_value(mapping, field))
    if not math.isfinite(value):
        raise ValueError(f"required Stage 10 metadata field is not finite: {field}")
    return value


def required_int(mapping, field):
    raw = required_value(mapping, field)
    if isinstance(raw, bool):
        raise ValueError(f"required Stage 10 metadata field is not integral: {field}")
    if isinstance(raw, str):
        text = raw.strip()
        if not text or not float(text).is_integer():
            raise ValueError(f"required Stage 10 metadata field is not integral: {field}")
    elif not float(raw).is_integer():
        raise ValueError(f"required Stage 10 metadata field is not integral: {field}")
    value = int(raw)
    return value


def iso_z(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_z(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def bandwidth_metadata(samp_rate, fft_size, edge_pct):
    sample_rate = float(samp_rate)
    fft_len = int(fft_size)
    edge = float(edge_pct)
    if not math.isfinite(sample_rate) or sample_rate <= 0.0:
        raise ValueError("sample rate must be finite and > 0")
    if fft_len <= 0:
        raise ValueError("FFT size must be > 0")
    if not math.isfinite(edge) or edge < 0.0 or edge >= 50.0:
        raise ValueError("visibility edge exclusion must be finite and in [0, 50)")
    n_edge = int(fft_len * edge / 100.0)
    n_used = fft_len - 2 * n_edge
    if n_used <= 0:
        raise ValueError("visibility edge exclusion leaves no retained FFT bins")
    return {
        "retained_fft_bins": int(n_used),
        "effective_correlated_bandwidth_hz": float(n_used) * sample_rate / float(fft_len),
    }


def validate_metadata(packet):
    try:
        source_mode = required_int(packet, "source_mode")
        source_name = str(required_value(packet, "source_name"))
        if source_name == "INVALID" or source_mode not in (0, 1):
            return False, "source mode is not supported"
        if source_name_for_mode(source_mode) != source_name:
            return False, "source_mode/source_name mismatch"
        for field in (
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
            "visibility_edge_exclude_pct",
            "instrument_delay_ns",
            "effective_integration_s",
        ):
            required_float(packet, field)
        fft_size = required_int(packet, "fft_size")
        if fft_size <= 0:
            return False, "FFT size must be > 0"
        n_int = required_int(packet, "n_int")
        if n_int <= 0:
            return False, "n_int must be > 0"
        if required_float(packet, "sky_cf_hz") <= 0.0:
            return False, "sky_cf_hz must be > 0"
        if required_float(packet, "samp_rate") <= 0.0:
            return False, "samp_rate must be > 0"
        baseline = [required_float(packet, f) for f in ("baseline_e_m", "baseline_n_m", "baseline_u_m")]
        if math.sqrt(sum(v * v for v in baseline)) <= 0.0:
            return False, "baseline magnitude must be > 0"
        if required_float(packet, "effective_integration_s") <= 0.0:
            return False, "effective integration must be > 0"
        if not bool_value(required_value(packet, "delay_correction_enable")):
            return False, "delay correction is disabled"
        if not bool_value(required_value(packet, "fringe_stop_enable")):
            return False, "fringe stop is disabled"
        if required_int(packet, "fringe_stop_sign") != -1:
            return False, "fringe stop sign is not Normal (-phi_geo)"
        if required_int(packet, "stokes_code") == 1:
            return False, "measured product must not be labelled as Stokes I"
        required_value(packet, "polarization_label")
        required_value(packet, "polarization_assumed")
        derived = bandwidth_metadata(
            required_float(packet, "samp_rate"),
            fft_size,
            required_float(packet, "visibility_edge_exclude_pct"),
        )
        if required_int(packet, "retained_fft_bins") != derived["retained_fft_bins"]:
            return False, "retained_fft_bins mismatch"
        published_bw = required_float(packet, "effective_correlated_bandwidth_hz")
        if not math.isclose(published_bw, derived["effective_correlated_bandwidth_hz"], rel_tol=1e-9, abs_tol=1e-3):
            return False, "effective_correlated_bandwidth_hz mismatch"
        emitted = parse_iso_z(required_value(packet, "emitted_utc"))
        center = parse_iso_z(required_value(packet, "integration_center_utc"))
        expected_center = emitted - timedelta(seconds=required_float(packet, "effective_integration_s") / 2.0)
        if abs((center - expected_center).total_seconds()) > 1e-6:
            return False, "integration_center_utc mismatch"
    except Exception as exc:
        return False, str(exc)
    return True, ""


def packet_from_visibility(sequence, visibility, window_coherence_pct, effective_integration_s, n_int, config):
    for field in REQUIRED_CONFIG_FIELDS:
        required_value(config, field)
    vis = complex(visibility)
    source_mode = required_int(config, "source_mode")
    emitted = datetime.now(timezone.utc)
    eff_s = finite_float(effective_integration_s)
    if not math.isfinite(eff_s) or eff_s <= 0.0:
        raise ValueError("effective integration must be finite and > 0")
    if isinstance(n_int, bool) or not float(n_int).is_integer() or int(n_int) <= 0:
        raise ValueError("n_int must be a positive integer")
    n_int_value = int(n_int)
    derived = bandwidth_metadata(
        required_float(config, "samp_rate"),
        required_int(config, "fft_size"),
        required_float(config, "visibility_edge_exclude_pct"),
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "sequence": int(sequence),
        "emitted_utc": iso_z(emitted),
        "integration_center_utc": iso_z(emitted - timedelta(seconds=eff_s / 2.0)),
        "source_mode": source_mode,
        "source_name": source_name_for_mode(source_mode),
        "manual_ra_hours": required_float(config, "manual_ra_hours"),
        "manual_dec_deg": required_float(config, "manual_dec_deg"),
        "site_lat_deg": required_float(config, "site_lat_deg"),
        "site_lon_deg": required_float(config, "site_lon_deg"),
        "site_height_m": required_float(config, "site_height_m"),
        "baseline_e_m": required_float(config, "baseline_e_m"),
        "baseline_n_m": required_float(config, "baseline_n_m"),
        "baseline_u_m": required_float(config, "baseline_u_m"),
        "sky_cf_hz": required_float(config, "sky_cf_hz"),
        "samp_rate": required_float(config, "samp_rate"),
        "fft_size": required_int(config, "fft_size"),
        "visibility_edge_exclude_pct": required_float(config, "visibility_edge_exclude_pct"),
        "retained_fft_bins": derived["retained_fft_bins"],
        "effective_correlated_bandwidth_hz": derived["effective_correlated_bandwidth_hz"],
        "instrument_delay_ns": required_float(config, "instrument_delay_ns"),
        "delay_correction_enable": bool_value(required_value(config, "delay_correction_enable")),
        "fringe_stop_enable": bool_value(required_value(config, "fringe_stop_enable")),
        "fringe_stop_sign": required_int(config, "fringe_stop_sign"),
        "stokes_code": required_int(config, "stokes_code"),
        "polarization_label": str(required_value(config, "polarization_label")),
        "polarization_assumed": bool_value(required_value(config, "polarization_assumed")),
        "visibility_real": float(vis.real),
        "visibility_imag": float(vis.imag),
        "window_coherence_pct": finite_float(window_coherence_pct),
        "effective_integration_s": eff_s,
        "n_int": n_int_value,
    }
    valid, reason = validate_metadata(packet)
    packet["metadata_valid"] = valid
    packet["metadata_error"] = reason
    return packet


def encode_packet(packet):
    return (json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def decode_line(line):
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    packet = json.loads(line)
    if int(packet.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError(f"unsupported Stage 10 schema_version {packet.get('schema_version')}")
    return packet


def verify_packet_metadata(packet):
    if int(packet.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError(f"unsupported Stage 10 schema_version {packet.get('schema_version')}")
    valid, reason = validate_metadata(packet)
    if not valid:
        raise ValueError(f"invalid Stage 10 metadata: {reason}")
    if not bool(packet.get("metadata_valid")):
        raise ValueError(f"publisher marked Stage 10 metadata invalid: {packet.get('metadata_error', '')}")
    return True


def packet_to_writer_config(packet, observation_name, output_dir):
    verify_packet_metadata(packet)
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
        "retained_fft_bins": int(packet["retained_fft_bins"]),
        "effective_correlated_bandwidth_hz": float(packet["effective_correlated_bandwidth_hz"]),
        "instrument_delay_ns": float(packet["instrument_delay_ns"]),
        "delay_correction_enable": bool(packet["delay_correction_enable"]),
        "fringe_stop_enable": bool(packet["fringe_stop_enable"]),
        "fringe_stop_sign": int(packet["fringe_stop_sign"]),
        "stokes_code": int(packet["stokes_code"]),
        "polarization_label": str(packet["polarization_label"]),
        "polarization_assumed": bool(packet["polarization_assumed"]),
        "integration_time_s": float(packet["effective_integration_s"]),
    }


def packet_to_writer_record(packet):
    from astropy.time import Time

    verify_packet_metadata(packet)
    return {
        "visibility": complex(float(packet["visibility_real"]), float(packet["visibility_imag"])),
        "coherence_pct": float(packet["window_coherence_pct"]),
        "effective_integration_s": float(packet["effective_integration_s"]),
        "n_int": int(packet["n_int"]),
        "emitted_utc": Time(parse_iso_z(packet["emitted_utc"]), scale="utc"),
        "t_center": Time(parse_iso_z(packet["integration_center_utc"]), scale="utc"),
    }
