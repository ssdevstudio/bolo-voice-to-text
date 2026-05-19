BILD — PRODUCT REQUIREMENTS DOCUMENT
Voice-to-Text for India
Version 1.0 | May 2025 | CONFIDENTIAL
======================================================================


1. EXECUTIVE SUMMARY
======================================================================

Bild is a lightweight, always-available voice-to-text desktop application
built specifically for Indian laptop users. It eliminates the friction of
switching to a dedicated dictation application by injecting transcribed text
directly into whatever input field is currently active — email clients,
browsers, IDEs, chat apps, document editors, and beyond.

The core interaction is deliberately minimal: hold the Right Alt key to speak,
release to commit. Bild handles the rest — language detection, real-time
transcription, and seamless text insertion — invisibly and instantly.

Unlike generic Western speech-to-text tools, Bild is engineered from the ground
up for India's linguistic landscape, providing accurate, low-latency
transcription across all 22 constitutionally recognised Indian languages plus
Hinglish (Hindi-English code-switching) — the way Indians actually communicate.

  Problem                      Market Gap                       Bild's Answer
  --------------------------   ------------------------------   --------------------------------
  Typing in Indian scripts     Existing STT tools have poor     Real-time, accent-aware,
  on laptops is slow and       accuracy for Indian accents      multilingual transcription with
  error-prone.                 and mixed language.              a single hotkey.

  Users must alt-tab to        No mainstream tool supports      Works inside any focused input
  dictation apps, breaking     Hinglish or code-switching.      — zero app switching required.
  workflow.

  Voice features built into    Right Alt is unused in Indian    Right Alt long-press —
  Western keyboards don't      laptop layouts, making it        ergonomic, conflict-free,
  map to Indian usage.         ideal for repurposing.           universal.


2. PRODUCT OVERVIEW
======================================================================

2.1  Product Identity
----------------------------------------------------------------------

  Attribute        Detail
  ---------------  ------------------------------------------------------------
  Product Name     Bild
  Platform         Windows 10/11 (v1.0); macOS 13+, Linux Ubuntu 22.04+ (v1.x)
  Distribution     Standalone installer (.exe / .dmg / .AppImage) and app stores
  Pricing Model    Freemium — Free tier (limited minutes/day); Pro tier
                   (unlimited, offline model, premium languages)
  Primary Users    Knowledge workers, students, content creators, professionals
  Connectivity     Online (cloud ASR) with optional offline model download (Pro)

2.2  Design Philosophy
----------------------------------------------------------------------

  - Invisible when idle — no dock icon, no persistent window, no interruptions.
  - Single-gesture activation — no menus, no clicks, no mode switching.
  - India-first accuracy — trained on Indian English accents, regional scripts,
    and code-switched speech.
  - Privacy by default — audio is processed and immediately discarded; no
    persistent voice storage on servers.
  - Progressive disclosure — advanced settings available but never required for
    basic use.


3. TARGET USER PERSONAS
======================================================================

Persona A — Priya, Corporate Professional
  Profile:     34-year-old sales manager, Mumbai. Writes 100+ emails/day in
               English and Hindi.
  Pain Point:  Typing Hindi on an English-layout keyboard is slow and
               frustrating.
  Bild Value:  Dictates emails in Hinglish; they appear correctly in the email
               client.
  Success:     Email composition time drops by 40%.

Persona B — Arjun, Student / Creator
  Profile:     21-year-old engineering student, Bhopal. Takes notes, writes
               assignments, codes.
  Pain Point:  Switches languages constantly; no tool keeps up with Hinglish.
  Bild Value:  Notes lectures verbatim in whatever language the professor uses.
  Success:     Note-taking accuracy in regional language improves to 90%+.

Persona C — Dr. Meera, Medical Professional
  Profile:     47-year-old physician, Chennai. Writes patient notes and
               prescriptions.
  Pain Point:  Cannot type Tamil and English medical terms quickly enough
               between patients.
  Bild Value:  Dictates notes in Tamil/English mix directly into HIS software.
  Success:     Patient throughput increases; documentation errors reduce.

Persona D — Ravi, Vernacular Content Creator
  Profile:     29-year-old YouTuber, Jaipur. Scripts content in
               Rajasthani-Hindi mix.
  Pain Point:  Typing Rajasthani dialect is unsupported in most keyboards.
  Bild Value:  Speaks naturally; Bild transcribes dialect-accurate scripts.
  Success:     Scripting time cut by 60%; more content published per week.


