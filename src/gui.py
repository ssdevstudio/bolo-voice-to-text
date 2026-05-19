import customtkinter as ctk
import math
import os
import tkinter.messagebox as messagebox
import pyperclip
from PIL import Image, ImageDraw
from . import config
from .utils import set_run_on_startup, is_run_on_startup
from .audio_engine import is_whisper_model_downloaded

# Colors & Fonts synced with config.py
BG = config.CONTENT_BG
SB = config.SIDEBAR_BG
CRD = config.CARD_BG
CRD2 = config.SURFACE_BG
BDR = config.BORDER_COLOR
ACC = config.ACCENT_COLOR
ACC2 = "#CC2626" # Hover color
SUCCESS = config.SUCCESS_COLOR
ERROR = config.ERROR_COLOR
TXT = config.TEXT_PRIMARY
MUT = config.TEXT_MUTED
DIM = config.TEXT_MUTED # Legacy support
FONT = config.FONT_FAMILY

def _f(sz, w="normal"): return ctk.CTkFont(family=FONT, size=sz, weight=w)

def create_default_icon():
    p = os.path.join(os.path.dirname(__file__), "icon.ico")
    img = Image.new("RGBA",(256,256),(0,0,0,0)); d = ImageDraw.Draw(img)
    for r in [(108,32,148,224),(56,80,96,176),(160,80,200,176),(4,112,44,144),(212,112,252,144)]:
        d.rectangle(r, fill=ACC)
    img.save(p, format="ICO"); return p

class PulseDot(ctk.CTkCanvas):
    def __init__(self, p, size=10, color=ACC, bg=BG, **kw):
        super().__init__(p, width=size, height=size, highlightthickness=0, bg=bg, **kw)
        self.sz=size; self.col=color; self._on=False; self._s=0; self._idle()
    def _idle(self):
        self.delete("all"); r=self.sz//2; c=self.sz//2
        self.create_oval(c-r,c-r,c+r,c+r, fill=MUT, outline="")
    def start_pulse(self): self._on=True; self._run()
    def stop_pulse(self): self._on=False; self._idle()
    def _run(self):
        if not self._on: return
        self._s+=0.18; p=math.sin(self._s)*0.4+0.6
        r=int((self.sz//2)*p); c=self.sz//2; self.delete("all")
        self.create_oval(c-r-3,c-r-3,c+r+3,c+r+3, fill="#2a080c", outline="")
        self.create_oval(c-r,c-r,c+r,c+r, fill=self.col, outline="")
        self.after(30, self._run)

class MicOrb(ctk.CTkCanvas):
    def __init__(self, p, size=148, **kw):
        kw.pop("bg", None)
        super().__init__(p, width=size, height=size, highlightthickness=0, bg=BG, **kw)
        self.sz=size; self._on=False; self._proc=False; self._s=0.0; self._draw()
    def _draw(self):
        self.delete("all"); c=self.sz//2; R=52
        if self._on:
            p=math.sin(self._s)*0.5+0.5
            for rr,col in [(R+22+int(p*8),"#280810"),(R+14+int(p*5),"#4a1020"),(R+7+int(p*3),"#7a1828")]:
                self.create_oval(c-rr,c-rr,c+rr,c+rr, fill=col, outline="")
            self.create_oval(c-R,c-R,c+R,c+R, fill=ACC, outline="")
        elif self._proc:
            # Thinking / Processing animation (rotating ring)
            self._s += 0.15
            self.create_oval(c-R,c-R,c+R,c+R, fill="#1a1400", outline=MUT, width=1)
            # Draw rotating arc
            angle = (self._s * 50) % 360
            self.create_arc(c-R, c-R, c+R, c+R, start=angle, extent=60, outline=ACC, width=3, style="arc")
            self.create_arc(c-R, c-R, c+R, c+R, start=angle+180, extent=60, outline=ACC, width=3, style="arc")
        else:
            self.create_oval(c-R-1,c-R-1,c+R+1,c+R+1, fill=CRD2, outline="")
            self.create_oval(c-R,c-R,c+R,c+R, fill=CRD, outline=BDR, width=2)
        col = ACC if self._on else (ACC if self._proc else MUT)
        mt=c-16; mb=c+10; mc=c
        self.create_rectangle(mc-7,mt,mc+7,mb, fill=col, outline="", width=0)
        self.create_arc(mc-8,mb-3,mc+8,mb+11, start=0,extent=-180, style="arc", outline=col, width=3)
        self.create_line(mc,mb+8,mc,mb+17, fill=col, width=3)
        self.create_line(mc-9,mb+17,mc+9,mb+17, fill=col, width=3)
    def start(self): self._on=True; self._proc=False; self._anim()
    def stop(self): self._on=False; self._proc=False; self._draw()
    def processing(self): self._on=False; self._proc=True; self._proc_anim()
    def _proc_anim(self):
        if not self._proc: return
        self._draw(); self.after(30, self._proc_anim)
    def _anim(self):
        if not self._on: return
        self._s+=0.10; self._draw(); self.after(30, self._anim)

class WaveformCanvas(ctk.CTkCanvas):
    def __init__(self, p, **kw):
        super().__init__(p, highlightthickness=0, **kw)
        self.n=24; self._on=False; self.t=0.0; self.color=ACC
    def start(self): self._on=True; self._anim()
    def stop(self): self._on=False; self.delete("all")
    def _anim(self):
        if not self._on: return
        self.delete("all"); W=self.winfo_width() or 300; H=self.winfo_height() or 40
        self.t+=0.16; bw=4; gap=3; tot=self.n*(bw+gap)-gap; sx=(W-tot)/2
        for i in range(self.n):
            d=abs(i-self.n/2)/(self.n/2); bell=max(0,1-d*d)
            rip=math.sin(self.t+i*0.42)*0.4+0.6
            bh=max(2,(H-6)*rip*bell); x=sx+i*(bw+gap)+bw/2; y0=(H-bh)/2
            self.create_line(x,y0,x,y0+bh, width=bw, capstyle="round", fill=self.color)
        self.after(30, self._anim)

class NavItem(ctk.CTkFrame):
    def __init__(self, p, icon, label, cmd, **kw):
        super().__init__(p, fg_color="transparent", cursor="hand2", corner_radius=8, **kw)
        self._active=False; self._cmd=cmd
        self._bar=ctk.CTkFrame(self, width=3, height=30, fg_color=ACC, corner_radius=2)
        self._ico=ctk.CTkLabel(self, text=icon, font=(FONT, 15), text_color=MUT, width=26)
        self._ico.pack(side="left", padx=(14,6), pady=10)
        self._lbl=ctk.CTkLabel(self, text=label, font=_f(13), text_color=MUT, anchor="w")
        self._lbl.pack(side="left", pady=10)
        for w in (self, self._ico, self._lbl):
            w.bind("<Button-1>", lambda e: self._cmd())
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))
    def activate(self, v):
        self._active=v
        self.configure(fg_color=CRD if v else "transparent")
        if v: self._bar.place(x=0, rely=0.5, anchor="w")
        else: self._bar.place_forget()
        self._ico.configure(text_color=ACC if v else MUT)
        self._lbl.configure(text_color=TXT if v else MUT, font=_f(13, "bold" if v else "normal"))
    def _hover(self, h):
        if not self._active:
            self.configure(fg_color=CRD2 if h else "transparent")
            self._ico.configure(text_color=TXT if h else MUT)
            self._lbl.configure(text_color=TXT if h else MUT)

