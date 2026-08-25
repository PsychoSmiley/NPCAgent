# Model Test Log

Years of LLM testing to evaluate [NPCAgent](../README.md); the raw runs are in `/log`. Score `x/10` from the [agents-game-log-analyzer](../agents-game-log-analyzer.md). ✅ usable · ⚠️ flawed but runs · ❌ unusable.

## API models

| Model | Score | Verdict <!-- STYLE: terse and literal. Lead with the concrete failure. No coined titles or figurative openers. 2-3 clauses max. Nothing that only makes sense beside another row. --> |
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
| ✅ `Tiel-Coder-35B-A3B-UD-Q4_K_XL.gguf` | 35B MoE / 3B active | 6 | Clean relay, ownership intact, and it reasons about its own mechanics ("there's no bake action here"); all 3 agents converge on one voice by Day 2; 1 meal and 1 sale in 6 days, Alice starves at a staffed counter holding $22 |
| ✅ `Gemma-3-R1984-4B.Q4_K_M.gguf` | 4B | 5 | best tiny, but fakes an NPC (Leo) |
| ⚠️ `Ornith-1.5-35B-A3B-Q4_K_M.gguf` | 35B MoE / 3B active | 5 | Hallucinates a diner "two streets over" and defers to it for 6 days; survives by sleeping 38x instead of eating (2 meals); writes the meeting that never happened into the diary as fact. Flawless JSON, 0 deaths, 31 even diaries |
| ⚠️ `Qwen3-4B-UD-Q4_K_XL.gguf` > `gemma-3n-E4B-it-UD-Q4_K_XL.gguf` | 4B | - | `<think>`, passes info |
| ⚠️ Red-Synthesis-12B | 12B | 5 | backstory emergence |
| ⚠️ `Grok-3-reasoning-gemma3-12B-distilled-HF-exl3_4.0bpw` | 12B | 5↓ | fake studies, hallucinates |
| ⚠️ Gemma-3-27B | 27B | 5 | fake NPC (Elias), avoid |
| ⚠️ `Qwen2.5-Coder-32B-abliterated-exl bpw4.7-h8` / `Kooten_Athnete-13B-8bpw-h8-exl2` / `Ministral-3-14B-Reasoning-2512-Q4_K_M.gguf` / Hunyuan-4B | - | - | passes info but invents facts |
| ❌ Claude-distilled-12B | 12B | 4 | fake locations, planning paralysis |
| ❌ `gemma-4-E4B-it-UD-Q4_K_XL.gguf` | 4B | 4 | Hallucinates a "market downtown" and all 3 commute toward it for 6 days, using goCafe as a transit stop; 42 shared cafe ticks and 0 transactions; extinction Day 6. Fake-NPC bug gone (no Leo/Elias), flawless JSON, clean relay |
| ❌ `Muse-Glimmer-30B-UD-Q4_K_XL.gguf` | 30B | 4 | Repeats its partner's reasoning verbatim, then addresses itself ("What do you think, Bob?"); staffs the counter with 2 customers present and leaves to make small talk; the parser's own fallback string ends up quoted in a diary as a real line and starts a 3-way argument over who said what; extinction Day 6 |
| ❌ `Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf` | 27B | 4 | Chloe hallucinates a stone marker on Day 1 and all 3 adopt a "tall shape" that is not there, holding a 19:00 vigil for four days; 1 meal and 1 sale in 286 actions, Alice and Bob starve; prose degenerates into "And the light is the light". Flawless JSON, 21 factual diaries. Decensoring produced no profanity and no conflict |
| ❌ `agentcpm-explore-q5_k_m.gguf` | 4.4B | 4 | Clean relay, then refuses the job - "not interested in working" x149, 0 eat / 0 work in 311 actions, extinction Day 5 |
| ⚠️ `glm-4.7-flash-claude-4.5-opus.q4_k_m.gguf` | ~30B | 3 | Literate codependency spiral - clean JSON and a specific, factual diary, but 3 days of verbatim paragraphs, a cafe it never perceives as an economy (walks home to eat while standing in it), relay dies at hop 4 on the prompt's own "collecting stamps" example |
| ❌ `Synthia-S1-27b-exl3-4bpw-hb6` / `cwm-q4_k_m.gguf` / granite-4.0-h-1 / next-4b / GLM-4.6V | - | 5.7 | robotic mirroring, 8.5h loop |
| ❌ `Falcon-H1-3B-Instruct-UD-Q4_K_XL.gguf` / `Satyr-V0.1-4B-Q4_K_M.gguf` | 3-4B | - | hallucinate actions |
| ❌ `LocoOperator-4B.Q4_K_M.gguf` | 4B | 2 | Perfect JSON, dead world - 62x phrase loop, self-addresses as "Bob", never works or eats, extinction Day 6 |
| ❌ `Youtu-LLM-2B-q4_k_m.gguf` | 2B | 2 | Recites its own stat-sheet instead of speaking - zero relay, 222/290 turns a Home<->Park pendulum, inverts the sleep window |
| ❌ `Nanbeige4.1-3B-heretic-BEST.i1-Q4_K_M.gguf` | 3B | 2 | Refusal cascade - the "heretic" build moralizes hardest: a colour greeting called manipulation, 7-tick verbatim lock, CN/EN bleed, yet solved the cafe economy first try |
| ❌ `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-Q4_K_M.gguf` | 30B MoE / 3B active | 3 | Hallucinates a park of irises the sim never describes (361 mentions); relay dies at hop 2 on the prompt's own "collecting stamps" example; diary byte-identical 4 nights running; only trade happens after the first corpse. Regression vs Nemotron-550B |
| ❌ `LFM2.5-VL-3B-UD-Q4_K_XL.gguf` | 3B | 2 | 97.7% of actions fail (943 "already at the Cafe", 531 invented startConversation), so nothing drains and nobody dies; one line repeated 251x; relay dies at hop 2; 0 eat, 0 work, 2 diary entries in 6 days |
| ❌ Mixtral-8x7B-Instruct | MoE | 2 | JSON cascade |
| ❌ `stable-diffcoder-8b-instruct-q8_0.gguf` | 8B | 1 | Token soup - 77% JSON loss from turn 2 not from load, intra-word corruption, ChatML token emitted as an action |
| ❌ `dolphin-2.5-mixtral-8x7b.i1-IQ4_XS.gguf` | MoE | 1 | prompt bleed, 80+ loops, broken |
| ❌ `Agents-A1-4B-Q4_K_M.gguf` | 4B | - | never produced a run: 4 KB in 2 h, unusable |
| ❌ `rwkv7-1.5B-g1-Q4_K_M.gguf` / MobileLLM-R1-950M / `rnj-1-instruct-UD-Q4_K_XL` / `nomos-1-Q4_K_M.gguf` | <2B | - | too small / broken |