4. FUNCTIONAL REQUIREMENTS
======================================================================

FR-001 — Hotkey Activation
----------------------------------------------------------------------

FR-001-01   Right Alt key held for >= 500 ms initiates a recording session.
            Shorter presses are ignored (pass-through to OS).

FR-001-02   Recording is active for the entire duration the key is held.
            Releasing the key ends the session and commits transcription.

FR-001-03   The system tray icon changes state (idle -> recording) within
            100 ms of activation to provide immediate visual feedback.

FR-001-04   An optional subtle audio cue (activation beep, <= 30 dBSPL) is
            played on session start and end. This must be toggleable.

FR-001-05   If no focused input field is detected, Bild buffers the transcribed
            text in an internal clipboard and shows a notification.

FR-001-06   Hotkey long-press threshold is user-configurable (200 ms – 2000 ms)
            with a default of 500 ms.


FR-002 — Focus Detection & Text Injection
----------------------------------------------------------------------

FR-002-01   Bild must use OS accessibility APIs (UIAutomation on Windows,
            AXUIElement on macOS) to identify the currently focused editable
            control.

FR-002-02   Transcribed text must be injected at the current cursor position
            within the focused control, preserving all existing text.

FR-002-03   Injection method must fall back gracefully:
              (1) Accessibility API direct insert
              (2) Clipboard paste simulation
              (3) Keyboard event simulation

FR-002-04   Bild must correctly handle rich text editors (Google Docs, Word,
            Notion), plain text fields, browser address bars, and terminal
            inputs.

FR-002-05   In environments where direct API injection fails, a floating Bild
            text bar appears near the cursor; the user copies text with one
            click.


FR-003 — Speech Recognition & Transcription Engine
----------------------------------------------------------------------

FR-003-01   Streaming (real-time) transcription must begin within 300 ms of
            the first detected syllable.

FR-003-02   The engine must support all 22 scheduled Indian languages (see
            Section 5) plus Hinglish with seamless mid-utterance language
            switching.

FR-003-03   Interim (partial) transcription results must be displayed in the
            floating status bar as the user speaks.

FR-003-04   Final transcription is committed to the input field only upon key
            release, to avoid injecting partial text.

FR-003-05   Automatic punctuation insertion must be supported (full stop,
            comma, question mark) based on prosodic pause length and
            intonation.

FR-003-06   Spoken commands — "new line", "full stop", "comma",
            "delete last word" — in English and the active language must
            be supported.

FR-003-07   Word Error Rate (WER) must be <= 8% for standard Indian English
            and <= 12% for regional language utterances in controlled test
            conditions.

FR-003-08   The engine must adapt to user vocabulary over time using a local
            personalisation model (on-device; personal lexicon never uploaded).


FR-004 — Language Management
----------------------------------------------------------------------

FR-004-01   Users must be able to pin up to 5 languages as "active". Bild
            auto-detects within pinned languages per utterance.

FR-004-02   Manual language override is accessible via system tray right-click
            within 2 clicks.

FR-004-03   Hinglish mode must be a first-class option alongside individual
            language selections, not an afterthought toggle.

FR-004-04   Script output follows Unicode standards: Devanagari, Bengali
            script, Tamil script, etc. Transliteration is opt-in per language.

FR-004-05   Language model files for offline usage must be downloadable
            individually and stored locally to avoid re-download.


FR-005 — User Interface & System Tray
----------------------------------------------------------------------

FR-005-01   Bild's primary UI is a system tray icon with a context menu. No
            persistent main window is shown during normal use.

FR-005-02   A non-intrusive floating status bar appears near the bottom of the
            screen during active recording, showing:
              - Language detected
              - Real-time interim transcription text
              - Recording duration

FR-005-03   The floating bar auto-dismisses 1.5 seconds after key release.
            It must not steal keyboard focus.

FR-005-04   A Settings panel (tray menu) must expose:
              - Active language selection
              - Hotkey threshold
              - Audio cue toggle
              - Auto-punctuation toggle
              - Offline model management
              - Account and subscription status

FR-005-05   On first launch, an onboarding flow (<= 4 screens) guides the user
            through language selection, microphone permission, and a live
            practice session.


FR-006 — History & Correction
----------------------------------------------------------------------

FR-006-01   Bild maintains a local session history of the last 50
            transcriptions. Each entry stores: timestamp, language, raw text,
            destination app.