class HistoryCard(ctk.CTkFrame):
    def __init__(self, p, text, ts, **kw):
        super().__init__(p, fg_color=CRD, corner_radius=10, border_width=1, border_color=BDR, **kw)
        self.text = text
        inn=ctk.CTkFrame(self, fg_color="transparent")
        inn.pack(fill="both", expand=True, padx=16, pady=12)
        
        # Right side button container
        btn_frame = ctk.CTkFrame(inn, fg_color="transparent")
        btn_frame.pack(side="right", padx=(10,0))
        
        self.copy_btn = ctk.CTkButton(btn_frame, text="Copy", width=64, height=28,
                                     fg_color=CRD2, hover_color=BDR, text_color=TXT,
                                     corner_radius=8, font=_f(11), command=self.copy_text)
        self.copy_btn.pack(pady=4)
        
        # Text and timestamp on the left
        txt_frame = ctk.CTkFrame(inn, fg_color="transparent")
        txt_frame.pack(side="left", fill="both", expand=True)
        
        ctk.CTkLabel(txt_frame, text=text, wraplength=420, justify="left", anchor="w",
                     font=_f(13), text_color=TXT).pack(fill="x")
        ctk.CTkLabel(txt_frame, text=ts, anchor="w", font=_f(10), text_color=MUT).pack(fill="x", pady=(4,0))

    def copy_text(self):
        try:
            pyperclip.copy(self.text)
            self.copy_btn.configure(text="Copied!", text_color=ACC, fg_color="#201012")
            self.after(1500, lambda: self.copy_btn.configure(text="Copy", text_color=TXT, fg_color=CRD2))
        except:
            pass


