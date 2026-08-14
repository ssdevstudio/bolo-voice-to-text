import collections
import json
import os
import re
import threading
import time

import numpy as np
import pyaudio
import speech_recognition as sr
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

from typing import Any, Optional, Callable

from . import config

# ─── Hinglish Data: loaded from external JSON ────────────────────────────
# Data file is co-located with this module.
_HINGLISH_DATA_PATH = os.path.join(os.path.dirname(__file__), "hinglish_data.json")

def _load_hinglish_data() -> dict[str, Any]:
    """Load Hinglish normalization data from JSON and compile regex patterns."""
    path = _HINGLISH_DATA_PATH
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {
        "prompt_artifacts": [re.compile(re.escape(a), re.IGNORECASE) for a in raw["prompt_artifacts"]],
        "regex_patterns": [(re.compile(p, re.IGNORECASE), r) for p, r in raw["regex_patterns"]],
        "phonetic_word_map": dict(raw["phonetic_word_map"]),
        "spoken_command_patterns": [(re.compile(p, re.IGNORECASE), r) for p, r in raw["spoken_command_patterns"]],
        "hindi_lowercase_midwords": frozenset(raw["hindi_lowercase_midwords"]),
        "trailing_a_whitelist": frozenset(raw["trailing_a_whitelist"]),
    }

_HD = _load_hinglish_data()
_PROMPT_ARTIFACTS = _HD["prompt_artifacts"]
_REGEX_PATTERNS = _HD["regex_patterns"]
_PHONETIC_WORD_MAP = _HD["phonetic_word_map"]
_SPOKEN_COMMAND_PATTERNS = _HD["spoken_command_patterns"]
_HINDI_LOWERCASE_MIDWORDS = _HD["hindi_lowercase_midwords"]
_TRAILING_A_WHITELIST = _HD["trailing_a_whitelist"]

# Legacy aliases — kept for any external callers.
_HINGLISH_CLEANUP_PATTERNS = _REGEX_PATTERNS
_ARTIFACT_PATTERNS = _PROMPT_ARTIFACTS
_HINGLISH_FIX_PATTERNS = []

# ─── Module-level compiled patterns (avoid recompile per call) ───────────
# Word-and-punctuation splitter used in _clean_hinglish
_RE_WORD_PUNCT = re.compile(r'^(.*?)([.,!?;:]+)?$')
# Post-processing: spacing around punctuation
_RE_SPACE_PUNCT = re.compile(r'[^\S\n]+([.,!?;:])')
_RE_PUNCT_NOSPACE = re.compile(r'([.,!?;:])(?=[^\s.,!?;:])')
_RE_NEWLINE_SPACE = re.compile(r'[^\S\n]*\n[^\S\n]*')
_RE_NEWLINE_3PLUS = re.compile(r'\n{3,}')
# Post-processing: punctuation dedup
_RE_PUNCT_REPEAT = re.compile(r'([!?,;:])\1+')
_RE_DOT_4PLUS = re.compile(r'\.{4,}')
_RE_DOT_EXACT2 = re.compile(r'(?<!\.)\.{2}(?!\.)')
_RE_SPACE_MULTI = re.compile(r'[^\S\n]+')
# Post-processing: lowercase-midword splitter
_RE_WORD_CASE = re.compile(r'^(\w+)([.,!?;:]*)$')
# Transliteration cleanup
_RE_ITRANS_DOT = re.compile(r'\.([a-zA-Z]+)')
_RE_ITRANS_MARKS = re.compile(r'[\^~`]')
_RE_DEVA_LEAK = re.compile(r'[ऀ-ॿ]')


def _detect_device() -> tuple[str, str]:
    """
    Advanced Hardware Detection for Bolo:
    Detects CUDA, checks VRAM, and sets optimal quantization.
    Uses CTranslate2 native CUDA API (no torch import needed).
    """
    try:
        import ctranslate2
        cuda_count = ctranslate2.get_cuda_device_count()
        if cuda_count > 0:
            import subprocess
            gpu_name = "NVIDIA GPU"
            vram_total = 0.0
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0 and res.stdout.strip():
                    parts = res.stdout.strip().split(",")
                    gpu_name = parts[0].strip()
                    try:
                        vram_total = float(parts[1].strip().split()[0]) / 1024
                    except (ValueError, IndexError):
                        vram_total = 0.0
            except Exception:
                pass
            print(f"[Hardware] CUDA detected: {gpu_name}" + (f" ({vram_total:.1f}GB VRAM)" if vram_total else ""))
            # int8_float16: store weights as int8 (VRAM efficient), compute in float16 (fast GPU)
            return "cuda", "int8_float16"
    except ImportError:
        pass

    print("[Hardware] Using CPU Mode (int8 quantization).")
    return "cpu", "int8"

