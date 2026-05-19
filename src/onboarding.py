"""First-launch onboarding wizard for Bolo.

Four pages:
    1. Welcome    — what Bolo does, what hotkey
    2. Microphone — live volume meter, confirm mic works
    3. Language   — pick primary language
    4. Practice   — try the hotkey once, see transcribed text

Shown only when config.ONBOARDING_COMPLETED is False. Sets the flag on
"Get started" so it never re-appears (unless user manually resets).
"""
import math
import threading

import customtkinter as ctk

from . import config


# Reuse GUI colours for visual consistency
BG = config.CONTENT_BG
SB = config.SIDEBAR_BG
CRD = config.CARD_BG
ACC = config.ACCENT_COLOR
TXT = config.TEXT_PRIMARY
MUT = config.TEXT_MUTED
BDR = config.BORDER_COLOR
FONT = config.FONT_FAMILY


def _f(sz, w="normal"):
    return ctk.CTkFont(family=FONT, size=sz, weight=w)


class OnboardingWizard(ctk.CTkToplevel):
    """Modal first-run wizard. Parent is the main BildGUI window."""

    def __init__(self, parent, audio_engine):
        super().__init__(parent)
        self.parent = parent
        self.audio_engine = audio_engine
        self._volume_anim_running = False
        self._chosen_lang = config.DEFAULT_LANGUAGE

        self.title(f"Welcome to {config.APP_NAME}")
        self.geometry("560x440")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(parent)
        try:
            self.grab_set()
        except Exception:
            pass

        # Build pages
        self._pages = [
            self._build_welcome,
            self._build_mic,
            self._build_language,
            self._build_practice,
        ]
        self._page_idx = 0

        # Page container + nav bar
        self._page_container = ctk.CTkFrame(self, fg_color=BG)
        self._page_container.pack(fill="both", expand=True)

        nav = ctk.CTkFrame(self, fg_color=SB, height=56)
        nav.pack(fill="x", side="bottom")
        nav.pack_propagate(False)
        ctk.CTkFrame(nav, height=1, fg_color=BDR).pack(fill="x")

        self._step_label = ctk.CTkLabel(nav, text="", font=_f(10), text_color=MUT)
        self._step_label.pack(side="left", padx=20)

        self._next_btn = ctk.CTkButton(
            nav, text="Next  >", width=110, height=34,
            fg_color=ACC, hover_color="#CC2626", text_color="white",
            corner_radius=8, font=_f(12, "bold"),
            command=self._on_next,
        )
        self._next_btn.pack(side="right", padx=14, pady=10)

        self._back_btn = ctk.CTkButton(
            nav, text="<  Back", width=90, height=34,
            fg_color="transparent", hover_color=CRD, text_color=MUT,
            border_width=1, border_color=BDR,
            corner_radius=8, font=_f(12),
            command=self._on_back,
        )
        self._back_btn.pack(side="right", padx=(0, 4), pady=10)

        self._skip_btn = ctk.CTkButton(
            nav, text="Skip", width=70, height=34,
            fg_color="transparent", hover_color=CRD, text_color=MUT,
            corner_radius=8, font=_f(11),
            command=self._on_skip,
        )
        self._skip_btn.pack(side="right", padx=(0, 4), pady=10)

        self._show_page(0)
        self.protocol("WM_DELETE_WINDOW", self._on_skip)

    # ── Page navigation ────────────────────────────────────────────────────
    def _show_page(self, idx):
        # Stop any background polling from the previous page
        self._volume_anim_running = False

        for w in self._page_container.winfo_children():
            w.destroy()
        self._page_idx = idx
        self._pages[idx]()

        # Update step label + button text
        self._step_label.configure(text=f"Step {idx + 1} of {len(self._pages)}")
        self._back_btn.configure(state="normal" if idx > 0 else "disabled")
        self._next_btn.configure(text="Finish" if idx == len(self._pages) - 1 else "Next  >")

    def _on_next(self):
        if self._page_idx == len(self._pages) - 1:
            self._finish()
        else:
            self._show_page(self._page_idx + 1)

    def _on_back(self):
        if self._page_idx > 0:
            self._show_page(self._page_idx - 1)

    def _on_skip(self):
        # User dismissed wizard — mark complete so it doesn't reopen
        self._finish()

    def _finish(self):
        config.save_setting("ONBOARDING_COMPLETED", True)
        if self._chosen_lang and self._chosen_lang != config.DEFAULT_LANGUAGE:
            config.save_setting("DEFAULT_LANGUAGE", self._chosen_lang)
            # Notify main app so audio engine / tray update
            try:
                self.parent.update_ui_language(self._chosen_lang)
                self.parent.on_settings_change("language", self._chosen_lang)
            except Exception:
                pass
        self._volume_anim_running = False
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    # ── Page 1: Welcome ───────────────────────────────────────────────────
    def _build_welcome(self):
        f = ctk.CTkFrame(self._page_container, fg_color=BG)
        f.pack(fill="both", expand=True, padx=40, pady=(40, 20))

        ctk.CTkLabel(f, text=f"Welcome to {config.APP_NAME}",
                     font=_f(26, "bold"), text_color=ACC).pack(anchor="w")
        ctk.CTkLabel(f, text="Voice-to-text for India",
                     font=_f(12), text_color=MUT).pack(anchor="w", pady=(2, 24))

        body = (
            "Bolo lets you dictate text into any application — email, browser,\n"
            "code editor, chat — using your voice in 12 Indian languages plus\n"
            "Hinglish.\n\n"
            f"How it works:\n"
            f"   1.  Click into any text field\n"
            f"   2.  Hold the {config.ACTIVATION_KEY.upper()} key and speak\n"
            f"   3.  Release — your words appear where the cursor is\n\n"
            "No typing. No copy-paste. Just hold and speak."
        )
        ctk.CTkLabel(f, text=body, font=_f(13), text_color=TXT,
                     justify="left", anchor="w").pack(anchor="w")

    # ── Page 2: Microphone check ──────────────────────────────────────────
    def _build_mic(self):
        f = ctk.CTkFrame(self._page_container, fg_color=BG)
        f.pack(fill="both", expand=True, padx=40, pady=(40, 20))

        ctk.CTkLabel(f, text="Check your microphone",
                     font=_f(22, "bold"), text_color=TXT).pack(anchor="w")
        ctk.CTkLabel(f, text="Speak now — you should see the bar move.",
                     font=_f(12), text_color=MUT).pack(anchor="w", pady=(2, 24))

        # Live volume bar (canvas)
        self._vol_canvas = ctk.CTkCanvas(f, width=460, height=40,
                                         bg=BG, highlightthickness=0)
        self._vol_canvas.pack(pady=(8, 16))

        self._mic_hint = ctk.CTkLabel(f, text="Waiting for input...",
                                      font=_f(11), text_color=MUT)
        self._mic_hint.pack(anchor="w")

        self._volume_anim_running = True
        self._animate_volume()

    def _animate_volume(self):
        """Pulled from audio_engine.current_volume; refreshed at ~30 Hz."""
        if not self._volume_anim_running:
            return
        try:
            vol = float(getattr(self.audio_engine, "current_volume", 0))
            # Normalize: typical speech RMS ~500-3000
            norm = min(1.0, vol / 3000.0)
            c = self._vol_canvas
            c.delete("all")
            w, h = 460, 40
            # Background
            c.create_rectangle(0, h // 2 - 6, w, h // 2 + 6,
                               fill=CRD, outline="")
            # Filled portion
            fill_w = int(w * norm)
            c.create_rectangle(0, h // 2 - 6, fill_w, h // 2 + 6,
                               fill=ACC, outline="")
            # Update hint
            if norm > 0.05:
                self._mic_hint.configure(
                    text=f"Good signal detected ({int(norm * 100)}%)",
                    text_color=config.SUCCESS_COLOR,
                )
            else:
                self._mic_hint.configure(
                    text="No signal — try speaking louder or check mic permissions.",
                    text_color=MUT,
                )
        except Exception:
            pass
        if self._volume_anim_running:
            self.after(33, self._animate_volume)

    # ── Page 3: Language ──────────────────────────────────────────────────
    def _build_language(self):
        f = ctk.CTkFrame(self._page_container, fg_color=BG)
        f.pack(fill="both", expand=True, padx=40, pady=(40, 20))

        ctk.CTkLabel(f, text="Pick your main language",
                     font=_f(22, "bold"), text_color=TXT).pack(anchor="w")
        ctk.CTkLabel(f, text="You can switch any time from the dashboard or system tray.",
                     font=_f(12), text_color=MUT).pack(anchor="w", pady=(2, 24))

        self._lang_var = ctk.StringVar(value=self._lang_label_for(self._chosen_lang))
        opts = list(config.SUPPORTED_LANGUAGES.keys())
        menu = ctk.CTkOptionMenu(
            f, values=opts, variable=self._lang_var,
            fg_color=CRD, button_color=ACC, button_hover_color="#CC2626",
            dropdown_fg_color=SB, dropdown_text_color=TXT,
            text_color=TXT, corner_radius=8, font=_f(13),
            dropdown_font=_f(12), width=280, height=38,
            command=self._on_lang_pick,
        )
        menu.pack(anchor="w", pady=(8, 4))

        ctk.CTkLabel(f, text="Hinglish is recommended for Hindi+English mix.",
                     font=_f(10), text_color=MUT).pack(anchor="w", pady=(12, 0))

    def _lang_label_for(self, code):
        for label, c in config.SUPPORTED_LANGUAGES.items():
            if c == code:
                return label
        return next(iter(config.SUPPORTED_LANGUAGES.keys()))

    def _on_lang_pick(self, label):
        self._chosen_lang = config.SUPPORTED_LANGUAGES.get(label, self._chosen_lang)

    # ── Page 4: Practice ──────────────────────────────────────────────────
    def _build_practice(self):
        f = ctk.CTkFrame(self._page_container, fg_color=BG)
        f.pack(fill="both", expand=True, padx=40, pady=(40, 20))

        ctk.CTkLabel(f, text="Try it out",
                     font=_f(22, "bold"), text_color=TXT).pack(anchor="w")
        ctk.CTkLabel(
            f,
            text=(f"Hold {config.ACTIVATION_KEY.upper()}, say a short sentence,\n"
                  f"then release. The text appears below."),
            font=_f(12), text_color=MUT, justify="left",
        ).pack(anchor="w", pady=(2, 16))

        # Hint card
        card = ctk.CTkFrame(f, fg_color=CRD, corner_radius=10,
                            border_width=1, border_color=BDR)
        card.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(card, text="Suggested phrase to dictate:",
                     font=_f(10), text_color=MUT, anchor="w").pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(card, text="\"Aaj ka mausam kaisa hai\"",
                     font=_f(14, "bold"), text_color=ACC, anchor="w").pack(anchor="w", padx=14, pady=(0, 10))

        ctk.CTkLabel(f, text="When ready, click Finish below.",
                     font=_f(11), text_color=MUT).pack(anchor="w", pady=(16, 0))


def maybe_show(parent_gui, audio_engine):
    """Open the wizard on first launch. No-op if already completed."""
    if config.ONBOARDING_COMPLETED:
        return None
    return OnboardingWizard(parent_gui, audio_engine)
