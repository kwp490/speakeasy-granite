# Changelog

All notable changes to SpeakEasy AI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.0] - Advanced Settings Tab, Formatting Style & Settings Refactor

### Added
- **`formatting_style` setting** (`config.py`): new field with three values — `sentence_case` (default), `plain_text`, `preserve_spoken_wording`; validated and clamped in `Settings.validate()`
- **`AdvancedSettingsWidget`** (`settings_dialog.py`): new embeddable widget for developer/runtime controls (model path, inference timeout, silence threshold/margin, sample rate, clear-logs-on-exit); wired into the Developer Panel as a dedicated tab
- **Developer Panel "Advanced Settings" tab** (tab index 1): `AdvancedSettingsWidget` wrapped in a scroll area; signals wired to `reload_model_requested` and `settings_applied`; `TAB_ADVANCED = "advanced"` constant; tab count 5 → 6
- **`"advanced"` added to valid `dev_panel_active_tab` values**; tab key↔index maps updated for 6 tabs
- **`"auto"` language option** added to `GRANITE_LANGUAGES` and `Settings._VALID_LANGUAGES`; `auto` detected and validated correctly
- **`GRANITE_FORMATTING_STYLES`** constant in `settings_dialog.py`; formatting style combo in `SettingsWidget` Transcription Style section
- **Transcription Style section** in `SettingsWidget`: groups punctuation toggle + formatting style combo; separate from the Model section

### Changed
- **`SettingsWidget`** (user-facing tab) trimmed: model path browse, silence threshold/margin, sample rate, clear-logs-on-exit, and inference timeout moved to `AdvancedSettingsWidget`; task row label renamed "Mode:" → hidden `Translate to:` row when transcribe is selected (using `setVisible`)
- **`SettingsWidget.reload_model_requested`** now fires only on device change (model path is an Advanced setting); `_on_apply()` diff check simplified
- **`GraniteTranscribeEngine.configure_prompt_options()`** gains `formatting_style` parameter; `_build_user_prompt()` uses it to select plain-text or preserve-spoken-wording prompt wording
- **Granite prompt logic refactored**: the `elif keywords / elif punctuation / else` chain is replaced with cleaner branching; `plain_text` and `preserve_spoken_wording` style prompts added
- **`Settings._VALID_TRANSLATION_TARGETS`** updated — "Portuguese" removed (not supported by Granite 4.1); validation now checks against the set and falls back to "English"
- **`Settings._VALID_LANGUAGES`** added with explicit set; unknown language codes fall back to `"en"` with a warning
- **`main_window.py`** passes `formatting_style` to `configure_prompt_options()` before transcription
- **README** updated with `formatting_style` field, expanded language/translation notes, and Granite prompt-driven behavior description

### Tests
- `test_config.py`: added `formatting_style` round-trip, auto-language validation, invalid language/translation-target/formatting-style fallback tests
- `test_config_persistence.py`: default width/height values updated; `advanced` tab added to parametrize; all width/height assertions updated
- `test_developer_panel_live.py`: 5→6 tabs; tab indices shifted; advanced tab navigation tests added; `_advanced_settings_widget` signal tests added
- `test_developer_panel_window.py`: 5→6 `addTab` assertion
- `test_granite_transcribe.py`: tests for `plain_text`, `preserve_spoken_wording`, punctuation-off, translate-without-punctuation, and keyword prompt variants
- `test_main_window_layout.py`: window size assertions updated; layout minimum height relaxed to 490
- `test_settings_widget.py`: `advanced_settings_widget` fixture added; model path, sample rate, clear-logs, and reload signal tests moved to use advanced fixture; `formatting_style` deferred-apply test added

## [0.9.3] - Developer Panel Size Persistence Fix

### Fixed
- **`show_snapped()` now respects saved panel height**: previously always resized to `geom.height()` (main window height), ignoring `settings.dev_panel_height`; now uses `settings.dev_panel_height` so the panel restores to its last-saved size on re-open

### Changed
- **Default `dev_panel_width`** updated 600 → 629 px and **`dev_panel_height`** 720 → 1131 px to match observed real-world usage; clamp floor values updated to match

