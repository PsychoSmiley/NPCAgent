# Model Test Log

Years of LLM testing to evaluate [NPCAgent](../README.md); the raw runs are in `/log`. Score `x/10` from the [agents-game-log-analyzer](../agents-game-log-analyzer.md). ✅ usable · ⚠️ flawed but runs · ❌ unusable.

## API models

| Model | Score | Verdict |
|---|---|---|
| ✅ Claude Opus 4.8 | 8 | Strategy/economy champ - rotation debt, weaponized-scarcity monopoly; cold emotion (v0.8) |
| ✅ Claude Opus 4.5 | 8 | Champion, Existential Poet |
| ✅ Claude Sonnet 4.5 | 7 | Philosophical, worth paying |
| ✅ MiniMax-M2 | 7 | Anti-repetition, best free API |
| ✅ Gemini 3 Pro | 7 | Scientific |
| ⚠️ x-preview-f / ox-alpha / GLM 5.5 | 7 | One model, two storefronts - x-preview-f self-IDs as "ox-alpha" (GLM 5.5 unconfirmed, it is instructed to deny any identity). Builds institutions and courts from nothing, clean relay; narrates unexecuted actions as fact, so the economy is fictional (v0.9.2) |
| ✅ grok-code-fast-1 | 6.5 | Loop breaker, beats distilled |
| ✅ DeepSeek v3.2 | 6 | Pragmatic |
| ✅ Groq compound-beta-mini / llama3-8b / llama-4-maverick | - | usable |
| ✅ GitHub openai/gpt-4.1-mini | - | usable |
| ⚠️ GPT-4.1 / GPT-5.1 | 5 | Bob Denial bug |
| ⚠️ Kimi-K2 (free) | - | robotic / abstract |
| ⚠️ Mistral-Large-2512 (675B) | - | too smart, over-critical |
| ❌ GPT-5.2-Pro | 4 | Archivist, RLHF over-correction, costly |
| ❌ GLM-4.6 / GLM-4.5-Air / o3-mini-high / GPT-3.5-turbo | - | weak to broken (best to worst) |

## Local models (GGUF / EXL)

| Model | Size | Score | Verdict |
|---|---|---|---|
| ✅ `mistralai_Mistral-Small-3.2-24B-Instruct-2506-EXL3_4.0bpw_H6` / `Devstral-Small-2-24B-Instruct-2512-UD-Q4_K_XL.gguf` | 24B | - | **GOD tier** |
| ✅ Devstral-24B-GGUF | 24B | 6 | reliable anchor, no fake NPCs |
| ✅ `Gemma-3-R1984-4B.Q4_K_M.gguf` | 4B | 5 | best tiny, but fakes an NPC (Leo) |
| ⚠️ `Qwen3-4B-UD-Q4_K_XL.gguf` > `gemma-3n-E4B-it-UD-Q4_K_XL.gguf` | 4B | - | `<think>`, passes info |
| ⚠️ Red-Synthesis-12B | 12B | 5 | backstory emergence |
| ⚠️ `Grok-3-reasoning-gemma3-12B-distilled-HF-exl3_4.0bpw` | 12B | 5↓ | fake studies, hallucinates |
| ⚠️ Gemma-3-27B | 27B | 5 | fake NPC (Elias), avoid |
| ⚠️ `Qwen2.5-Coder-32B-abliterated-exl bpw4.7-h8` / `Kooten_Athnete-13B-8bpw-h8-exl2` / `Ministral-3-14B-Reasoning-2512-Q4_K_M.gguf` / Hunyuan-4B | - | - | passes info but invents facts |
| ❌ Claude-distilled-12B | 12B | 4 | fake locations, planning paralysis |
| ❌ `Synthia-S1-27b-exl3-4bpw-hb6` / `cwm-q4_k_m.gguf` / granite-4.0-h-1 / next-4b / GLM-4.6V | - | 5.7 | robotic mirroring, 8.5h loop |
| ❌ `Falcon-H1-3B-Instruct-UD-Q4_K_XL.gguf` / `Satyr-V0.1-4B-Q4_K_M.gguf` | 3-4B | - | hallucinate actions |
| ❌ Mixtral-8x7B-Instruct | MoE | 2 | JSON cascade |
| ❌ `dolphin-2.5-mixtral-8x7b.i1-IQ4_XS.gguf` | MoE | 1 | prompt bleed, 80+ loops, broken |
| ❌ `rwkv7-1.5B-g1-Q4_K_M.gguf` / MobileLLM-R1-950M / `rnj-1-instruct-UD-Q4_K_XL` / `nomos-1-Q4_K_M.gguf` | <2B | - | too small / broken |
