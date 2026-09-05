import csv
import math
import os
import pathlib
import time
from datetime import datetime, timezone

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, TETE, get_sun
from astropy.io import fits
from astropy.time import Time
from astropy.utils import iers


iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"


C_M_S = 299792458.0
DEFAULT_CHUNK_ROWS = 10
DEFAULT_CHUNK_AGE_S = 5.0
STATE_OFF = 0
STATE_RECORDING = 1
STATE_FINALIZING = 2
STATE_COMPLETE = 3
STATE_ERROR = -1


def default_config():
    return {
        "observation_name": "obs1",
        "output_dir": "~/FX_Correlator_Data",
        "source_mode": 0,
        "manual_ra_hours": 5.0,
        "manual_dec_deg": -30.0,
        "site_lat_deg": -32.724,
        "site_lon_deg": 152.130167,
        "site_height_m": 70.0,
        "baseline_e_m": -5.785,
        "baseline_n_m": 0.095,
        "baseline_u_m": 0.580,
        "sky_cf_hz": 4.800e9,
        "samp_rate": 30.72e6,
        "fft_size": 4096,
        "visibility_edge_exclude_pct": 20.0,
        "instrument_delay_ns": 0.0,
        "delay_correction_enable": True,
        "fringe_stop_enable": True,
        "fringe_stop_sign": -1,
        "integration_time_s": 1.0,
        "gain0": 40.0,
        "gain1": 40.0,
        "stokes_code": -5,
        "polarization_label": "XX",
        "polarization_assumed": True,
        "observer": "FX GNU Radio Correlator",
        "git_commit": "unknown",
        "chunk_rows": DEFAULT_CHUNK_ROWS,
        "chunk_age_s": DEFAULT_CHUNK_AGE_S,
    }


def merged_config(overrides):
    cfg = default_config()
    if overrides:
        cfg.update(overrides)
    return cfg


def sanitize_token(value, fallback):
    text = str(value or "").strip()
    keep = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    cleaned = "".join(keep).strip("_")
    return cleaned[:64] or fallback


def source_name(config):
    mode = int(config["source_mode"])
    if mode == 0:
        return "Sun"
    if mode == 1:
        return "Manual"
    return "INVALID"


def effective_bandwidth_hz(samp_rate, fft_size, edge_pct):
    n_edge = int(int(fft_size) * float(edge_pct) / 100.0)
    n_used = int(fft_size) - 2 * n_edge
    if n_used <= 0:
        raise ValueError("Stage 10 effective bandwidth has no retained FFT channels")
    return n_edge, n_used, float(n_used) * float(samp_rate) / float(fft_size)


def enu_to_ecef_offset(east_m, north_m, up_m, lat_deg, lon_deg):
    lat = math.radians(float(lat_deg))
    lon = math.radians(float(lon_deg))
    east = float(east_m)
    north = float(north_m)
    up = float(up_m)
    return np.array(
        [
            -math.sin(lon) * east - math.sin(lat) * math.cos(lon) * north + math.cos(lat) * math.cos(lon) * up,
            math.cos(lon) * east - math.sin(lat) * math.sin(lon) * north + math.cos(lat) * math.sin(lon) * up,
            math.cos(lat) * north + math.sin(lat) * up,
        ],
        dtype=np.float64,
    )


def ecef_offset_to_enu(dx_m, dy_m, dz_m, lat_deg, lon_deg):
    lat = math.radians(float(lat_deg))
    lon = math.radians(float(lon_deg))
    dx = float(dx_m)
    dy = float(dy_m)
    dz = float(dz_m)
    return np.array(
        [
            -math.sin(lon) * dx + math.cos(lon) * dy,
            -math.sin(lat) * math.cos(lon) * dx - math.sin(lat) * math.sin(lon) * dy + math.cos(lat) * dz,
            math.cos(lat) * math.cos(lon) * dx + math.cos(lat) * math.sin(lon) * dy + math.sin(lat) * dz,
        ],
        dtype=np.float64,
    )