## [0.9.2] - Record Button Typography & Window Sizing

### Changed
- **Window size** reduced to minimum: 640×485, default resize 720×485 (single-screen height fit)
- **Record button title font** increased 13 → 16 pt; explicit `font-size: 16pt` in stylesheet
- **Record button label heights** pinned to `QFontMetrics.height()` so all three inline labels (title, dot, status) align on the same baseline
- **Status/dot font** increased 10 → 13 pt
- **Settings button** icon size 22 → 20 px; `GEAR_BUTTON` minimum width 68 → 76 px; gear style padding adjusted to `4px SM` with explicit `icon-size: 18px`

## [0.9.1] - Bug Fixes and Test Alignment

### Fixed
- **Duplicate `set_progress` call** in `_on_transcription_partial()` removed (called twice in v0.9.0)
- **Stray panel-toggle code** at the end of `_flush_history_buffer()` removed — the hide/show block was accidentally left in the method after the `_on_toggle_dev_panel()` refactor in v0.9.0, causing the panel to always open/close after flushing buffered history entries

### Changed
- **Tests updated** to reflect the v0.9.0 architecture:
  - `test_panel_has_four_tabs` → `test_panel_has_five_tabs` (both AST and live tests)
  - `_on_toggle_dev_panel` source checks changed to `_ensure_dev_panel` in `test_integration_full_flow.py` and `test_logging_buffer.py`
  - `test_history_section_exists` now checks `developer_panel.py` for `HistoryWidget` instead of `_build_ui` for `_history_layout`
  - `test_history_min_height_compact` replaced by `test_history_widget_has_scroll_area` (checks `history_widget.py`)
  - `test_clear_history_button_in_build_ui` replaced by `test_clear_history_button_in_history_widget`
  - `_history_entries()` helper updated to import `_HistoryEntry` from `history_widget` and read from `dev_panel.history_widget.history_layout`
  - `test_no_partial_creates_plain_entry` now calls `win._ensure_dev_panel()` first so the history layout exists
  - `mock_main_window` fixture adds `_on_clear_history` mock

## [0.9.0] - History Moved to Developer Panel Tab

### Added
- **`speakeasy/history_widget.py`**: new module containing `_WordWrapLabel`, `_HistoryEntry`, and `HistoryWidget`; `HistoryWidget` is a self-contained tab with a scroll area, Clear button, and `clear_requested` signal
- **Developer Panel History tab**: `DeveloperPanel` gains a fifth tab (🕒 History) backed by `HistoryWidget`; `TAB_HISTORY = "history"` constant added; tab index maps updated to support 5 tabs
- **`"history"` added to valid `dev_panel_active_tab` values** in `config.py`
- **History button** in the main window bottom row opens the Developer Panel directly to the History tab via `_on_show_history()`
- **`_ensure_dev_panel()`** extracted from `_on_toggle_dev_panel()` so panel creation can happen without immediately showing the panel (used when history entries arrive before the panel is opened)
- **`_history_buffer`**: pre-panel history entries are buffered and flushed into the History tab on first panel creation via `_flush_history_buffer()`

### Changed
- **`_HistoryEntry` and `_WordWrapLabel`** moved from `main_window.py` into `history_widget.py`; `main_window.py` imports them from there at call sites
- **Inline history section removed** from `_build_ui()`: the `History` `SectionPanel`, scroll area, toggle row, and Clear button inside the main window are gone; history lives exclusively in the Developer Panel tab
- **`_on_toggle_dev_panel()`** refactored to call `_ensure_dev_panel()` then toggle visibility, removing duplicated panel-creation code
- **`_active_draft_entry`** type annotation relaxed to bare `None` (no longer `Optional[_HistoryEntry]`) since the type is now imported lazily
- History entries are inserted into `hw.history_layout` / `hw.history_content` (Developer Panel) rather than `self._history_layout` / `self._history_widget`
- `_on_clear_history()` clears `_history_buffer` and delegates layout clearing to the panel's `HistoryWidget` if the panel exists

## [0.8.4] - Window Size & Layout Spacer Fix