class BildGUI(ctk.CTk):
    def __init__(self, on_settings_change, on_exit):
        super().__init__()
        self.on_settings_change = on_settings_change
        self.on_exit_callback = on_exit
        self.title(config.APP_NAME)
        self.geometry("860x590"); self.minsize(720, 500)
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=BG)
        try: self.iconbitmap(create_default_icon())
        except: pass

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ───────────────────────────────────────────────────────
        sb = ctk.CTkFrame(self, width=192, corner_radius=0, fg_color=SB)
        sb.grid(row=0, column=0, sticky="nsew"); sb.grid_propagate(False)
        sb.grid_rowconfigure(3, weight=1)
        # Right border
        ctk.CTkFrame(sb, width=1, fg_color=BDR, corner_radius=0).place(relx=1, rely=0, relheight=1, anchor="ne")

        # Brand
        bf = ctk.CTkFrame(sb, fg_color="transparent")
        bf.grid(row=0, column=0, sticky="ew", padx=16, pady=(24,12))
        ctk.CTkLabel(bf, text="Bolo", font=_f(28,"bold"), text_color=ACC, anchor="w").pack(anchor="w")
        ctk.CTkLabel(bf, text="Voice · AI · Local", font=_f(9), text_color=MUT, anchor="w").pack(anchor="w")

        # Separator
        ctk.CTkFrame(sb, height=1, fg_color=BDR).grid(row=1, column=0, sticky="ew", padx=14, pady=(0,8))

        # Nav
        nf = ctk.CTkFrame(sb, fg_color="transparent")
        nf.grid(row=2, column=0, sticky="ew", padx=8)
        self._navs = []
        def _nav(i, icon, label, fn):
            item = NavItem(nf, icon, label, lambda i=i, fn=fn: self._switch(i, fn))
            item.pack(fill="x", pady=2)
            self._navs.append(item)
        _nav(0, "⌂", "Dashboard",  self._show_dash)
        _nav(1, "⧖", "History",    self._show_hist)
        _nav(2, "⚙", "Settings",   self._show_sett)

        # Spacer
        ctk.CTkFrame(sb, fg_color="transparent").grid(row=3, column=0)

        # Quit — separator + styled button at bottom
        quit_area = ctk.CTkFrame(sb, fg_color="transparent")
        quit_area.grid(row=4, column=0, sticky="ew", padx=0, pady=(0,0))
        ctk.CTkFrame(quit_area, height=1, fg_color=BDR).pack(fill="x")
        ctk.CTkButton(quit_area, text="  Quit",
            fg_color="transparent", hover_color="#1f0505",
            text_color="#cc3333", anchor="w",
            corner_radius=0, font=_f(12), height=44,
            command=self.on_exit_callback
        ).pack(fill="x", padx=0)

        # ── Content area ─────────────────────────────────────────────────
        # Use a plain frame as container
        self._cont = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        self._cont.grid(row=0, column=1, sticky="nsew")

        # Build all views — use place() so CTkScrollableFrame renders correctly
        self.dash_v = self._build_dash()
        self.hist_v = self._build_hist()
        self.sett_v = self._build_sett()

        # Place all views on top of each other; lift() to switch — no flicker
        for v in (self.dash_v, self.hist_v, self.sett_v):
            v.place(in_=self._cont, relx=0, rely=0, relwidth=1, relheight=1)

        self._switch(0, self._show_dash)
        self.update_engine_info()
        # Initial language badge
        self.update_ui_language(config.DEFAULT_LANGUAGE)
        self.protocol("WM_DELETE_WINDOW", self.on_close_clicked)
        # Re-raise active view on restore
        self.bind("<Map>", self._on_restore)

    def _switch(self, idx, fn=None):
        if hasattr(self, "_active_idx") and self._active_idx == idx: return
        for i, n in enumerate(self._navs): n.activate(i == idx)
        
        # Smooth transition: prepare content then lift
        if fn: fn()
        self._active_idx = idx
        views = [self.dash_v, self.hist_v, self.sett_v]
        
        # Lifting with a tiny delay ensures the UI thread is free to render properly
        self.after(10, lambda: views[idx].lift())

    def _on_restore(self, e=None):
        if e and e.widget is not self:
            return
        try:
            views = [self.dash_v, self.hist_v, self.sett_v]
            views[self._active_idx].lift()
        except: pass

    def _show_dash(self):
        # Refresh dynamic dashboard labels (hotkey may have changed elsewhere)
        try:
            self.hotkey_lbl.configure(text=f"Hold  {config.ACTIVATION_KEY.upper()}  to record")
            self.update_engine_info()
        except Exception:
            pass

    def _show_hist(self): self.refresh_history()
    def _show_sett(self):
        self.refresh_download_button()
        self._toggle_whisper_ui(config.TRANSCRIPTION_ENGINE)
        self.update_model_description()
        self.update_engine_info()

    # public aliases used by main.py
    def show_dashboard(self): self._switch(0, self._show_dash)
    def show_history(self):   self._switch(1, self._show_hist)
    def show_settings(self):  self._switch(2, self._show_sett)

    # ── Dashboard ─────────────────────────────────────────────────────────
    def _build_dash(self):
        v = ctk.CTkFrame(self._cont, corner_radius=0, fg_color=BG)

        # Header
        hdr = ctk.CTkFrame(v, fg_color=SB, corner_radius=0, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkFrame(hdr, height=1, fg_color=BDR).pack(fill="x", side="bottom")
        ctk.CTkLabel(hdr, text="Dashboard", font=_f(13,"bold"), text_color=TXT).pack(side="left", padx=20)
        self.status_badge = ctk.CTkLabel(hdr, text="  ●  Idle  ", font=_f(10),
            text_color=MUT, fg_color=CRD, corner_radius=6)
        self.status_badge.pack(side="right", padx=(8, 16), pady=8)
        # Current language indicator (live; reflects tray + dashboard changes)
        self.lang_badge = ctk.CTkLabel(hdr, text="", font=_f(10),
            text_color=ACC, fg_color=CRD, corner_radius=6)
        self.lang_badge.pack(side="right", padx=(0, 4), pady=8)

        # Orb center
        mid = ctk.CTkFrame(v, fg_color=BG)
        mid.pack(fill="both", expand=True)
        mid.grid_rowconfigure(0, weight=1); mid.grid_columnconfigure(0, weight=1)
        box = ctk.CTkFrame(mid, fg_color=BG)
        box.grid(row=0, column=0)

        self.mic_orb = MicOrb(box, size=148)
        self.mic_orb.pack(pady=(24,12))

        self.status_lbl = ctk.CTkLabel(box, text="Ready to transcribe",
            font=_f(20,"bold"), text_color=TXT)
        self.status_lbl.pack()

        self.hotkey_lbl = ctk.CTkLabel(box,
            text=f"Hold  {config.ACTIVATION_KEY.upper()}  to record",
            font=_f(12), text_color=MUT)
        self.hotkey_lbl.pack(pady=(4,2))

        self.engine_info_label = ctk.CTkLabel(box, text="", font=_f(10), text_color=MUT)
        self.engine_info_label.pack()

        self.waveform = WaveformCanvas(box, width=260, height=40, bg=BG)
        self.waveform.pack(pady=(10,24))

        # Language strip (bottom)
        strip = ctk.CTkFrame(v, fg_color=CRD, corner_radius=0, height=58)
        strip.pack(fill="x", side="bottom"); strip.pack_propagate(False)
        ctk.CTkFrame(strip, height=1, fg_color=BDR).pack(fill="x")
        lr = ctk.CTkFrame(strip, fg_color="transparent")
        lr.pack(fill="both", expand=True, padx=20)
        ctk.CTkLabel(lr, text="Input Language", font=_f(12), text_color=MUT).pack(side="left")
        self.lang_option = ctk.CTkOptionMenu(lr,
            values=list(config.SUPPORTED_LANGUAGES.keys()),
            command=self.change_language, fg_color=CRD2,
            button_color=ACC, button_hover_color=ACC2,
            dropdown_fg_color=SB, dropdown_hover_color=CRD2,
            dropdown_text_color=TXT, text_color=TXT,
            corner_radius=8, font=_f(12), dropdown_font=_f(11), width=220)
        self.lang_option.set(next((l for l,c in config.SUPPORTED_LANGUAGES.items()
                                    if c==config.DEFAULT_LANGUAGE), "English (India)"))
        self.lang_option.pack(side="right", pady=8)
        return v

    # ── History ───────────────────────────────────────────────────────────
    def _build_hist(self):
        v = ctk.CTkFrame(self._cont, corner_radius=0, fg_color=BG)

        hdr = ctk.CTkFrame(v, fg_color=SB, corner_radius=0, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkFrame(hdr, height=1, fg_color=BDR).pack(fill="x", side="bottom")
        ctk.CTkLabel(hdr, text="History", font=_f(13,"bold"), text_color=TXT).pack(side="left", padx=20)
        self.clear_btn = ctk.CTkButton(hdr, text="Clear All", width=84,
            fg_color="transparent", border_width=1, text_color="#e05555",
            border_color="#3a1515", hover_color="#1f0a0a",
            corner_radius=8, font=_f(11), height=30, command=self.clear_history)
        self.clear_btn.pack(side="right", padx=14, pady=7)

        # Scrollable area — pack with fill+expand so it sizes correctly
        self.history_scroll = ctk.CTkScrollableFrame(v,
            fg_color=BG, corner_radius=0,
            scrollbar_button_color=CRD2,
            scrollbar_button_hover_color=BDR)
        self.history_scroll.pack(fill="both", expand=True, padx=14, pady=12)
        return v

    # ── Settings ──────────────────────────────────────────────────────────
    def _build_sett(self):
        v = ctk.CTkFrame(self._cont, corner_radius=0, fg_color=BG)

        hdr = ctk.CTkFrame(v, fg_color=SB, corner_radius=0, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkFrame(hdr, height=1, fg_color=BDR).pack(fill="x", side="bottom")
        ctk.CTkLabel(hdr, text="Settings", font=_f(13,"bold"), text_color=TXT).pack(side="left", padx=20)

        # CTkScrollableFrame — full remaining space
        sc = ctk.CTkScrollableFrame(v, fg_color=BG, corner_radius=0,
            scrollbar_button_color=CRD2, scrollbar_button_hover_color=BDR)
        sc.pack(fill="both", expand=True)
        sc.grid_columnconfigure(0, weight=1)

        def grp(title):
            """Labelled group card"""
            wrap = ctk.CTkFrame(sc, fg_color="transparent")
            wrap.pack(fill="x", padx=18, pady=(10,0))
            ctk.CTkLabel(wrap, text=title, font=_f(9), text_color=MUT, anchor="w").pack(anchor="w", padx=2)
            card = ctk.CTkFrame(wrap, fg_color=CRD, corner_radius=12,
                                 border_width=1, border_color=BDR)
            card.pack(fill="x", pady=(4,0))
            return card

        def row(card, label, subtitle, last=False):
            """A setting row inside a card"""
            f = ctk.CTkFrame(card, fg_color="transparent")
            f.pack(fill="x", padx=18, pady=(14, 14 if last else 0))
            lf = ctk.CTkFrame(f, fg_color="transparent")
            lf.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(lf, text=label, font=_f(13,"bold"), text_color=TXT, anchor="w").pack(anchor="w")
            ctk.CTkLabel(lf, text=subtitle, font=_f(10), text_color=MUT, anchor="w").pack(anchor="w")
            if not last:
                ctk.CTkFrame(card, height=1, fg_color=BDR).pack(fill="x")
            return f

        def opt(f, vals, cmd, default, w=180):
            m = ctk.CTkOptionMenu(f, values=vals, command=cmd,
                fg_color=CRD2, button_color=ACC, button_hover_color=ACC2,
                dropdown_fg_color=SB, dropdown_hover_color=CRD2,
                dropdown_text_color=TXT, text_color=TXT,
                corner_radius=8, font=_f(12), dropdown_font=_f(11), width=w)
            m.set(default); m.pack(side="right", padx=(12,0)); return m

        def sw(f, cmd, default):
            s = ctk.CTkSwitch(f, text="", progress_color=ACC,
                button_color="#ffffff", button_hover_color="#dddddd",
                width=44, height=22, command=cmd)
            (s.select if default else s.deselect)(); s.pack(side="right"); return s

        # ── System card ──────────────────────────────────────────────────
        c1 = grp("SYSTEM")
        r1 = row(c1, "Run on Startup", "Launch Bolo automatically when Windows starts.")
        self.startup_switch = sw(r1, self.toggle_startup, config.RUN_ON_STARTUP)

        r2 = row(c1, "Activation Key", "The key you hold down to begin recording.")
        # Curated list of commonly used activation keys (subset of VALID_HOTKEYS)
        valid_activation_keys = ["left alt", "right alt", "alt gr", "left ctrl", "right ctrl",
                                  "left shift", "right shift", "space", "f1", "f2", "f3"]
        self.hotkey_option = opt(r2, valid_activation_keys,
                                  self.change_hotkey, config.ACTIVATION_KEY)

        r2b = row(c1, "Long-Press Threshold", "Hold time before recording starts (short presses pass through to OS).")
        lp_choices = ["100ms", "150ms", "200ms", "300ms", "500ms", "1000ms"]
        self.longpress_option = opt(r2b, lp_choices, self.change_longpress,
                                     f"{int(config.LONG_PRESS_THRESHOLD * 1000)}ms", w=120)

        r3 = row(c1, "Beep Sounds", "Audio feedback when recording starts and stops.", last=True)
        self.beep_switch = sw(r3, self.toggle_beeps, config.BEEP_ON_START)

        # ── Engine card ───────────────────────────────────────────────────
        c2 = grp("TRANSCRIPTION ENGINE")
        eng_def = next((l for l,c in config.TRANSCRIPTION_ENGINES.items()
                         if c==config.TRANSCRIPTION_ENGINE),
                        list(config.TRANSCRIPTION_ENGINES)[0])
        r4 = row(c2, "Engine", "Google Speech (online) or Whisper AI (local, offline).", last=True)
        self.engine_option = opt(r4, list(config.TRANSCRIPTION_ENGINES.keys()),
                                  self.change_engine, eng_def, w=200)

        # ── Whisper model card ────────────────────────────────────────────
        c3 = grp("WHISPER MODEL")
        r5 = row(c3, "Model Size", "Larger models are slower but more accurate.")
        self.model_option = opt(r5, list(config.WHISPER_MODELS),
                                 self.change_model, config.WHISPER_MODEL)
        # Download row
        dl = ctk.CTkFrame(c3, fg_color="transparent")
        dl.pack(fill="x", padx=18, pady=(0,14))
        self.download_btn = ctk.CTkButton(dl, text="Download", width=100,
            fg_color=ACC, hover_color=ACC2, text_color="white",
            corner_radius=8, font=_f(11), height=28, command=self.download_whisper_model)
        self.download_btn.pack(side="left")
        self.model_desc_label = ctk.CTkLabel(dl, text="", font=_f(10), text_color=MUT)
        self.model_desc_label.pack(side="left", padx=10)

        self.refresh_download_button()
        self.update_model_description()
        self._toggle_whisper_ui(config.TRANSCRIPTION_ENGINE)

        # ── Hinglish model card ─────────────────────────────────────────
        c3b = grp("HINGLISH MODEL (Zero-STT)")
        r5b = row(c3b, "Specialized Hinglish ASR", "Optimized model for Hindi-English code-switching. Used automatically when language is Hinglish + Whisper engine.", last=True)
        zdl = ctk.CTkFrame(c3b, fg_color="transparent")
        zdl.pack(fill="x", padx=18, pady=(0, 14))
        self.zero_stt_btn = ctk.CTkButton(zdl, text="Download", width=140,
            fg_color=ACC, hover_color=ACC2, text_color="white",
            corner_radius=8, font=_f(11), height=28, command=self.download_zero_stt)
        self.zero_stt_btn.pack(side="left")
        self.zero_stt_status = ctk.CTkLabel(zdl, text="", font=_f(10), text_color=MUT)
        self.zero_stt_status.pack(side="left", padx=10)
        self.refresh_zero_stt_button()

        # ── Text Processing card ────────────────────────────────────────
        c_text = grp("TEXT PROCESSING")
        r_ap = row(c_text, "Auto Punctuation", "Append '.' to transcriptions that don't end with punctuation.")
        self.auto_punct_switch = sw(r_ap, self.toggle_auto_punct, config.AUTO_PUNCTUATION)

        r_cap = row(c_text, "Capitalize First Letter", "Capitalize the first letter of every transcription.")
        self.capitalize_switch = sw(r_cap, self.toggle_capitalize, config.CAPITALIZE_FIRST)

        r_sc = row(c_text, "Spoken Commands",
                   'Convert "comma", "full stop", "new line", "question mark" etc. into their symbols.',
                   last=True)
        self.spoken_cmd_switch = sw(r_sc, self.toggle_spoken_commands, config.SPOKEN_COMMANDS)

        # ── Audio card ──────────────────────────────────────────────────
        c4 = grp("AUDIO QUALITY")
        r6 = row(c4, "Auto Sensitivity", "Automatically adjust microphone threshold for background noise.")
        self.auto_energy_switch = sw(r6, self.toggle_auto_energy, config.AUTO_ENERGY_THRESHOLD)
        
        r7 = row(c4, "Start Buffer (Pre-roll)", "Captures extra audio before you speak to prevent cutting first words.")
        opt(r7, ["0.2s", "0.5s", "0.8s", "1.0s"], self.change_pre_roll, f"{config.PRE_ROLL_SECONDS}s", w=100)
        
        r8 = row(c4, "End Buffer (Post-roll)", "Keeps recording longer after release to prevent cutting last words.", last=True)
        opt(r8, ["0.2s", "0.5s", "0.8s", "1.0s"], self.change_post_roll, f"{config.POST_ROLL_SECONDS}s", w=100)

        # Reset button
        ctk.CTkButton(sc, text="Reset to Defaults",
            fg_color="transparent", border_width=1, border_color=BDR,
            text_color=MUT, hover_color=CRD2, corner_radius=8,
            font=_f(11), height=30, command=self.reset_all_settings
        ).pack(anchor="w", padx=18, pady=(8,24))
        return v


    # ── State ─────────────────────────────────────────────────────────────
    def set_listening_state(self, state, text=""):
        if state == "listening":
            self.mic_orb.start(); self.waveform.color=ACC; self.waveform.start()
            self.status_lbl.configure(text="Listening…", text_color=ACC)
            self.status_badge.configure(text="  ●  Recording  ", text_color=ACC, fg_color="#2a0610")
        elif state == "processing":
            self.mic_orb.processing(); self.waveform.stop()
            self.status_lbl.configure(text="Processing…", text_color="#f59e0b")
            self.status_badge.configure(text="  ●  Processing  ", text_color="#f59e0b", fg_color="#1a1200")
        else:
            self.mic_orb.stop(); self.waveform.stop()
            self.status_lbl.configure(text="Ready to transcribe", text_color=TXT)
            self.status_badge.configure(text="  ●  Idle  ", text_color=MUT, fg_color=CRD)

    def update_ui_language(self, lang_code):
        for label, c in config.SUPPORTED_LANGUAGES.items():
            if c == lang_code:
                try:
                    self.lang_option.set(label)
                except Exception:
                    pass
                # Update dashboard header badge — short form for compactness
                short = label.split(" (")[0]   # "English (India)" -> "English"
                try:
                    self.lang_badge.configure(text=f"  {short}  ")
                except Exception:
                    pass
                break

    # ── History ───────────────────────────────────────────────────────────
    def refresh_history(self):
        items = config.atomic_json_read(config._get_history_path(), default=[])
        if not isinstance(items, list):
            items = []

        for w in self.history_scroll.winfo_children():
            w.destroy()
        if not items:
            ctk.CTkLabel(self.history_scroll, text="No transcriptions yet.",
                font=_f(14), text_color=MUT).pack(pady=60)
            return
        for e in reversed(items):
            HistoryCard(self.history_scroll, e.get("text", ""), e.get("time", "")).pack(fill="x", pady=5)

    def clear_history(self):
        if not messagebox.askyesno("Clear History", "Delete all transcription history?\n\nThis cannot be undone."):
            return
        config.atomic_json_write(config._get_history_path(), [])
        self.refresh_history()

    # ── Callbacks ─────────────────────────────────────────────────────────
    def change_language(self, choice):
        code = config.SUPPORTED_LANGUAGES[choice]
        config.save_setting("DEFAULT_LANGUAGE", code); self.on_settings_change("language", code)

    def change_hotkey(self, choice):
        # Validate hotkey before saving
        if not config.save_setting("ACTIVATION_KEY", choice):
            # Show error message to user
            self._show_hotkey_error(choice)
            # Reset to current valid hotkey
            self.hotkey_option.set(config.ACTIVATION_KEY)
            return
        self.on_settings_change("hotkey", choice)
        self.hotkey_lbl.configure(text=f"Hold  {choice.upper()}  to record")

    def _show_hotkey_error(self, invalid_choice):
        """Show error message when hotkey validation fails."""
        error_msg = f"Invalid hotkey: '{invalid_choice}'\n\nValid hotkeys:\nleft alt, right alt, ctrl, shift, space"
        # Update status label with error
        self.status_lbl.configure(text=f"Invalid hotkey: {invalid_choice}", text_color=ERROR)
        # Schedule status reset after 3 seconds
        self.after(3000, lambda: self.status_lbl.configure(
            text="Ready to transcribe", text_color=TXT))
        print(f"[GUI] Hotkey validation failed for: {invalid_choice}")

    def toggle_beeps(self):
        v = bool(self.beep_switch.get())
        config.save_setting("BEEP_ON_START", v); config.save_setting("BEEP_ON_END", v)

    def change_engine(self, choice):
        code = config.TRANSCRIPTION_ENGINES[choice]
        config.save_setting("TRANSCRIPTION_ENGINE", code)
        self.on_settings_change("engine", code)
        self._toggle_whisper_ui(code); self.update_engine_info()

    def change_model(self, choice):
        config.save_setting("WHISPER_MODEL", choice); self.on_settings_change("model", choice)
        self.refresh_download_button(); self.update_model_description(); self.update_engine_info()

    def update_model_description(self):
        self.model_desc_label.configure(
            text=config.WHISPER_MODEL_DESCRIPTIONS.get(config.WHISPER_MODEL, ""))

    def update_engine_info(self):
        e = config.TRANSCRIPTION_ENGINE
        t = ("Engine: Google Speech (Online)" if e == "google"
             else f"Engine: Whisper AI · {config.WHISPER_MODEL}")
        if hasattr(self, "engine_info_label"): self.engine_info_label.configure(text=t)

    def _toggle_whisper_ui(self, engine):
        s = "normal" if engine == "whisper" else "disabled"
        self.model_option.configure(state=s); self.download_btn.configure(state=s)
        self.model_desc_label.configure(text_color=MUT if engine != "whisper" else MUT)

    def download_whisper_model(self):
        # CRITICAL: Prevent multiple simultaneous downloads
        if hasattr(self, '_is_downloading') and self._is_downloading:
            print("[GUI] Download already in progress, ignoring duplicate request")
            return
        self._is_downloading = True
        self.download_btn.configure(text="Downloading...", state="disabled", fg_color="#666666")
        self.on_settings_change("download_model", None)

    def on_download_progress(self, mb, status_text):
        """Called from poller thread; schedule a GUI update on the main thread."""
        def update():
            try:
                self.download_btn.configure(text=f"{mb:.0f} MB")
                if hasattr(self, 'model_desc_label'):
                    self.model_desc_label.configure(text=status_text)
            except Exception:
                pass
        try:
            self.after(0, update)
        except Exception:
            pass

    def on_zero_stt_progress(self, mb, status_text):
        """Called from poller thread; schedule a GUI update on the main thread."""
        def update():
            try:
                if isinstance(mb, (int, float)) and mb > 0:
                    self.zero_stt_btn.configure(text=f"{mb:.0f} MB")
                self.zero_stt_status.configure(text=status_text)
            except Exception:
                pass
        try:
            self.after(0, update)
        except Exception:
            pass

    def refresh_download_button(self):
        try:
            if is_whisper_model_downloaded(config.WHISPER_MODEL):
                self.download_btn.configure(text="✓ Downloaded", state="disabled",
                    fg_color=CRD2, text_color=MUT)
            else:
                self.download_btn.configure(text="Download", state="normal",
                    fg_color=ACC, text_color="white")
        except: pass

    def toggle_startup(self):
        v = self.startup_switch.get()
        config.save_setting("RUN_ON_STARTUP", v); set_run_on_startup(config.APP_NAME, v)

    def toggle_auto_energy(self):
        v = bool(self.auto_energy_switch.get())
        config.save_setting("AUTO_ENERGY_THRESHOLD", v)
        self.on_settings_change("auto_energy", v)

    def change_pre_roll(self, choice):
        v = float(choice.replace("s", ""))
        config.save_setting("PRE_ROLL_SECONDS", v)
        self.on_settings_change("pre_roll", v)

    def change_post_roll(self, choice):
        v = float(choice.replace("s", ""))
        config.save_setting("POST_ROLL_SECONDS", v)
        self.on_settings_change("post_roll", v)

    def change_longpress(self, choice):
        v = int(choice.replace("ms", "")) / 1000.0
        config.save_setting("LONG_PRESS_THRESHOLD", v)
        self.on_settings_change("longpress", v)

    def toggle_auto_punct(self):
        v = bool(self.auto_punct_switch.get())
        config.save_setting("AUTO_PUNCTUATION", v)

    def toggle_capitalize(self):
        v = bool(self.capitalize_switch.get())
        config.save_setting("CAPITALIZE_FIRST", v)

    def toggle_spoken_commands(self):
        v = bool(self.spoken_cmd_switch.get())
        config.save_setting("SPOKEN_COMMANDS", v)

    def download_zero_stt(self):
        """Trigger zero-stt download via main app callback."""
        if getattr(self, '_zero_stt_downloading', False):
            return
        self._zero_stt_downloading = True
        self.zero_stt_btn.configure(text="Downloading...", state="disabled", fg_color="#666666")
        self.zero_stt_status.configure(text="This can take a few minutes...")
        self.on_settings_change("download_zero_stt", None)

    def on_zero_stt_complete(self, success):
        """Called from main app after zero-stt download finishes."""
        self._zero_stt_downloading = False
        if success:
            self.zero_stt_status.configure(text="Downloaded successfully.", text_color=SUCCESS)
        else:
            self.zero_stt_status.configure(text="Download failed. Check console / network.", text_color=ERROR)
        self.refresh_zero_stt_button()
        self.after(4000, lambda: self.zero_stt_status.configure(text="", text_color=MUT))

    def refresh_zero_stt_button(self):
        try:
            from .audio_engine import is_zero_stt_downloaded
            if is_zero_stt_downloaded():
                self.zero_stt_btn.configure(text="✓ Downloaded", state="disabled",
                    fg_color=CRD2, text_color=MUT)
            else:
                self.zero_stt_btn.configure(text="Download (~1 GB)", state="normal",
                    fg_color=ACC, text_color="white")
        except Exception:
            pass

    def reset_all_settings(self):
        """Reset all settings to defaults, then sync GUI controls.

        Avoids triggering the change_* callbacks (which would each write to
        disk separately). config.reset_settings() removes the file in one go.
        """
        if not messagebox.askyesno("Reset Settings", "Reset all settings to defaults?\n\nThis does not delete history."):
            return
        config.reset_settings()
        # Sync GUI without firing callbacks
        self.hotkey_option.set(config.ACTIVATION_KEY)
        self.longpress_option.set(f"{int(config.LONG_PRESS_THRESHOLD * 1000)}ms")
        (self.beep_switch.select if config.BEEP_ON_START else self.beep_switch.deselect)()
        (self.startup_switch.select if config.RUN_ON_STARTUP else self.startup_switch.deselect)()
        (self.auto_energy_switch.select if config.AUTO_ENERGY_THRESHOLD else self.auto_energy_switch.deselect)()
        (self.auto_punct_switch.select if config.AUTO_PUNCTUATION else self.auto_punct_switch.deselect)()
        (self.capitalize_switch.select if config.CAPITALIZE_FIRST else self.capitalize_switch.deselect)()
        (self.spoken_cmd_switch.select if config.SPOKEN_COMMANDS else self.spoken_cmd_switch.deselect)()
        self.update_ui_language(config.DEFAULT_LANGUAGE)
        eng = next((l for l, c in config.TRANSCRIPTION_ENGINES.items()
                    if c == config.TRANSCRIPTION_ENGINE), "")
        if eng:
            self.engine_option.set(eng)
        self.model_option.set(config.WHISPER_MODEL)
        self._toggle_whisper_ui(config.TRANSCRIPTION_ENGINE)
        self.update_engine_info()
        self.update_model_description()
        self.hotkey_lbl.configure(text=f"Hold  {config.ACTIVATION_KEY.upper()}  to record")
        # Sync OS-level state that doesn't live in settings.json
        set_run_on_startup(config.APP_NAME, config.RUN_ON_STARTUP)
        self.on_settings_change("hotkey", config.ACTIVATION_KEY)
        self.on_settings_change("longpress", config.LONG_PRESS_THRESHOLD)
        self.on_settings_change("language", config.DEFAULT_LANGUAGE)

    # ── Window ────────────────────────────────────────────────────────────
    def hide_window(self): self.withdraw()
    def on_close_clicked(self): self.hide_window()
    def show_window(self):
        self.deiconify(); self.lift(); self.focus_force()
        # Re-raise the correct view after restore
        self.after(50, self._on_restore)


def start_gui(on_settings_change, on_exit):
    return BildGUI(on_settings_change, on_exit)
