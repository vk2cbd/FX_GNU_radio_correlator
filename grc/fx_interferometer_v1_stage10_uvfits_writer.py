import csv
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, TETE, get_sun
from astropy.time import Time
from astropy.utils import iers

iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"


STATE_OFF = 0
STATE_RECORDING = 1
STATE_FINALIZING = 2
STATE_COMPLETE = 3
STATE_ERROR = 4

STATE_NAMES = {
    STATE_OFF: "OFF",
    STATE_RECORDING: "RECORDING",
    STATE_FINALIZING: "FINALIZING",
    STATE_COMPLETE: "COMPLETE",
    STATE_ERROR: "ERROR",
}

SOURCE_SUN = 0
SOURCE_MANUAL = 1

DEFAULT_POLARIZATION = "xx"
TELESCOPE_NAME = "FX_GNU_RADIO_INTERFEROMETER"
ANTENNA_NAMES = ("ANT0_2P4M", "ANT1_1P7M")
ANTENNA_NUMBERS = (0, 1)


@dataclass(frozen=True)
class Stage10Config:
    observation_name: str = "observation"
    output_dir: str = "~/FX_Correlator_Data"
    source_mode: int = SOURCE_SUN
    manual_ra_hours: float = 5.0
    manual_dec_deg: float = -30.0
    site_lat_deg: float = -32.724
    site_lon_deg: float = 152.130167
    site_height_m: float = 70.0
    baseline_e_m: float = -5.785
    baseline_n_m: float = 0.095
    baseline_u_m: float = 0.580
    sky_cf_hz: float = 4.800e9
    lnb_lo_hz: float = 5.950e9
    samp_rate_hz: float = 30.72e6
    fft_size: int = 4096
    visibility_edge_exclude_pct: float = 20.0
    polarization: str = DEFAULT_POLARIZATION
    delay_correction_enabled: bool = True
    fringe_stop_enabled: bool = True
    fringe_stop_sign: int = -1
    instrument_delay_ns: float = 0.0
    gain0_db: float = 40.0
    gain1_db: float = 40.0
    calibration_state: str = "UNCALIBRATED"
    software_commit: str = "unknown"
    gnuradio_version: str = "unknown"

    def source_name(self):
        return "Sun" if int(self.source_mode) == SOURCE_SUN else "Manual"

    def validate_for_science_recording(self):
        if not bool(self.delay_correction_enabled):
            raise ValueError("UVFITS recording cannot start: delay correction is disabled.")
        if not bool(self.fringe_stop_enabled) or int(self.fringe_stop_sign) != -1:
            raise ValueError("UVFITS recording cannot start: fringe-stop mode is not Normal (-phi_geo).")
        if int(self.source_mode) == SOURCE_SUN:
            version = pyuvdata_version() or "the installed pyuvdata version"
            raise ValueError(
                f"UVFITS recording cannot start: pyuvdata {version} does not write moving Sun "
                "ephemeris phase centres to UVFITS without force-phasing. Use Manual RA/Dec "
                "for Stage 10 recording until the Sun file-format path is resolved."
            )
        if int(self.fft_size) <= 0:
            raise ValueError("UVFITS recording cannot start: FFT size is invalid.")
        if float(self.samp_rate_hz) <= 0.0:
            raise ValueError("UVFITS recording cannot start: sample rate is invalid.")


@dataclass(frozen=True)
class VisibilityRecord:
    output_utc_iso: str
    integration_center_utc_iso: str
    integration_center_jd: float
    vis_real: float
    vis_imag: float
    window_coherence_pct: float
    effective_integration_s: float
    integration_samples: float
    apparent_ra_h: float
    apparent_dec_deg: float
    lmst_h: float
    ha_h: float
    az_deg: float
    el_deg: float
    u_m: float
    v_m: float
    w_m: float
    u_lambda: float
    v_lambda: float
    w_lambda: float


def pyuvdata_version():
    try:
        import pyuvdata

        return pyuvdata.__version__
    except Exception:
        return None


def require_pyuvdata():
    try:
        import pyuvdata
        from pyuvdata import Telescope, UVData, utils

        return pyuvdata, UVData, Telescope, utils
    except Exception as exc:
        raise RuntimeError(
            "pyuvdata is required for Stage 10 UVFITS writing. Install a GNU Radio "
            "Python-compatible pyuvdata package on Ubuntu, for example: "
            "python3 -m pip install pyuvdata"
        ) from exc