### Changed
- **Window size** further reduced: minimum 640×620 → 640×600, default 720×720 → 720×640; window is now wider than it is tall
- **`root.addStretch()`** removed after History section so Quit sits flush below content instead of being pushed to the bottom of an expanding gap
- Tests updated to match new sizes and assert landscape aspect ratio

## [0.8.3] - Compact Layout Pass

### Changed
- **Window size** reduced: minimum 640×700 → 640×620, default resize 720×820 → 720×720
- **Root layout** margins/spacing tightened: `LG/SECTION` → `MD/MD`
- **Record button**: icon 30 → 26 px; internal spacing `LG/MD` → `MD/SM`; removed redundant `setFixedSize` on gear button (now uses `setMinimumSize` + `setMaximumSize` only)
- **Status bar container** minimum height 52 → `STATUS_CARD_MIN_HEIGHT` (44 px); internal padding `LG/SM` → `MD/XS`; separator height 34 → 28 px; icon size 22 → 20 px
- **`SIZE` constants**: `BUTTON_HEIGHT_PRIMARY` 64 → 56 px; `GEAR_BUTTON` 76 → 68 px; `STATUS_CARD_MIN_HEIGHT` 52 → 44 px
- **`make_section_panel()`** margins/spacing `LG/MD` → `MD/SM`
- **`make_setting_row()`** separator height and outer spacing use `XS` instead of `SM`
- **`make_bounded_content()`** inner spacing `MD` → `XS`
- **`make_action_row()`** height 36 → 32 px
- **`primary_button_style()`** padding `SM/LG` → `XS/MD`
- **Profile combo** in Transcription Mode section placed in a fixed-height `QHBoxLayout` row alongside a "Profile" label instead of two separate stacked widgets
- **`_chk_professional`** constructed without label text (`ToggleSwitch()` instead of `ToggleSwitch("Enable")`) — label is supplied by the `make_setting_row` call
- **Clear History button** uses default style + `setMinimumHeight` instead of `primary_button_style()`
- **History scroll area** minimum height 200 → 120 px
- **Tests updated**: layout assertions aligned to new sizes and API (`test_main_window_layout.py`, `test_developer_panel_window.py`, `test_developer_panel_live.py`)

## [0.8.2] - Record Button & Status Bar Refinements

### Changed
- **Record button layout** (`main_window.py`): icon size increased 20 → 30 px; title uses explicit 13 pt DemiBold font; status text uses 10 pt DemiBold; spacing between elements increased SM → MD
- **Record row** no longer wraps in `make_bounded_content()`; row widget is full-width with 5:1 stretch ratio between record button and settings button; settings button is now responsive (expands) rather than fixed-width
- `BUTTON_HEIGHT_PRIMARY` increased 52 → 64 px for more visual weight
- **Status bar separators** (`status_pills.py`): width 1 → 2 px, height 30 → 34 px; style changed from `color:` to `background-color:` so the separator actually renders as a filled line
- History section icon changed from `history-document` to `clock`

## [0.8.1] - Record Button State Machine & UI Polish

### Changed
- **Record button state machine** (`main_window.py`): replaced static text labels with a proper state-driven `_set_record_button_state()` method supporting `idle`, `recording`, `processing`, and `disabled` states; button now shows an icon, title, colored dot, and status text inside an `HBoxLayout` overlay
- **Record button** gains a `processing` state that disables the button and shows a spinner-style dot while the engine is transcribing
- **Status segment hover** (`status_pills.py`): clickable segments now show a subtle background on hover via QSS; layout alignment changed from `addStretch` bookends to `AlignCenter`
- **`primary_record_button_style()`** (`theme.py`): signature changed from `(recording, processing)` booleans to a single `state: str` parameter (`"idle"`, `"recording"`, `"processing"`, `"disabled"`); per-state border colors added
- **`gear_button_style()`**: button background changed from `transparent` to a subtle panel color with visible border for discoverability
- **`subtle_danger_button_style()`**: Quit button gains a faint red border and hover background
- **`make_bounded_content()`** helper extracted to `theme.py` for reuse in record-row and bottom-row centering
- **`make_separator()`** helper extracted to `theme.py` to eliminate duplicated `QFrame` setup
- **`make_section_panel()`** refactored to use `make_bounded_content()` internally
- **`make_action_row()`** default background changed from opaque panel to transparent with hover-only fill
- **Disabled input styles** added to global QSS for `QLineEdit`, `QComboBox`, `QSpinBox`, `QDoubleSpinBox`
- **History panel** is now collapsed by default; a `_on_toggle_history` slot toggles scroll area and Clear button visibility
- Main window `_build_ui` reorganized into named sections: Automation, Transcription Mode, History with `make_section_panel()` wrappers; `QGroupBox` for Professional Mode replaced
- `SIZE.BUTTON_HEIGHT_PRIMARY` reduced from 58 → 52 px

