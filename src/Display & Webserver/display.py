"""
Dual MAX30001 Visualiser – v8.4 Fixed Web Sync + Waveforms
GUI and Web Dashboard show identical real-time data including waveforms
"""

import sys, struct, os, time, socket, json
import numpy as np
import pyqtgraph as pg
import joblib
import pandas as pd
from scipy.signal import butter, filtfilt, iirnotch, medfilt
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget,
    QPushButton, QHBoxLayout, QLabel, QFrame, QSizePolicy, QGridLayout)
from PyQt6.QtCore import QTimer, Qt
from collections import deque
import tempfile
import shutil

# ── Config ────────────────────────────────────────────────────────────────────
FS = 128
WINDOW_SIZE = int(FS * 12)

# Wireless Config
UDP_IP = "0.0.0.0"
UDP_PORT = 12345

# Shared state file for web server
VITALS_FILE = "vitals_state.json"

# Physiological Parameters
DISTANCE_M = 1.35  

# Visual Marker Offsets
VISUAL_SHIFT_ECG = 5
VISUAL_SHIFT_APW1 = 10
VISUAL_SHIFT_APW2 = 12

# Packet constants
PKT_START_1 = 0x0A
PKT_START_2 = 0xFA
PKT_STOP = 0x0B
DATA_LEN = 29
HEADER_LEN = 5
TOTAL_PKT = 36

FLAG_R_PEAK = 0x01
FLAG_APW1_FOOT = 0x02
FLAG_APW2_FOOT = 0x04