def uvw_project_m(ha_hour, dec_deg, baseline_e_m, baseline_n_m, baseline_u_m, site_lat_deg):
    phi = math.radians(float(site_lat_deg))
    h = math.radians(float(ha_hour) * 15.0)
    dec = math.radians(float(dec_deg))
    baseline = np.array([baseline_e_m, baseline_n_m, baseline_u_m], dtype=np.float64)
    u_hat = np.array([math.cos(h), -math.sin(phi) * math.sin(h), math.cos(phi) * math.sin(h)], dtype=np.float64)
    v_hat = np.array(
        [
            math.sin(dec) * math.sin(h),
            math.cos(phi) * math.cos(dec) + math.sin(phi) * math.sin(dec) * math.cos(h),
            math.sin(phi) * math.cos(dec) - math.cos(phi) * math.sin(dec) * math.cos(h),
        ],
        dtype=np.float64,
    )
    w_hat = np.array(
        [
            -math.cos(dec) * math.sin(h),
            math.sin(dec) * math.cos(phi) - math.cos(dec) * math.cos(h) * math.sin(phi),
            math.sin(dec) * math.sin(phi) + math.cos(dec) * math.cos(h) * math.cos(phi),
        ],
        dtype=np.float64,
    )
    return float(np.dot(baseline, u_hat)), float(np.dot(baseline, v_hat)), float(np.dot(baseline, w_hat))


def date_time_from_time(obstime):
    utc = obstime.utc.datetime.replace(tzinfo=timezone.utc)
    midnight = datetime(utc.year, utc.month, utc.day, tzinfo=timezone.utc)
    midnight_time = Time(midnight, scale="utc")
    return float(midnight_time.jd), float((utc - midnight).total_seconds() / 86400.0)


def time_from_date_time(date_jd, time_days):
    return Time(float(date_jd) + float(time_days), format="jd", scale="utc")


def source_metadata(config, obstime):
    location = EarthLocation(
        lat=float(config["site_lat_deg"]) * u.deg,
        lon=float(config["site_lon_deg"]) * u.deg,
        height=float(config["site_height_m"]) * u.m,
    )
    obstime = Time(obstime, scale="utc", location=location)
    if int(config["source_mode"]) == 0:
        coord = get_sun(obstime)
        raepo_deg = float(coord.icrs.ra.deg)
        decepo_deg = float(coord.icrs.dec.deg)
    else:
        coord = SkyCoord(
            ra=float(config["manual_ra_hours"]) * u.hourangle,
            dec=float(config["manual_dec_deg"]) * u.deg,
            frame="icrs",
        )
        raepo_deg = float(coord.ra.deg)
        decepo_deg = float(coord.dec.deg)

    apparent = coord.transform_to(TETE(obstime=obstime, location=location))
    altaz = coord.transform_to(AltAz(obstime=obstime, location=location, pressure=0 * u.hPa))
    lmst_hour = obstime.sidereal_time("apparent", longitude=float(config["site_lon_deg"]) * u.deg).hour % 24.0
    apparent_ra_hour = apparent.ra.hour % 24.0
    ha_hour = ((lmst_hour - apparent_ra_hour + 12.0) % 24.0) - 12.0
    return {
        "source": source_name(config),
        "raepo_deg": raepo_deg,
        "decepo_deg": decepo_deg,
        "raapp_deg": float(apparent.ra.deg),
        "decapp_deg": float(apparent.dec.deg),
        "apparent_ra_hour": apparent_ra_hour,
        "apparent_dec_deg": float(apparent.dec.deg),
        "lmst_hour": float(lmst_hour),
        "ha_hour": float(ha_hour),
        "az_deg": float(altaz.az.deg % 360.0),
        "el_deg": float(altaz.alt.deg),
    }