## [0.8.0] - UI Redesign, CUDA Thread Fix & Public Model Download

### Added
- **Compact status bar** (`status_pills.py`): replaced responsive card/pill layout with a single fixed-height bar containing three segments (Model, Mic, Mode) separated by vertical dividers; always compact, no layout switching
- **New theme helpers** (`theme.py`): `compact_status_bar_style()`, `section_panel_style()`, `primary_record_button_style()`, `subtle_danger_button_style()`, `make_setting_row()`, `make_section_panel()`, `make_action_row()` for a unified design system
- **New SVG icons**: clipboard, clock, document, history-document, keyboard, log-out, microphone-white, settings — shipped in `speakeasy/assets/icons/`
- **CUDA thread pre-creation fix** (`workers.py`, `__main__.py`): `DedicatedWorkerPool.warmup()` creates and parks the engine worker thread *before* torch/CUDA DLLs load, avoiding a Windows CUDA `DllMain(DLL_THREAD_ATTACH)` stack-corruption bug that caused access violations in innocent code
- **Engine cleanup improvements** (`engine/base.py`): calls `accelerate.hooks.remove_hook_from_submodules()` before model deletion; double `gc.collect()`; `torch.cuda.reset_peak_memory_stats()` on unload
- **pytest timeout** (`pyproject.toml`): added `pytest-timeout` dev dependency; global 120 s per-test timeout via `addopts`
- **Custom `tmp_path` fixture** (`conftest.py`): bypasses pytest's basetemp to avoid permission errors when a prior elevated process owns `%TEMP%\pytest-of-{user}\`

### Changed
- **Model download no longer requires a HuggingFace token**: `ibm-granite/granite-speech-4.1-2b` is a public model; all token prompts, password fields, and `HF_TOKEN` injection removed from installer scripts, Inno Setup pages, and `download-model` CLI help text
- **Installer GUID corrected**: uninstall registry keys in `Build-Installer.ps1` updated to match the actual Inno Setup `AppId` `{7B99C492-7E14-4E3A-A8F2-71F8B23D9A42}`
- **Installer welcome messages** updated with concrete system requirements (disk space, VRAM, RAM)
- **`engine_pool` parameter** added to `MainWindow.__init__` so the pre-warmed pool from `__main__.py` is reused rather than creating a second pool
- **`GraniteTranscribeEngine`**: top-level `import torch` and `transformers` imports (moved out of `load()`/`_transcribe_impl()` for clarity); `unload()` resets `_actual_device` to `"cpu"`; trailing newline added to file
- **Build script test runner**: removed `-n auto` (xdist) flag; added `PYTHONUNBUFFERED=1` for live output
- **README requirements**: added concrete disk/VRAM/RAM minimums
- **`test_build_naming.py`**: torch/torchaudio version tests now run in a subprocess to avoid CUDA daemon thread interference with pytest worker exit
- **`test_model_presence.py`**: removed slow/flaky runtime-dependency import tests (librosa, scipy, transformers) that triggered CUDA initialization in test workers

### Fixed
- `test_pro_mode_widget.py`: monkeypatched `DEFAULT_PRESETS_DIR` in `pro_mode_widget` module to fix preset-loading test isolation

## [0.7.1] - Hotkey Registration Fix for Frozen Builds

### Fixed
- **Global hotkeys not registering in frozen (PyInstaller) builds**: deferred Win32 `RegisterHotKey` by one event-loop tick via `QTimer.singleShot(0)` so the native HWND is stable after `show()`. Qt can recreate the window handle during `show()` in frozen builds, silently invalidating any hotkey registered earlier in `__init__`.