# ─────────────────────────────────────────────────────────────────────────────
# 1. ECG Signal Processor
# ─────────────────────────────────────────────────────────────────────────────
class ECGProcessor:
    def __init__(self, fs: float):
        self.fs = fs

    def preprocess(self, ecg: np.ndarray) -> np.ndarray:
        ecg = ecg.astype(float)
        kernel = max(3, int(0.2 * self.fs) | 1)
        ecg = ecg - medfilt(ecg, kernel_size=kernel)
        nyq = self.fs / 2.0
        high = min(45.0, nyq * 0.95)
        b, a = butter(3, [0.5 / nyq, high / nyq], btype='band')
        ecg = filtfilt(b, a, ecg)
        for f0 in [50.0, 60.0]:
            if f0 < nyq - 1:
                b, a = iirnotch(f0, Q=30, fs=self.fs)
                ecg = filtfilt(b, a, ecg)
        e_min = ecg.min(); e_max = ecg.max(); rng = e_max - e_min
        if rng > 1e-9:
            ecg = (ecg - e_min) / rng
        return ecg

    def pan_tompkins(self, ecg: np.ndarray) -> np.ndarray:
        N = len(ecg)
        if N < int(self.fs * 1.5): return np.array([], dtype=int)
        if abs(ecg.min()) > abs(ecg.max()): ecg = -ecg
        diff = np.diff(ecg, prepend=ecg[0])
        mwi = np.convolve(diff ** 2, np.ones(max(1, int(0.15 * self.fs))) / max(1, int(0.15 * self.fs)), mode='same')
        thr = 0.40 * mwi.max()
        if thr < 1e-12: return np.array([], dtype=int)
        refractory = int(0.25 * self.fs)
        coarse, last = [], -refractory
        for i in range(1, N - 1):
            if (mwi[i] > thr and mwi[i] >= mwi[i-1] and mwi[i] >= mwi[i+1] and i - last >= refractory):
                coarse.append(i); last = i
        if len(coarse) < 2: return np.array([], dtype=int)
        margin = max(1, int(0.02 * self.fs))
        refined = []
        for p in coarse:
            s = max(0, p - margin); e = min(N, p + margin + 1)
            refined.append(s + int(np.argmax(ecg[s:e])))
        return np.array(refined, dtype=int)

    def _median_beat(self, ecg, r_peaks):
        pre = int(0.2 * self.fs); post = int(0.4 * self.fs)
        beats = []
        for r in r_peaks:
            if r - pre >= 0 and r + post < len(ecg):
                beats.append(ecg[r - pre: r + post])
        if not beats: return None, pre
        return np.median(np.array(beats), axis=0), pre

    def _qrs_bounds(self, beat, r_off, thr_frac=0.15):
        thr = abs(beat[r_off]) * thr_frac
        onset = r_off
        for i in range(r_off, 0, -1):
            if abs(beat[i]) < thr: onset = i; break
        offset = r_off
        for i in range(r_off, len(beat) - 1):
            if abs(beat[i]) < thr: offset = i; break
        return onset, offset

    def analyse(self, raw_ecg: np.ndarray) -> dict:
        res = dict(hr_bpm=None, hr_status=None, sdnn_ms=None, rmssd_ms=None, pnn50=None,
                   qrs_ms=None, pr_ms=None, qt_ms=None, qtc_ms=None, st_offset=None, 
                   rr_regularity=None, r_count=0, alerts=[])

        if len(raw_ecg) < self.fs * 3: return res
        ecg = self.preprocess(raw_ecg)
        r = self.pan_tompkins(ecg)
        res["r_count"] = len(r)

        if len(r) < 2:
            res["alerts"].append("⚠ Not enough beats for morphology")
            return res

        rr_s = np.diff(r) / self.fs
        rr_ms = rr_s * 1000.0
        hr = float(np.mean(60.0 / rr_s))
        res["hr_bpm"] = round(hr, 1)

        if hr < 50: 
            res["hr_status"] = "Bradycardia"
            res["alerts"].append("⚠ Bradycardia (HR < 50)")
        elif hr > 110: 
            res["hr_status"] = "Tachycardia"
            res["alerts"].append("⚠ Tachycardia (HR > 110)")
        else: 
            res["hr_status"] = "Normal Sinus"

        if len(rr_ms) >= 2:
            diffs = np.diff(rr_ms)
            res["sdnn_ms"] = round(float(np.std(rr_ms)), 1)
            res["rmssd_ms"] = round(float(np.sqrt(np.mean(diffs ** 2))), 1)
            res["pnn50"] = round(float(np.mean(np.abs(diffs) > 50) * 100), 1)

        cv = float(np.std(rr_ms) / (np.mean(rr_ms) + 1e-6))
        res["rr_regularity"] = "Irregular" if cv > 0.15 else "Regular"
        if cv > 0.15:
            res["alerts"].append("⚠ Irregular RR (possible AF)")

        beat, r_off = self._median_beat(ecg, r)
        if beat is None: return res

        amp_max = np.max(np.abs(beat)) + 1e-9
        qrs_on, qrs_off = self._qrs_bounds(beat, r_off)
        qrs_ms = (qrs_off - qrs_on) / self.fs * 1000.0
        res["qrs_ms"] = round(qrs_ms, 1)
        if qrs_ms > 120: res["alerts"].append("⚠ Wide QRS > 120ms")

        p_start = max(0, qrs_on - int(0.20 * self.fs))
        if qrs_on - p_start >= 3:
            p_idx = p_start + int(np.argmax(np.abs(beat[p_start:qrs_on])))
            pr_ms = (qrs_on - p_idx) / self.fs * 1000.0
            res["pr_ms"] = round(pr_ms, 1)

        t_start = qrs_off + int(0.05 * self.fs)
        t_end = min(len(beat), qrs_off + int(0.40 * self.fs))
        if t_end - t_start >= 3:
            t_idx = t_start + int(np.argmax(np.abs(beat[t_start:t_end])))
            qt_ms = (t_idx - qrs_on + int(0.05*self.fs)) / self.fs * 1000.0
            rr_avg = float(np.mean(rr_s))
            qtc = qt_ms / np.sqrt(rr_avg) if rr_avg > 0 else None
            res["qtc_ms"] = round(qtc, 1) if qtc else None

        j80 = qrs_off + int(0.08 * self.fs)
        iso_s = max(0, r_off - int(0.05 * self.fs))
        if j80 < len(beat) and iso_s < r_off:
            baseline = float(np.mean(beat[iso_s:r_off]))
            st = (float(beat[j80]) - baseline) / amp_max
            res["st_offset"] = round(st, 3)

        return res