class FitsIdiWriter:
    def __init__(self, config):
        self.config = merged_config(config)
        self.state = STATE_OFF
        self.records_written = 0
        self.chunks_written = 0
        self.current_file = ""
        self.partial_file = ""
        self.final_file = ""
        self.diagnostic_csv = ""
        self._chunk = []
        self._chunk_started_monotonic = None
        self._csv_handle = None
        self._csv_writer = None
        self._start_time = None
        self._common = {}

    def start(self):
        if self.state == STATE_RECORDING:
            return
        self._validate_start()
        self._start_time = Time(datetime.now(timezone.utc), scale="utc")
        out_dir = pathlib.Path(os.path.expanduser(str(self.config["output_dir"]))).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        obs = sanitize_token(self.config["observation_name"], "obs")
        src = sanitize_token(source_name(self.config), "source")
        stamp = self._start_time.utc.datetime.strftime("%Y%m%dT%H%M%SZ")
        base = f"{stamp}_{obs}_{src}_B01"
        self.final_file = str(self._unique_path(out_dir / f"{base}.fitsidi"))
        self.partial_file = self.final_file[:-8] + ".partial.fitsidi"
        self.current_file = self.partial_file
        self.diagnostic_csv = str(pathlib.Path(self.final_file).with_name(f"{base}_diagnostics.csv"))
        self._common = self._common_keywords()
        hdul = fits.HDUList(
            [
                self._primary_hdu(),
                self._array_geometry_hdu(),
                self._frequency_hdu(),
                self._source_hdu(),
            ]
        )
        hdul.writeto(self.partial_file, overwrite=False, checksum=True)
        self._patch_primary_signature(self.partial_file)
        self._verify_file(self.partial_file)
        self._csv_handle = open(self.diagnostic_csv, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_handle, fieldnames=self._diagnostic_fields())
        self._csv_writer.writeheader()
        self.state = STATE_RECORDING

    def add_record(self, record):
        if self.state != STATE_RECORDING:
            return
        prepared = self._prepare_record(record)
        self._chunk.append(prepared)
        if self._csv_writer is not None:
            self._csv_writer.writerow(self._diagnostic_row(prepared))
            self._csv_handle.flush()
        now = time.monotonic()
        if self._chunk_started_monotonic is None:
            self._chunk_started_monotonic = now
        age = now - self._chunk_started_monotonic
        if len(self._chunk) >= int(self.config["chunk_rows"]) or age >= float(self.config["chunk_age_s"]):
            self.flush()

    def flush(self):
        if not self._chunk:
            return
        self._append_chunk(self._chunk)
        self.records_written += len(self._chunk)
        self.chunks_written += 1
        self._chunk = []
        self._chunk_started_monotonic = None

    def stop(self):
        if self.state not in (STATE_RECORDING, STATE_FINALIZING):
            return self.final_file
        self.state = STATE_FINALIZING
        self.flush()
        if self._csv_handle is not None:
            self._csv_handle.close()
            self._csv_handle = None
        validate_fitsidi_file(self.partial_file, expected_records=self.records_written)
        if os.path.exists(self.final_file):
            raise FileExistsError(self.final_file)
        os.replace(self.partial_file, self.final_file)
        self.current_file = self.final_file
        self.state = STATE_COMPLETE
        return self.final_file

    def abort_error(self):
        self.state = STATE_ERROR
        if self._csv_handle is not None:
            self._csv_handle.close()
            self._csv_handle = None

    def _validate_start(self):
        if not bool(self.config["delay_correction_enable"]):
            raise ValueError("FITS-IDI recording requires Stage-7 delay correction enabled")
        if not bool(self.config["fringe_stop_enable"]) or int(self.config["fringe_stop_sign"]) != -1:
            raise ValueError("FITS-IDI recording requires Stage-8 Normal (-phi_geo) fringe stopping")
        if source_name(self.config) == "INVALID":
            raise ValueError("FITS-IDI recording requires a valid source mode")
        if int(self.config["stokes_code"]) == 1:
            raise ValueError("Stage 10 must not label the measured product as Stokes I")

    def _common_keywords(self):
        n_edge, n_used, bw = effective_bandwidth_hz(
            self.config["samp_rate"],
            self.config["fft_size"],
            self.config["visibility_edge_exclude_pct"],
        )
        return {
            "OBSCODE": sanitize_token(self.config["observation_name"], "obs")[:8],
            "NO_STKD": 1,
            "STK_1": int(self.config["stokes_code"]),
            "NO_BAND": 1,
            "NO_CHAN": 1,
            "REF_FREQ": float(self.config["sky_cf_hz"]),
            "CHAN_BW": float(bw),
            "EFF_BW": float(bw),
            "SAMP_HZ": float(self.config["samp_rate"]),
            "FFT_LEN": int(self.config["fft_size"]),
            "EDGEPCT": float(self.config["visibility_edge_exclude_pct"]),
            "N_EDGE": int(n_edge),
            "N_USED": int(n_used),
            "REF_PIXL": 1.0,
            "RDATE": self._start_time.utc.datetime.strftime("%Y-%m-%d"),
        }

    def _apply_common(self, header, extname, tabrev=1):
        header["EXTNAME"] = extname
        header["TABREV"] = int(tabrev)
        for key, value in self._common.items():
            header[key] = value

    def _primary_hdu(self):
        hdu = fits.PrimaryHDU()
        hdr = hdu.header
        hdr["NAXIS"] = 0
        hdr["EXTEND"] = True
        hdr["GROUPS"] = True
        hdr["GCOUNT"] = 0
        hdr["PCOUNT"] = 0
        hdr["CORRELAT"] = "FXGNU"
        hdr["TELESCOP"] = "B210-FX"
        hdr["OBSERVER"] = str(self.config["observer"])[:68]
        hdr["DATE-OBS"] = self._start_time.utc.datetime.strftime("%Y-%m-%d")
        hdr["FXCORVER"] = str(self.config["git_commit"])[:68]
        hdr["CALSTAT"] = "UNCALIBRATED"
        histories = [
            "FX GNU Radio Correlator Stage 10",
            "B01 = r1-r0 internally",
            "C01 = X0*conj(X1)",
            "FITS antenna 1 = project antenna 0",
            "FITS antenna 2 = project antenna 1",
            "FITS UVW = -project Stage-6 UVW",
            "visibility is NOT conjugated at write",
            "Stage-7 delay correction enabled",
            "Stage-8 Normal fringe stopping",
            "visibility = Stage-9 integrated V_stopped",
            "host UTC integration-centre timestamp method",
            "calibration state = uncalibrated",
            "single-channel continuum; FREQUENCY bandwidth is retained FFT bandwidth",
        ]
        if int(self.config["source_mode"]) == 0:
            histories.append("Sun is a moving ephemeris source; SOURCE table coordinates are reference coordinates.")
            histories.append("Per-record apparent coordinates are retained in the Stage-10 diagnostic sidecar.")
        if bool(self.config.get("polarization_assumed", True)):
            histories.append("STK_1=-5 XX is a project metadata assumption pending feed confirmation.")
        for item in histories:
            hdr.add_history(item)
        return hdu

    def _array_geometry_hdu(self):
        location = EarthLocation(
            lat=float(self.config["site_lat_deg"]) * u.deg,
            lon=float(self.config["site_lon_deg"]) * u.deg,
            height=float(self.config["site_height_m"]) * u.m,
        )
        x, y, z = [float(v.to_value(u.m)) for v in location.to_geocentric()]
        offset = enu_to_ecef_offset(
            self.config["baseline_e_m"],
            self.config["baseline_n_m"],
            self.config["baseline_u_m"],
            self.config["site_lat_deg"],
            self.config["site_lon_deg"],
        )
        cols = [
            fits.Column(name="ANNAME", format="8A", array=np.array(["ANT0", "ANT1"])),
            fits.Column(name="STABXYZ", format="3D", unit="METERS", array=np.array([[0.0, 0.0, 0.0], offset])),
            fits.Column(name="DERXYZ", format="3E", unit="METERS/S", array=np.zeros((2, 3), dtype=np.float32)),
            fits.Column(name="ORBPARM", format="0D", array=np.zeros((2, 0), dtype=np.float64)),
            fits.Column(name="NOSTA", format="1I", array=np.array([1, 2], dtype=np.int16)),
            fits.Column(name="MNTSTA", format="1J", array=np.array([0, 0], dtype=np.int32)),
            fits.Column(name="STAXOF", format="3E", unit="METERS", array=np.zeros((2, 3), dtype=np.float32)),
            fits.Column(name="DIAMETER", format="1E", unit="METERS", array=np.array([2.4, 1.7], dtype=np.float32)),
        ]
        hdu = fits.BinTableHDU.from_columns(cols)
        self._apply_common(hdu.header, "ARRAY_GEOMETRY", 1)
        hdu.header["EXTVER"] = 1
        hdu.header["ARRNAM"] = "FXB01"
        hdu.header["FRAME"] = "GEOCENTRIC"
        hdu.header["ARRAYX"] = x
        hdu.header["ARRAYY"] = y
        hdu.header["ARRAYZ"] = z
        hdu.header["NUMORB"] = 0
        hdu.header["FREQ"] = float(self.config["sky_cf_hz"])
        hdu.header["TIMESYS"] = "UTC"
        hdu.header["RDATE"] = self._common["RDATE"]
        hdu.header["GSTIA0"] = 0.0
        hdu.header["DEGPDY"] = 360.98564736629
        hdu.header["UT1UTC"] = 0.0
        hdu.header["IATUTC"] = 37.0
        hdu.header["POLARX"] = 0.0
        hdu.header["POLARY"] = 0.0
        return hdu

    def _frequency_hdu(self):
        bw = self._common["CHAN_BW"]
        cols = [
            fits.Column(name="FREQID", format="1J", array=np.array([1], dtype=np.int32)),
            fits.Column(name="BANDFREQ", format="1D", unit="HZ", array=np.array([[0.0]], dtype=np.float64)),
            fits.Column(name="CH_WIDTH", format="1E", unit="HZ", array=np.array([[bw]], dtype=np.float32)),
            fits.Column(name="TOTAL_BANDWIDTH", format="1E", unit="HZ", array=np.array([[bw]], dtype=np.float32)),
            fits.Column(name="SIDEBAND", format="1J", array=np.array([[1]], dtype=np.int32)),
        ]
        hdu = fits.BinTableHDU.from_columns(cols)
        self._apply_common(hdu.header, "FREQUENCY", 1)
        return hdu

    def _source_hdu(self):
        meta = source_metadata(self.config, self._start_time)
        src = source_name(self.config)
        cols = [
            fits.Column(name="SOURCE_ID", format="1J", array=np.array([1], dtype=np.int32)),
            fits.Column(name="SOURCE", format="16A", array=np.array([src])),
            fits.Column(name="QUAL", format="1J", array=np.array([1], dtype=np.int32)),
            fits.Column(name="CALCODE", format="4A", array=np.array([""])),
            fits.Column(name="FREQID", format="1J", array=np.array([1], dtype=np.int32)),
            fits.Column(name="IFLUX", format="1E", unit="JY", array=np.array([[0.0]], dtype=np.float32)),
            fits.Column(name="QFLUX", format="1E", unit="JY", array=np.array([[0.0]], dtype=np.float32)),
            fits.Column(name="UFLUX", format="1E", unit="JY", array=np.array([[0.0]], dtype=np.float32)),
            fits.Column(name="VFLUX", format="1E", unit="JY", array=np.array([[0.0]], dtype=np.float32)),
            fits.Column(name="ALPHA", format="1E", array=np.array([[0.0]], dtype=np.float32)),
            fits.Column(name="FREQOFF", format="1E", unit="HZ", array=np.array([[0.0]], dtype=np.float32)),
            fits.Column(name="RAEPO", format="1D", unit="DEGREES", array=np.array([meta["raepo_deg"]], dtype=np.float64)),
            fits.Column(name="DECEPO", format="1D", unit="DEGREES", array=np.array([meta["decepo_deg"]], dtype=np.float64)),
            fits.Column(name="EQUINOX", format="8A", array=np.array(["J2000"])),
            fits.Column(name="RAAPP", format="1D", unit="DEGREES", array=np.array([meta["raapp_deg"]], dtype=np.float64)),
            fits.Column(name="DECAPP", format="1D", unit="DEGREES", array=np.array([meta["decapp_deg"]], dtype=np.float64)),
        ]
        hdu = fits.BinTableHDU.from_columns(cols)
        self._apply_common(hdu.header, "SOURCE", 1)
        return hdu

    def _prepare_record(self, record):
        vis = complex(record["visibility"])
        eff_s = float(record.get("effective_integration_s", self.config["integration_time_s"]))
        t_center = record.get("t_center")
        if t_center is None:
            received = Time(datetime.now(timezone.utc), scale="utc")
            t_center = received - (eff_s / 2.0) * u.s
        else:
            t_center = Time(t_center, scale="utc")
        meta = source_metadata(self.config, t_center)
        uvw_supplied = "project_uvw_m" in record
        if uvw_supplied:
            u_m, v_m, w_m = [float(v) for v in record["project_uvw_m"]]
        else:
            u_m, v_m, w_m = uvw_project_m(
                meta["ha_hour"],
                meta["apparent_dec_deg"],
                float(self.config["baseline_e_m"]),
                float(self.config["baseline_n_m"]),
                float(self.config["baseline_u_m"]),
                float(self.config["site_lat_deg"]),
            )
        if not uvw_supplied:
            self._validate_uvw_norm(u_m, v_m, w_m)
        date_jd, time_days = date_time_from_time(t_center)
        wavelength_m = C_M_S / float(self.config["sky_cf_hz"])
        return {
            "t_center": t_center,
            "date_jd": date_jd,
            "time_days": time_days,
            "visibility": vis,
            "weight": 1.0 if math.isfinite(vis.real) and math.isfinite(vis.imag) else 0.0,
            "coherence_pct": float(record.get("coherence_pct", np.nan)),
            "effective_integration_s": eff_s,
            "n_int": float(record.get("n_int", np.nan)),
            "u_project_m": u_m,
            "v_project_m": v_m,
            "w_project_m": w_m,
            "uu_fits_s": -u_m / C_M_S,
            "vv_fits_s": -v_m / C_M_S,
            "ww_fits_s": -w_m / C_M_S,
            "u_lambda": u_m / wavelength_m,
            "v_lambda": v_m / wavelength_m,
            "w_lambda": w_m / wavelength_m,
            "meta": meta,
        }

    def _validate_uvw_norm(self, u_m, v_m, w_m):
        uvw2 = u_m * u_m + v_m * v_m + w_m * w_m
        b2 = (
            float(self.config["baseline_e_m"]) ** 2
            + float(self.config["baseline_n_m"]) ** 2
            + float(self.config["baseline_u_m"]) ** 2
        )
        if abs(uvw2 - b2) > max(1e-6, b2 * 1e-9):
            raise ValueError("Stage 10 UVW norm check failed")

    def _append_chunk(self, rows):
        if any(not np.isfinite(row["date_jd"] + row["time_days"]) for row in rows):
            raise ValueError("Stage 10 refuses to write non-finite FITS-IDI times")
        times = [row["date_jd"] + row["time_days"] for row in rows]
        if any(times[i] >= times[i + 1] for i in range(len(times) - 1)):
            raise ValueError("Stage 10 UV_DATA chunk times are not chronological")
        flux = np.zeros((len(rows), 3), dtype=np.float32)
        for idx, row in enumerate(rows):
            vis = row["visibility"]
            if not (math.isfinite(vis.real) and math.isfinite(vis.imag)):
                raise ValueError("Stage 10 refuses to write non-finite visibility")
            flux[idx, :] = [float(vis.real), float(vis.imag), float(row["weight"])]
        cols = [
            fits.Column(name="UU", format="1D", unit="SECONDS", array=np.array([r["uu_fits_s"] for r in rows])),
            fits.Column(name="VV", format="1D", unit="SECONDS", array=np.array([r["vv_fits_s"] for r in rows])),
            fits.Column(name="WW", format="1D", unit="SECONDS", array=np.array([r["ww_fits_s"] for r in rows])),
            fits.Column(name="DATE", format="1D", unit="DAYS", array=np.array([r["date_jd"] for r in rows])),
            fits.Column(name="TIME", format="1D", unit="DAYS", array=np.array([r["time_days"] for r in rows])),
            fits.Column(name="BASELINE", format="1J", array=np.full(len(rows), 258, dtype=np.int32)),
            fits.Column(name="ARRAY", format="1J", array=np.ones(len(rows), dtype=np.int32)),
            fits.Column(name="SOURCE_ID", format="1J", array=np.ones(len(rows), dtype=np.int32)),
            fits.Column(name="FREQID", format="1J", array=np.ones(len(rows), dtype=np.int32)),
            fits.Column(name="INTTIM", format="1D", unit="SECONDS", array=np.array([r["effective_integration_s"] for r in rows])),
            fits.Column(name="FLUX", format="3E", unit="UNCALIB", array=flux),
        ]
        hdu = fits.BinTableHDU.from_columns(cols)
        self._apply_common(hdu.header, "UV_DATA", 2)
        hdu.header["EXTVER"] = self.chunks_written + 1
        hdu.header["NMATRIX"] = 1
        hdu.header["MAXIS"] = 5
        hdu.header["MAXIS1"] = 3
        hdu.header["CTYPE1"] = "COMPLEX"
        hdu.header["CDELT1"] = 1.0
        hdu.header["CRPIX1"] = 1.0
        hdu.header["CRVAL1"] = 1.0
        hdu.header["MAXIS2"] = 1
        hdu.header["CTYPE2"] = "STOKES"
        hdu.header["CDELT2"] = 1.0
        hdu.header["CRPIX2"] = 1.0
        hdu.header["CRVAL2"] = int(self.config["stokes_code"])
        hdu.header["MAXIS3"] = 1
        hdu.header["CTYPE3"] = "FREQ"
        hdu.header["CDELT3"] = self._common["CHAN_BW"]
        hdu.header["CRPIX3"] = self._common["REF_PIXL"]
        hdu.header["CRVAL3"] = self._common["REF_FREQ"]
        hdu.header["MAXIS4"] = 1
        hdu.header["CTYPE4"] = "RA"
        hdu.header["CDELT4"] = 1.0
        hdu.header["CRPIX4"] = 1.0
        hdu.header["CRVAL4"] = 0.0
        hdu.header["MAXIS5"] = 1
        hdu.header["CTYPE5"] = "DEC"
        hdu.header["CDELT5"] = 1.0
        hdu.header["CRPIX5"] = 1.0
        hdu.header["CRVAL5"] = 0.0
        hdu.header["EQUINOX"] = "J2000"
        hdu.header["WEIGHTYP"] = "NORMAL"
        hdu.header["DATE-OBS"] = self._start_time.utc.datetime.strftime("%Y-%m-%d")
        hdu.header["SORT"] = "T "
        hdu.header["TMATX11"] = True
        hdu.add_checksum()
        with fits.open(self.partial_file, mode="append", checksum=False, memmap=False) as hdul:
            hdul.append(hdu)
            hdul.flush()
        self._patch_primary_signature(self.partial_file)

    def _diagnostic_fields(self):
        return [
            "utc_iso",
            "julian_date",
            "source",
            "apparent_ra_hour",
            "apparent_dec_deg",
            "lmst_hour",
            "ha_hour",
            "az_deg",
            "el_deg",
            "u_project_m",
            "v_project_m",
            "w_project_m",
            "uu_fits_s",
            "vv_fits_s",
            "ww_fits_s",
            "u_lambda",
            "v_lambda",
            "w_lambda",
            "vis_real",
            "vis_imag",
            "vis_amplitude",
            "vis_phase_deg",
            "window_coherence_pct",
            "effective_integration_s",
            "n_int",
            "sky_cf_hz",
            "samp_rate_hz",
            "fft_size",
            "visibility_edge_exclude_pct",
            "retained_fft_bins",
            "effective_correlated_bandwidth_hz",
        ]

    def _diagnostic_row(self, row):
        vis = row["visibility"]
        meta = row["meta"]
        return {
            "utc_iso": row["t_center"].utc.isot,
            "julian_date": row["date_jd"] + row["time_days"],
            "source": meta["source"],
            "apparent_ra_hour": meta["apparent_ra_hour"],
            "apparent_dec_deg": meta["apparent_dec_deg"],
            "lmst_hour": meta["lmst_hour"],
            "ha_hour": meta["ha_hour"],
            "az_deg": meta["az_deg"],
            "el_deg": meta["el_deg"],
            "u_project_m": row["u_project_m"],
            "v_project_m": row["v_project_m"],
            "w_project_m": row["w_project_m"],
            "uu_fits_s": row["uu_fits_s"],
            "vv_fits_s": row["vv_fits_s"],
            "ww_fits_s": row["ww_fits_s"],
            "u_lambda": row["u_lambda"],
            "v_lambda": row["v_lambda"],
            "w_lambda": row["w_lambda"],
            "vis_real": vis.real,
            "vis_imag": vis.imag,
            "vis_amplitude": abs(vis),
            "vis_phase_deg": math.degrees(math.atan2(vis.imag, vis.real)),
            "window_coherence_pct": row["coherence_pct"],
            "effective_integration_s": row["effective_integration_s"],
            "n_int": row["n_int"],
            "sky_cf_hz": self.config["sky_cf_hz"],
            "samp_rate_hz": self._common["SAMP_HZ"],
            "fft_size": self._common["FFT_LEN"],
            "visibility_edge_exclude_pct": self._common["EDGEPCT"],
            "retained_fft_bins": self._common["N_USED"],
            "effective_correlated_bandwidth_hz": self._common["CHAN_BW"],
        }

    def _verify_file(self, path):
        with fits.open(path, checksum=False, memmap=False) as hdul:
            for hdu in hdul:
                hdu.verify("exception")

    def _patch_primary_signature(self, path):
        raw = bytearray(pathlib.Path(path).read_bytes())
        for offset in range(0, min(len(raw), 2880), 80):
            key = bytes(raw[offset : offset + 8]).decode("ascii", errors="ignore").strip()
            if key == "NAXIS":
                raw[offset : offset + 80] = b"NAXIS   =                    0                                                  "
            elif key == "NAXIS1":
                raw[offset : offset + 80] = b"                                                                                "
        pathlib.Path(path).write_bytes(raw)

    def _unique_path(self, path):
        candidate = pathlib.Path(path)
        if not candidate.exists() and not pathlib.Path(str(candidate)[:-8] + ".partial.fitsidi").exists():
            return candidate
        stem = candidate.stem
        for idx in range(1, 1000):
            alt = candidate.with_name(f"{stem}_{idx:03d}{candidate.suffix}")
            if not alt.exists() and not pathlib.Path(str(alt)[:-8] + ".partial.fitsidi").exists():
                return alt
        raise FileExistsError("unable to allocate unique FITS-IDI filename")


