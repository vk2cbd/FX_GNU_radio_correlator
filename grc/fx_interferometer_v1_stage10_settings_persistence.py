from gnuradio import gr

from fx_interferometer_v1_stage10_settings import save_settings


class blk(gr.sync_block):
    """Persist Stage 10 operator settings as GRC variables change."""

    def __init__(
        self,
        site_lat_deg=-32.724,
        site_lon_deg=152.130167,
        site_height_m=70.0,
        source_mode=0,
        manual_ra_hours="5.0",
        manual_dec_deg="-30.0",
        baseline_e_m=-5.785,
        baseline_n_m=0.095,
        baseline_u_m=0.580,
        sky_cf=4.800e9,
        gain0=40,
        gain1=40,
        fft_size=4096,
        accum_time=0.1,
        instrument_delay_ns="0.0",
        delay_correction_enable=True,
        fringe_stop_enable=True,
        fringe_stop_sign=-1,
        visibility_edge_exclude_pct=20.0,
        integration_time_s="1.0",
        phase_rate_fit_window_s=60.0,
        coherence_target_pct=95.0,
        uvfits_output_dir="~/FX_Correlator_Data",
        observation_name="observation",
    ):
        gr.sync_block.__init__(self, name="Stage 10 Settings Persistence", in_sig=None, out_sig=None)
        self._settings = {}
        self._save(
            site_lat_deg=site_lat_deg,
            site_lon_deg=site_lon_deg,
            site_height_m=site_height_m,
            source_mode=source_mode,
            manual_ra_hours=manual_ra_hours,
            manual_dec_deg=manual_dec_deg,
            baseline_e_m=baseline_e_m,
            baseline_n_m=baseline_n_m,
            baseline_u_m=baseline_u_m,
            sky_cf=sky_cf,
            gain0=gain0,
            gain1=gain1,
            fft_size=fft_size,
            accum_time=accum_time,
            instrument_delay_ns=instrument_delay_ns,
            delay_correction_enable=delay_correction_enable,
            fringe_stop_enable=fringe_stop_enable,
            fringe_stop_sign=fringe_stop_sign,
            visibility_edge_exclude_pct=visibility_edge_exclude_pct,
            integration_time_s=integration_time_s,
            phase_rate_fit_window_s=phase_rate_fit_window_s,
            coherence_target_pct=coherence_target_pct,
            uvfits_output_dir=uvfits_output_dir,
            observation_name=observation_name,
        )

    def _save(self, **kwargs):
        changed = {key: value for key, value in kwargs.items() if self._settings.get(key) != value}
        if not changed:
            return
        self._settings.update(changed)
        try:
            save_settings(**changed)
        except Exception as exc:
            print(f"Stage 10 settings persistence failed: {exc}", flush=True)

    def set_site_lat_deg(self, value):
        self._save(site_lat_deg=value)

    def set_site_lon_deg(self, value):
        self._save(site_lon_deg=value)

    def set_site_height_m(self, value):
        self._save(site_height_m=value)

    def set_source_mode(self, value):
        self._save(source_mode=value)

    def set_manual_ra_hours(self, value):
        self._save(manual_ra_hours=value)

    def set_manual_dec_deg(self, value):
        self._save(manual_dec_deg=value)

    def set_baseline_e_m(self, value):
        self._save(baseline_e_m=value)

    def set_baseline_n_m(self, value):
        self._save(baseline_n_m=value)

    def set_baseline_u_m(self, value):
        self._save(baseline_u_m=value)

    def set_sky_cf(self, value):
        self._save(sky_cf=value)

    def set_gain0(self, value):
        self._save(gain0=value)

    def set_gain1(self, value):
        self._save(gain1=value)

    def set_fft_size(self, value):
        self._save(fft_size=value)

    def set_accum_time(self, value):
        self._save(accum_time=value)

    def set_instrument_delay_ns(self, value):
        self._save(instrument_delay_ns=value)

    def set_delay_correction_enable(self, value):
        self._save(delay_correction_enable=value)

    def set_fringe_stop_enable(self, value):
        self._save(fringe_stop_enable=value)

    def set_fringe_stop_sign(self, value):
        self._save(fringe_stop_sign=value)

    def set_visibility_edge_exclude_pct(self, value):
        self._save(visibility_edge_exclude_pct=value)

    def set_integration_time_s(self, value):
        self._save(integration_time_s=value)

    def set_phase_rate_fit_window_s(self, value):
        self._save(phase_rate_fit_window_s=value)

    def set_coherence_target_pct(self, value):
        self._save(coherence_target_pct=value)

    def set_uvfits_output_dir(self, value):
        self._save(uvfits_output_dir=value)

    def set_observation_name(self, value):
        self._save(observation_name=value)