# ─────────────────────────────────────────────────────────────────────────────
# 2. Packet parser 
# ─────────────────────────────────────────────────────────────────────────────
class PacketParser:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf.extend(data)
        out = []
        while len(self.buf) >= TOTAL_PKT:
            idx = -1
            for i in range(len(self.buf) - 1):
                if self.buf[i] == PKT_START_1 and self.buf[i+1] == PKT_START_2:
                    idx = i; break
            if idx == -1:
                self.buf = bytearray([self.buf[-1]]) if self.buf else bytearray()
                break
            if idx > 0: self.buf = self.buf[idx:]
            if len(self.buf) < TOTAL_PKT: break
            if self.buf[2] != DATA_LEN: self.buf = self.buf[2:]; continue
            if self.buf[HEADER_LEN + DATA_LEN + 1] != PKT_STOP: self.buf = self.buf[2:]; continue

            pl = self.buf[HEADER_LEN: HEADER_LEN + DATA_LEN]
            ecg1 = struct.unpack_from('<i', pl, 0)[0]
            bz1 = struct.unpack_from('<i', pl, 4)[0]
            ecg2 = struct.unpack_from('<i', pl, 8)[0]
            bz2 = struct.unpack_from('<i', pl, 12)[0]
            flags = pl[16]
            v_bus, i_ma, p_mw = struct.unpack_from('<fff', pl, 17)

            out.append((ecg1, bz1, ecg2, bz2, flags, v_bus, i_ma, p_mw))
            self.buf = self.buf[TOTAL_PKT:]
        return out

