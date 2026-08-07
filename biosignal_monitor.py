"""
biosignal_monitor.py — MI/EMG training visualizer, styled like a real
clinical biosignal monitor (scrolling traces, grid, threshold line, trigger
light) so you can see what "rest" vs. a real detected event actually looks
like before ever putting the real hardware on.

Standalone, doesn't touch aispe.py. Runs on the SAME detector logic
(mi_detector.py / emg_detector.py) as the real app — this is watching the
real decision-making, not a separate simplified demo.

Currently synthetic data only (real hardware isn't connected yet). Once it
arrives, only the data source swaps out — the display and detection logic
stay as-is.

Controls: M = show MI channels, E = show EMG channels, Esc = quit.

Run: python biosignal_monitor.py
Needs: pip install PyQt6
"""

import sys
from collections import deque
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath, QFont

from mi_detector import MIDetector, MI_LATERALIZATION_DELTA
from emg_detector import EMGDetector, EMG_TRIGGER_MULTIPLIER
from real_hardware_source import RealEEGSource, RealEMGSource

BUFFER_LEN = 220          # points shown across the screen width (~11 sec at 50ms/sample)
SAMPLE_INTERVAL_MS = 50   # ~20 samples/sec, matching the detectors' own pacing

# Classic monitor palette
COLOR_BG = QColor(5, 8, 5)
COLOR_GRID = QColor(25, 35, 25)
COLOR_TRACE_A = QColor(0, 255, 90)     # green — primary trace (C3 / raw EMG)
COLOR_TRACE_B = QColor(255, 176, 0)    # amber — secondary trace (C4 / envelope)
COLOR_TRACE_C = QColor(0, 220, 255)    # cyan — derived value (lateralization index)
COLOR_THRESHOLD = QColor(255, 60, 60)
COLOR_TEXT = QColor(180, 255, 180)
COLOR_TRIGGER_IDLE = QColor(0, 120, 40)
COLOR_TRIGGER_FLASH = QColor(255, 30, 30)


class ScopeWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: black;")
        self.mode = "MI"

        # --- MI data ---
        self.mi_source = RealEEGSource()
        self.mi_detector = MIDetector()
        self.c3_buf = deque(maxlen=BUFFER_LEN)
        self.c4_buf = deque(maxlen=BUFFER_LEN)
        self.mi_index_buf = deque(maxlen=BUFFER_LEN)

        # --- EMG data ---
        self.emg_source = RealEMGSource()
        self.emg_detector = EMGDetector()
        self.emg_raw_buf = deque(maxlen=BUFFER_LEN)
        self.emg_env_buf = deque(maxlen=BUFFER_LEN)

        self.trigger_flash_ticks = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(SAMPLE_INTERVAL_MS)

        self.font = QFont("Consolas", 11)

    def _tick(self):
        # Both detectors keep running regardless of which view is showing,
        # so switching views doesn't lose data or reset calibration.
        c3, c4, _ = self.mi_source.next_sample()
        mi_triggered = self.mi_detector.update(c3, c4)
        self.c3_buf.append(c3)
        self.c4_buf.append(c4)
        self.mi_index_buf.append((c4 - c3) / (c4 + c3 + 1e-9))

        raw, _ = self.emg_source.next_sample()
        emg_triggered = self.emg_detector.update(raw)
        self.emg_raw_buf.append(raw)
        self.emg_env_buf.append(self.emg_detector.envelope or 0.0)

        active_triggered = mi_triggered if self.mode == "MI" else emg_triggered
        if active_triggered:
            self.trigger_flash_ticks = 6  # stay flashed for ~300ms
        elif self.trigger_flash_ticks > 0:
            self.trigger_flash_ticks -= 1

        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font)
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, COLOR_BG)

        grid_pen = QPen(COLOR_GRID)
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for x in range(0, w, 40):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, 40):
            painter.drawLine(0, y, w, y)

        if self.mode == "MI":
            self._paint_mi(painter, w, h)
        else:
            self._paint_emg(painter, w, h)

        self._draw_trigger_light(painter, w)
        self._draw_controls_hint(painter, w, h)

    def _draw_controls_hint(self, painter, w, h):
        dim_text = QColor(90, 130, 90)
        painter.setPen(QPen(dim_text))
        painter.drawText(10, h - 10, "type M for MI view   E for EMG view   ESC to quit")

    def _draw_trace(self, painter, buf, color, y_center, y_scale, w, width_px=2):
        if len(buf) < 2:
            return
        pen = QPen(color)
        pen.setWidth(width_px)
        painter.setPen(pen)
        path = QPainterPath()
        step = w / BUFFER_LEN
        offset = BUFFER_LEN - len(buf)
        for i, val in enumerate(buf):
            x = (offset + i) * step
            y = y_center - val * y_scale
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)

    def _draw_dashed_hline(self, painter, y, w):
        pen = QPen(COLOR_THRESHOLD)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(0, int(y), w, int(y))

    def _draw_trigger_light(self, painter, w):
        color = COLOR_TRIGGER_FLASH if self.trigger_flash_ticks > 0 else COLOR_TRIGGER_IDLE
        painter.setPen(QPen(color))
        painter.setBrush(color)
        painter.drawEllipse(w - 46, 14, 22, 22)
        painter.setPen(QPen(COLOR_TEXT))
        painter.drawText(w - 130, 46, "TRIGGER")

    def _paint_mi(self, painter, w, h):
        top_center = h * 0.28
        top_scale = 1.4
        self._draw_trace(painter, self.c3_buf, COLOR_TRACE_A, top_center, top_scale, w)
        self._draw_trace(painter, self.c4_buf, COLOR_TRACE_B, top_center, top_scale, w)

        bottom_center = h * 0.72
        bottom_scale = h * 1.6
        self._draw_trace(painter, self.mi_index_buf, COLOR_TRACE_C, bottom_center, bottom_scale, w, width_px=2)

        baseline = self.mi_detector.baseline_index or 0.0
        threshold_y = bottom_center - (baseline + MI_LATERALIZATION_DELTA) * bottom_scale
        self._draw_dashed_hline(painter, threshold_y, w)

        status = "connected" if self.mi_source.is_connected else "NOT DETECTED — no headband connected"
        painter.setPen(QPen(COLOR_TEXT))
        painter.drawText(10, 24, f"aispe biosignal monitor — MI (C3 / C4) — {status}")
        painter.setPen(QPen(COLOR_TRACE_A))
        painter.drawText(10, int(top_center - 60), "C3")
        painter.setPen(QPen(COLOR_TRACE_B))
        painter.drawText(10, int(top_center - 40), "C4")
        painter.setPen(QPen(COLOR_TRACE_C))
        painter.drawText(10, int(bottom_center - 60), "Lateralization Index")

        cur = self.mi_index_buf[-1] if self.mi_index_buf else 0.0
        painter.setPen(QPen(COLOR_TEXT))
        painter.drawText(10, h - 32,
                          f"Index: {cur:+.3f}   Baseline: {baseline:+.3f}   "
                          f"Threshold: {baseline + MI_LATERALIZATION_DELTA:+.3f}")

    def _paint_emg(self, painter, w, h):
        center = h * 0.5
        scale = 1.6
        self._draw_trace(painter, self.emg_raw_buf, COLOR_TRACE_A, center, scale, w, width_px=1)
        self._draw_trace(painter, self.emg_env_buf, COLOR_TRACE_B, center, scale, w, width_px=2)

        baseline = self.emg_detector.baseline_envelope or 0.0
        threshold_y = center - (baseline * EMG_TRIGGER_MULTIPLIER) * scale
        self._draw_dashed_hline(painter, threshold_y, w)

        status = "connected" if self.emg_source.is_connected else "NOT DETECTED — no headband connected"
        painter.setPen(QPen(COLOR_TEXT))
        painter.drawText(10, 24, f"aispe biosignal monitor — EMG — {status}")
        painter.setPen(QPen(COLOR_TRACE_A))
        painter.drawText(10, int(center - 80), "EMG Raw (µV)")
        painter.setPen(QPen(COLOR_TRACE_B))
        painter.drawText(10, int(center - 60), "EMG Envelope")

        cur_env = self.emg_detector.envelope or 0.0
        painter.setPen(QPen(COLOR_TEXT))
        painter.drawText(10, h - 32,
                          f"Envelope: {cur_env:5.1f}µV   Baseline: {baseline:5.1f}µV   "
                          f"Threshold: {baseline * EMG_TRIGGER_MULTIPLIER:5.1f}µV")


class MonitorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("aispe biosignal monitor")
        self.resize(1000, 640)
        self.scope = ScopeWidget()
        self.setCentralWidget(self.scope)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_M:
            self.scope.set_mode("MI")
        elif event.key() == Qt.Key.Key_E:
            self.scope.set_mode("EMG")
        else:
            super().keyPressEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MonitorWindow()
    window.show()
    sys.exit(app.exec())