---

## [0.7.0] - Status Pill Bar, SVG Icons & UI Consistency

### Added
- **Responsive Status Pill Bar** (`status_pills.py`): new three-card status widget (AI Model, Dictation, Professional Mode) that adapts between card and compact pill layouts based on window width; cards are clickable and display animated pulsing dots during recording/processing
- **SVG icon system**: vector icons (brain, microphone, sparkles) for status cards with `load_icon()` helper in `theme.py` using `QSvgRenderer`; icons shipped in `speakeasy/assets/icons/`
- **GPU fallback detection**: `GraniteTranscribeEngine.actual_device` property reports device after model load; main window warns via status pill when GPU was requested but CPU was used
- **Theme helpers**: `status_card_style()`, `status_card_hover_style()`, `make_toggle_row()`, `PANEL_HOVER` color, `Spacing.SECTION`, `Size.STATUS_ICON_CARD/PILL`, `Size.STATUS_CARD/PILL_MIN_HEIGHT`, `Size.STATUS_LAYOUT_THRESHOLD`
- **Test audio isolation**: `_FakeAudioRecorder` mock in `conftest.py` prevents parallel xdist workers from opening real microphone streams

### Changed
- **Status display**: replaced HTML label (`_lbl_global_status`) with `StatusPillBar`; `DictationState` and `ModelStatus` enums gained `display` properties for readable text
- **Toggle switch standardization**: replaced all `QCheckBox` widgets in Settings and Pro Mode dialogs with `ToggleSwitch`; consistent `make_toggle_row()` layout across both UIs
- **Toggle switch sizing**: refined to 38×22 px with proportional 16 px knob (Material Design spec)
- **Input background**: changed from `#020617` to `#1F2937` (gray-800) for better contrast per UI spec
- **Build specs**: added `PySide6.QtSvg` to PyInstaller hidden imports; removed `Qt6Svg` from strip patterns so SVG icons render in frozen builds
- **Professional Mode settings**: accessible via embedded `ProModeWidget` in the settings panel rather than a separate modal dialog
- **Test isolation**: fixed `test_model_presence.py` librosa import test to avoid xdist deadlocks

### Removed
- `pro_settings_dialog.py` (595 lines) — modal Pro Mode dialog replaced by embedded widget
- `tests/test_pro_settings_dialog_ok.py` (230 lines) — tests for deleted dialog
- `_dot_segment()` helper — superseded by `StatusPillBar` methods

---

## [0.6.1] - ASR Throughput Instrumentation & Sparkline Enhancements

### Added
- **ASR throughput section** in Developer Panel Realtime tab: displays realtime factor, decoder token rate, total tokens, and total audio processed from the Granite engine
- **ASR sparkline**: plots realtime factor over time with a 1.0x reference line; uses sticky-max scaling to prevent visual creep during CUDA warm-up
- **Engine instrumentation** (`GraniteTranscribeEngine`): tracks per-chunk throughput counters (`token_stats` property) including inference sequence number for sparkline deduplication
- **LLM call sequence tracking** (`TextProcessor`): `token_stats` now returns a monotonic `call_seq` counter for consistent sparkline updates
- **Parallel test execution**: added `pytest-xdist` dev dependency; build script now runs `pytest -n auto`
- **Session-scoped QApplication fixture** in `conftest.py` for xdist worker isolation

### Changed
- **TokenSparkline** widget overhauled: sticky-max Y-axis scaling, configurable value units/format, optional horizontal reference line, current/max text overlay, border frame, and "awaiting samples" placeholder state
- **RealtimeDataWidget**: replaced audio input-level meter with dedicated ASR Throughput and LLM Throughput sections; both sparklines use spike-and-zero semantics with sequence-based deduplication
- **Main window resource monitor**: now forwards both ASR and LLM token stats to the Developer Panel on each poll tick; pushes engine state to panel on first open
- **Inno Setup**: added `LZMANumBlockThreads=8` for faster fast-compression dev builds

---

## [0.6.0] - Developer Panel & UI Overhaul