def sanitize_component(value, default="observation"):
    text = str(value or default).strip().replace(" ", "_")
    text = re.sub(r"[\\/:\*\?\"<>\|\s]+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    return text or default


def unique_observation_paths(config, start_time=None):
    out_dir = Path(os.path.expanduser(str(config.output_dir))).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not out_dir.is_dir():
        raise ValueError(f"UVFITS recording cannot start: output directory is not a directory: {out_dir}")
    stamp_time = start_time or datetime.now(timezone.utc)
    stamp = stamp_time.strftime("%Y%m%dT%H%M%SZ")
    obs = sanitize_component(config.observation_name)
    source = sanitize_component(config.source_name(), "source")
    stem = f"{stamp}_{obs}_{source}_B01"
    for suffix in [""] + [f"_{idx:03d}" for idx in range(1, 1000)]:
        candidate = out_dir / f"{stem}{suffix}.uvfits"
        if not candidate.exists():
            return {
                "uvfits": candidate,
                "partial_uvfits": out_dir / f"{stem}{suffix}.partial.uvfits",
                "journal": out_dir / f".{stem}{suffix}.stage10.sqlite",
                "diagnostics_csv": out_dir / f"{stem}{suffix}_diagnostics.csv",
            }
    raise ValueError("UVFITS recording cannot start: could not create a unique output filename.")


def effective_bandwidth_hz(fft_size, samp_rate_hz, edge_exclude_pct):
    nfft = int(fft_size)
    edge_pct = float(edge_exclude_pct)
    if edge_pct < 0.0:
        edge_pct = 0.0
    elif edge_pct >= 50.0:
        edge_pct = 49.0
    n_edge = int(nfft * edge_pct / 100.0)
    if nfft - 2 * n_edge < 2:
        n_edge = 0
    n_used = nfft - 2 * n_edge
    delta_f = float(samp_rate_hz) / float(nfft)
    return n_edge, n_used, delta_f, n_used * delta_f


def uvw_from_enu(baseline_enu_m, site_lat_deg, hour_angle_h, apparent_dec_deg):
    e_m, n_m, up_m = [float(value) for value in baseline_enu_m]
    baseline = np.array([e_m, n_m, up_m], dtype=np.float64)
    phi = math.radians(float(site_lat_deg))
    h_rad = math.radians(float(hour_angle_h) * 15.0)
    dec = math.radians(float(apparent_dec_deg))

    u_hat = np.array(
        [
            math.cos(h_rad),
            -math.sin(phi) * math.sin(h_rad),
            math.cos(phi) * math.sin(h_rad),
        ],
        dtype=np.float64,
    )
    v_hat = np.array(
        [
            math.sin(dec) * math.sin(h_rad),
            math.cos(phi) * math.cos(dec) + math.sin(phi) * math.sin(dec) * math.cos(h_rad),
            math.sin(phi) * math.cos(dec) - math.cos(phi) * math.sin(dec) * math.cos(h_rad),
        ],
        dtype=np.float64,
    )
    w_hat = np.array(
        [
            -math.cos(dec) * math.sin(h_rad),
            math.sin(dec) * math.cos(phi) - math.cos(dec) * math.cos(h_rad) * math.sin(phi),
            math.sin(dec) * math.sin(phi) + math.cos(dec) * math.cos(h_rad) * math.cos(phi),
        ],
        dtype=np.float64,
    )
    return np.array([baseline @ u_hat, baseline @ v_hat, baseline @ w_hat], dtype=np.float64)


def source_metadata(config, center_time):
    location = EarthLocation(
        lat=float(config.site_lat_deg) * u.deg,
        lon=float(config.site_lon_deg) * u.deg,
        height=float(config.site_height_m) * u.m,
    )
    if isinstance(center_time, Time):
        obstime = Time(center_time.utc.jd, format="jd", scale="utc", location=location)
    else:
        obstime = Time(center_time, scale="utc", location=location)
    if int(config.source_mode) == SOURCE_SUN:
        source_coord = get_sun(obstime)
        cat_name = "Sun"
        cat_type = "ephem"
    else:
        source_coord = SkyCoord(
            ra=float(config.manual_ra_hours) * u.hourangle,
            dec=float(config.manual_dec_deg) * u.deg,
            frame="icrs",
        )
        cat_name = "Manual"
        cat_type = "sidereal"

    apparent = source_coord.transform_to(TETE(obstime=obstime, location=location))
    altaz = source_coord.transform_to(AltAz(obstime=obstime, location=location, pressure=0 * u.hPa))
    lmst_h = obstime.sidereal_time("apparent", longitude=float(config.site_lon_deg) * u.deg).hour % 24.0
    apparent_ra_h = apparent.ra.hour % 24.0
    apparent_dec_deg = apparent.dec.deg
    ha_h = ((lmst_h - apparent_ra_h + 12.0) % 24.0) - 12.0
    uvw_m = uvw_from_enu(
        (config.baseline_e_m, config.baseline_n_m, config.baseline_u_m),
        config.site_lat_deg,
        ha_h,
        apparent_dec_deg,
    )
    wavelength_m = 299792458.0 / float(config.sky_cf_hz)
    return {
        "time": obstime,
        "source_coord": source_coord,
        "cat_name": cat_name,
        "cat_type": cat_type,
        "apparent_ra_h": apparent_ra_h,
        "apparent_dec_deg": apparent_dec_deg,
        "lmst_h": lmst_h,
        "ha_h": ha_h,
        "az_deg": altaz.az.deg % 360.0,
        "el_deg": altaz.alt.deg,
        "uvw_m": uvw_m,
        "uvw_lambda": uvw_m / wavelength_m,
    }


def make_visibility_record(config, visibility, window_coherence_pct, effective_integration_s, integration_samples, output_time=None):
    output_astropy = output_time if isinstance(output_time, Time) else Time(output_time or datetime.now(timezone.utc), scale="utc")
    center_time = output_astropy - float(effective_integration_s) * 0.5 * u.s
    meta = source_metadata(config, center_time)
    uvw_m = meta["uvw_m"]
    uvw_l = meta["uvw_lambda"]
    value = complex(visibility)
    return VisibilityRecord(
        output_utc_iso=output_astropy.utc.isot,
        integration_center_utc_iso=center_time.utc.isot,
        integration_center_jd=float(center_time.utc.jd),
        vis_real=float(value.real),
        vis_imag=float(value.imag),
        window_coherence_pct=float(window_coherence_pct),
        effective_integration_s=float(effective_integration_s),
        integration_samples=float(integration_samples),
        apparent_ra_h=float(meta["apparent_ra_h"]),
        apparent_dec_deg=float(meta["apparent_dec_deg"]),
        lmst_h=float(meta["lmst_h"]),
        ha_h=float(meta["ha_h"]),
        az_deg=float(meta["az_deg"]),
        el_deg=float(meta["el_deg"]),
        u_m=float(uvw_m[0]),
        v_m=float(uvw_m[1]),
        w_m=float(uvw_m[2]),
        u_lambda=float(uvw_l[0]),
        v_lambda=float(uvw_l[1]),
        w_lambda=float(uvw_l[2]),
    )


def init_journal(path, config, outputs):
    path = Path(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL, outputs_json TEXT NOT NULL)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            output_utc_iso TEXT NOT NULL,
            integration_center_utc_iso TEXT NOT NULL,
            integration_center_jd REAL NOT NULL,
            vis_real REAL NOT NULL,
            vis_imag REAL NOT NULL,
            window_coherence_pct REAL NOT NULL,
            effective_integration_s REAL NOT NULL,
            integration_samples REAL NOT NULL,
            apparent_ra_h REAL NOT NULL,
            apparent_dec_deg REAL NOT NULL,
            lmst_h REAL NOT NULL,
            ha_h REAL NOT NULL,
            az_deg REAL NOT NULL,
            el_deg REAL NOT NULL,
            u_m REAL NOT NULL,
            v_m REAL NOT NULL,
            w_m REAL NOT NULL,
            u_lambda REAL NOT NULL,
            v_lambda REAL NOT NULL,
            w_lambda REAL NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO config(id, json, outputs_json) VALUES (1, ?, ?)",
        (json.dumps(asdict(config), sort_keys=True), json.dumps({k: str(v) for k, v in outputs.items()}, sort_keys=True)),
    )
    conn.commit()
    return conn