FR-006-02   A quick-access history panel (tray menu -> "History") lets users
            re-copy any past transcription.

FR-006-03   Undo hotkey (Ctrl+Z within 5 seconds of injection) must remove the
            last transcription block from the focused input.

FR-006-04   History is stored locally and is never transmitted to Bild servers.
            Users can clear history from Settings.


5. LANGUAGE SUPPORT MATRIX
======================================================================

All 22 languages listed in the Eighth Schedule of the Indian Constitution plus
Hinglish are supported as first-class transcription targets.

  Language              Script / Output            Speakers     V1.0     Offline
  --------------------  -------------------------  -----------  -------  -------
  Hindi                 Devanagari                 600 M+       GA       Yes
  English (Indian)      Latin                      125 M+       GA       Yes
  Hinglish              Devanagari + Latin          350 M+       GA       Yes
  Bengali               Bengali script             100 M+       GA       Yes
  Telugu                Telugu script              85 M+        GA       Yes
  Marathi               Devanagari                 83 M+        GA       Yes
  Tamil                 Tamil script               78 M+        GA       Yes
  Gujarati              Gujarati script            60 M+        GA       Yes
  Kannada               Kannada script             58 M+        GA       Yes
  Malayalam             Malayalam script           38 M+        GA       Yes
  Odia                  Odia script                35 M+        GA       Yes
  Punjabi               Gurmukhi                   32 M+        GA       Yes
  Assamese              Bengali-Assamese script    15 M+        Beta     Roadmap
  Maithili              Devanagari / Mithilakshar  13 M+        Beta     Roadmap
  Santali               Ol Chiki                   7.6 M+       Beta     Roadmap
  Kashmiri              Nastaliq / Devanagari      6.8 M+       Beta     Roadmap
  Nepali                Devanagari                 2.9 M+       Beta     Roadmap
  Sindhi                Devanagari / Perso-Arabic  2.5 M+       Beta     Roadmap
  Dogri                 Devanagari                 2.6 M+       Beta     Roadmap
  Manipuri (Meitei)     Meitei Mayek               1.8 M+       Beta     Roadmap
  Bodo                  Devanagari                 1.4 M+       Beta     Roadmap
  Konkani               Devanagari                 2.3 M+       Beta     Roadmap
  Sanskrit              Devanagari                 Ceremonial   Beta     Roadmap

Note: GA = Generally Available at launch. Beta languages are feature-complete
but undergo ongoing model improvements based on user feedback.


6. NON-FUNCTIONAL REQUIREMENTS
======================================================================

6.1  Performance Targets
----------------------------------------------------------------------

  Metric                              Target           Measurement
  ----------------------------------  ---------------  --------------------------------
  Hotkey to recording start           <= 100 ms        OS event timestamp diff
  First word transcription latency    <= 300 ms        Synthetic audio benchmark
  Text injection latency (p95)        <= 200 ms        Automated UI test harness
  Idle CPU usage                      < 0.1%           Task Manager / Activity Monitor
  Active recording CPU usage          < 8% (2-core)    Profiler instrumentation
  RAM footprint (idle)                < 80 MB          Process Monitor
  Offline model size (per language)   < 300 MB         Package measurement

6.2  Reliability & Availability
----------------------------------------------------------------------

  - Application uptime: 99.5% during active user sessions (excluding OS/
    hardware faults).
  - Crash recovery: on crash, Bild auto-restarts within 3 seconds. In-progress
    transcription is preserved.
  - Network interruption: if cloud ASR becomes unavailable, Bild falls back to
    cached/offline model (if available) or displays a clear "offline" indicator.
  - Minimum supported hardware: 4 GB RAM, dual-core 2.0 GHz, Windows 10 21H2+.

6.3  Security & Privacy
----------------------------------------------------------------------

  - Audio data is streamed over TLS 1.3 to Bild's ASR endpoint and is not
    persisted on Bild's servers.
  - No audio recordings, voice prints, or personal transcription history leave
    the device.
  - API keys for the cloud ASR backend are stored in the OS credential store
    (Windows Credential Manager / macOS Keychain), never in plain config files.
  - The application requests only microphone permission at OS level; no camera,
    location, or contact access.
  - Local transcription history is encrypted at rest using AES-256 with a key
    derived from the OS user account.
  - Bild complies with the DPDP Act 2023 (India's Digital Personal Data
    Protection Act).