class AudioEngine:
    """
    Core audio engine for Bolo voice-to-text application.

    Responsibilities:
        - Microphone stream management (PyAudio)
        - Audio recording with pre-roll buffer
        - Speech-to-text via Google Speech API or Whisper AI
        - Audio preprocessing (HPF, VAD, normalization, gain)
        - Hinglish transcription support with post-processing

    Thread Safety:
        - Uses threading.Lock for shared state (is_recording, audio_frames)
        - Background listener thread for volume metering and pre-roll buffer
        - File locking for history writes

    Configuration:
        - Audio parameters from config.py (SAMPLE_RATE, CHUNK_SIZE, etc.)
        - Transcription settings (engine, language, model)
        - Audio preprocessing (VAD_THRESHOLD, DIGITAL_GAIN, etc.)
    """
    def __init__(self) -> None:
        self.recognizer: sr.Recognizer = sr.Recognizer()
        self.is_recording: bool = False
        self._lock: threading.Lock = threading.Lock()
        self.audio_frames: list[bytes] = []

        self.p: Optional[pyaudio.PyAudio] = None
        self.format: int = pyaudio.paInt16
        self.channels: int = config.CHANNELS
        self.rate: int = config.SAMPLE_RATE
        self.chunk_size: int = config.CHUNK_SIZE
        self.sample_width: int = 2

        self.current_volume: float = 0
        self._stop_event: threading.Event = threading.Event()
        self._record_thread: Optional[threading.Thread] = None

        self._whisper_model: Optional[Any] = None
        self._zero_stt_model: Optional[Any] = None
        self._device: str = ""
        self._compute_type: str = ""
        self._device, self._compute_type = _detect_device()

        self.stream: Optional[Any] = None
        print(f"[Audio] Device: {self._device}, Compute: {self._compute_type}")

        # Pre-roll circular buffer (spec-compliant: 0.5s)
        self.pre_roll_buffer: collections.deque[bytes] = collections.deque(
            maxlen=int(self.rate / self.chunk_size * config.PRE_ROLL_SECONDS)
        )
        self._stop_engine_event = threading.Event()
        self._bg_listener_thread = None

        self._init_audio()
        self._start_bg_listener()
        # Non-blocking noise calibration (avoids 0.8s startup delay)
        threading.Thread(target=self._adjust_noise, daemon=True).start()

    def _init_audio(self) -> None:
        try:
            self.kill_stream()
            self.p = pyaudio.PyAudio()
            # Verify stream support
            self._initialize_stream()
            print(f"[Audio] Engine ready at {self.rate}Hz Mono")
        except Exception as e:
            print(f"[Audio] Engine Init Error: {e}")

    def _initialize_stream(self) -> None:
        """Initialize audio stream with error handling and auto-recovery."""
        try:
            self.stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                start=True
            )
            print("[Audio] Stream initialized successfully")
        except Exception as e:
            print(f"[Audio] Failed to initialize stream: {e}")
            self.stream = None
            # Try to recover: reinitialize PyAudio if stream init fails
            try:
                print("[Audio] Attempting stream recovery...")
                if self.p:
                    self.p.terminate()
                self.p = pyaudio.PyAudio()
                self.stream = self.p.open(
                    format=self.format,
                    channels=self.channels,
                    rate=self.rate,
                    input=True,
                    frames_per_buffer=self.chunk_size,
                    start=True
                )
                print("[Audio] Stream recovered successfully")
            except Exception as e2:
                print(f"[Audio] Stream recovery failed: {e2}")
                raise RuntimeError(f"Cannot initialize audio stream: {e2}")

    def _adjust_noise(self) -> None:
        try:
            print("Calibrating microphone...")
            with sr.Microphone(sample_rate=self.rate) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.8)
            print(f"Calibration complete. Energy threshold: {self.recognizer.energy_threshold}")
        except Exception as e:
            print(f"[Audio] Noise calibration error: {e}")

    def _start_bg_listener(self) -> None:
        if self._bg_listener_thread is None or not self._bg_listener_thread.is_alive():
            self._stop_engine_event.clear()
            self._bg_listener_thread = threading.Thread(target=self._bg_listener_loop, daemon=True)
            self._bg_listener_thread.start()

    def _bg_listener_loop(self) -> None:
        """Always running background thread to fill pre-roll buffer and show volume."""
        while not self._stop_engine_event.is_set():
            if not self.is_recording:
                try:
                    if self.stream is None or not self.stream.is_active():
                        time.sleep(0.1)
                        continue

                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    if data:
                        with self._lock:
                            # Double-check under lock to prevent TOCTOU race with start_recording()
                            if not self.is_recording:
                                self.pre_roll_buffer.append(data)
                            # Update volume for UI meters (always update, even during recording)
                            # Vectorized RMS — avoids Python-level unpack + loop (~31x/sec)
                            samples = np.frombuffer(data, dtype=np.int16)
                            if samples.size:
                                samples_f = samples.astype(np.float32)
                                self.current_volume = float(np.sqrt(np.mean(samples_f * samples_f)))
                except Exception:
                    time.sleep(0.1)
            else:
                # When recording, the record_loop handles it, but we still want to
                # keep the pre_roll buffer somewhat fresh or just wait.
                time.sleep(0.1)

    # ------------------------------------------------------------------
    #  Whisper Helpers
    # ------------------------------------------------------------------
    def _get_whisper_model(self) -> Any:
        if self._whisper_model is None:
            model_size = config.WHISPER_MODEL
            print(f"[Audio] Loading Whisper model '{model_size}'...")
            try:
                from faster_whisper import WhisperModel
                self._whisper_model = WhisperModel(
                    model_size,
                    device=self._device,
                    compute_type=self._compute_type,
                )
                print(f"[Audio] Whisper model '{model_size}' loaded ({self._device}).")
            except Exception as e:
                print(f"[Audio] Failed to load Whisper: {e}")
                raise
        return self._whisper_model

    def _ensure_zero_stt_model(self, progress_cb: Optional[Callable[[int, str], None]] = None) -> str:
        """Ensure shunyalabs/zero-stt-hinglish is available as a CTranslate2 model.

        Steps:
            1. Use existing converted model if model.bin already on disk.
            2. Otherwise pull weights from HuggingFace Hub into HF cache
               (auto-download — no manual huggingface-cli needed).
            3. Convert HF model → CTranslate2 quantized model for faster-whisper.

        progress_cb: optional callable(stage: str) for UI feedback.
        """
        model_path = config.ZERO_STT_MODEL_PATH
        if os.path.exists(os.path.join(model_path, "model.bin")):
            print("[Audio] zero-stt model present, using cached conversion.")
            return model_path

        # 1. Make sure raw HF weights are downloaded
        cache_path = self._get_hf_cache_path()
        if not cache_path or not os.path.exists(os.path.join(cache_path, "model.safetensors")):
            if progress_cb:
                progress_cb(0, "Downloading zero-stt-hinglish from HuggingFace Hub...")
            print(f"[Audio] Downloading {config.ZERO_STT_MODEL_ID} from HuggingFace Hub...")
            try:
                from huggingface_hub import snapshot_download
                cache_path = snapshot_download(
                    repo_id=config.ZERO_STT_MODEL_ID,
                    allow_patterns=["*.json", "*.txt", "*.safetensors", "tokenizer*", "preprocessor*"],
                )
                print(f"[Audio] Downloaded zero-stt to: {cache_path}")
            except Exception as e:
                raise RuntimeError(f"Failed to download {config.ZERO_STT_MODEL_ID}: {e}")

        # 2. Convert HF → CTranslate2 for faster-whisper compatibility
        if progress_cb:
            progress_cb(0, "Converting model for fast inference (one-time)...")
        try:
            from ctranslate2.converters import TransformersConverter
            converter = TransformersConverter(
                model_name_or_path=cache_path,
                low_cpu_mem_usage=True,
            )
            converter.convert(
                output_dir=model_path,
                force=True,
                quantization=self._compute_type,
            )
            print(f"[Audio] zero-stt converted to {model_path}")
        except Exception as e:
            raise RuntimeError(f"CTranslate2 conversion failed: {e}")

        return model_path

    def _get_hf_cache_path(self) -> Optional[str]:
        """Return the resolved local path of shunyalabs/zero-stt-hinglish in HF cache."""
        try:
            import os
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
            snapshots_dir = os.path.join(
                cache_dir, "models--shunyalabs--zero-stt-hinglish", "snapshots"
            )
            if not os.path.isdir(snapshots_dir):
                return None
            for rev in os.listdir(snapshots_dir):
                rev_path = os.path.join(snapshots_dir, rev)
                if os.path.isdir(rev_path) and os.path.exists(
                    os.path.join(rev_path, "model.safetensors")
                ):
                    return rev_path
        except Exception as e:
            print(f"[Audio] HF cache path lookup failed: {e}")
        return None

    def _get_zero_stt_model(self) -> Any:
        """Lazy-load the zero-stt model. Each call may retry — no permanent
        failure cache (network/disk issues can heal between attempts).
        """
        if self._zero_stt_model is not None:
            return self._zero_stt_model
        model_path = self._ensure_zero_stt_model()
        print("[Audio] Loading zero-stt-hinglish model...")
        try:
            from faster_whisper import WhisperModel
            self._zero_stt_model = WhisperModel(
                model_path,
                device=self._device,
                compute_type=self._compute_type,
            )
            print("[Audio] zero-stt-hinglish model loaded.")
            return self._zero_stt_model
        except Exception as e:
            self._zero_stt_model = None
            raise RuntimeError(f"Failed to load zero-stt: {e}")

    def download_zero_stt_now(self, progress_cb: Optional[Callable[[int, str], None]] = None) -> bool:
        """Trigger zero-stt download + conversion explicitly (used by GUI).

        progress_cb(mb, status_text) is invoked from a poller thread during
        the HF download phase; the CTranslate2 conversion phase reports only
        the stage label (no per-MB progress).
        """
        stop = threading.Event()
        poller = None
        if progress_cb:
            poller = threading.Thread(
                target=self._poll_download_progress,
                args=(self._hf_cache_root(), stop, progress_cb, "Zero-STT-Hinglish"),
                daemon=True,
            )
            poller.start()
        try:
            self._ensure_zero_stt_model(progress_cb=progress_cb)
            return True
        except Exception as e:
            print(f"[Audio] zero-stt download failed: {e}")
            return False
        finally:
            stop.set()
            if poller:
                poller.join(timeout=2.0)

    def _transcribe_zero_stt(self, raw_data: bytes) -> str:
        audio_np = self._preprocess_audio(raw_data, self.rate, for_whisper=True)
        model = self._get_zero_stt_model()

        print("[Audio] Zero-STT: transcribing in Hindi...")
        segs, _ = model.transcribe(
            audio_np,
            beam_size=2,  # Fast CPU inference (matches _transcribe_whisper_raw)
            best_of=1,
            language="hi",
            task="transcribe",
            temperature=0.0,
            no_speech_threshold=config.NO_SPEECH_THRESHOLD,
            log_prob_threshold=config.LOG_PROB_THRESHOLD,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            repetition_penalty=1.15,
            vad_filter=True,
            vad_parameters=dict(
                min_speech_duration_ms=250,
                min_silence_duration_ms=500,
                speech_pad_ms=400,
            ),
        )
        hindi_text = " ".join([s.text.strip() for s in segs]).strip()

        if not hindi_text:
            return ""

        print(f"[Audio] Zero-STT Hindi output: {hindi_text}")

        # Transliterate Devanagari → Roman, then apply Hinglish polisher
        text = self._transliterate_to_roman(hindi_text)
        print(f"[Audio] Transliterated: {text}")
        text = AudioEngine._clean_hinglish(text)
        return text

    @staticmethod
    def _clean_hinglish(text: Optional[str]) -> str:
        """Polish Roman Hinglish text: strip prompt artifacts, normalize spelling,
        fix conjugation suffixes, drop stray trailing vowels from ASR output.

        Pipeline (no destructive English-word collateral):
            1. Strip Whisper / Zero-STT prompt-leak hallucinations
            2. Apply curated regex patterns (nasal, plural, schwa, char repeats)
            3. Word-level: dict lookup → verb-suffix heuristics → trailing-vowel
        """
        if not text:
            return text

        # 1. Strip prompt-leak artifacts
        for pattern in _PROMPT_ARTIFACTS:
            text = pattern.sub('', text)

        # 2. Curated regex pass
        for pattern, replacement in _REGEX_PATTERNS:
            text = pattern.sub(replacement, text)

        # 3. Word-level cleanup. Preserve original word/case unless a fix applies
        # (so proper nouns like "Sam", "Delhi" survive untouched).
        out = []
        for raw in text.split():
            if not raw:
                continue
            # Peel trailing punctuation so dict matching works on bare word
            m = _RE_WORD_PUNCT.match(raw)
            word = m.group(1) if m else raw
            punct = (m.group(2) if m else '') or ''
            low = word.lower()

            # 3a. Direct phonetic dictionary hit
            fixed = _PHONETIC_WORD_MAP.get(low)
            if fixed is not None:
                out.append(fixed + punct)
                continue

            # 3b. Verb-suffix heuristics — only rewrite if pattern matches.
            # NOTE: `at -> ta` removed; was corrupting nouns like dikkat,
            # adalat, haqeeqat, jaroorat, imarat, etc. Verb stems that need
            # this fix (karat, bolat) are in _PHONETIC_WORD_MAP.
            rewritten = None
            if low.endswith('ane') and len(low) > 4:
                rewritten = low[:-3] + 'ne'      # khadagane -> khadne
            elif low.endswith('ate') and len(low) > 4:
                rewritten = low[:-3] + 'te'      # karate -> karte
            elif low.endswith('ati') and len(low) > 4:
                rewritten = low[:-3] + 'ti'      # karati -> karti
            elif low.endswith('eg') and len(low) > 3:
                rewritten = low[:-2] + 'ega'     # kareg -> karega

            # 3c. Trailing-vowel cleanup (Zero-STT drops/adds short final 'a'/'ah')
            # NEVER strip future-tense suffixes (-ega, -egi, -enge — Hindi भविष्य काल)
            if rewritten is None and len(low) > 3 and low not in _TRAILING_A_WHITELIST:
                if low.endswith('ah'):
                    rewritten = low[:-1]
                elif low.endswith('a') and not (low.endswith('ega') or low.endswith('egi')
                                                 or low.endswith('enge')):
                    trimmed = low[:-1]
                    if len(trimmed) >= 3:
                        rewritten = trimmed

            # 3d. Cascade lookup: trimmed form may itself be a dict key
            # (e.g. "matalaba" -> trim -> "matalab" -> dict -> "matlab")
            if rewritten is not None:
                cascade = _PHONETIC_WORD_MAP.get(rewritten)
                if cascade is not None:
                    rewritten = cascade

            # If no rewrite triggered, keep the ORIGINAL word (case preserved)
            out.append((rewritten if rewritten is not None else word) + punct)
        return ' '.join(out).strip()


    def reload_zero_stt_model(self) -> None:
        self._zero_stt_model = None
        print("[Audio] zero-stt model will be reloaded on next use.")

    @staticmethod
    def _resample_audio(audio_np: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
        """Resample using linear interpolation (good enough for speech)."""
        if orig_rate == target_rate:
            return audio_np
        duration = len(audio_np) / orig_rate
        target_length = int(duration * target_rate)
        indices = np.linspace(0, len(audio_np) - 1, target_length)
        return np.interp(indices, np.arange(len(audio_np)), audio_np)

    @staticmethod
    def _high_pass_filter(data: np.ndarray, cutoff: float = 100, fs: int = 16000) -> np.ndarray:
        """First-order IIR high-pass filter.

        Recurrence:  y[n] = alpha * (y[n-1] + x[n] - x[n-1])
            alpha = RC / (RC + dt),  RC = 1 / (2*pi*cutoff),  dt = 1/fs

        Uses scipy.signal.lfilter for a vectorized C-level pass that gives the
        true IIR response (the previous numpy-cumsum implementation produced a
        different — and incorrect — transfer function).
        """
        if len(data) < 2:
            return data
        rc = 1.0 / (2.0 * np.pi * cutoff)
        dt = 1.0 / fs
        alpha = rc / (rc + dt)
        try:
            from scipy.signal import lfilter
            # Transfer function: H(z) = alpha (1 - z^-1) / (1 - alpha z^-1)
            b = np.array([alpha, -alpha], dtype=np.float32)
            a = np.array([1.0, -alpha], dtype=np.float32)
            return lfilter(b, a, data).astype(np.float32)
        except ImportError:
            # Fallback: pure-numpy IIR using a Python loop. Slow but correct.
            y = np.empty_like(data)
            y[0] = data[0]
            for n in range(1, len(data)):
                y[n] = alpha * (y[n - 1] + data[n] - data[n - 1])
            return y

    @staticmethod
    def _trim_silence(audio_np: np.ndarray, threshold: Optional[float] = None, frame_length: int = 512) -> np.ndarray:
        # Use configurable VAD_THRESHOLD from config
        if threshold is None:
            threshold = config.VAD_THRESHOLD
        if len(audio_np) < frame_length:
            return audio_np
        n_frames = (len(audio_np) - frame_length + 1) // frame_length
        if n_frames <= 0:
            return audio_np
        truncated = audio_np[:n_frames * frame_length]
        frames_rms = np.sqrt(np.mean(truncated.reshape(n_frames, frame_length) ** 2, axis=1))
        above = frames_rms > threshold
        if not np.any(above):
            return audio_np
        # Find first frame above threshold
        first_active = np.argmax(above)
        # Find last frame above threshold
        last_active = len(above) - 1 - np.argmax(above[::-1])
        # Keep more context to preserve beginning and end of speech
        # 5 frames before speech starts (~160ms), 6 frames after it ends (~192ms)
        start_idx = max(0, first_active - 5) * frame_length
        end_idx = min(len(audio_np), (last_active + 7) * frame_length)
        return audio_np[start_idx:end_idx]

    def _preprocess_audio(self, raw_data: bytes, sample_rate: int, for_whisper: bool = False) -> Any:
        """Audio preprocessing pipeline:

            1. int16 → float32 normalize
            2. Resample to 16 kHz if needed
            3. 100 Hz HPF (remove fan/hum)
            4. RMS-target normalize (consistent loudness across recordings)
            5. Optional digital gain
            6. VAD silence trim
            7. Soft clip + symmetric silence padding
        """
        audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

        if sample_rate != 16000:
            audio = self._resample_audio(audio, sample_rate, 16000)

        # 1. HPF — remove low-frequency hum/fan noise
        audio = self._high_pass_filter(audio, cutoff=config.HPF_CUTOFF, fs=16000)

        # 2. RMS normalize to target loudness (single source of truth for level)
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms > 1e-3:
            audio = audio * (config.NORMALIZATION_RMS / rms)

        # 3. Apply user-configurable digital gain (post-normalize)
        if config.DIGITAL_GAIN != 1.0:
            audio = audio * config.DIGITAL_GAIN

        # 4. VAD trim on normalized signal
        audio = self._trim_silence(audio, threshold=config.VAD_THRESHOLD * 1.2)

        # 5. Soft-clip to prevent hard distortion if gain pushed peaks > 1.0
        audio = np.tanh(audio * 0.95)

        # 6. Symmetric silence padding (gives ASR context at edges)
        pad_len = int(16000 * (config.SILENCE_PADDING_MS / 1000.0))
        if pad_len > 0:
            padding = np.zeros(pad_len, dtype=np.float32)
            audio = np.concatenate([padding, audio, padding])

        if for_whisper:
            # Faster-Whisper accepts arbitrary-length audio. Only pad very short
            # clips; power-of-two padding could nearly double inference work
            # (for example, a 17-second recording became 32 seconds).
            min_samples = 3 * 16000
            if len(audio) < min_samples:
                audio = np.pad(audio, (0, min_samples - len(audio)), 'constant')
            return audio
        else:
            # int16 bytes for speech_recognition.AudioData
            audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            return audio_int16.tobytes()

    # ------------------------------------------------------------------
    #  Recording
    # ------------------------------------------------------------------
    def start_recording(self) -> None:
        print("[Audio] start_recording() called")
        with self._lock:
            if self.is_recording:
                print("[Audio] Already recording, ignoring")
                return

            print("[Audio] Setting up recording state...")
            self._stop_event.clear()
            self.is_recording = True

            # Start with the pre-roll buffer to catch the beginning of the speech
            # CRITICAL: Must acquire lock to prevent race with bg_listener_loop
            self.audio_frames = list(self.pre_roll_buffer)
            print(f"[Audio] Pre-roll buffer has {len(self.pre_roll_buffer)} frames")
            # We don't clear pre_roll_buffer here, we'll just stop adding to it in bg_listener

            if self.p is None:
                print("[Audio] Initializing audio (PyAudio is None)")
                self._init_audio()
            else:
                print("[Audio] PyAudio already initialized")

            # Stream is kept active by background listener (start=True in _initialize_stream)
            # Only need recovery if stream is None or unexpectedly inactive
            if self.stream is None or not self.stream.is_active():
                print("[Audio] Stream needs initialization/recovery")
                if self.stream:
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                self._initialize_stream()

            if not self.stream or not self.stream.is_active():
                print("[Audio] CRITICAL: Stream failed to start")
                self.is_recording = False
                return

            print("[Audio] Stream active and ready")

            print("[Audio] Starting record thread...")
            self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
            self._record_thread.start()
            print("[Audio] Record thread started")

    def _record_loop(self) -> None:
        """Stream read loop. Holds lock briefly to snapshot stream ref so
        kill_stream() can't null it under us between is_active() and read().
        """
        print("[Audio] _record_loop() started")
        frame_count = 0
        expected_bytes = self.chunk_size * self.sample_width
        while self.is_recording and not self._stop_event.is_set():
            # Snapshot stream under lock — kill_stream() may null self.stream
            with self._lock:
                stream = self.stream
                if stream is None:
                    break
            try:
                if not stream.is_active():
                    print(f"[Audio] Stream not active, exiting loop ({frame_count} frames)")
                    break
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                if not data or len(data) < expected_bytes:
                    print(f"[Audio] Incomplete frame: {len(data) if data else 0}/{expected_bytes} bytes")
                    continue
                self.audio_frames.append(data)
                frame_count += 1
                samples = np.frombuffer(data, dtype=np.int16)
                if samples.size:
                    samples_f = samples.astype(np.float32)
                    self.current_volume = float(np.sqrt(np.mean(samples_f * samples_f)))
            except OSError as e:
                # Stream closed mid-read; expected during shutdown
                print(f"[Audio] Stream OSError during read: {e}")
                break
            except Exception as e:
                print(f"[Audio] Recording error: {e}")
                break
        print(f"[Audio] _record_loop() ended ({frame_count} frames)")
        self.current_volume = 0

    def stop_recording(self, language: str = config.DEFAULT_LANGUAGE) -> str:
        print(f"[Audio] stop_recording() called (language={language})")
        # 1. Post-roll: Wait for 0.5s before actually stopping the capture
        # This ensures the ending words are not cut off.
        time.sleep(config.POST_ROLL_SECONDS)

        with self._lock:
            self.is_recording = False
            self._stop_event.set()

        if self._record_thread:
            print("[Audio] Waiting for record thread to finish...")
            self._record_thread.join(timeout=2.0)
            self._record_thread = None

        # Stream stays active for background listener (continuous pre-roll)

        print(f"[Audio] Audio frames captured: {len(self.audio_frames)}")
        if not self.audio_frames:
            print("[Audio] No audio frames captured.")
            return ""

        return self._process_audio(language)

    # ------------------------------------------------------------------
    #  Processing
    # ------------------------------------------------------------------
    def _process_audio(self, language: str) -> str:
        print("[Audio] _process_audio() called")
        raw_data = b"".join(self.audio_frames)
        # DON'T clear audio_frames here — preserve them if transcription fails
        # so a retry or diagnostic can re-use the data. Cleared on next
        # start_recording() instead.

        if not raw_data:
            print("[Audio] Raw audio data is empty.")
            self.audio_frames = []
            return ""
        print(f"[Audio] Processing {len(raw_data)} bytes of audio data")

        total_duration = len(raw_data) / (self.rate * self.sample_width)
        print(f"[Audio] Captured {total_duration:.2f}s of audio ({len(raw_data)} bytes)")

        if total_duration < 1.0:
            print("[Audio] Audio too short (<1s), skipping transcription to avoid gibberish.")
            return ""

        engine = getattr(config, 'TRANSCRIPTION_ENGINE', 'google')
        is_hinglish = language == 'xx-HI'
        # For Hinglish, Google's en-IN handles code-switching naturally and outputs Roman
        google_lang = 'en-IN' if is_hinglish else language

        if engine == 'google':
            text = self._transcribe_google(raw_data, google_lang, skip_history=(is_hinglish))
            if is_hinglish and text:
                text = AudioEngine._clean_hinglish(text)
                self.log_history(text, 'xx-HI')
            return text

        if engine == 'whisper':
            if is_hinglish:
                # 1. Primary: Zero-STT (most optimized for Hinglish)
                try:
                    print("[Audio] Mode: Local (Zero-STT) -> Hinglish Pipeline")
                    text = self._transcribe_zero_stt(raw_data)
                    if text and len(text.strip()) > 1:
                        text = AudioEngine._clean_hinglish(text)
                        text = AudioEngine._post_process_transcription(text)
                        self.log_history(text, 'xx-HI')
                        return text
                    print("[Audio] Zero-STT returned empty/short output. Trying fallback...")
                except Exception as e:
                    print(f"[Audio] Zero-STT Error: {e}. Falling back to Whisper Large-v3-Turbo.")

                # 2. Secondary: Whisper Large-v3-Turbo (Hindi → Romanized)
                try:
                    print("[Audio] Mode: Local (Whisper Fallback) -> Hinglish Pipeline")
                    text = self._transcribe_whisper_hinglish_fallback(raw_data)
                    if text and len(text.strip()) > 1:
                        text = AudioEngine._clean_hinglish(text)
                        text = AudioEngine._post_process_transcription(text)
                        self.log_history(text, 'xx-HI')
                        return text
                    print("[Audio] Whisper Fallback returned empty/short output. Trying Google Cloud.")
                except Exception as e:
                    print(f"[Audio] Whisper Fallback Error: {e}. Falling back to Google Cloud.")

                # 3. Tertiary: Google Cloud (en-IN handles code-switching well)
                print("[Audio] Mode: Cloud (Google en-IN)")
                text = self._transcribe_google(raw_data, 'en-IN', skip_history=True)
                if text:
                    text = AudioEngine._clean_hinglish(text)
                    self.log_history(text, 'xx-HI')
                return text

            try:
                text = self._transcribe_whisper(raw_data, language)
                return AudioEngine._post_process_transcription(text)
            except Exception as e:
                print(f"[Audio] Whisper failed ({e}), falling back to Google...")
                return self._transcribe_google(raw_data, google_lang)

        return self._transcribe_google(raw_data, google_lang)

    @staticmethod
    def _apply_spoken_commands(text: Optional[str]) -> Optional[str]:
        """Replace spoken punctuation/formatting commands with their symbols.

        Supports English and a few common Hindi phrases. Examples:
            "Hello comma how are you" -> "Hello, how are you"
            "End of line full stop"   -> "End of line."
            "Naya paragraph"          -> "\\n\\n"

        Order matters — longer phrases first so "exclamation mark" beats
        "exclamation". Runs space normalization after substitution to
        clean up artifacts like " ." or " ,".
        """
        if not text:
            return text
        for pattern, replacement in _SPOKEN_COMMAND_PATTERNS:
            text = pattern.sub(replacement, text)
        # Tighten spacing around punctuation: " ." -> ".", " ," -> ","
        # (Excludes newlines so "word\nword" stays intact.)
        text = _RE_SPACE_PUNCT.sub(r'\1', text)
        # Ensure exactly one space after punctuation when followed by a
        # non-space, non-punct character. Doesn't touch consecutive punct
        # like "..." (ellipsis) or "?!".
        text = _RE_PUNCT_NOSPACE.sub(r'\1 ', text)
        # Trim spaces around newlines: "word \n word" -> "word\nword"
        text = _RE_NEWLINE_SPACE.sub('\n', text)
        # Collapse triple+ newlines
        text = _RE_NEWLINE_3PLUS.sub('\n\n', text)
        return text

    @staticmethod
    def _post_process_transcription(text: Optional[str]) -> str:
        """Professional finish: dedup punctuation, normalize spaces,
        capitalize first letter, append terminal punctuation if missing.

        Terminal punctuation respects '?', '!', '.', ':', ';' and ellipsis.
        Auto-punctuation and capitalization can be disabled via config.
        """
        if not text:
            return ""
        text = text.strip()

        # Spoken commands BEFORE other cleanup so "full stop" -> "." then "."
        # gets the terminal-punct check below.
        if config.SPOKEN_COMMANDS:
            text = AudioEngine._apply_spoken_commands(text)

        # Collapse runs of repeated terminators (!!! -> !, ??? -> ?)
        # Dots handled specially so "..." ellipsis survives.
        text = _RE_PUNCT_REPEAT.sub(r'\1', text)
        text = _RE_DOT_4PLUS.sub('...', text)
        text = _RE_DOT_EXACT2.sub('.', text)
        # Multi-space normalize (preserve newlines from "new line"/"new paragraph")
        text = _RE_SPACE_MULTI.sub(' ', text)

        # Lowercase Hindi common words that Google randomly Title-Cases
        # mid-sentence. Only affects positions AFTER the first word; first
        # word will get capitalized below.
        words = text.split(' ')
        if len(words) > 1:
            for i in range(1, len(words)):
                w = words[i]
                # Strip trailing punct for lookup
                m = _RE_WORD_CASE.match(w)
                if not m:
                    continue
                bare, punct = m.group(1), m.group(2)
                # Only retitle if it's currently Title-Case (1 upper + rest lower)
                # AND the lowercase form is a known Hindi stopword.
                if bare[:1].isupper() and bare[1:] == bare[1:].lower():
                    if bare.lower() in _HINDI_LOWERCASE_MIDWORDS:
                        words[i] = bare.lower() + punct
            text = ' '.join(words)

        if config.CAPITALIZE_FIRST and text:
            text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()

        if config.AUTO_PUNCTUATION and text:
            # Don't append "." if already terminated (covers ellipsis "..." too)
            if text[-1] not in '.!?:;':
                text += '.'
        return text

    @staticmethod
    def _fix_hinglish_spelling(text: Optional[str]) -> str:
        """Legacy alias — _clean_hinglish now does everything in one pass.

        Kept for any external callers; safe to call after _clean_hinglish.
        """
        return AudioEngine._clean_hinglish(text)

    def _transcribe_whisper_hinglish_fallback(self, raw_data: bytes) -> str:
        """
        Hinglish fallback using forced Hindi transcription + Romanization.
        Uses large-v3-turbo when zero-stt is unavailable or fails.
        """
        audio_np = self._preprocess_audio(raw_data, self.rate, for_whisper=True)

        model = self._get_whisper_model()
        print("[Audio] Whisper Hinglish (Fallback): transcribing...")
        segs, info = model.transcribe(
            audio_np,
            language="hi",
            task="transcribe",
            beam_size=2,  # Fast CPU inference (matches _transcribe_whisper_raw)
            best_of=1,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            no_speech_threshold=config.NO_SPEECH_THRESHOLD,
            log_prob_threshold=config.LOG_PROB_THRESHOLD,
            condition_on_previous_text=False,
            repetition_penalty=1.15,
            vad_filter=True,
            vad_parameters=dict(min_speech_duration_ms=200, speech_pad_ms=400)
        )

        # Combine segments (Whisper outputs Devanagari when lang='hi')
        hindi_text = " ".join([s.text.strip() for s in segs]).strip()
        if not hindi_text:
            return ""

        # Transliterate Devanagari → Roman, then polish for Hinglish
        text = self._transliterate_to_roman(hindi_text)
        text = AudioEngine._clean_hinglish(text)

        print(f"[Audio] Whisper Hinglish (Romanized): {text}")
        return text

    def _transcribe_whisper_raw(self, raw_data: bytes, language: Optional[str] = None, hinglish_prompt: bool = False) -> str:
        audio_np = self._preprocess_audio(raw_data, self.rate, for_whisper=True)

        if len(audio_np) < int(16000 * 0.3):
            print("[Audio] Audio too short after preprocessing.")
            return ""

        model = self._get_whisper_model()
        lang_code = language.split('-')[0] if language else None

        print(f"[Audio] Transcribing with Whisper ({lang_code or 'auto'})...")
        kwargs = dict(
            audio=audio_np,
            language=lang_code,
            task="transcribe",
            beam_size=2,  # Fast CPU inference (was 5)
            best_of=1,
            temperature=0.0,
            vad_filter=True,
        )
        if hinglish_prompt:
            kwargs['initial_prompt'] = (
                "Acha, toh main abhi Hindi aur English mix karke bol raha hoon, "
                "please isse Roman script mein likho."
            )
        segments, info = model.transcribe(**kwargs)

        text = " ".join([segment.text.strip() for segment in segments]).strip()
        return self._filter_whisper_hallucinations(text)

    def _transcribe_whisper(self, raw_data: bytes, language: str) -> str:
        text = self._transcribe_whisper_raw(raw_data, language)

        if text:
            print(f"[Audio] Whisper Result: {text}")
            self.log_history(text, language)
        else:
            print("[Audio] No speech detected by Whisper.")
        return text

    # ------------------------------------------------------------------
    #  Whisper Hallucination Filtering
    # ------------------------------------------------------------------
    def _filter_whisper_hallucinations(self, text: Optional[str]) -> Optional[str]:
        """
        Cleans up common Whisper hallucinations and ensures Devanagari text
        is converted to Roman Hinglish using the transliteration logic.
        """
        if not text:
            return text
        has_devanagari = any('\u0900' <= c <= '\u097F' for c in text)
        has_arabic = any('\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F' for c in text)

        if not has_devanagari and not has_arabic:
            # Already Roman — return as-is (preserves English words in Hinglish)
            return text

        if has_arabic:
            text = AudioEngine._strip_arabic_to_latin(text)

        if has_devanagari:
            text = self._transliterate_to_roman(text)
            text = text.lower().strip()

        return AudioEngine._fix_hinglish_spelling(text)

    @staticmethod
    def _strip_arabic_to_latin(text: str) -> str:
        mapping = {
            'ا': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ٹ': 't', 'ث': 's',
            'ج': 'j', 'چ': 'ch', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ڈ': 'd',
            'ذ': 'z', 'ر': 'r', 'ڑ': 'r', 'ز': 'z', 'ژ': 'zh', 'س': 's',
            'ش': 'sh', 'ص': 's', 'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': 'a',
            'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ک': 'k', 'گ': 'g', 'ل': 'l',
            'م': 'm', 'ن': 'n', 'ں': 'n', 'و': 'w', 'ہ': 'h', 'ھ': 'h',
            'ء': '', 'ی': 'y', 'ے': 'e', 'ئ': 'y', 'ؤ': 'w',
            'ً': 'an', 'ٌ': 'un', 'ٍ': 'in', 'َ': 'a', 'ُ': 'u', 'ِ': 'i',
            'ّ': '', 'ْ': '', 'ٰ': 'a',
            'آ': 'aa', 'إ': 'i', 'أ': 'a',
        }
        result = []
        for char in text:
            if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F':
                result.append(mapping.get(char, ''))
            else:
                result.append(char)
        return ''.join(result)

    def _transcribe_google(self, raw_data: bytes, language: str, skip_history: bool = False) -> str:
        processed_data = self._preprocess_audio(raw_data, self.rate, for_whisper=False)
        audio = sr.AudioData(processed_data, 16000, self.sample_width)

        print(f"[Audio] Transcribing with Google ({language})...")
        try:
            # CRITICAL: Add timeout to prevent indefinite freezes
            # Google API can hang on slow networks without timeout
            import threading
            result = [None]  # Use list to avoid nonlocal issues
            error = [None]

            def transcribe_with_timeout():
                try:
                    result[0] = self.recognizer.recognize_google(audio, language=language, show_all=False)
                except sr.UnknownValueError:
                    error[0] = "unknown"
                except sr.RequestError as e:
                    error[0] = str(e)
                except Exception as e:
                    error[0] = f"timeout: {e}"

            thread = threading.Thread(target=transcribe_with_timeout)
            thread.daemon = True
            thread.start()
            thread.join(timeout=30.0)  # 30-second timeout

            if thread.is_alive():
                print("[Audio] Google transcription timeout (30s) - network too slow")
                return ""

            if error[0]:
                if error[0] == "unknown":
                    print("[Audio] Google could not understand audio.")
                else:
                    print(f"[Audio] Google request failed: {error[0]}")
                return ""

            text = result[0] if result[0] else ""
        except Exception as e:
            print(f"[Audio] Google transcription error: {e}")
            return ""

        if text:
            print(f"[Audio] Raw Google result: {text}")
            logged_lang = language
            if language == 'hi-IN':
                text = self._transliterate_to_roman(text)
                print(f"[Audio] Transliterated: {text}")
                logged_lang = 'xx-HI'
            text = self._post_process_transcription(text)
            if not skip_history:
                self.log_history(text, logged_lang)
        else:
            print("[Audio] No speech detected.")
        return text


    def log_history(self, text: str, lang: str) -> None:
        """Append a transcription entry to history.json atomically.

        Uses config.atomic_json_* under per-path RLock — safe for concurrent
        callers (GUI clear vs audio thread append).
        """
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "lang": lang,
        }
        history_path = config._get_history_path()
        with config._lock_for(history_path):
            history = config.atomic_json_read(history_path, default=[])
            if not isinstance(history, list):
                history = []
            history.append(entry)
            if len(history) > config.MAX_HISTORY:
                history = history[-config.MAX_HISTORY:]
            if config.atomic_json_write(history_path, history):
                print(f"[Audio] History updated ({len(history)} entries)")

    def reload_whisper_model(self) -> None:
        self._whisper_model = None
        print("[Audio] Whisper model will be reloaded on next use.")

    def download_model_now(self, progress_cb: Optional[Callable[[int, str], None]] = None) -> bool:
        """Download Whisper model. progress_cb(mb_downloaded, status_text) is
        called from a poller thread roughly every 500ms during download.
        """
        model_size = config.WHISPER_MODEL
        print(f"[Audio] Downloading Whisper model '{model_size}'...")

        # Start a disk-poller that watches the HF cache dir size growing
        stop = threading.Event()
        poller = None
        if progress_cb:
            poller = threading.Thread(
                target=self._poll_download_progress,
                args=(self._hf_cache_root(), stop, progress_cb, f"Whisper {model_size}"),
                daemon=True,
            )
            poller.start()

        try:
            from faster_whisper import WhisperModel
            self._whisper_model = WhisperModel(
                model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            print(f"[Audio] Whisper model '{model_size}' downloaded and loaded.")
            return True
        except Exception as e:
            print(f"[Audio] Failed to download: {e}")
            self._whisper_model = None
            return False
        finally:
            stop.set()
            if poller:
                poller.join(timeout=2.0)

    @staticmethod
    def _hf_cache_root() -> str:
        """Root of the HuggingFace Hub cache (where snapshots land)."""
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")

    @staticmethod
    def _dir_size_mb(path: str) -> float:
        """Total size of a directory tree in MB. Safe for missing dirs."""
        if not os.path.isdir(path):
            return 0.0
        total = 0
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total / (1024 * 1024)

    @staticmethod
    def _poll_download_progress(watch_dir: str, stop_event: threading.Event, callback: Callable[[float, str], None], label: str) -> None:
        """Periodically report download progress by polling directory size."""
        baseline = AudioEngine._dir_size_mb(watch_dir)
        while not stop_event.is_set():
            current = AudioEngine._dir_size_mb(watch_dir)
            delta = current - baseline
            if delta > 0:
                callback(delta, f"{label}: {delta:.1f} MB downloaded...")
            stop_event.wait(0.5)

    def kill_stream(self) -> None:
        """Gracefully shut down audio stream with verification and retry."""
        self._stop_engine_event.set()
        try:
            # Wait for background listener to stop
            if self._bg_listener_thread:
                self._bg_listener_thread.join(timeout=2.0)
                if self._bg_listener_thread.is_alive():
                    print("[Audio] Background listener did not stop cleanly")

            # Stop and close stream with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                if not hasattr(self, 'stream') or self.stream is None:
                    break
                try:
                    if self.stream.is_active():
                        try:
                            self.stream.stop_stream()
                        except Exception:
                            pass
                    self.stream.close()
                    self.stream = None
                    print(f"[Audio] Stream closed successfully (attempt {attempt + 1})")
                    break
                except AttributeError:
                    # stream doesn't exist yet
                    break
                except Exception as e:
                    print(f"[Audio] Error closing stream (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        print("[Audio] Failed to close stream after max retries, forcing None")
                        self.stream = None
                    else:
                        time.sleep(0.1)

            # Terminate PyAudio instance with retry
            for attempt in range(max_retries):
                if not hasattr(self, 'p') or self.p is None:
                    break
                try:
                    self.p.terminate()
                    self.p = None
                    print(f"[Audio] PyAudio terminated successfully (attempt {attempt + 1})")
                    break
                except AttributeError:
                    # p doesn't exist yet
                    break
                except Exception as e:
                    print(f"[Audio] Error terminating PyAudio (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        print("[Audio] Failed to terminate PyAudio after max retries")
                        self.p = None
                    else:
                        time.sleep(0.1)

            print("[Audio] Stream shutdown complete")
        except Exception as e:
            print(f"[Audio] Unexpected error in kill_stream: {e}")

    def reconnect_mic(self) -> bool:
        """Surgically re-initializes audio capture without restarting the app."""
        print("[Audio] Attempting mic reconnection...")
        try:
            self.kill_stream()
            self._stop_engine_event.clear()
            self._init_audio()
            self._start_bg_listener()
            return True
        except Exception as e:
            print(f"[Audio] Reconnection failed: {e}")
            return False

    def check_health(self) -> bool:
        """Health check for the background listener. Returns True if alive."""
        if self._bg_listener_thread and not self._bg_listener_thread.is_alive():
            print("[Audio] Background listener died. Restarting...")
            self._start_bg_listener()
            return False
        return True


    # Pre-clean map for Devanagari marks ITRANS doesn't render cleanly.
    # Applied before transliterate() to prevent raw Devanagari leakage
    # (e.g. "सॉन्ड" -> "saॉnda" without preclean).
    _DEVA_PRECLEAN = {
        'ॅ': 'ा',  # chandra-E sign  -> aa-matra
        'ॉ': 'ो',  # chandra-O sign  -> o-matra
        'ॲ': 'a',       # candra-A letter -> latin 'a'
        'ँ': 'n',       # chandrabindu    -> n
        'ं': 'n',       # anusvara        -> n
        '़': '',        # nukta — drop, ITRANS handles base char
    }
    _DEVA_PRECLEAN_TABLE = str.maketrans(_DEVA_PRECLEAN)

    @staticmethod
    def _transliterate_to_roman(text: str) -> str:
        """Devanagari (Hindi script) -> natural Hinglish Roman via ITRANS.

        Pre-cleans Devanagari marks (chandra vowels, anusvara, nukta) that
        ITRANS doesn't handle, so they don't leak into the Roman output.
        Strips ITRANS dot-prefixed retroflex/nasal markers.
        """
        if not any('\u0900' <= char <= '\u097f' for char in text):
            return text

        try:
            # Pre-clean Devanagari marks ITRANS doesn't handle
            pre = text.translate(AudioEngine._DEVA_PRECLEAN_TABLE)
            res = transliterate(pre, sanscript.DEVANAGARI, sanscript.ITRANS)
            res = res.lower()
            # Strip ITRANS dot-prefixed markers (.d, .n, .t etc.)
            res = _RE_ITRANS_DOT.sub(r'\1', res)
            # Strip svarita (^), tilde (~), grave (`)
            res = _RE_ITRANS_MARKS.sub('', res)
            # Last-ditch: drop any Devanagari that survived
            res = _RE_DEVA_LEAK.sub('', res)
            return res
        except Exception as e:
            print(f"[Audio] Transliteration error: {e}")
            return text

def is_whisper_model_downloaded(model_size):
    """Check if a given Whisper model is already cached locally."""
    try:
        from faster_whisper.utils import download_model
        download_model(model_size, local_files_only=True)
        return True
    except Exception:
        return False


def is_zero_stt_downloaded():
    """Check if zero-stt-hinglish model is already converted locally."""
    return os.path.exists(os.path.join(config.ZERO_STT_MODEL_PATH, "model.bin"))
