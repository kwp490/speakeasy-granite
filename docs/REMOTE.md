# Remote ASR (transcribe from another computer)

SpeakEasy can run its transcription engine on one machine (the **server**) and let one or more
other machines (the **clients**) send audio to it over HTTP. This is useful when only one computer
has a capable GPU.

> **Remote ASR is opt-in and off by default.** In every local engine mode, audio never leaves your
> machine. In remote mode, recorded audio is sent to the server you configure and the transcript is
> returned. The app requires a one-time disclosure acknowledgement before any audio is sent.

---

## 1. Quick start (trusted LAN)

### On the server machine

1. Make sure the Granite model is available (download it through the app once, or run
   `speakeasy download-model`).
2. Generate a bearer token and keep it secret:

   ```powershell
   speakeasy serve --generate-token
   ```

   Copy the printed token.

3. Start the server, bound to your LAN address, with the token:

   ```powershell
   speakeasy serve --bind 0.0.0.0:8765 --allow-remote --token "<paste-token-here>"
   ```

   - `--bind 0.0.0.0:8765` listens on all interfaces. To restrict to one NIC, use that NIC's IP.
   - `--allow-remote` is **required** to bind a non-loopback address. Without a token the server
     refuses to start in this configuration.
   - `--device cuda` (default on GPU builds) or `--device cpu` selects the compute device.
   - `--model-dir <path>` points at a non-default model location.

   Leave this process running. It serves until you stop it (Ctrl+C).

### On the client machine

1. Open **Settings → Advanced → Model location**.
2. Select **Remote**.
3. Enter the server URL, e.g. `http://192.168.1.50:8765`.
4. Paste the bearer token.
5. Click **Test connection**. A healthy server reports its engine and device.
6. Click **Apply**. Accept the privacy disclosure dialog when prompted.

The client now sends recorded audio to the server and shows the returned transcript. The token is
stored in the Windows Credential Manager (never in `settings.json` or logs).

---

## 2. Command reference

```
speakeasy serve [--bind HOST:PORT] [--device {cuda,cpu}] [--model-dir DIR]
                [--token TOKEN] [--generate-token] [--allow-remote]
```

| Flag | Default | Purpose |
|---|---|---|
| `--bind` | `127.0.0.1:8765` | Address to listen on. Loopback-only unless `--allow-remote`. |
| `--device` | `cpu` (CPU build) / `cuda` (GPU build) | Compute device for the engine. |
| `--model-dir` | managed models dir | Directory containing the Granite model. |
| `--token` | none | Bearer token clients must present. Required for non-loopback binds. |
| `--generate-token` | — | Print a fresh random token and exit (does not start the server). |
| `--allow-remote` | off | Permit binding a non-loopback address. Requires `--token`. |

### HTTP endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/health` | Liveness + engine/device/version info. |
| `GET` | `/v1/capabilities` | Languages, translation targets, device list, etc. |
| `POST` | `/v1/transcribe` | Body: raw 16 kHz mono PCM16 WAV. Options JSON in the `X-SpeakEasy-Options` header. Returns the transcript as JSON. |

All requests must include `Authorization: Bearer <token>` when the server was started with a token.

---

## 3. Security & hardening

Plain `speakeasy serve` over HTTP is appropriate for a **trusted LAN**. The bearer token
authenticates clients but does **not** encrypt traffic — audio and transcripts travel in plaintext.

For any link beyond a trusted LAN:

- **Use TLS.** Put the server behind a reverse proxy (Caddy, nginx, Traefik) that terminates HTTPS,
  and point the client at the `https://` endpoint. Or tunnel over SSH/WireGuard/Tailscale and keep
  the server bound to loopback on the host.
- **Restrict the firewall.** Only allow the server port from the specific client IPs that need it.
- **Keep `--allow-remote` deliberate.** Loopback-only is the default for a reason; only expose the
  port when you intend to.
- **Rotate the token** if you suspect it leaked. Generate a new one with `--generate-token`, restart
  the server, and update the token in each client's Settings.

Built-in protections:

- Constant-time token comparison (no timing oracle).
- Request body cap (16 MB) → HTTP 413 for oversized uploads.
- Single inference lock serializes transcription so one client can't over-subscribe the GPU.
- Non-loopback bind without a token is refused at startup.

See [SECURITY.md](../SECURITY.md#remote-asr-mode) for the full threat model.

---

## 4. Privacy disclosure

When you enable a Remote model source, SpeakEasy shows a one-time disclosure dialog explaining that
recorded audio will be sent to the server you configured. Audio is **not** sent until you accept it.
The acknowledgement is recorded as `remote_disclosure_accepted` in `settings.json`. Changing the
remote URL re-prompts the disclosure.

The server processes audio in memory and returns the transcript; it does not write audio or
transcripts to disk, and its logs contain diagnostic data only (no speech content).

---

## 5. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| **Test connection: unreachable** | Server not running, wrong host/port, or firewall blocking the port. |
| **Test connection: authentication failed** | Token mismatch. Re-copy the token from the server. |
| **Test connection: version mismatch** | Client and server are different SpeakEasy versions. Upgrade both to the same release. |
| **Server won't start (ValueError)** | Non-loopback `--bind` without `--token`. Add `--allow-remote` and `--token`. |
| **HTTP 413** | Audio clip exceeds the 16 MB body cap. Record shorter clips. |
