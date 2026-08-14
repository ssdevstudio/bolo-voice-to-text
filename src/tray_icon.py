import math
import threading
import tkinter as tk
from typing import Any, Callable, Optional

import pystray
from PIL import Image, ImageDraw

from . import config


class TrayIcon:
    def __init__(self, on_exit: Callable[..., None], on_lang_change: Callable[..., None]) -> None:
        self.on_exit = on_exit
        self.on_lang_change = on_lang_change
        self.on_show_gui = None
        self.on_reconnect = None
        self.current_lang_label = "English (India)"
        for label, code in config.SUPPORTED_LANGUAGES.items():
            if code == config.DEFAULT_LANGUAGE:
                self.current_lang_label = label
                break
        self.icon = None
        self._status_visible = False
        self._status_window = None
        self._tk_root = None
        self._lock = threading.Lock()
        self.smoothed_vol = 0.0
        self.time_step = 0.0
        self.volume_provider = None
        self._tk_thread = None
        self._update_scheduled = False

    def create_icon_image(self, color: str) -> Any:
        image = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        dc.rectangle((27, 8, 37, 56), fill=color)
        dc.rectangle((14, 20, 24, 44), fill=color)
        dc.rectangle((40, 20, 50, 44), fill=color)
        dc.rectangle((1, 28, 11, 36), fill=color)
        dc.rectangle((53, 28, 63, 36), fill=color)
        return image

    def _setup_menu(self) -> Any:
        lang_menu = []
        for label, code in config.SUPPORTED_LANGUAGES.items():
            lang_menu.append(pystray.MenuItem(
                label,
                self._make_lang_setter(label, code),
                checked=lambda item, it=label: self.current_lang_label == it
            ))

        return pystray.Menu(
            pystray.MenuItem("Dashboard", self._on_dashboard_clicked, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Language", pystray.Menu(*lang_menu)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Reconnect Mic", self._on_reconnect_clicked),
            pystray.MenuItem("Exit", self._on_exit_clicked)
        )

    def _on_dashboard_clicked(self, icon: Any, item: Any) -> None:
        if self.on_show_gui:
            self.on_show_gui()

    def _on_reconnect_clicked(self, icon: Any, item: Any) -> None:
        if self.on_reconnect:
            success = self.on_reconnect()
            if success:
                print("[Tray] Mic reconnected successfully")
            else:
                print("[Tray] Mic reconnection failed")

    def _make_lang_setter(self, label: str, code: str) -> Callable[[Any, Any], None]:
        def set_lang(icon: Any, item: Any) -> None:
            self.current_lang_label = label
            self.on_lang_change(code)
        return set_lang

    def _on_exit_clicked(self, icon: Any, item: Any) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
        try:
            self.on_exit()
        except Exception as e:
            print(f"Exit error: {e}")

    def run(self) -> None:
        self.icon = pystray.Icon(
            config.APP_NAME,
            self.create_icon_image(config.ACCENT_COLOR),
            menu=self._setup_menu()
        )
        self._tk_thread = threading.Thread(target=self._run_tk, daemon=True)
        self._tk_thread.start()
        self.icon.run()

    def _run_tk(self) -> None:
        try:
            self._tk_root = tk.Tk()
            self._tk_root.withdraw()
            self._tk_root.overrideredirect(True)
            self._tk_root.attributes("-topmost", True)
            self._tk_root.attributes("-alpha", 1.0)
            transparent_color = "#1a1a1a"
            self._tk_root.configure(bg=transparent_color)
            self._tk_root.attributes("-transparentcolor", transparent_color)
            self._canvas = tk.Canvas(
                self._tk_root,
                width=200, height=60,
                bg=transparent_color, highlightthickness=0
            )
            self._canvas.pack(padx=10, pady=5)
            screen_width = self._tk_root.winfo_screenwidth()
            screen_height = self._tk_root.winfo_screenheight()
            window_width = 220
            window_height = 70
            x = (screen_width // 2) - (window_width // 2)
            y = screen_height - 150
            self._tk_root.geometry(f"{window_width}x{window_height}+{x}+{y}")
            self._update_scheduled = True
            self._update_waveform()
            self._tk_root.mainloop()
        except Exception as e:
            print(f"Tray icon error: {e}")

    def _update_waveform(self) -> None:
        try:
            if self._tk_root and self._status_visible:
                self._canvas.delete("all")
                vol = 0
                if self.volume_provider:
                    vol = getattr(self.volume_provider, 'current_volume', 0)
                target_vol = min(1.0, vol / 3000.0)
                self.smoothed_vol += (target_vol - self.smoothed_vol) * 0.3
                self.time_step += 0.2
                num_bars = 15
                w = 200
                h = 60
                bar_w = 4
                gap = 6
                total_w = num_bars * bar_w + (num_bars - 1) * gap
                start_x = (w - total_w) / 2
                for i in range(num_bars):
                    dist = abs(i - num_bars / 2) / (num_bars / 2)
                    bell = max(0, 1.0 - dist * dist)
                    idle_ripple = math.sin(self.time_step + i * 0.5) * 0.15 + 0.15
                    bar_scale = (self.smoothed_vol * 0.8 + idle_ripple) * bell
                    bar_h = max(4, h * bar_scale)
                    x = start_x + i * (bar_w + gap) + (bar_w / 2)
                    y0 = (h - bar_h) / 2
                    y1 = y0 + bar_h
                    self._canvas.create_line(x, y0, x, y1, width=bar_w, capstyle=tk.ROUND, fill=config.RECORDING_COLOR)
            if self._tk_root and self._update_scheduled:
                self._tk_root.after(30, self._update_waveform)
        except Exception:
            if self._tk_root:
                try:
                    self._tk_root.after(30, self._update_waveform)
                except RuntimeError:
                    pass

    def show_status(self, text: str, color: Optional[str] = None) -> None:
        with self._lock:
            self._status_visible = True
            if self._tk_root:
                self._tk_root.after(0, self._tk_root.deiconify)

    def hide_status(self) -> None:
        with self._lock:
            self._status_visible = False
            if self._tk_root:
                self._tk_root.after(0, self._tk_root.withdraw)

    def set_icon_state(self, recording: bool = False) -> None:
        color = config.RECORDING_COLOR if recording else config.ACCENT_COLOR
        if self.icon:
            self.icon.icon = self.create_icon_image(color)

    def update_language_state(self, lang_code: str) -> None:
        with self._lock:
            for label, code in config.SUPPORTED_LANGUAGES.items():
                if code == lang_code:
                    self.current_lang_label = label
                    if self.icon:
                        try:
                            self.icon.menu = self._setup_menu()
                        except Exception:
                            pass
                    break