def append_record(conn, record):
    values = asdict(record)
    columns = list(values)
    placeholders = ",".join(["?"] * len(columns))
    conn.execute(
        f"INSERT INTO records ({','.join(columns)}) VALUES ({placeholders})",
        [values[col] for col in columns],
    )


def load_journal(path):
    conn = sqlite3.connect(Path(path))
    conn.row_factory = sqlite3.Row
    config_row = conn.execute("SELECT json, outputs_json FROM config WHERE id=1").fetchone()
    if config_row is None:
        raise ValueError(f"Journal has no Stage 10 configuration: {path}")
    config = Stage10Config(**json.loads(config_row["json"]))
    outputs = json.loads(config_row["outputs_json"])
    record_columns = [field.name for field in fields(VisibilityRecord)]
    records = [
        VisibilityRecord(**dict(row))
        for row in conn.execute(f"SELECT {','.join(record_columns)} FROM records ORDER BY seq")
    ]
    conn.close()
    return config, outputs, records


def antenna_positions_ecef_offsets(config):
    _, _, _, utils = require_pyuvdata()
    location = EarthLocation(
        lat=float(config.site_lat_deg) * u.deg,
        lon=float(config.site_lon_deg) * u.deg,
        height=float(config.site_height_m) * u.m,
    )
    enu = np.array(
        [
            [0.0, 0.0, 0.0],
            [float(config.baseline_e_m), float(config.baseline_n_m), float(config.baseline_u_m)],
        ],
        dtype=np.float64,
    )
    absolute = utils.ECEF_from_ENU(enu, center_loc=location)
    origin = location.itrs.cartesian.xyz.to_value(u.m)
    return absolute - origin