6.4  Accessibility
----------------------------------------------------------------------

  - Floating status bar must meet WCAG 2.1 AA contrast ratio requirements.
  - All tray menu actions must be navigable via keyboard (Tab + Enter).
  - Screen reader compatibility (NVDA on Windows, VoiceOver on macOS) must be
    maintained for the Settings panel.


7. KEY USER FLOWS
======================================================================

7.1  First-Time Setup Flow
----------------------------------------------------------------------

  Step 1   User installs Bild and launches.
           -> Onboarding wizard opens. App requests microphone permission.

  Step 2   User grants microphone permission.
           -> Permission stored. App moves to language selection screen.

  Step 3   User selects up to 3 primary languages (e.g. Hindi, English,
           Hinglish).
           -> Languages pinned. Offline model download offered.

  Step 4   User completes practice session (reads sample sentence aloud).
           -> Transcription accuracy feedback shown. Setup marked complete.

  Step 5   Wizard closes.
           -> Bild minimises to system tray. Ready state.

7.2  Primary Dictation Flow
----------------------------------------------------------------------

  Step 1   User clicks into any input field (e.g. Gmail compose box).
           -> OS focus captured. Bild detects active input; tray icon shows
              "ready".

  Step 2   User holds Right Alt key for >= 500 ms.
           -> Recording session begins. Floating status bar appears. Audio cue
              played.

  Step 3   User speaks naturally (any supported language or Hinglish mix).
           -> Real-time interim transcription displayed in floating bar.
              Language auto-detected.

  Step 4   User releases Right Alt key.
           -> Recording ends. Final transcription committed to focused input
              field at cursor position.

  Step 5   User continues typing or speaks again.
           -> No interference. Repeat from Step 2 as needed.


8. TECHNICAL ARCHITECTURE OVERVIEW
======================================================================

8.1  Component Breakdown
----------------------------------------------------------------------

  Component             Responsibility                          Tech Stack
  --------------------  --------------------------------------  --------------------------
  Input Monitor         Intercepts OS keyboard events;          C++ (Windows Hook API),
                        detects Right Alt long-press            Swift (CGEvent, macOS)
  Audio Capture         Opens microphone stream at 16 kHz,      PortAudio / CoreAudio /
                        16-bit mono                             WASAPI
  ASR Engine (Cloud)    Streams audio, returns streaming        gRPC -> Bild ASR service
                        transcription                           (Whisper-based + IndicASR)
  ASR Engine (Offline)  Local on-device model for Pro tier      ONNX Runtime + quantised
                                                                Whisper / MMS model
  Language Detector     Identifies active language per          FastText LangDetect,
                        utterance                               IndicLID
  Text Injector         Writes text into focused OS input       UIAutomation (Win),
                        field                                   AXUIElement (macOS)
  Local Personaliser    Fine-tunes vocabulary to user patterns  SQLite lexicon + n-gram LM
  System Tray UI        Icon, context menu, settings panel      Tauri (Rust + WebView2)
  Floating Status Bar   Real-time transcription display         DirectComposition (Win) /
                        overlay                                 CALayer (macOS)
  History Store         Encrypted local transcription log       SQLite + SQLCipher (AES-256)

8.2  ASR Engine — Indian Language Support
----------------------------------------------------------------------

Bild's ASR backend combines four model families:

  1. OpenAI Whisper (large-v3)
     Fine-tuned on Indian English, Hindi, and major Dravidian languages using
     IndicVoices and IISc corpora.

  2. Meta MMS (Massively Multilingual Speech)
     Covers low-resource scheduled languages including Santali, Bodo, Dogri,
     and Manipuri.

  3. IndicASR (AI4Bharat)
     State-of-the-art models trained specifically on Indian language speech;
     primary engine for 14 major regional languages.

  4. Hinglish Code-Switching Model
     Custom bilingual model trained on Hinglish social media, call-centre, and
     conversational corpora.


9. SUCCESS METRICS & KPIs
======================================================================

  Metric                    Definition                           3 Months   12 Months
  ------------------------  -----------------------------------  ---------  ---------
  DAU / MAU Ratio           Daily vs monthly active users        >= 35%     >= 50%
  Dictation Success Rate    Sessions with error-free injection   >= 92%     >= 97%
  WER — Indian English      Word error rate on benchmark set     <= 8%      <= 5%
  WER — Regional Languages  Word error rate on benchmark set     <= 14%     <= 10%
  Activation Latency (p95)  Key press to recording start         <= 120 ms  <= 100 ms
  Transcription Latency     Key release to text in field (p95)   <= 400 ms  <= 250 ms
  App Crash Rate            Crashes per 1,000 sessions           < 2        < 0.5
  Pro Conversion Rate       Free users converting to Pro         >= 5%      >= 12%
  NPS                       Net Promoter Score                   >= 35      >= 55
  Retention (D30)           Users active 30 days after install   >= 30%     >= 45%


