---
summary: "Expose the Gateway (and optional voice webhook) with ngrok"
read_when:
  - You see 'port is already online' or ERR_NGROK_334 with multiple tunnels
  - You want one ngrok agent for both gateway and voice-call
title: "Gateway over ngrok"
---

# Exposing the Gateway with ngrok

To expose the OpenClaw gateway (and optionally the voice-call webhook) over the internet with ngrok, use a **single ngrok agent** with multiple tunnels. Running two separate `ngrok` processes (e.g. one from the voice-call plugin and one for the gateway) can trigger "port is already online" or ERR_NGROK_334 (endpoint already in use).

## One agent, two tunnels (recommended with paid ngrok)

1. **Create an ngrok config file** (e.g. `~/.openclaw/ngrok.yml` or `./ngrok.yml`):

```yaml
version: "2"
authtoken: YOUR_NGROK_AUTH_TOKEN

tunnels:
  gateway:
    proto: http
    addr: 18789
    # optional: bind_tls: true
  voice:
    proto: http
    addr: 3335
    domain: unleathered-alayah-speckless.ngrok-free.dev # your existing paid domain
```

Replace `YOUR_NGROK_AUTH_TOKEN` with your token (or omit and set `NGROK_AUTHTOKEN` in the environment). Replace `addr: 3335` if your voice-call plugin uses a different port. Replace `domain` with your actual ngrok domain for the voice webhook.

2. **Stop the voice-call plugin from starting its own ngrok**  
   In OpenClaw config (`~/.openclaw/openclaw.json`), under `plugins.entries["voice-call"].config`:
   - Set `tunnel.provider` to `"none"`.
   - Keep `publicUrl` as your voice webhook URL (e.g. `https://unleathered-alayah-speckless.ngrok-free.dev/voice/webhook`).

   So the plugin no longer spawns ngrok; it uses the URL that your single ngrok agent will serve.

3. **Start both tunnels in one agent:**

```bash
ngrok start --all --config ~/.openclaw/ngrok.yml
```

Or start only the gateway tunnel:

```bash
ngrok start gateway --config ~/.openclaw/ngrok.yml
```

4. **Use the gateway URL**  
   In the ngrok output, the `gateway` tunnel will show a public URL (e.g. `https://abc123.ngrok-free.app`). Use that for remote access:
   - WebSocket: `wss://<that-host>/`
   - HTTP (health, Control UI): `https://<that-host>/`

5. **Restart the OpenClaw app** (or gateway) after changing the voice-call tunnel config so the plugin no longer starts a second ngrok process.

## Why "port is already online" appears

- **Two ngrok processes:** The voice-call plugin starts an ngrok process for the webhook. If you then run `ngrok http 18789`, a second agent starts; with one domain or account limits, ngrok can report the endpoint or port as already in use.
- **Fix:** Run one ngrok agent with a config file that defines both tunnels (gateway + voice), and set the plugin to `tunnel.provider: "none"` with a fixed `publicUrl`.

## See also

- [Remote access](/gateway/remote) (SSH, Tailscale)
- [Tailscale](/gateway/tailscale) (alternative to ngrok)
