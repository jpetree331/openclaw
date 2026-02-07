#!/usr/bin/env bun
/**
 * Search openclaw.json for all TTS / ElevenLabs config and API key locations.
 * Use to verify a single ElevenLabs key is used everywhere (or see where keys differ).
 *
 * Run: bun scripts/search-config-tts.ts  (or pnpm exec tsx scripts/search-config-tts.ts)
 */

import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const configPath = path.join(os.homedir(), ".openclaw", "openclaw.json");

function mask(s: string): string {
  if (s.length <= 16) return "***";
  return s.slice(0, 8) + "…" + s.slice(-4);
}

function collect(
  obj: unknown,
  prefix: string,
  out: { path: string; value: string; kind: string }[],
): void {
  if (!obj || typeof obj !== "object") return;
  const record = obj as Record<string, unknown>;
  for (const [k, v] of Object.entries(record)) {
    const p = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "string") {
      if (k === "apiKey" || k === "token" || k === "api_key") {
        out.push({ path: p, value: mask(v), kind: "secret" });
      } else if (
        k === "provider" ||
        k === "voiceId" ||
        k === "voice" ||
        k === "modelId" ||
        k === "model"
      ) {
        out.push({ path: p, value: v, kind: "setting" });
      }
    } else if (v && typeof v === "object" && !Array.isArray(v)) {
      collect(v, p, out);
    }
  }
}

// Paths we care about for "same ElevenLabs key everywhere"
const TTS_RELEVANT = [
  "talk.apiKey",
  "talk.voiceId",
  "messages.tts",
  "plugins.entries.voice-call.config.tts",
];

function main(): void {
  if (!fs.existsSync(configPath)) {
    console.error("Config not found:", configPath);
    process.exit(1);
  }
  const raw = fs.readFileSync(configPath, "utf-8");
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch (e) {
    console.error("Invalid JSON:", configPath, e);
    process.exit(1);
  }

  const out: { path: string; value: string; kind: string }[] = [];
  collect(data, "", out);

  const secrets = out.filter((x) => x.kind === "secret");
  const ttsPaths = new Set<string>();
  for (const r of out) {
    for (const base of TTS_RELEVANT) {
      if (r.path === base || r.path.startsWith(base + ".")) ttsPaths.add(r.path);
    }
  }

  console.log("--- TTS / ElevenLabs / Talk config in openclaw.json ---\n");
  const byBase: Record<string, typeof out> = {};
  for (const r of out) {
    let base = "";
    for (const b of TTS_RELEVANT) {
      if (r.path === b || r.path.startsWith(b + ".")) {
        base = b.split(".")[0] ?? b;
        break;
      }
    }
    if (base) {
      if (!byBase[base]) byBase[base] = [];
      byBase[base].push(r);
    }
  }
  for (const base of ["talk", "messages", "plugins"]) {
    const items = byBase[base] ?? [];
    if (items.length === 0) continue;
    console.log(base + ":");
    for (const r of items) {
      console.log("  ", r.path, "=>", r.value);
    }
    console.log();
  }

  console.log("--- All API keys / tokens (path + masked value) ---\n");
  for (const r of secrets) {
    const isTts =
      r.path.includes("tts") ||
      r.path.includes("talk") ||
      r.path.includes("eleven");
    console.log("  ", r.path, " ", r.value, isTts ? "  [TTS/talk]" : "");
  }

  console.log("\n--- Where ElevenLabs is used in code ---");
  console.log("  • Messages TTS (Telegram voice, etc.): config.messages.tts.elevenlabs.apiKey OR env ELEVENLABS_API_KEY / XI_API_KEY");
  console.log("  • Talk: config.talk.apiKey OR env ELEVENLABS_API_KEY (or from ~/.profile)");
  console.log("  • Voice-call plugin: plugins.entries[\"voice-call\"].config.tts.provider + .tts.elevenlabs.apiKey OR env ELEVENLABS_API_KEY");
  console.log("  To use the same key everywhere: set ELEVENLABS_API_KEY and optionally set talk.apiKey and messages.tts.elevenlabs.apiKey to the same value (or leave unset to use env).");
  console.log("  Voice-call: if tts.provider is \"openai\", OpenAI is used for calls (not ElevenLabs). Switch to provider \"elevenlabs\" to use ElevenLabs there too.");
}

main();