### Added
- **Developer Panel**: Snappable side window (toggle with **Ctrl+Alt+D**) with four tabs:
  - **Settings** — quick access to engine, audio, and UX settings via reusable `SettingsWidget`
  - **Realtime** — live engine status, RAM/VRAM progress bars, GPU metrics, and token throughput sparkline
  - **Logs** — scrollable read-only application log viewer with clear and copy buttons (500-block rolling buffer)
  - **Pro Mode** — embedded Professional Mode configuration (API key, presets, vocabulary)
- **Design token system** (`theme.py`): single source of truth for colors, typography, spacing, and stylesheet helpers
- **`RealtimeDataWidget`**: live engine monitoring with RAM/VRAM usage, GPU temperature/utilization, and reload/validate actions
- **`TokenSparkline`**: custom-painted line chart for real-time token throughput visualization
- **`LogsWidget`**: application log display with real-time streaming from `QtLogHandler`
- **`ProModeWidget`**: embeddable Professional Mode UI for API key, preset, and instruction management
- Six new developer panel settings: `dev_panel_open`, `dev_panel_active_tab`, `dev_panel_width`, `dev_panel_height`, `dev_panel_snapped`, `hotkey_dev_panel`
- Dev dependencies: `pytest-qt`, `pytest-cov`, `pytest-mock`
- Comprehensive test suite for Developer Panel, RealtimeDataWidget, TokenSparkline, LogsWidget, ProModeWidget, and SettingsWidget

### Changed
- **Settings Dialog**: simplified by extracting Professional Mode section into dedicated `ProSettingsDialog`; now focuses on engine, audio, and UX settings
- **Hotkey system**: added Developer Panel toggle hotkey (Ctrl+Alt+D) with `dev_panel_toggle_requested` signal
- **Main window**: refactored to manage Developer Panel lifecycle, snapping behavior, and state persistence

---

## [0.5.1] - Per-User Logs & Hardening

### Changed
- **Per-user log directory**: Logs now write to `%LOCALAPPDATA%\SpeakEasy AI Granite\logs`
  instead of the shared `%ProgramData%` path, preventing cross-user log access
  on shared machines. Dev/source mode (`SPEAKEASY_HOME`) is unchanged.
- **Audio resampling**: Replaced manual linear-interpolation resampler with
  `librosa.resample()` for higher-quality sample-rate conversion.

### Security
- **HuggingFace token masking**: The model-download token dialog now uses
  password echo mode so the token is not visible on screen.
- **Dependency auditing**: CI workflow runs `pip-audit --strict` on every push
  and PR to catch known-vulnerable dependencies.
- **Dependabot**: Automated weekly dependency update PRs for pip packages and
  GitHub Actions.

### Added
- **`RELEASE.md`**: Step-by-step release checklist (version bump → tag → publish).
- **`.github/dependabot.yml`**: Automated dependency update configuration.
- **`pip-audit`** added to dev dependencies.

### Removed
- Installer no longer creates or manages a shared `logs/` directory under
  `%ProgramData%\SpeakEasy AI Granite` — log storage is now per-user.

---

## [0.5.0] - Streaming Partials

### Added
- **Live-draft transcription**: long recordings (>30 s) now stream each internal
  transcription chunk into the history pane as soon as it is ready, instead of
  showing nothing until the entire recording has been transcribed. The draft
  entry is updated in place and replaced by the authoritative stitched text
  once the final chunk completes. Clipboard and auto-paste still fire exactly
  once, on the final result. Controlled by the new
  `streaming_partials_enabled` setting (default on; toggle in Settings)
- **`SpeechEngine` partial-callback contract**: `transcribe()` / `_transcribe_impl()`
  accept an optional `partial_callback(text, chunk_index, total_chunks)` which
  the Granite engine invokes after each chunk of a multi-chunk transcription;
  callback exceptions are logged and swallowed
- **`WorkerSignals.partial(str, int, int)`** signal for routing per-chunk
  updates from the engine worker to the UI thread via `Qt.QueuedConnection`

---

## [0.4.0] - RegisterHotKey & Privacy Disclosure

### Changed
- **Hotkey system rewrite**: Replaced the `keyboard` library (low-level `SetWindowsHookEx`
  hook) with the Win32 `RegisterHotKey` API — only the configured chord is delivered to the
  application; no global keyboard hook is installed
