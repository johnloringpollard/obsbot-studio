"""Local software effects controls and settings persistence."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QStandardPaths
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSlider,
    QPushButton, QFileDialog, QColorDialog,
)
from PySide6.QtGui import QColor

from .effects import EffectSettings


class EffectsPanel(QWidget):
    changed = Signal(object)

    def __init__(self, parent=None, settings_path=None):
        super().__init__(parent)
        self.settings_path = settings_path or Path(QStandardPaths.writableLocation(QStandardPaths.GenericConfigLocation)) / "obsbot-studio" / "effects.json"
        self.settings = EffectSettings()
        load_error = ""
        try:
            self.settings = EffectSettings.from_dict(json.loads(self.settings_path.read_text()))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as exc:
            load_error = f"Saved effects could not be loaded: {exc}"
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._emit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 14, 16)
        note = QLabel("Effects output 720p · 30 fps; camera settings still affect the physical camera. Other apps need a virtual camera. Slow motion is unavailable with effects.")
        note.setWordWrap(True)
        note.setObjectName("reason")
        layout.addWidget(note)
        self.background = self._combo(layout, "Background", "background", ["off", "blur", "image", "color"])
        self.blur = self._slider(layout, "Blur strength", "blur", 0, 100)
        self.background_image = QPushButton("Choose background image…")
        self.background_image.clicked.connect(self._background_image)
        layout.addWidget(self.background_image)
        self.background_color = QPushButton("Choose background color…")
        self.background_color.clicked.connect(self._background_color)
        layout.addWidget(self.background_color)
        self.gamma = self._slider(layout, "Gamma", "gamma", 50, 200, 100)
        self.filter = self._combo(layout, "Color filter", "filter", ["original", "mono", "warm", "cool"])
        overlay = QHBoxLayout()
        self.overlay = QPushButton("Choose PNG overlay…")
        self.overlay.clicked.connect(self._overlay)
        overlay.addWidget(self.overlay)
        self.clear_overlay = QPushButton("Remove overlay")
        self.clear_overlay.clicked.connect(lambda: self._update(overlay_path=""))
        overlay.addWidget(self.clear_overlay)
        layout.addLayout(overlay)
        self.overlay_opacity = self._slider(layout, "Overlay opacity", "overlay_opacity", 0, 100)
        self.overlay_scale = self._slider(layout, "Overlay size", "overlay_scale", 5, 100)
        self.paths = QLabel()
        self.paths.setWordWrap(True)
        self.paths.setObjectName("reason")
        layout.addWidget(self.paths)
        self.reset = QPushButton("Reset effects")
        self.reset.clicked.connect(self._reset)
        layout.addWidget(self.reset)
        self.message = QLabel(load_error)
        self.message.setWordWrap(True)
        self.message.setObjectName("reason")
        layout.addWidget(self.message)
        layout.addStretch()
        self._refresh()

    def _combo(self, layout, title, field, values):
        layout.addWidget(QLabel(title))
        widget = QComboBox()
        widget.setObjectName(f"effect_{field}")
        for value in values:
            widget.addItem(value.capitalize(), value)
        widget.setCurrentIndex(widget.findData(getattr(self.settings, field)))
        widget.currentIndexChanged.connect(lambda: self._update(**{field: widget.currentData()}))
        layout.addWidget(widget)
        return widget

    def _slider(self, layout, title, field, minimum, maximum, divisor=1):
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        value = QLabel()
        value.setMinimumWidth(42)
        value.setAlignment(Qt.AlignRight)
        row.addWidget(value)
        layout.addLayout(row)
        widget = QSlider(Qt.Horizontal)
        widget.setObjectName(f"effect_{field}")
        widget.setRange(minimum, maximum)
        widget.setValue(round(getattr(self.settings, field) * divisor))
        def update_label(number):
            value.setText(f"{number / divisor:.2f}" if divisor != 1 else str(number))
        update_label(widget.value())
        widget.valueChanged.connect(update_label)
        widget.valueChanged.connect(lambda number: self._update(**{field: number / divisor if divisor != 1 else number}))
        layout.addWidget(widget)
        return widget

    def _update(self, **values):
        if not self.isEnabled():
            return
        if values.get("background") == "image" and not values.get("background_path", self.settings.background_path):
            self._background_image()
            self._refresh()
            return
        self.settings = replace(self.settings, **values)
        self._refresh()
        self.timer.start()

    def _refresh(self):
        self.background.blockSignals(True)
        self.background.setCurrentIndex(self.background.findData(self.settings.background))
        self.background.blockSignals(False)
        self.blur.setEnabled(self.settings.background == "blur")
        self.clear_overlay.setEnabled(bool(self.settings.overlay_path))
        self.paths.setText("\n".join(value for value in (
            f"Background: {Path(self.settings.background_path).name}" if self.settings.background_path else "",
            f"Color: {self.settings.background_color}" if self.settings.background == "color" else "",
            f"Overlay: {Path(self.settings.overlay_path).name}" if self.settings.overlay_path else "",
        ) if value))

    def _emit(self):
        if not self.isEnabled():
            return
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(self.settings), indent=2) + "\n")
            temporary.replace(self.settings_path)
            self.message.clear()
        except OSError as exc:
            self.message.setText(f"Effects work for this session but could not be saved: {exc}")
        self.changed.emit(self.settings)

    def flush(self):
        if self.timer.isActive():
            self.timer.stop()
            self._emit()

    def _background_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Background image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._update(background="image", background_path=path)

    def _background_color(self):
        color = QColorDialog.getColor(QColor(self.settings.background_color), self, "Background color")
        if color.isValid():
            self._update(background="color", background_color=color.name())

    def _overlay(self):
        path, _ = QFileDialog.getOpenFileName(self, "PNG overlay", "", "PNG images (*.png)")
        if path:
            self._update(overlay_path=path)

    def _reset(self):
        if not self.isEnabled():
            return
        self.settings = EffectSettings()
        for field, divisor in (("blur", 1), ("gamma", 100), ("overlay_opacity", 1), ("overlay_scale", 1)):
            widget = getattr(self, field)
            widget.setValue(round(getattr(self.settings, field) * divisor))
        self.filter.setCurrentIndex(self.filter.findData(self.settings.filter))
        self._refresh()
        self.timer.start()