def antenna_offsets_to_enu(config, antenna_positions):
    _, _, _, utils = require_pyuvdata()
    location = EarthLocation(
        lat=float(config.site_lat_deg) * u.deg,
        lon=float(config.site_lon_deg) * u.deg,
        height=float(config.site_height_m) * u.m,
    )
    origin = location.itrs.cartesian.xyz.to_value(u.m)
    return utils.ENU_from_ECEF(np.asarray(antenna_positions, dtype=np.float64) + origin, center_loc=location)


def phase_center_catalog(config, records):
    if int(config.source_mode) == SOURCE_SUN:
        times = np.array([record.integration_center_jd for record in records], dtype=np.float64)
        lon = np.radians([record.apparent_ra_h * 15.0 for record in records])
        lat = np.radians([record.apparent_dec_deg for record in records])
        return {
            0: {
                "cat_name": "Sun",
                "cat_type": "ephem",
                "cat_lon": lon,
                "cat_lat": lat,
                "cat_frame": "icrs",
                "cat_epoch": None,
                "cat_times": times,
                "cat_pm_ra": None,
                "cat_pm_dec": None,
                "cat_vrad": None,
                "cat_dist": None,
                "info_source": "Stage 10 Astropy apparent solar ephemeris",
            }
        }
    return {
        0: {
            "cat_name": sanitize_component(config.source_name(), "Manual"),
            "cat_type": "sidereal",
            "cat_lon": math.radians(float(config.manual_ra_hours) * 15.0),
            "cat_lat": math.radians(float(config.manual_dec_deg)),
            "cat_frame": "icrs",
            "cat_epoch": 2000.0,
            "cat_times": None,
            "cat_pm_ra": None,
            "cat_pm_dec": None,
            "cat_vrad": None,
            "cat_dist": None,
            "info_source": "Stage 10 manual ICRS phase center",
        }
    }