- **Auto-paste rewrite**: `simulate_paste()` now uses Win32 `keybd_event` instead of
  `keyboard.send()`, removing the last `keyboard` library dependency
- **Dependency removed**: `keyboard` package removed from `pyproject.toml`

### Added
- **Professional Mode data-privacy disclosure**: One-time dialog warns users that
  transcribed text is transmitted to `api.openai.com` under their personal API key
  before Professional Mode can be enabled (shown in both the main window toggle and
  the Pro Settings dialog)
- **`pro_disclosure_accepted`** setting persisted so the notice is shown only once

### Security
- **SECURITY.md** updated to reflect the new hotkey mechanism and corrected log/data paths
- **README.md** adds a data-privacy callout in the Professional Mode section

---

## [0.3.3] - Permission Fix

### Fixed
- **Log directory permissions**: Installer now grants the `Users` group write access
  to all `C:\ProgramData\SpeakEasy AI` subdirectories (`logs`, `config`, `temp`, `models`),
  fixing a `PermissionError: [Errno 13]` crash on first launch for standard (non-admin) accounts
- **Logging fallback**: App no longer crashes if the log file is unwritable; falls back to
  console-only logging so the application always starts

---

## [0.3.1] - CPU Build Fix

### Fixed
- **CPU build variant patching**: Moved `_build_variant.py` restore in `speakeasy-cpu.spec` from after `Analysis()` to after `PYZ()` so the frozen CPU build correctly has `VARIANT = "cpu"`
- **Settings dialog CUDA guard**: CPU edition now shows both device options in the dropdown but blocks CUDA selection with an inline warning and disables the OK button, preventing users from saving an invalid device setting

### Added
- **CPU build variant** (`speakeasy-cpu.spec`, `speakeasy-cpu-setup.iss`): smaller installer without CUDA/GPU dependencies
- **Build installer script**: `Install-SpeakEasy-Source.ps1` for automated source installs with GPU/CPU variant support
- **Copilot instructions**: `.github/copilot-instructions.md` for AI-assisted development

### Changed
- **Build system**: RAM disk acceleration (via [AIM Toolkit](https://sourceforge.net/projects/aim-toolkit/)), source-hash caching, and improved build pipeline
- **GPU monitor**: CPU variant gracefully skips GPU metrics

---

## [0.3.0] - Cohere-Only Release

### Changed
- **Single engine**: Replaced dual-engine architecture with Cohere Transcribe 03-2026 as the sole speech engine
- **HuggingFace token**: Installation now prompts for a HuggingFace API token (required for gated model access)
- **Punctuation control**: New setting replaces the legacy keywords field — toggle automatic punctuation on/off
- **Simplified settings**: Removed engine selection dropdown, streamlined UI
- **Language dropdown**: Settings now shows all 14 Cohere-supported languages in a dropdown

### Removed
- **Previous secondary speech engine** and all related code
- **Keywords** setting (replaced by punctuation toggle)
- **Engine selection** UI (single engine, no choice needed)

---

## [0.1.0] - Initial Release

### Added
- **Secondary compact speech engine** — 1B-parameter model, ~3 GB VRAM, 7 languages
- **Cohere Transcribe 03-2026** engine — high-accuracy 2B-parameter model, ~5 GB VRAM, 14 languages
- Both engines run via HuggingFace `transformers` — single-process, no subprocess bridge
- Automatic model download from HuggingFace Hub
- PySide6 (Qt) GUI with real-time resource monitoring (RAM, VRAM, GPU temperature)
- Global hotkeys (start/stop recording, quit) with sleep/wake recovery
- Auto-paste transcribed text into the active window
- Professional Mode with AI-powered text cleanup via OpenAI API
  - 5 built-in presets + custom presets
  - Domain vocabulary preservation
  - Per-preset model selection and custom system prompts
- Microphone device selection
- Single-instance guard (system mutex)
- PyInstaller binary distribution + Inno Setup installer
- Source install via `uv` + automated `Install-SpeakEasy-Source.ps1`
- Windows Defender exclusion configuration
