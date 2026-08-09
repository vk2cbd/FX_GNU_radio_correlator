#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: FX Interferometer V1 Stage 1-3
# Description: Minimal two-channel B210 FX correlator commissioning flowgraph.
# GNU Radio version: 3.10.9.2

from PyQt5 import Qt
from gnuradio import qtgui
from PyQt5.QtCore import QObject, pyqtSlot
from gnuradio import blocks
from gnuradio import eng_notation
from gnuradio import fft
from gnuradio.fft import window
from gnuradio import gr
from gnuradio.filter import firdes
import sys
import signal
from PyQt5 import Qt
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import uhd
import time
import fx_interferometer_v1_stage1_3_astronomy_coordinate_engine as astronomy_coordinate_engine  # embedded python block
import fx_interferometer_v1_stage1_3_phase_slope_delay_estimator as phase_slope_delay_estimator  # embedded python block
import sip



class fx_interferometer_v1_stage1_3(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "FX Interferometer V1 Stage 1-3", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("FX Interferometer V1 Stage 1-3")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)
        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("GNU Radio", "fx_interferometer_v1_stage1_3")

        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)

        ##################################################
        # Variables
        ##################################################
        self.sky_cf = sky_cf = 4.800e9
        self.samp_rate = samp_rate = 30.72e6
        self.lnb_lo = lnb_lo = 5.950e9
        self.fft_size = fft_size = 4096
        self.if_cf = if_cf = lnb_lo-sky_cf
        self.fft_rate = fft_rate = samp_rate/fft_size
        self.accum_time = accum_time = 0.1
        self.source_mode = source_mode = 0
        self.sky_axis_step = sky_axis_step = -samp_rate/fft_size
        self.sky_axis_start = sky_axis_start = lnb_lo-(if_cf-samp_rate/2)
        self.site_lon_deg = site_lon_deg = +152.130167
        self.site_lat_deg = site_lat_deg = -32.724
        self.site_height_m = site_height_m = 70
        self.manual_ra_hours = manual_ra_hours = '5.0'
        self.manual_dec_deg = manual_dec_deg = '-30.0'
        self.gain1 = gain1 = 40
        self.gain0 = gain0 = 40
        self.accum_frames = accum_frames = int(round(fft_rate*accum_time))

        ##################################################
        # Blocks
        ##################################################

        # Create the options list
        self._source_mode_options = [0, 1]
        # Create the labels list
        self._source_mode_labels = ['Sun', 'Manual RA/Dec']
        # Create the combo box
        self._source_mode_tool_bar = Qt.QToolBar(self)
        self._source_mode_tool_bar.addWidget(Qt.QLabel("Source" + ": "))
        self._source_mode_combo_box = Qt.QComboBox()
        self._source_mode_tool_bar.addWidget(self._source_mode_combo_box)
        for _label in self._source_mode_labels: self._source_mode_combo_box.addItem(_label)
        self._source_mode_callback = lambda i: Qt.QMetaObject.invokeMethod(self._source_mode_combo_box, "setCurrentIndex", Qt.Q_ARG("int", self._source_mode_options.index(i)))
        self._source_mode_callback(self.source_mode)
        self._source_mode_combo_box.currentIndexChanged.connect(
            lambda i: self.set_source_mode(self._source_mode_options[i]))
        # Create the radio buttons
        self.top_layout.addWidget(self._source_mode_tool_bar)
        self._manual_ra_hours_tool_bar = Qt.QToolBar(self)
        self._manual_ra_hours_tool_bar.addWidget(Qt.QLabel("Manual RA (h)" + ": "))
        self._manual_ra_hours_line_edit = Qt.QLineEdit(str(self.manual_ra_hours))
        self._manual_ra_hours_tool_bar.addWidget(self._manual_ra_hours_line_edit)
        self._manual_ra_hours_line_edit.editingFinished.connect(
            lambda: self.set_manual_ra_hours(str(str(self._manual_ra_hours_line_edit.text()))))
        self.top_layout.addWidget(self._manual_ra_hours_tool_bar)
        self._manual_dec_deg_tool_bar = Qt.QToolBar(self)
        self._manual_dec_deg_tool_bar.addWidget(Qt.QLabel("Manual Dec (deg)" + ": "))
        self._manual_dec_deg_line_edit = Qt.QLineEdit(str(self.manual_dec_deg))
        self._manual_dec_deg_tool_bar.addWidget(self._manual_dec_deg_line_edit)
        self._manual_dec_deg_line_edit.editingFinished.connect(
            lambda: self.set_manual_dec_deg(str(str(self._manual_dec_deg_line_edit.text()))))
        self.top_layout.addWidget(self._manual_dec_deg_tool_bar)
        self.uhd_usrp_source_0 = uhd.usrp_source(
            ",".join(('', "num_recv_frames=256")),
            uhd.stream_args(
                cpu_format="fc32",
                otw_format="sc16",
                args='',
                channels=[0,1],
            ),
        )
        self.uhd_usrp_source_0.set_clock_source('external', 0)
        self.uhd_usrp_source_0.set_time_source('internal', 0)
        self.uhd_usrp_source_0.set_samp_rate(samp_rate)
        self.uhd_usrp_source_0.set_time_unknown_pps(uhd.time_spec(0))

        self.uhd_usrp_source_0.set_center_freq(if_cf, 0)
        self.uhd_usrp_source_0.set_gain(gain0, 0)

        self.uhd_usrp_source_0.set_center_freq(if_cf, 1)
        self.uhd_usrp_source_0.set_gain(gain1, 1)
        self.rx1_stream_to_vector = blocks.stream_to_vector(gr.sizeof_gr_complex*1, fft_size)
        self.rx1_power_db = blocks.nlog10_ff(10, fft_size, 0)
        self.rx1_power_accum = blocks.integrate_ff(accum_frames, fft_size)
        self.rx1_mag2 = blocks.complex_to_mag_squared(fft_size)
        self.rx1_fft = fft.fft_vcc(fft_size, True, window.blackmanharris(fft_size), True, 1)
        self.rx0_stream_to_vector = blocks.stream_to_vector(gr.sizeof_gr_complex*1, fft_size)
        self.rx0_power_db = blocks.nlog10_ff(10, fft_size, 0)
        self.rx0_power_accum = blocks.integrate_ff(accum_frames, fft_size)
        self.rx0_mag2 = blocks.complex_to_mag_squared(fft_size)
        self.rx0_fft = fft.fft_vcc(fft_size, True, window.blackmanharris(fft_size), True, 1)
        self.phase_slope_number_sink = qtgui.number_sink(
            gr.sizeof_float,
            0,
            qtgui.NUM_GRAPH_NONE,
            1,
            None # parent
        )
        self.phase_slope_number_sink.set_update_time(0.25)
        self.phase_slope_number_sink.set_title("Phase Slope (deg/MHz)")

        labels = ['Phase Slope', '', '', '', '',
            '', '', '', '', '']
        units = ['deg/MHz', '', '', '', '',
            '', '', '', '', '']
        colors = [("blue", "red"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"),
            ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black")]
        factor = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]

        for i in range(1):
            self.phase_slope_number_sink.set_min(i, -1000)
            self.phase_slope_number_sink.set_max(i, 1000)
            self.phase_slope_number_sink.set_color(i, colors[i][0], colors[i][1])
            if len(labels[i]) == 0:
                self.phase_slope_number_sink.set_label(i, "Data {0}".format(i))
            else:
                self.phase_slope_number_sink.set_label(i, labels[i])
            self.phase_slope_number_sink.set_unit(i, units[i])
            self.phase_slope_number_sink.set_factor(i, factor[i])

        self.phase_slope_number_sink.enable_autoscale(True)
        self._phase_slope_number_sink_win = sip.wrapinstance(self.phase_slope_number_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._phase_slope_number_sink_win)
        self.phase_slope_delay_estimator = phase_slope_delay_estimator.blk(fft_size=fft_size, samp_rate=samp_rate)
        self.phase_fit_rms_number_sink = qtgui.number_sink(
            gr.sizeof_float,
            0,
            qtgui.NUM_GRAPH_NONE,
            1,
            None # parent
        )
        self.phase_fit_rms_number_sink.set_update_time(0.25)
        self.phase_fit_rms_number_sink.set_title("Phase Fit RMS (deg)")

        labels = ['Phase Fit RMS', '', '', '', '',
            '', '', '', '', '']
        units = ['deg', '', '', '', '',
            '', '', '', '', '']
        colors = [("blue", "red"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"),
            ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black")]
        factor = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]

        for i in range(1):
            self.phase_fit_rms_number_sink.set_min(i, 0)
            self.phase_fit_rms_number_sink.set_max(i, 180)
            self.phase_fit_rms_number_sink.set_color(i, colors[i][0], colors[i][1])
            if len(labels[i]) == 0:
                self.phase_fit_rms_number_sink.set_label(i, "Data {0}".format(i))
            else:
                self.phase_fit_rms_number_sink.set_label(i, labels[i])
            self.phase_fit_rms_number_sink.set_unit(i, units[i])
            self.phase_fit_rms_number_sink.set_factor(i, factor[i])

        self.phase_fit_rms_number_sink.enable_autoscale(True)
        self._phase_fit_rms_number_sink_win = sip.wrapinstance(self.phase_fit_rms_number_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._phase_fit_rms_number_sink_win)
        self.delay_number_sink = qtgui.number_sink(
            gr.sizeof_float,
            0,
            qtgui.NUM_GRAPH_NONE,
            1,
            None # parent
        )
        self.delay_number_sink.set_update_time(0.25)
        self.delay_number_sink.set_title("Differential Delay (ns)")

        labels = ['Differential Delay', '', '', '', '',
            '', '', '', '', '']
        units = ['ns', '', '', '', '',
            '', '', '', '', '']
        colors = [("blue", "red"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"),
            ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black")]
        factor = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]

        for i in range(1):
            self.delay_number_sink.set_min(i, -100)
            self.delay_number_sink.set_max(i, 100)
            self.delay_number_sink.set_color(i, colors[i][0], colors[i][1])
            if len(labels[i]) == 0:
                self.delay_number_sink.set_label(i, "Data {0}".format(i))
            else:
                self.delay_number_sink.set_label(i, labels[i])
            self.delay_number_sink.set_unit(i, units[i])
            self.delay_number_sink.set_factor(i, factor[i])

        self.delay_number_sink.enable_autoscale(True)
        self._delay_number_sink_win = sip.wrapinstance(self.delay_number_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._delay_number_sink_win)
        self.cross_phase_sink = qtgui.vector_sink_f(
            fft_size,
            (sky_axis_start/1e9),
            (sky_axis_step/1e9),
            'Sky frequency (GHz)',
            'Cross phase (deg)',
            "",
            1, # Number of inputs
            None # parent
        )
        self.cross_phase_sink.set_update_time(0.10)
        self.cross_phase_sink.set_y_axis((-180), 180)
        self.cross_phase_sink.enable_autoscale(False)
        self.cross_phase_sink.enable_grid(True)
        self.cross_phase_sink.set_x_axis_units("")
        self.cross_phase_sink.set_y_axis_units("")
        self.cross_phase_sink.set_ref_level(0)


        labels = ['arg(C01), X0 * conj(X1)', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.cross_phase_sink.set_line_label(i, "Data {0}".format(i))
            else:
                self.cross_phase_sink.set_line_label(i, labels[i])
            self.cross_phase_sink.set_line_width(i, widths[i])
            self.cross_phase_sink.set_line_color(i, colors[i])
            self.cross_phase_sink.set_line_alpha(i, alphas[i])

        self._cross_phase_sink_win = sip.wrapinstance(self.cross_phase_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._cross_phase_sink_win)
        self.cross_phase_rad = blocks.complex_to_arg(fft_size)
        self.cross_phase_deg = blocks.multiply_const_vff([57.29577951308232]*fft_size)
        self.cross_multiply_conjugate = blocks.multiply_conjugate_cc(fft_size)
        self.cross_mag_sink = qtgui.vector_sink_f(
            fft_size,
            (sky_axis_start/1e9),
            (sky_axis_step/1e9),
            'Sky frequency (GHz)',
            'Relative cross magnitude (dB)',
            "",
            1, # Number of inputs
            None # parent
        )
        self.cross_mag_sink.set_update_time(0.10)
        self.cross_mag_sink.set_y_axis((-140), 10)
        self.cross_mag_sink.enable_autoscale(True)
        self.cross_mag_sink.enable_grid(True)
        self.cross_mag_sink.set_x_axis_units("")
        self.cross_mag_sink.set_y_axis_units("")
        self.cross_mag_sink.set_ref_level(0)


        labels = ['|C01|, X0 * conj(X1)', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.cross_mag_sink.set_line_label(i, "Data {0}".format(i))
            else:
                self.cross_mag_sink.set_line_label(i, labels[i])
            self.cross_mag_sink.set_line_width(i, widths[i])
            self.cross_mag_sink.set_line_color(i, colors[i])
            self.cross_mag_sink.set_line_alpha(i, alphas[i])

        self._cross_mag_sink_win = sip.wrapinstance(self.cross_mag_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._cross_mag_sink_win)
        self.cross_mag_db = blocks.nlog10_ff(20, fft_size, 0)
        self.cross_mag = blocks.complex_to_mag(fft_size)
        self.cross_accum = blocks.integrate_cc(accum_frames, fft_size)
        self.auto_spectra_sink = qtgui.vector_sink_f(
            fft_size,
            (sky_axis_start/1e9),
            (sky_axis_step/1e9),
            'Sky frequency (GHz)',
            'Relative power (dB)',
            "",
            2, # Number of inputs
            None # parent
        )
        self.auto_spectra_sink.set_update_time(0.10)
        self.auto_spectra_sink.set_y_axis((-140), 10)
        self.auto_spectra_sink.enable_autoscale(True)
        self.auto_spectra_sink.enable_grid(True)
        self.auto_spectra_sink.set_x_axis_units("")
        self.auto_spectra_sink.set_y_axis_units("")
        self.auto_spectra_sink.set_ref_level(0)


        labels = ['RX0 P0: antenna 0 / 2.4 m', 'RX1 P1: antenna 1 / 1.7 m', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(2):
            if len(labels[i]) == 0:
                self.auto_spectra_sink.set_line_label(i, "Data {0}".format(i))
            else:
                self.auto_spectra_sink.set_line_label(i, labels[i])
            self.auto_spectra_sink.set_line_width(i, widths[i])
            self.auto_spectra_sink.set_line_color(i, colors[i])
            self.auto_spectra_sink.set_line_alpha(i, alphas[i])

        self._auto_spectra_sink_win = sip.wrapinstance(self.auto_spectra_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._auto_spectra_sink_win)
        self.astronomy_number_sink = qtgui.number_sink(
            gr.sizeof_float,
            0,
            qtgui.NUM_GRAPH_NONE,
            7,
            None # parent
        )
        self.astronomy_number_sink.set_update_time(0.5)
        self.astronomy_number_sink.set_title("Astronomy / Source Coordinates")

        labels = ['UTC', 'LMST', 'Hour Angle', 'Azimuth', 'Elevation',
            'Apparent RA', 'Apparent Dec', '', '', '']
        units = ['h', 'h', 'h', 'deg', 'deg',
            'h', 'deg', '', '', '']
        colors = [("blue", "red"), ("blue", "red"), ("blue", "red"), ("blue", "red"), ("blue", "red"),
            ("blue", "red"), ("blue", "red"), ("black", "black"), ("black", "black"), ("black", "black")]
        factor = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]

        for i in range(7):
            self.astronomy_number_sink.set_min(i, -180)
            self.astronomy_number_sink.set_max(i, 360)
            self.astronomy_number_sink.set_color(i, colors[i][0], colors[i][1])
            if len(labels[i]) == 0:
                self.astronomy_number_sink.set_label(i, "Data {0}".format(i))
            else:
                self.astronomy_number_sink.set_label(i, labels[i])
            self.astronomy_number_sink.set_unit(i, units[i])
            self.astronomy_number_sink.set_factor(i, factor[i])

        self.astronomy_number_sink.enable_autoscale(True)
        self._astronomy_number_sink_win = sip.wrapinstance(self.astronomy_number_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._astronomy_number_sink_win)
        self.astronomy_coordinate_engine = astronomy_coordinate_engine.blk(fft_size=fft_size, site_lat_deg=site_lat_deg, site_lon_deg=site_lon_deg, site_height_m=site_height_m, source_mode=source_mode, manual_ra_hours=manual_ra_hours, manual_dec_deg=manual_dec_deg)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.astronomy_coordinate_engine, 1), (self.astronomy_number_sink, 1))
        self.connect((self.astronomy_coordinate_engine, 5), (self.astronomy_number_sink, 5))
        self.connect((self.astronomy_coordinate_engine, 6), (self.astronomy_number_sink, 6))
        self.connect((self.astronomy_coordinate_engine, 0), (self.astronomy_number_sink, 0))
        self.connect((self.astronomy_coordinate_engine, 3), (self.astronomy_number_sink, 3))
        self.connect((self.astronomy_coordinate_engine, 4), (self.astronomy_number_sink, 4))
        self.connect((self.astronomy_coordinate_engine, 2), (self.astronomy_number_sink, 2))
        self.connect((self.cross_accum, 0), (self.astronomy_coordinate_engine, 0))
        self.connect((self.cross_accum, 0), (self.cross_mag, 0))
        self.connect((self.cross_accum, 0), (self.cross_phase_rad, 0))
        self.connect((self.cross_accum, 0), (self.phase_slope_delay_estimator, 0))
        self.connect((self.cross_mag, 0), (self.cross_mag_db, 0))
        self.connect((self.cross_mag_db, 0), (self.cross_mag_sink, 0))
        self.connect((self.cross_multiply_conjugate, 0), (self.cross_accum, 0))
        self.connect((self.cross_phase_deg, 0), (self.cross_phase_sink, 0))
        self.connect((self.cross_phase_rad, 0), (self.cross_phase_deg, 0))
        self.connect((self.phase_slope_delay_estimator, 0), (self.delay_number_sink, 0))
        self.connect((self.phase_slope_delay_estimator, 2), (self.phase_fit_rms_number_sink, 0))
        self.connect((self.phase_slope_delay_estimator, 1), (self.phase_slope_number_sink, 0))
        self.connect((self.rx0_fft, 0), (self.cross_multiply_conjugate, 0))
        self.connect((self.rx0_fft, 0), (self.rx0_mag2, 0))
        self.connect((self.rx0_mag2, 0), (self.rx0_power_accum, 0))
        self.connect((self.rx0_power_accum, 0), (self.rx0_power_db, 0))
        self.connect((self.rx0_power_db, 0), (self.auto_spectra_sink, 0))
        self.connect((self.rx0_stream_to_vector, 0), (self.rx0_fft, 0))
        self.connect((self.rx1_fft, 0), (self.cross_multiply_conjugate, 1))
        self.connect((self.rx1_fft, 0), (self.rx1_mag2, 0))
        self.connect((self.rx1_mag2, 0), (self.rx1_power_accum, 0))
        self.connect((self.rx1_power_accum, 0), (self.rx1_power_db, 0))
        self.connect((self.rx1_power_db, 0), (self.auto_spectra_sink, 1))
        self.connect((self.rx1_stream_to_vector, 0), (self.rx1_fft, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.rx0_stream_to_vector, 0))
        self.connect((self.uhd_usrp_source_0, 1), (self.rx1_stream_to_vector, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "fx_interferometer_v1_stage1_3")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_sky_cf(self):
        return self.sky_cf

    def set_sky_cf(self, sky_cf):
        self.sky_cf = sky_cf
        self.set_if_cf(self.lnb_lo-self.sky_cf)

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.set_fft_rate(self.samp_rate/self.fft_size)
        self.set_sky_axis_start(self.lnb_lo-(self.if_cf-self.samp_rate/2))
        self.set_sky_axis_step(-self.samp_rate/self.fft_size)
        self.phase_slope_delay_estimator.samp_rate = self.samp_rate
        self.uhd_usrp_source_0.set_samp_rate(self.samp_rate)

    def get_lnb_lo(self):
        return self.lnb_lo

    def set_lnb_lo(self, lnb_lo):
        self.lnb_lo = lnb_lo
        self.set_if_cf(self.lnb_lo-self.sky_cf)
        self.set_sky_axis_start(self.lnb_lo-(self.if_cf-self.samp_rate/2))

    def get_fft_size(self):
        return self.fft_size

    def set_fft_size(self, fft_size):
        self.fft_size = fft_size
        self.set_fft_rate(self.samp_rate/self.fft_size)
        self.set_sky_axis_step(-self.samp_rate/self.fft_size)
        self.astronomy_coordinate_engine.fft_size = self.fft_size
        self.cross_phase_deg.set_k([57.29577951308232]*self.fft_size)
        self.phase_slope_delay_estimator.fft_size = self.fft_size

    def get_if_cf(self):
        return self.if_cf

    def set_if_cf(self, if_cf):
        self.if_cf = if_cf
        self.set_sky_axis_start(self.lnb_lo-(self.if_cf-self.samp_rate/2))
        self.uhd_usrp_source_0.set_center_freq(self.if_cf, 0)
        self.uhd_usrp_source_0.set_center_freq(self.if_cf, 1)

    def get_fft_rate(self):
        return self.fft_rate

    def set_fft_rate(self, fft_rate):
        self.fft_rate = fft_rate
        self.set_accum_frames(int(round(self.fft_rate*self.accum_time)))

    def get_accum_time(self):
        return self.accum_time

    def set_accum_time(self, accum_time):
        self.accum_time = accum_time
        self.set_accum_frames(int(round(self.fft_rate*self.accum_time)))

    def get_source_mode(self):
        return self.source_mode

    def set_source_mode(self, source_mode):
        self.source_mode = source_mode
        self._source_mode_callback(self.source_mode)
        self.astronomy_coordinate_engine.source_mode = self.source_mode

    def get_sky_axis_step(self):
        return self.sky_axis_step

    def set_sky_axis_step(self, sky_axis_step):
        self.sky_axis_step = sky_axis_step
        self.auto_spectra_sink.set_x_axis((self.sky_axis_start/1e9), (self.sky_axis_step/1e9))
        self.cross_mag_sink.set_x_axis((self.sky_axis_start/1e9), (self.sky_axis_step/1e9))
        self.cross_phase_sink.set_x_axis((self.sky_axis_start/1e9), (self.sky_axis_step/1e9))

    def get_sky_axis_start(self):
        return self.sky_axis_start

    def set_sky_axis_start(self, sky_axis_start):
        self.sky_axis_start = sky_axis_start
        self.auto_spectra_sink.set_x_axis((self.sky_axis_start/1e9), (self.sky_axis_step/1e9))
        self.cross_mag_sink.set_x_axis((self.sky_axis_start/1e9), (self.sky_axis_step/1e9))
        self.cross_phase_sink.set_x_axis((self.sky_axis_start/1e9), (self.sky_axis_step/1e9))

    def get_site_lon_deg(self):
        return self.site_lon_deg

    def set_site_lon_deg(self, site_lon_deg):
        self.site_lon_deg = site_lon_deg
        self.astronomy_coordinate_engine.site_lon_deg = self.site_lon_deg

    def get_site_lat_deg(self):
        return self.site_lat_deg

    def set_site_lat_deg(self, site_lat_deg):
        self.site_lat_deg = site_lat_deg
        self.astronomy_coordinate_engine.site_lat_deg = self.site_lat_deg

    def get_site_height_m(self):
        return self.site_height_m

    def set_site_height_m(self, site_height_m):
        self.site_height_m = site_height_m
        self.astronomy_coordinate_engine.site_height_m = self.site_height_m

    def get_manual_ra_hours(self):
        return self.manual_ra_hours

    def set_manual_ra_hours(self, manual_ra_hours):
        self.manual_ra_hours = manual_ra_hours
        Qt.QMetaObject.invokeMethod(self._manual_ra_hours_line_edit, "setText", Qt.Q_ARG("QString", str(self.manual_ra_hours)))
        self.astronomy_coordinate_engine.manual_ra_hours = self.manual_ra_hours

    def get_manual_dec_deg(self):
        return self.manual_dec_deg

    def set_manual_dec_deg(self, manual_dec_deg):
        self.manual_dec_deg = manual_dec_deg
        Qt.QMetaObject.invokeMethod(self._manual_dec_deg_line_edit, "setText", Qt.Q_ARG("QString", str(self.manual_dec_deg)))
        self.astronomy_coordinate_engine.manual_dec_deg = self.manual_dec_deg

    def get_gain1(self):
        return self.gain1

    def set_gain1(self, gain1):
        self.gain1 = gain1
        self.uhd_usrp_source_0.set_gain(self.gain1, 1)

    def get_gain0(self):
        return self.gain0

    def set_gain0(self, gain0):
        self.gain0 = gain0
        self.uhd_usrp_source_0.set_gain(self.gain0, 0)

    def get_accum_frames(self):
        return self.accum_frames

    def set_accum_frames(self, accum_frames):
        self.accum_frames = accum_frames




def main(top_block_cls=fx_interferometer_v1_stage1_3, options=None):

    qapp = Qt.QApplication(sys.argv)

    tb = top_block_cls()

    tb.start()

    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec_()

if __name__ == '__main__':
    main()
