"""Metrics bridge — routes ResourceMonitor samples to the main window's status
strip and (when open) the Developer Panel's Diagnostics widgets.

Part of the Phase 6 MainWindow decomposition (plan §9).  This is a plain
``QObject`` controller that holds a back-reference to the owning
:class:`~speakeasy.main_window.MainWindow` and reaches into its widgets; it owns
no UI of its own.  It must not import the ML stack at module scope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Slot

from .._build_variant import VARIANT

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..main_window import MainWindow


class MetricsBridge(QObject):
    """Apply resource-monitor samples to the main window and Developer Panel."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__(main_window)
        self._mw = main_window

    @Slot(object)
    def on_metrics_result(self, metrics) -> None:
        from ..theme import Color as TC

        mw = self._mw

        def _bar_color(pct: float) -> str:
            if pct > 90:
                return TC.DANGER
            if pct > 75:
                return TC.WARNING
            return TC.PRIMARY

        def _bar_style(pct: float) -> str:
            c = _bar_color(pct)
            return (
                f"QProgressBar {{ border: 1px solid {TC.BORDER}; border-radius: 3px; background: {TC.INPUT_BG}; }}"
                f"QProgressBar::chunk {{ background-color: {c}; border-radius: 3px; }}"
            )

        if metrics.ram_total_gb > 0:
            mw._lbl_ram.setText(
                f"RAM: {metrics.ram_used_gb:.1f} / {metrics.ram_total_gb:.1f} GB "
                f"({metrics.ram_percent:.0f}%)"
            )
            mw._pb_ram.setValue(int(metrics.ram_percent))
            mw._pb_ram.setStyleSheet(_bar_style(metrics.ram_percent))
        else:
            mw._lbl_ram.setText("RAM: —")
            mw._pb_ram.setValue(0)

        gpu = metrics.gpu
        if VARIANT != "cpu" and gpu.vram_total_gb > 0:
            pct = gpu.vram_percent
            vram_text_color = _bar_color(pct)
            mw._lbl_vram.setText(
                f'VRAM: <span style="color:{vram_text_color}"><b>{gpu.vram_used_gb:.1f}</b></span>'
                f" / {gpu.vram_total_gb:.1f} GB ({pct:.0f}%)"
            )
            mw._pb_vram.setValue(int(pct))
            mw._pb_vram.setStyleSheet(_bar_style(pct))
            mw._lbl_gpu_info.setText(f"GPU: {gpu.name} ({gpu.temperature_c}°C)")
        else:
            mw._lbl_vram.setText("VRAM: —")
            mw._pb_vram.setValue(0)
            mw._lbl_gpu_info.setText("GPU: —")

        # Forward to Developer Panel
        if mw._dev_panel is not None:
            rw = mw._dev_panel.realtime_widget
            rw.update_ram(metrics.ram_used_gb, metrics.ram_total_gb, metrics.ram_percent)
            gpu = metrics.gpu
            if VARIANT != "cpu" and gpu.vram_total_gb > 0:
                rw.update_vram(gpu.vram_used_gb, gpu.vram_total_gb, gpu.vram_percent)
                rw.update_gpu(f"{gpu.name} ({gpu.temperature_c}°C)")
            else:
                rw.update_vram(0, 0, 0)
                rw.update_gpu("—")
            # Forward LLM token stats so the sparkline updates continuously
            if mw._text_processor is not None:
                tps, ti, to, llm_seq = mw._text_processor.token_stats
            else:
                tps, ti, to, llm_seq = 0.0, 0, 0, 0
            rw.update_tokens(tps, ti, to, seq=llm_seq)
            # Forward speech-engine token stats
            asr_stats = mw._service.stats()
            rw.update_asr_tokens(
                asr_stats.tokens_per_second,
                asr_stats.total_tokens,
                asr_stats.total_audio_seconds,
                asr_stats.realtime_factor,
                seq=asr_stats.inference_count,
            )