def history_text(config):
    _, _, _, effective_bw = effective_bandwidth_hz(
        config.fft_size, config.samp_rate_hz, config.visibility_edge_exclude_pct
    )
    return "\n".join(
        [
            "FX GNU Radio Correlator Stage 10",
            f"software commit SHA: {config.software_commit}",
            f"GNU Radio version: {config.gnuradio_version}",
            f"Python version: {sys.version.split()[0]}",
            f"pyuvdata version: {pyuvdata_version() or 'missing'}",
            "B01 = r1-r0; ant1=0 ant2=1 in pyuvdata",
            "C01 = X0*conj(X1)",
            "Stage-7 delay correction enabled",
            "Stage-8 fringe-stop Normal (-phi_geo)",
            "Stage-9 integration: non-overlapping complex mean",
            "UTC is host-clock estimated integration-centre time; Version 1 one-B210 system does not use PPS sample timestamps.",
            "CALIBRATION STATE = UNCALIBRATED",
            f"sky centre frequency Hz: {float(config.sky_cf_hz):.6f}",
            f"effective correlated bandwidth Hz: {effective_bw:.6f}",
            f"FFT size: {int(config.fft_size)}",
            f"sample rate Hz: {float(config.samp_rate_hz):.6f}",
            f"visibility edge exclusion pct: {float(config.visibility_edge_exclude_pct):.6f}",
            f"site lat/lon/height: {config.site_lat_deg}, {config.site_lon_deg}, {config.site_height_m}",
            f"baseline ENU metres: {config.baseline_e_m}, {config.baseline_n_m}, {config.baseline_u_m}",
            f"antenna identities: {ANTENNA_NAMES[0]}, {ANTENNA_NAMES[1]}",
        ]
    )


def build_uvdata(config, records):
    if not records:
        raise ValueError("Cannot build UVFITS: no Stage-10 visibility records captured.")
    _, UVData, Telescope, _ = require_pyuvdata()
    location = EarthLocation(
        lat=float(config.site_lat_deg) * u.deg,
        lon=float(config.site_lon_deg) * u.deg,
        height=float(config.site_height_m) * u.m,
    )
    telescope = Telescope.new(
        name=TELESCOPE_NAME,
        location=location,
        antenna_positions=antenna_positions_ecef_offsets(config),
        antenna_names=list(ANTENNA_NAMES),
        antenna_numbers=list(ANTENNA_NUMBERS),
        antenna_diameters=np.array([2.4, 1.7], dtype=np.float64),
        instrument="Ettus B210",
        x_orientation="east",
        mount_type="alt-az",
        update_from_known=False,
    )
    _, _, _, effective_bw = effective_bandwidth_hz(
        config.fft_size, config.samp_rate_hz, config.visibility_edge_exclude_pct
    )
    n = len(records)
    data_array = np.array([[[complex(r.vis_real, r.vis_imag)]] for r in records], dtype=np.complex64)
    uv = UVData.new(
        freq_array=np.array([float(config.sky_cf_hz)], dtype=np.float64),
        polarization_array=[str(config.polarization)],
        times=np.array([r.integration_center_jd for r in records], dtype=np.float64),
        telescope=telescope,
        antpairs=[(0, 1)] * n,
        do_blt_outer=False,
        integration_time=np.array([r.effective_integration_s for r in records], dtype=np.float64),
        channel_width=np.array([effective_bw], dtype=np.float64),
        data_array=data_array,
        flag_array=np.zeros((n, 1, 1), dtype=bool),
        nsample_array=np.ones((n, 1, 1), dtype=np.float64),
        vis_units="uncalib",
        phase_center_catalog=phase_center_catalog(config, records),
        phase_center_id_array=np.zeros(n, dtype=int),
        history=history_text(config),
    )
    uv.uvw_array = np.array([[r.u_m, r.v_m, r.w_m] for r in records], dtype=np.float64)
    uv.set_lsts_from_time_array()
    uv.extra_keywords = {
        "STAGE": 10,
        "CALSTATE": "UNCAL",
        "LNBFREQ": float(config.lnb_lo_hz),
        "HIGHSIDE": 1,
    }
    return uv


def validate_roundtrip(original_uv, read_uv, atol=1e-5):
    np.testing.assert_allclose(read_uv.uvw_array, original_uv.uvw_array, atol=atol, rtol=0.0)
    np.testing.assert_allclose(read_uv.data_array, original_uv.data_array, atol=atol, rtol=0.0)
    np.testing.assert_allclose(read_uv.time_array, original_uv.time_array, atol=1e-9, rtol=0.0)
    np.testing.assert_allclose(read_uv.integration_time, original_uv.integration_time, atol=1e-6, rtol=0.0)
    np.testing.assert_allclose(read_uv.freq_array, original_uv.freq_array, atol=1e-3, rtol=0.0)
    np.testing.assert_allclose(read_uv.channel_width, original_uv.channel_width, atol=1e-3, rtol=0.0)
    if str(read_uv.vis_units).lower() != "uncalib":
        raise AssertionError(f"Unexpected visibility units: {read_uv.vis_units}")