def validate_fitsidi_file(path, expected_records=None):
    path = str(path)
    with fits.open(path, checksum=False, memmap=False) as hdul:
        for hdu in hdul:
            hdu.verify("exception")
        names = [hdu.name for hdu in hdul]
        required = ["PRIMARY", "ARRAY_GEOMETRY", "FREQUENCY", "SOURCE"]
        if names[:4] != required:
            raise ValueError(f"unexpected FITS-IDI table order: {names[:4]}")
        uv_indices = [idx for idx, name in enumerate(names) if name == "UV_DATA"]
        if any(name not in required + ["UV_DATA"] for name in names):
            raise ValueError(f"unexpected FITS-IDI HDU list: {names}")
        total = 0
        previous_last = None
        for idx in uv_indices:
            data = hdul[idx].data
            if data is None:
                continue
            times = np.asarray(data["DATE"], dtype=np.float64) + np.asarray(data["TIME"], dtype=np.float64)
            if len(times) and np.any(np.diff(times) <= 0):
                raise ValueError("UV_DATA times overlap or are not chronological within chunk")
            if previous_last is not None and len(times) and previous_last >= times[0]:
                raise ValueError("UV_DATA chunks overlap or are not chronological")
            if len(times):
                previous_last = float(times[-1])
            if np.any(np.asarray(data["BASELINE"]) != 258):
                raise ValueError("unexpected FITS-IDI baseline number")
            total += len(data)
        if expected_records is not None and int(expected_records) != total:
            raise ValueError(f"expected {expected_records} records, found {total}")
        return {"hdu_names": names, "uv_chunks": len(uv_indices), "records": total}