# ─────────────────────────────────────────────────────────────────────────────
# 3. Main Window
# ─────────────────────────────────────────────────────────────────────────────
class DualPTT(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Biomedical Monitor | Wireless DSP + Morphology + Web Sync")
        self.resize(1400, 950)
        
        pg.setConfigOption('background', '#0d1117')
        pg.setConfigOption('foreground', '#8b949e')
        pg.setConfigOptions(antialias=True)

        self._build_ui()

        self.state = {
            "hr": None, "bp": None, "pwv": None, "ptt": None,
            "v_bus": None, "i_ma": None, "p_mw": None,
            "sdnn": None, "rmssd": None, "pnn50": None,
            "reg": None, "qrs": None, "pr": None, "qtc": None, "st": None,
            "alerts": [],
            "wave_ecg": [], "wave_apw1": [], "wave_apw2": [],
            "markers_r": [], "markers_f1": [], "markers_f2": []
        }

        self.d_ecg1 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.d_apw1 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.d_apw2 = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
        self.d_flags = deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)

        self.parser = PacketParser()
        self.ecg_proc = ECGProcessor(FS)
        self.last_analysis_time = 0
        self.last_export_time = 0.0
        self.EXPORT_INTERVAL = 0.25

        self._rl, self._f1l, self._f2l = [], [], []
        self.serial = None
        self.bytes_rx = self.pkts_rx = 0
        self._last_v = self._last_i = self._last_p = 0.0
        self.ptt_queue = deque(maxlen=50)
        
        self.bp_model = None
        if os.path.exists('bp_xgboost_model.pkl'):
            try: 
                self.bp_model = joblib.load('bp_xgboost_model.pkl')
            except Exception: 
                pass

        self._sample_count = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0d1117; }
            QLabel { color: #c9d1d9; font-family: 'Segoe UI', Arial, sans-serif; }
            QPushButton {
                background-color: #238636; border: 1px solid #2ea043;
                color: #ffffff; border-radius: 6px; padding: 6px 16px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background-color: #2ea043; }
            QFrame#MetricCard { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; }
            QFrame#MiniCard { background-color: #0a0d12; border: 1px solid #21262d; border-radius: 6px; }
        """)

        cw = QWidget(); self.setCentralWidget(cw); main_layout = QVBoxLayout(cw)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Top Control Bar
        top_bar = QHBoxLayout()
        self.btn = QPushButton("Connect UDP Listener")
        self.btn.clicked.connect(self._toggle)
        
        self.status_lbl = QLabel("Status: Disconnected")
        self.status_lbl.setStyleSheet("color: #8b949e; font-style: italic;")
        
        self.ina_lbl = QLabel("🔋 Battery: -- V | -- mA | -- mW")
        self.ina_lbl.setStyleSheet("color: #00ffff; font-size: 14px; font-weight: bold; font-family: monospace; padding: 0px 15px;")

        top_bar.addWidget(self.btn)
        top_bar.addSpacing(20)
        top_bar.addWidget(self.status_lbl)
        top_bar.addStretch()
        top_bar.addWidget(self.ina_lbl)
        main_layout.addLayout(top_bar)

        # Primary Vitals
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(15)
        self.lbl_hr = self._create_metric_card("HEART RATE", "---", "bpm", "#39d353")
        self.lbl_bp = self._create_metric_card("BLOOD PRESSURE", "---/---", "mmHg", "#ff7b72")
        self.lbl_pwv = self._create_metric_card("PULSE WAVE VEL", "---", "m/s", "#79c0ff")
        self.lbl_ptt = self._create_metric_card("AVERAGE PTT", "---", "ms", "#d2a8ff")
        metrics_layout.addWidget(self.lbl_hr['card'])
        metrics_layout.addWidget(self.lbl_bp['card'])
        metrics_layout.addWidget(self.lbl_pwv['card'])
        metrics_layout.addWidget(self.lbl_ptt['card'])
        main_layout.addLayout(metrics_layout)

        # Advanced ECG Metrics Panel
        adv_container = QFrame()
        adv_container.setObjectName("MetricCard")
        adv_layout = QVBoxLayout(adv_container)
        adv_title = QLabel("Advanced ECG Morphology & HRV (10s Window)")
        adv_title.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        adv_layout.addWidget(adv_title)
        
        self.mini_metrics = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        
        mini_keys = [
            ("SDNN", "ms", 0, 0), ("RMSSD", "ms", 0, 1), ("pNN50", "%", 0, 2), ("Reg", "", 0, 3),
            ("QRS", "ms", 1, 0), ("PR", "ms", 1, 1), ("QTc", "ms", 1, 2), ("ST Off", "n", 1, 3)
        ]
        for key, unit, r, c in mini_keys:
            card, val_lbl = self._create_mini_card(key, "—", unit)
            self.mini_metrics[key] = val_lbl
            grid.addWidget(card, r, c)
            
        adv_layout.addLayout(grid)
        
        self.alerts_lbl = QLabel("✓ No clinical flags detected.")
        self.alerts_lbl.setStyleSheet("color: #39d353; font-weight: bold; font-size: 12px; margin-top: 5px;")
        adv_layout.addWidget(self.alerts_lbl)
        
        main_layout.addWidget(adv_container)

        # Graphs
        self.p1 = pg.PlotWidget(title="Electrocardiogram (ECG1) - Live Hardware Stream")
        self.p1.showGrid(x=True, y=True, alpha=0.2)
        self.ce = self.p1.plot(pen=pg.mkPen('#39d353', width=2))
        main_layout.addWidget(self.p1, stretch=2)

        self.ipg_container = QWidget()
        ipg_layout = QVBoxLayout(self.ipg_container)
        
        self.p2 = pg.PlotWidget(title="IPG (APW1) - Onboard Cubic-Poly Foot")
        self.p2.showGrid(x=True, y=True, alpha=0.2)
        self.p2.setXLink(self.p1)
        self.c1 = self.p2.plot(pen=pg.mkPen('#e3b341', width=1.5))
        self.sc1 = pg.ScatterPlotItem(size=10, brush=pg.mkBrush('#39d353'))
        self.p2.addItem(self.sc1)
        
        self.p3 = pg.PlotWidget(title="IPG (APW2) - Onboard V-Shape Trough")
        self.p3.showGrid(x=True, y=True, alpha=0.2)
        self.p3.setXLink(self.p1)
        self.c2 = self.p3.plot(pen=pg.mkPen('#d2a8ff', width=1.5))
        self.sc2 = pg.ScatterPlotItem(size=10, brush=pg.mkBrush('#39d353'))
        self.p3.addItem(self.sc2)

        ipg_layout.addWidget(self.p2)
        ipg_layout.addWidget(self.p3)
        main_layout.addWidget(self.ipg_container, stretch=3)

        # Footer
        footer = QHBoxLayout()
        self.debug_lbl = QLabel("Pkts: 0 | Buffer: 0s")
        self.debug_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        footer.addStretch()
        footer.addWidget(self.debug_lbl)
        main_layout.addLayout(footer)

    def _create_metric_card(self, title, val, unit, color):
        card = QFrame(); card.setObjectName("MetricCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card); layout.setContentsMargins(15, 10, 15, 15)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #8b949e; font-size: 12px; font-weight: bold; letter-spacing: 1px;")
        lbl_val = QLabel(val)
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_val.setStyleSheet(f"color: {color}; font-size: 34px; font-weight: bold; font-family: monospace;")
        lbl_unit = QLabel(unit); lbl_unit.setAlignment(Qt.AlignmentFlag.AlignRight)
        lbl_unit.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(lbl_title); layout.addWidget(lbl_val); layout.addWidget(lbl_unit)
        return {'card': card, 'val': lbl_val}

    def _create_mini_card(self, title, val, unit):
        card = QFrame(); card.setObjectName("MiniCard")
        lay = QHBoxLayout(card); lay.setContentsMargins(10, 5, 10, 5)
        lbl_t = QLabel(title); lbl_t.setStyleSheet("color: #8b949e; font-size: 11px; font-weight:bold;")
        lbl_v = QLabel(f"{val} {unit}"); lbl_v.setStyleSheet("color: #c9d1d9; font-size: 12px; font-family: monospace;")
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(lbl_t); lay.addWidget(lbl_v)
        return card, lbl_v

    def _toggle(self):
        if self.serial is None:
            try:
                self.serial = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.serial.bind((UDP_IP, UDP_PORT))
                self.serial.setblocking(False)
                
                self.btn.setText("Disconnect")
                self.btn.setStyleSheet("background-color: #da3633; border: 1px solid #f85149;")
                self.status_lbl.setText(f"Connected - Listening on UDP {UDP_PORT}")
                self.status_lbl.setStyleSheet("color: #39d353; font-weight: bold;")
                self.timer.start(20)
            except Exception as e:
                self.status_lbl.setText(f"Socket Error: {e}")
                self.status_lbl.setStyleSheet("color: #ff7b72;")
        else:
            self.timer.stop()
            if self.serial: self.serial.close()
            self.serial = None
            self.btn.setText("Connect UDP Listener")
            self.btn.setStyleSheet("")
            self.status_lbl.setText("Disconnected")
            self.status_lbl.setStyleSheet("color: #8b949e;")

    def _clear(self):
        for l in self._rl: self.p1.removeItem(l)
        for l in self._f1l: self.p2.removeItem(l)
        for l in self._f2l: self.p3.removeItem(l)
        self._rl.clear(); self._f1l.clear(); self._f2l.clear()
        self.sc1.setData([], []); self.sc2.setData([], [])

    def _vline(self, plot, lst, pos, col, dash=False):
        ln = pg.InfiniteLine(pos=pos, angle=90, pen=pg.mkPen(color=col, width=1.5, 
                             style=Qt.PenStyle.DashLine if dash else Qt.PenStyle.SolidLine))
        plot.addItem(ln); lst.append(ln)

    # ── Safer atomic export for Windows ─────────────────────────────────────
    def _export_vitals(self, extra_metrics=None):
        if extra_metrics:
            self.state.update({
                "sdnn": extra_metrics.get("sdnn_ms"),
                "rmssd": extra_metrics.get("rmssd_ms"),
                "pnn50": extra_metrics.get("pnn50"),
                "reg": extra_metrics.get("rr_regularity"),
                "qrs": extra_metrics.get("qrs_ms"),
                "pr": extra_metrics.get("pr_ms"),
                "qtc": extra_metrics.get("qtc_ms"),
                "st": extra_metrics.get("st_offset"),
                "alerts": extra_metrics.get("alerts", []),
            })

        # Prepare waveform data for web (downsampled)
        ecg_arr = np.array(self.d_ecg1, dtype=float)
        apw1_arr = np.array(self.d_apw1, dtype=float)
        apw2_arr = np.array(self.d_apw2, dtype=float)
        flags_arr = np.array(self.d_flags, dtype=np.uint8)

        step = max(1, len(ecg_arr) // 180)
        self.state["wave_ecg"] = ecg_arr[::step].tolist()
        self.state["wave_apw1"] = apw1_arr[::step].tolist()
        self.state["wave_apw2"] = apw2_arr[::step].tolist()

        r_pos = np.where(flags_arr & FLAG_R_PEAK)[0]
        f1_pos = np.where(flags_arr & FLAG_APW1_FOOT)[0]
        f2_pos = np.where(flags_arr & FLAG_APW2_FOOT)[0]

        self.state["markers_r"] = (r_pos[::max(1, len(r_pos)//20)] / step).astype(int).tolist()
        self.state["markers_f1"] = (f1_pos[::max(1, len(f1_pos)//20)] / step).astype(int).tolist()
        self.state["markers_f2"] = (f2_pos[::max(1, len(f2_pos)//20)] / step).astype(int).tolist()

        data = {
            "ts": time.time(),
            "connected": self.serial is not None,
            **{k: v for k, v in self.state.items() if v is not None}
        }

        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', dir=os.getcwd()) as f:
                tmp = f.name
                json.dump(data, f, separators=(',', ':'))
            
            for attempt in range(5):
                try:
                    shutil.move(tmp, VITALS_FILE)
                    break
                except Exception:
                    if attempt == 4:
                        raise
                    time.sleep(0.05)
        except Exception as e:
            print(f"[export] write error: {e}")
            if tmp and os.path.exists(tmp):
                try: os.unlink(tmp)
                except: pass

    # ── Main tick ─────────────────────────────────────────────────────────────
    def _tick(self):
        if not self.serial: return
        
        has_new_data = False
        latest_v, latest_i, latest_p = 0.0, 0.0, 0.0

        while True:
            try:
                raw, addr = self.serial.recvfrom(1024)
                if not raw: break
                self.bytes_rx += len(raw)
                pkts = self.parser.feed(raw)
                self.pkts_rx += len(pkts)

                for ecg1_v, bz1_v, ecg2_v, bz2_v, flags, v_bus, i_ma, p_mw in pkts:
                    self._sample_count += 1
                    self.d_ecg1.append(ecg1_v)
                    self.d_apw1.append(float(bz1_v))
                    self.d_apw2.append(float(bz2_v))
                    self.d_flags.append(flags)
                    latest_v, latest_i, latest_p = v_bus, i_ma, p_mw
                    has_new_data = True
            except BlockingIOError: 
                break
            except Exception: 
                break

        if not has_new_data: return

        try:
            self._last_v, self._last_i, self._last_p = latest_v, latest_i, latest_p
            self.ina_lbl.setText(f"🔋 Battery: {latest_v:.2f} V | {latest_i:.1f} mA | {latest_p:.1f} mW")

            ecg1 = np.array(self.d_ecg1, dtype=float)
            apw1 = np.array(self.d_apw1, dtype=float)
            apw2 = np.array(self.d_apw2, dtype=float)
            flags_arr = np.array(self.d_flags, dtype=np.uint8)

            self.ce.setData(ecg1)
            self.c1.setData(apw1)
            self.c2.setData(apw2)
            self._clear()

            r_positions = np.where(flags_arr & FLAG_R_PEAK)[0]
            f1_positions = np.where(flags_arr & FLAG_APW1_FOOT)[0]
            f2_positions = np.where(flags_arr & FLAG_APW2_FOOT)[0]

            for pos in r_positions:
                vp = max(0, pos - VISUAL_SHIFT_ECG)
                self._vline(self.p1, self._rl, int(vp), '#39d353', dash=True)

            sc1_xs, sc1_ys, sc2_xs, sc2_ys = [], [], [], []
            for pos in f1_positions:
                vp = max(0, pos - VISUAL_SHIFT_APW1)
                self._vline(self.p2, self._f1l, int(vp), '#ff7b72')
                sc1_xs.append(int(vp)); sc1_ys.append(apw1[int(vp)])
            for pos in f2_positions:
                vp = max(0, pos - VISUAL_SHIFT_APW2)
                self._vline(self.p3, self._f2l, int(vp), '#ff7b72')
                sc2_xs.append(int(vp)); sc2_ys.append(apw2[int(vp)])

            self.sc1.setData(sc1_xs, sc1_ys)
            self.sc2.setData(sc2_xs, sc2_ys)

            if len(r_positions) >= 2:
                valid_rr = np.diff(r_positions)[np.diff(r_positions) > 0]
                if len(valid_rr) > 0:
                    hr = 60.0 / (np.mean(valid_rr) / FS)
                    self.state["hr"] = round(hr, 1)
                    self.lbl_hr['val'].setText(f"{self.state['hr']:.0f}")

            if len(f1_positions) > 0 and len(f2_positions) > 0:
                for f1p in f1_positions:
                    diffs = (f2_positions.astype(int) - int(f1p))
                    valid_diffs = diffs[diffs >= 0]
                    if len(valid_diffs) > 0:
                        ptt_val = valid_diffs[0] / FS * 1000.0
                        if 160 < ptt_val < 450: 
                            self.ptt_queue.append(ptt_val)

            if len(self.ptt_queue) > 0:
                ptt_mean = np.mean(self.ptt_queue)
                self.state["ptt"] = round(ptt_mean, 1)
                self.state["pwv"] = round(DISTANCE_M / (ptt_mean / 1000.0), 1)
                self.lbl_ptt['val'].setText(f"{self.state['ptt']:.1f}")
                self.lbl_pwv['val'].setText(f"{self.state['pwv']:.1f}")

                if self.bp_model is not None:
                    try:
                        X_pred = pd.DataFrame({'PTT':[ptt_mean], 'inv_PTT':[1.0/ptt_mean], 
                                               'inv_PTT2':[1.0/(ptt_mean**2)], 'ln_PTT':[np.log(ptt_mean)]})
                        bp = self.bp_model.predict(X_pred)[0]
                        self.state["bp"] = f"{bp[0]:.0f}/{bp[1]:.0f}"
                        self.lbl_bp['val'].setText(self.state["bp"])
                    except Exception: 
                        pass

            self.state["v_bus"] = round(latest_v, 3)
            self.state["i_ma"] = round(latest_i, 1)
            self.state["p_mw"] = round(latest_p, 1)

            self.debug_lbl.setText(f"Pkts: {self.pkts_rx} | Buffer: {len(ecg1)/FS:.1f}s")

            # Throttled export
            if time.time() - self.last_export_time > self.EXPORT_INTERVAL:
                self.last_export_time = time.time()
                self._export_vitals()

            # Morphology every 5 seconds
            if time.time() - self.last_analysis_time > 5.0:
                self.last_analysis_time = time.time()
                analyze_samples = int(FS * 10)
                if len(ecg1) >= analyze_samples:
                    recent_ecg = ecg1[-analyze_samples:]
                    metrics = self.ecg_proc.analyse(recent_ecg)
                    
                    def _s(val, prec=1): return f"{val:.{prec}f}" if val is not None else "—"
                    self.mini_metrics["SDNN"].setText(f"{_s(metrics.get('sdnn_ms'))} ms")
                    self.mini_metrics["RMSSD"].setText(f"{_s(metrics.get('rmssd_ms'))} ms")
                    self.mini_metrics["pNN50"].setText(f"{_s(metrics.get('pnn50'))} %")
                    self.mini_metrics["Reg"].setText(f"{metrics.get('rr_regularity') or '—'}")
                    self.mini_metrics["QRS"].setText(f"{_s(metrics.get('qrs_ms'))} ms")
                    self.mini_metrics["PR"].setText(f"{_s(metrics.get('pr_ms'))} ms")
                    self.mini_metrics["QTc"].setText(f"{_s(metrics.get('qtc_ms'))} ms")
                    self.mini_metrics["ST Off"].setText(f"{_s(metrics.get('st_offset'), 2)} n")

                    alts = metrics.get('alerts', [])
                    if len(alts) > 0:
                        self.alerts_lbl.setText(" | ".join(alts))
                        self.alerts_lbl.setStyleSheet("color: #ff7b72; font-weight: bold; font-size: 12px; margin-top: 5px;")
                    else:
                        self.alerts_lbl.setText("✓ No clinical flags detected.")
                        self.alerts_lbl.setStyleSheet("color: #39d353; font-weight: bold; font-size: 12px; margin-top: 5px;")

                    self._export_vitals(metrics)

        except Exception as e:
            print(f"[Python] tick error: {e}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = DualPTT()
    w.show()
    sys.exit(app.exec())
