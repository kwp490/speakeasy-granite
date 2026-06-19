# Architecture

SpeakEasy AI Granite is a single PySide6 desktop app for Windows whose UI talks
to its speech engine through one transport-agnostic contract. The same interface
is satisfied by an in-process engine (the default, fully local) and by a remote
HTTP client, so "model on another computer" is an inference endpoint rather than
a network-filesystem hack.

## Layering

```text
+--------------------------------------------------------------+
|  speakeasy/ui/         PySide6 views + controllers           |
|    main_window, model_controller, dictation_controller,      |
|    metrics_bridge, developer_panel, settings, tooltips       |
+----------------------------+---------------------------------+
                             | depends only on the contract
                             v
+--------------------------------------------------------------+
|  speakeasy/core/       transport-agnostic contract           |
|    contract (TranscriptionService Protocol + dataclasses),   |
|    model_source, errors, wire, resample   (NO torch / Qt)    |
+----------------------------+---------------------------------+
                             | implemented by
            +----------------+-----------------+
            v                                  v
+---------------------------+      +---------------------------+
|  services/inprocess.py    |      |  services/remote_client.py|
|  wraps a local engine     |      |  HTTP -> services/server  |
+-------------+-------------+      +-------------+-------------+
              | drives                           ^
              v                                  | HTTP /v1
+---------------------------+                    |
|  engines/ (registry,fake) |      +---------------------------+
|  engine/granite_transcribe|<-----+  services/server.py       |
|  torch / transformers     |      |  serve() on the host      |
+---------------------------+      +---------------------------+
```

The dependency arrow points **one way**: the UI imports the `core` contract; the
service adapters implement it; only the engine layer imports the heavy ML stack.

### Layering rules (enforced by tests)

- **`core/`, `services/`, `engines/registry`, and `ui/` must not import
  `torch` / `transformers` / `librosa` / `accelerate` at module scope.** The
  Granite engine loads them lazily inside `load()` and the transcription methods.
  Enforced by [tests/test_ml_import_isolation.py](../tests/test_ml_import_isolation.py)
  (a subprocess meta-path blocker raises on those imports) and
  [tests/test_frozen_ml_isolation.py](../tests/test_frozen_ml_isolation.py) (AST
  checks of module scope).
- **`core/` must not import Qt.** It depends only on numpy.
- The UI never reaches into an engine directly; it holds a
  `core.contract.TranscriptionService` and speaks only its methods.

## The contract

[`speakeasy/core/contract.py`](../speakeasy/core/contract.py) defines
`TranscriptionService`, a `@runtime_checkable` `typing.Protocol`. Any object that
provides these methods satisfies it, in-process or remote:

| Method | Purpose |
| --- | --- |
| `descriptor()` | name / version / `is_remote` identity |
| `capabilities()` | languages, translation targets, formatting styles, devices, max clip seconds — the UI populates its combos from this |
| `load(source, device)` | load a model from a `ModelSource`; returns a `LoadReport` |
| `unload()` / `is_loaded()` | lifecycle |
| `transcribe(audio, options)` | one request; returns a `TranscriptionResult` |
| `health()` | readiness snapshot (`ok` / `model_missing` / `unreachable` / `not_loaded`) |
| `stats()` | cumulative `EngineStats` |

All payloads are frozen dataclasses (`TranscriptionOptions`,
`TranscriptionResult`, `EngineCapabilities`, `HealthReport`, `EngineStats`, …) so
they round-trip cleanly to JSON. Per-request parameters travel **with** the
request in `TranscriptionOptions` (no engine-state mutation side-channel).

`CONTRACT_VERSION` is an integer in `contract.py`, reported by the server's
`/v1/health` and verified by the remote client. It is independent of the app's
`__version__` and bumps only on incompatible contract changes.

### Model location

[`speakeasy/core/model_source.py`](../speakeasy/core/model_source.py) is a
discriminated union:

- `ManagedSource` — the app-managed models directory (default).
- `LocalDirSource` — a custom local folder or UNC/network path.
- `RemoteSource` — an `http(s)` SpeakEasy Server URL; the bearer token lives in
  the OS keyring and is referenced (never serialized) via `auth_token_ref`.

`Settings` keeps a resolved `model_path` mirror for backward compatibility, so a
0.14.5 `settings.json` migrates forward and a 0.15.0 file still boots 0.14.x. An
unreachable custom/UNC path is **preserved and flagged**, never silently reset.

## Threading model

- The Qt **main thread** owns all widgets, clipboard writes, and paste
  simulation.
- A **dedicated engine worker** (`DedicatedWorkerPool`) runs model load and
  inference off the UI thread. `torch`/`transformers` first-import **on that
  worker thread** at model-load time, which keeps the CUDA `DllMain`
  initialization invariant satisfied on Windows.
- Audio capture runs on a persistent PortAudio stream; captured frames are
  pulled from memory when recording stops, resampled to 16 kHz with `soxr`, and
  handed to the service.
- In the server, a single inference lock serializes `transcribe` calls across
  the threading HTTP server.

## Wire protocol v1

The remote leg ([`services/server.py`](../speakeasy/services/server.py) +
[`services/remote_client.py`](../speakeasy/services/remote_client.py)) shares the
torch-free (de)serialization in
[`speakeasy/core/wire.py`](../speakeasy/core/wire.py).

| Route | Method | Request | Response |
| --- | --- | --- | --- |
| `/v1/health` | GET | — | status + `contract_version` |
| `/v1/capabilities` | GET | — | `EngineCapabilities` JSON |
| `/v1/transcribe` | POST | 16 kHz mono PCM16 **WAV** body + `X-SpeakEasy-Options` JSON header | `TranscriptionResult` JSON |

- **Auth:** every request carries `Authorization: Bearer <token>`; the server
  compares with `secrets.compare_digest`. Missing/invalid → `401`.
- **Safety:** request bodies are capped (`413` over the limit); engine errors map
  to `409` with a typed `error_type`. `create_server()` raises if asked to bind a
  non-loopback address without a token, and `--allow-remote` is required for any
  non-loopback bind.
- Options are sent as a JSON **header** with a raw WAV body (no `multipart`/`cgi`
  dependency), keeping the body a clean, cappable stream.

See [REMOTE.md](REMOTE.md) for server setup and the security posture, and
[../SECURITY.md](../SECURITY.md) for the remote-mode threat model.

## Where things live

| Path | Role |
| --- | --- |
| `speakeasy/core/` | Contract, model-source schema, errors, wire format, resample — torch-free, Qt-free |
| `speakeasy/services/` | `inprocess` adapter, `remote_client`, `server`, `provisioning` |
| `speakeasy/engines/` | Torch-free `registry` + `fake` test double |
| `speakeasy/engine/` | The real Granite engine (`granite_transcribe`) — the only module-scope owner of torch/transformers, loaded lazily |
| `speakeasy/ui/` | Controllers (`model_controller`, `dictation_controller`, `metrics_bridge`) + tooltip registry |
| `speakeasy/main_window.py` | The window/view; holds a `TranscriptionService`, delegates logic to controllers |