10. PRODUCT ROADMAP
======================================================================

  v1.0 — GA  |  Q3 2025
  Right Alt hotkey activation, 12 GA languages + Hinglish, cloud ASR,
  real-time injection, system tray UI, Windows 11 support, freemium model.

  v1.1  |  Q4 2025
  Offline model download (Pro), remaining 10 Beta languages, macOS 13+ support,
  auto-punctuation improvements, D30 retention optimisations.

  v1.2  |  Q1 2026
  Custom vocabulary / glossary (Pro), dictation shortcuts (voice commands for
  formatting), Hinglish model v2, Linux AppImage.

  v2.0  |  Q2 2026
  AI post-processing layer (grammar correction, filler word removal), API access
  for enterprise, multilingual document mode, team shared vocabulary (Enterprise
  tier).

  v2.x  |  H2 2026
  Browser extension (Chrome, Firefox, Edge), integration with productivity
  suites (Notion, Slack), custom wake-word option (replace Right Alt), regional
  dialect sub-models.


11. RISKS & MITIGATIONS
======================================================================

  Risk                                              Severity  Mitigation
  ------------------------------------------------  --------  ------------------------------------
  Poor ASR accuracy for low-resource languages      HIGH      Partner with AI4Bharat; launch Beta
  at launch                                                   languages with accuracy disclaimers;
                                                              integrate user correction feedback.

  Right Alt key conflict with existing OS           MEDIUM    Detect keyboard locale; disable
  shortcuts (e.g. AltGr on EU keyboards)                      AltGr pass-through only on Indian
                                                              keyboard layouts; provide hotkey
                                                              remapping in Settings.

  Text injection failures in non-standard apps      MEDIUM    Three-tier fallback injection
  (Electron, Java Swing, etc.)                                strategy (FR-002-03); app-specific
                                                              override list maintained post-launch.

  User privacy concerns about microphone access     HIGH      On-premise audio processing promise;
                                                              no audio stored server-side;
                                                              transparent privacy dashboard;
                                                              independent third-party audit.

  Background battery drain on laptops               LOW       Voice Activity Detection (VAD)
                                                              suspends engine when microphone is
                                                              silent; idle CPU < 0.1% enforced.

  Competition from OS-native speech input           MEDIUM    Differentiate on Indian language
  (Windows Speech Recognition, Apple Dictation)               breadth, Hinglish, and seamless
                                                              third-party app injection; build
                                                              community flywheel.


12. OPEN QUESTIONS & DECISIONS REQUIRED
======================================================================

  #  Question                                                   Owner              Due
  -  ---------------------------------------------------------  -----------------  ----------
  1  Should Bild support custom hotkey remapping in v1.0 or    PM + Engineering   Sprint 2
     defer to v1.1?

  2  Which cloud ASR provider(s) will be used as primary and   CTO                Sprint 1
     fallback? (AWS Transcribe / Azure AI Speech / Bild-hosted)

  3  What is the free-tier minute cap per day to balance cost   PM + Finance       Sprint 3
     and conversion?

  4  Should Hinglish transliteration (Devanagari -> Latin) be  PM + Marketing     Sprint 2
     a free or Pro feature?

  5  How will we handle OS accessibility permission prompts on  Engineering +      Sprint 4
     macOS (privacy-sensitive)?                                 Legal


13. DOCUMENT APPROVALS
======================================================================

  Role                Name          Signature     Date
  ------------------  ------------  ------------  ------------
  Product Manager     ___________   ___________   ___________
  VP Engineering      ___________   ___________   ___________
  Head of Design      ___________   ___________   ___________
  Legal / Privacy     ___________   ___________   ___________
  CEO / Sponsor       ___________   ___________   ___________


======================================================================
Document Details
  Version:        1.0 (Initial Release)
  Status:         Draft — For Internal Review
  Date:           May 2025
  Classification: CONFIDENTIAL

(c) 2025 Bild. All Rights Reserved.
======================================================================
