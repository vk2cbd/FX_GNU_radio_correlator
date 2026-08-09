import time

import numpy as np
from gnuradio import gr

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, TETE, get_sun
from astropy.time import Time
from astropy.utils import iers

iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = 'warn'


class blk(gr.sync_block):
    """Stage 5 source/site/time astronomy-coordinate engine."""

    def __init__(
        self,
        fft_size=4096,
        site_lat_deg=-32.724,
        site_lon_deg=152.130167,
        site_height_m=70.0,
        source_mode=0,
        manual_ra_hours=5.0,
        manual_dec_deg=-30.0,
    ):
        self.fft_size = int(fft_size)
        self.site_lat_deg = float(site_lat_deg)
        self.site_lon_deg = float(site_lon_deg)
        self.site_height_m = float(site_height_m)
        self.source_mode = int(source_mode)
        self.manual_ra_hours = float(manual_ra_hours)
        self.manual_dec_deg = float(manual_dec_deg)
        self._last_update = 0.0
        self._cache = np.full(7, np.nan, dtype=np.float32)
        gr.sync_block.__init__(
            self,
            name='Astronomy Coordinate Engine',
            in_sig=[(np.complex64, self.fft_size)],
            out_sig=[
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
                np.float32,
            ],
        )

    def _invalidate(self):
        self._last_update = 0.0

    def set_site_lat_deg(self, value):
        self.site_lat_deg = float(value)
        self._invalidate()

    def set_site_lon_deg(self, value):
        self.site_lon_deg = float(value)
        self._invalidate()

    def set_site_height_m(self, value):
        self.site_height_m = float(value)
        self._invalidate()

    def set_source_mode(self, value):
        self.source_mode = int(value)
        self._invalidate()

    def set_manual_ra_hours(self, value):
        self.manual_ra_hours = float(value)
        self._invalidate()

    def set_manual_dec_deg(self, value):
        self.manual_dec_deg = float(value)
        self._invalidate()

    def _compute(self):
        site_lat_deg = float(self.site_lat_deg)
        site_lon_deg = float(self.site_lon_deg)
        site_height_m = float(self.site_height_m)
        source_mode = int(self.source_mode)
        manual_ra_hours = float(self.manual_ra_hours)
        manual_dec_deg = float(self.manual_dec_deg)

        location = EarthLocation(
            lat=site_lat_deg * u.deg,
            lon=site_lon_deg * u.deg,
            height=site_height_m * u.m,
        )
        obstime = Time.now()
        obstime.location = location

        if source_mode == 0:
            source_coord = get_sun(obstime)
        else:
            source_coord = SkyCoord(
                ra=manual_ra_hours * u.hourangle,
                dec=manual_dec_deg * u.deg,
                frame='icrs',
            )

        apparent = source_coord.transform_to(TETE(obstime=obstime, location=location))
        altaz = source_coord.transform_to(
            AltAz(obstime=obstime, location=location, pressure=0 * u.hPa)
        )

        utc_dt = obstime.utc.datetime
        utc_hour = (
            utc_dt.hour
            + utc_dt.minute / 60.0
            + (utc_dt.second + utc_dt.microsecond * 1e-6) / 3600.0
        )
        lmst_hour = (
            obstime.sidereal_time('apparent', longitude=site_lon_deg * u.deg).hour
            % 24.0
        )
        apparent_ra_hour = apparent.ra.hour % 24.0
        apparent_dec_deg = apparent.dec.deg
        ha_hour = ((lmst_hour - apparent_ra_hour + 12.0) % 24.0) - 12.0

        self._cache = np.array(
            [
                utc_hour,
                lmst_hour,
                ha_hour,
                altaz.az.deg % 360.0,
                altaz.alt.deg,
                apparent_ra_hour,
                apparent_dec_deg,
            ],
            dtype=np.float32,
        )
        self._last_update = time.monotonic()

    def work(self, input_items, output_items):
        nout = len(input_items[0])
        if nout == 0:
            return 0

        if self._last_update == 0.0 or time.monotonic() - self._last_update >= 1.0:
            try:
                self._compute()
            except Exception as exc:
                print(f"Stage 5 astronomy error: {exc}", flush=True)
                self._cache = np.full(7, np.nan, dtype=np.float32)
                self._last_update = time.monotonic()

        for idx, value in enumerate(self._cache):
            output_items[idx][:nout] = value

        return nout