def write_uvfits(config, records, output_path, readback=True):
    _, UVData, _, _ = require_pyuvdata()
    uv = build_uvdata(config, records)
    output_path = Path(output_path)
    partial = output_path.with_suffix(".partial.uvfits")
    if partial.exists():
        partial.unlink()
    kwargs = {
        "write_lst": True,
        "uvw_double": True,
        "run_check": True,
        "check_extra": True,
        "run_check_acceptability": True,
        "strict_uvw_antpos_check": False,
        "force_phase": False,
    }
    uv.write_uvfits(str(partial), **kwargs)
    if readback:
        read_uv = UVData()
        read_uv.read_uvfits(str(partial))
        validate_roundtrip(uv, read_uv)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing UVFITS file: {output_path}")
    os.replace(partial, output_path)
    return uv


def write_diagnostics_csv(config, records, csv_path):
    _, _, _, effective_bw = effective_bandwidth_hz(
        config.fft_size, config.samp_rate_hz, config.visibility_edge_exclude_pct
    )
    fieldnames = [
        "UTC_ISO",
        "UTC_JD",
        "observation",
        "source",
        "apparent_RA_h",
        "apparent_Dec_deg",
        "LMST_h",
        "HA_h",
        "Az_deg",
        "El_deg",
        "u_m",
        "v_m",
        "w_m",
        "U_lambda",
        "V_lambda",
        "W_lambda",
        "vis_real",
        "vis_imag",
        "vis_amplitude",
        "vis_phase_deg",
        "window_coherence_pct",
        "effective_integration_s",
        "integration_samples",
        "sky_cf_hz",
        "effective_bandwidth_hz",
        "fringe_stop_mode",
        "delay_correction_enabled",
        "calibration_state",
    ]
    with Path(csv_path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            value = complex(record.vis_real, record.vis_imag)
            writer.writerow(
                {
                    "UTC_ISO": record.integration_center_utc_iso,
                    "UTC_JD": record.integration_center_jd,
                    "observation": config.observation_name,
                    "source": config.source_name(),
                    "apparent_RA_h": record.apparent_ra_h,
                    "apparent_Dec_deg": record.apparent_dec_deg,
                    "LMST_h": record.lmst_h,
                    "HA_h": record.ha_h,
                    "Az_deg": record.az_deg,
                    "El_deg": record.el_deg,
                    "u_m": record.u_m,
                    "v_m": record.v_m,
                    "w_m": record.w_m,
                    "U_lambda": record.u_lambda,
                    "V_lambda": record.v_lambda,
                    "W_lambda": record.w_lambda,
                    "vis_real": record.vis_real,
                    "vis_imag": record.vis_imag,
                    "vis_amplitude": abs(value),
                    "vis_phase_deg": math.degrees(math.atan2(value.imag, value.real)),
                    "window_coherence_pct": record.window_coherence_pct,
                    "effective_integration_s": record.effective_integration_s,
                    "integration_samples": record.integration_samples,
                    "sky_cf_hz": config.sky_cf_hz,
                    "effective_bandwidth_hz": effective_bw,
                    "fringe_stop_mode": "Normal (-phi_geo)" if config.fringe_stop_enabled and config.fringe_stop_sign == -1 else "NOT_SCIENCE",
                    "delay_correction_enabled": bool(config.delay_correction_enabled),
                    "calibration_state": config.calibration_state,
                }
            )


def finalize_journal(journal_path, uvfits_path=None, diagnostics_csv_path=None):
    config, outputs, records = load_journal(journal_path)
    uvfits = Path(uvfits_path or outputs["uvfits"])
    diagnostics = Path(diagnostics_csv_path or outputs["diagnostics_csv"])
    uv = write_uvfits(config, records, uvfits, readback=True)
    write_diagnostics_csv(config, records, diagnostics)
    return uvfits, diagnostics, uv


def write_synthetic_journal(path, config, records, outputs=None):
    outputs = outputs or {
        "uvfits": str(Path(path).with_suffix(".uvfits")),
        "partial_uvfits": str(Path(path).with_suffix(".partial.uvfits")),
        "journal": str(path),
        "diagnostics_csv": str(Path(path).with_name(Path(path).stem + "_diagnostics.csv")),
    }
    conn = init_journal(path, config, outputs)
    for record in records:
        append_record(conn, record)
    conn.commit()
    conn.close()
    return Path(path)
