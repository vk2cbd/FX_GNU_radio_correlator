import math
import pathlib
import unittest
import warnings

import yaml

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, TETE, get_sun
from astropy.time import Time
from astropy.utils import iers


iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"


SITE_LAT_DEG = -32.724
SITE_LON_DEG = 152.130167
SITE_HEIGHT_M = 0.0
TEST_TIME = "2026-08-09T00:00:00"


def compute_coordinates(source_mode, manual_ra_hours=5.0, manual_dec_deg=-30.0, isot=TEST_TIME):
    location = EarthLocation(
        lat=SITE_LAT_DEG * u.deg,
        lon=SITE_LON_DEG * u.deg,
        height=SITE_HEIGHT_M * u.m,
    )
    obstime = Time(isot, scale="utc", location=location)
    if int(source_mode) == 0:
        coord = get_sun(obstime)
    else:
        coord = SkyCoord(
            ra=manual_ra_hours * u.hourangle,
            dec=manual_dec_deg * u.deg,
            frame="icrs",
        )

    altaz = coord.transform_to(AltAz(obstime=obstime, location=location, pressure=0 * u.hPa))
    apparent = coord.transform_to(TETE(obstime=obstime, location=location))
    lmst_hour = obstime.sidereal_time("apparent", longitude=SITE_LON_DEG * u.deg).hour % 24.0
    apparent_ra_hour = apparent.ra.hour % 24.0
    ha_hour = ((lmst_hour - apparent_ra_hour + 12.0) % 24.0) - 12.0

    return {
        "lmst_hour": lmst_hour,
        "ha_hour": ha_hour,
        "az_deg": altaz.az.deg % 360.0,
        "el_deg": altaz.alt.deg,
        "apparent_ra_hour": apparent_ra_hour,
        "apparent_dec_deg": apparent.dec.deg,
    }


class Stage5CoordinateTests(unittest.TestCase):
    def test_longitude_is_east_positive(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            greenwich = Time(TEST_TIME, scale="utc").sidereal_time("apparent", longitude=0 * u.deg).hour
            east = Time(TEST_TIME, scale="utc").sidereal_time("apparent", longitude=SITE_LON_DEG * u.deg).hour
        delta = ((east - greenwich + 12.0) % 24.0) - 12.0
        self.assertAlmostEqual(delta, SITE_LON_DEG / 15.0, places=6)

    def test_manual_coordinates_ranges_and_hour_angle_sign(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            coords = compute_coordinates(1, manual_ra_hours=5.0, manual_dec_deg=-30.0)
            east_source = compute_coordinates(1, manual_ra_hours=9.0, manual_dec_deg=-30.0)
        self.assertGreaterEqual(coords["lmst_hour"], 0.0)
        self.assertLess(coords["lmst_hour"], 24.0)
        self.assertGreaterEqual(coords["ha_hour"], -12.0)
        self.assertLess(coords["ha_hour"], 12.0)
        self.assertGreater(coords["ha_hour"], 0.0)  # RA 5 h is west of meridian at this time/site.
        self.assertLess(east_source["ha_hour"], 0.0)  # Larger RA is east of the meridian here.
        self.assertGreaterEqual(coords["az_deg"], 0.0)
        self.assertLess(coords["az_deg"], 360.0)
        self.assertGreaterEqual(coords["el_deg"], -90.0)
        self.assertLessEqual(coords["el_deg"], 90.0)

    def test_altaz_azimuth_convention(self):
        location = EarthLocation(
            lat=SITE_LAT_DEG * u.deg,
            lon=SITE_LON_DEG * u.deg,
            height=SITE_HEIGHT_M * u.m,
        )
        obstime = Time(TEST_TIME, scale="utc", location=location)
        east = SkyCoord(
            az=90 * u.deg,
            alt=0 * u.deg,
            frame=AltAz(obstime=obstime, location=location, pressure=0 * u.hPa),
        )
        self.assertAlmostEqual(east.az.deg, 90.0)

    def test_sun_coordinates_are_finite_and_time_varying(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            t0 = compute_coordinates(0, isot="2026-08-09T00:00:00")
            t1 = compute_coordinates(0, isot="2026-08-09T01:00:00")
        for coords in (t0, t1):
            for value in coords.values():
                self.assertTrue(math.isfinite(value))
        self.assertNotAlmostEqual(t0["az_deg"], t1["az_deg"], places=3)
        self.assertNotAlmostEqual(t0["el_deg"], t1["el_deg"], places=3)

    def test_manual_source_transform_is_finite(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            coords = compute_coordinates(1, manual_ra_hours=12.5, manual_dec_deg=-45.0)
        for value in coords.values():
            self.assertTrue(math.isfinite(value))

    def test_stage4_connections_remain_present(self):
        grc_path = pathlib.Path(__file__).resolve().parents[1] / "grc" / "fx_interferometer_v1_stage1_3.grc"
        graph = yaml.safe_load(grc_path.read_text())
        connections = {tuple(connection) for connection in graph["connections"]}
        expected_stage4 = {
            ("cross_accum", "0", "phase_slope_delay_estimator", "0"),
            ("phase_slope_delay_estimator", "0", "delay_number_sink", "0"),
            ("phase_slope_delay_estimator", "1", "phase_slope_number_sink", "0"),
            ("phase_slope_delay_estimator", "2", "phase_fit_rms_number_sink", "0"),
        }
        self.assertTrue(expected_stage4.issubset(connections))

    def test_stage5_does_not_replace_stage1_4_science_path(self):
        grc_path = pathlib.Path(__file__).resolve().parents[1] / "grc" / "fx_interferometer_v1_stage1_3.grc"
        graph = yaml.safe_load(grc_path.read_text())
        connections = {tuple(connection) for connection in graph["connections"]}
        expected_science_path = {
            ("cross_multiply_conjugate", "0", "cross_accum", "0"),
            ("cross_accum", "0", "cross_mag", "0"),
            ("cross_accum", "0", "cross_phase_rad", "0"),
            ("rx0_fft", "0", "cross_multiply_conjugate", "0"),
            ("rx1_fft", "0", "cross_multiply_conjugate", "1"),
        }
        self.assertTrue(expected_science_path.issubset(connections))


if __name__ == "__main__":
    unittest.main()
