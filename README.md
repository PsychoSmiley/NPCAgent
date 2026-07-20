# NPCAgent - Project Overview

A deliberately minimal LLM-simulation prove NPC emergence by unseeded agents. Three agents that move from places Park / Home / Cafe sandbox, run a small circular economy, and remember through one lossy diary. Function-based, no classes, a single Python file that runs on many LLMs (even old ones like llama2) with no GPT-4, no vector embeddings, no huge context window. Inspired by `joonspk-research/generative_agents` (`Generative Agents: Interactive Simulacra of Human Behavior` 1y-6ppl) and `a16z-infra/ai-town`, but dev solo and focused on simplicity and incremental features: persistent, believable agents that share information and interact with their environment.

## VS Stanford Generative Agents
Stanford spent **$1000+ to run 25 agents** on a per-action multi-step LLM pipeline plus a **vector DB + embeddings** and a rigid planner. NPCAgent replaces all of it with one lossy diary, 100x cheaper, and still grows emergent bureaucracy, grief, and paranoia.

| Stanford / AI-Town | NPCAgent |
|--------------------|----------|
| multi-step LLM pipeline per action, replay after sim, AI-Town splits each decision into many steps to avoid "lost in conversation" | one LLM call per turn, real-time gameplay, P2P conversation isolated from the open-world loop, so talk + action stay one seamless flow |
| vector-DB memory stream, embeddings, fact-extraction, 1-10 importance ranking, no death/scarcity, heavy hand-held Simulacra | memories -> reflection -> goal/plan |
| rigid planner / schedule | none, which avoids omniscient info-leak |
| the famous Valentine's party was not the agent's own idea: the planner is fed the calendar date AND one agent was handed "throw a Valentine's party" as its goal; only the word-of-mouth spread of invites was emergent | no date fed in, no planner - NPCs act on memory and what they notice, so nothing is pre-arranged by the calendar |
| parallel / batch LLM calls | one LLM switches perspective across all agents, immediate per turn (avoids conflicts) |
| dynamic ctx-manager, prompt-cache, profiling, metrics, experiment-config, pathfinding, nested `<observation>` tags | no over-optimization complexity: light text-reflection (beats hard-stop overhead) |

## Philosophy

**Terrarium, not script**
- create CONDITIONS, observe emergence, "Hollow Level 3" economic OUTCOMES (wealth gap) ≠ strategic COGNITION (intentional hoarding)
- never script the story; the goal of life is to survive - nothing explicitly prompts it, let it emerge from goals + personality + social dynamics + resource constraints
- Circular-economy creates meaning, the last survivor always dies (can't self-serve) - no scarcity → no stakes → fluff chat
- Generalizable, lightweight, organized script, prioritized for learning, avoid assumptions over a direct solution: don't cheat or bleed the prompt, e.g. `SYSTEM_CONTENT` should not be `Bob: If someone says their favorite color is "dark red"`

**Do more with less**
- incremental features beat a complex environment (complexity reduces reliability)
- simple actions + text-adventure-style transitions execute more reliably than complex actions / more locations (cf. "Degrees of Lewdity" / "Free Cities", where darker stakes drive the drama, toxicity is a trait, not a bug - enemies and friends both belong)
- Rule "NOT NEEDED now": script condensed - sleek/compact/concise/clean minimal/efficient DRY well-structured and avoid unnecessary/repetition, consistent function naming across versions and required test-flow integrity; simplicity over complexity.
- Less prompt = agentic framework does more = less freedom capability for the LLM = less creativity ≠ *Minimalist* SOTA Stanford-level Agent Simulation with Natural emergence
- no stats: `target["trauma"]=50` limits natural LLM reasoning

## Architecture

**JSON contract**
- every turn is `{"response": "text", "action": "action"}`
- plain single-line JSON, no complex schema (ideal for small models), beats MCP overhead
- the parser keeps only the spoken `response`, separating inner thought from utterance to prevent raw-history pollution and the self-imitation cascade
- reflection on a failed action (which step failed -> adjust / alt-strategy / abandon) enables learning

**Budget**
- `MAX_RESPONSE_TOKENS = 100` - token efficiency, the sinews of war: just enough for a non-reasoning model to flow words, avoid verbosity / truncation
- the Observation (fails root cause & uncertain) -> Thought (gathering information?) -> Action flow (Perceive, Retrieve, Plan, Execute, Reflect), to stay coherent and enforce emergent behavior (GPT-4 struggles past 50 actions)
- the `25 msg × 100 tok = 2500 tok` window fits everything from old 4K-context locals to 32k+ flagships, over any OpenAI-compatible API

**Loop**
- turn-based to prevent conflicts, on a 30-min tick (1min = slow repetitive day)
- cap ~7±2 key events/day, drawn from consequences, never hardcoded
- actions must be meaningful: use `none`, never `rest`/`wait`/`idle`
- no decorative `playFrisbee`/`lightsOn`/`wakeUp`; no redundant social verbs (`greetUser`/`askQuestion`/`shareInfo`) that duplicate `talkToX`

**Diary = long-term memory**
- a new note is appended whenever `sleep` triggers
- notes append at morning reminder in the end of history where attention is strongest, injected once at wake then ages out of history naturally (avoids redundancy + overflow)
- it lives in the message history, not the system prompt (already heavy, yields shallow recall)

**Prompt craft**
- dense linked phrasing
- deliberate ambiguity "`considering memories observations`" forces reflection
- "NPC" not "agent" (less robotic)
- generic `EXAMPLES:` placeholders (concrete inert values like "collecting stamps", never bracketed `[HOBBY]` - dumb models emit the literal brackets) + a leading `...` token to self-correct and dodge prompt-bleed
- single keywords (`Opinion`/`Help`/`Question`) over full phrases
- failure messages teach mechanics, not prompt explanations

**Role-switching** - a system prompt + `Name:` speaker-prefix is required because each turn flips BOTH the speaker role AND the JSON shape (questioner `{"input":...}` <-> answerer `{"response":...}`); without it the model lies or hallucinates mid-switch:

```
[Answer/ChatbotAI]: role: "Bob": `{"response": "Hello, my name is bob!"...`
[Question/userAnswer] role: "Alice":` `{"input": "Cool, my name is Alice!...` # notice how this changes to a Question-like-user.
[AnswerChatbotAI] role: "Bob":` `{"response": "Alice, have you spoken to anyone else in this AI town? I would love to meet them!...`
```

## Emergence Levels & Victory Conditions

| Level | Score | What it demonstrates | Status & who reached it |
|-------|-------|----------------------|-------------------------|
| -1 | 1-3/10 | flawed but not broken JSON | GPT-5.1, GLM-4.5 (Bob Denial), Gemma (Fake NPCs) |
| 0 | 6/10 | **The Relay**: JSON compliance + info chain Bob→Alice→Chloe→Bob (middleman wiped, so it must recall) - a memory + role-switching stress test, no full-history dump | ✅ ACHIEVED baseline: Devstral-24B, DeepSeek v3.2, MiniMax-M2 |
| 1 | 7/10 | **The Planner**: self-directed scheduling + long-term goals + anticipation via exploration, WITHOUT seeding (⚠️ TRAP: planning can substitute for action; Stanford needed seeding) | ⚠️ PARTIAL |
| 2 | 8/10 | **The Persona**: emotional permanence + evolving personality - traits drive choices/preferences (foods, activities, people), sentiment trust/distrust grows from experience (unknown ↔ toxicity / friend ↔ love), fighting LLM positivity bias (bad people exist). Simplified Theory of Mind; **story-arc** tension + resolution; learn/adapt into new capability/knowledge (learning-rate varies per agent). e.g.: Grudge (Alice lies → Bob avoids 10+ days), Love (prioritizes another over survival), Drift (same prompt → different personalities by Day 5) | 🎯 once by Claude Opus 4.5 (creative + grounded) |
| 2+ | 9/10 | Level 2 reliable + Level 3 glimpses | not reached |
| 3 | 10/10 | **The Architect**: spontaneous economy (jobs = income, inter-agent trade via overwork, supply & demand, outcomes shape relationships) + social network of 3+ (group formation, hierarchy/reputation, social stratification, unprompted roles like leader/mediator, conflict + resolution, cultural/opinion norms), all WITHOUT coding them ("I have info, you want info, do my chores in exchange" → economy emerges); needs Level 2 foundation + longer runs. The dream: NPCs live their life (player NOT the center of the story), secrets have VALUE → blackmail emerges from scarcity | 🔮 CEILING |

Scores rated by the [agents-game-log-analyzer](agents-game-log-analyzer.md) agent. Size ≠ Quality: dense 12B > MoE 46B, training > size. **Intelligence ≠ Creativity ≠ Humanity.**

## TODO
1. Kids/reproduction so the terrarium outlives its individuals - the intended path to longer runs (the circular-economy death is a designed law, not a bug: new life replaces the dead, never defuse scarcity).

## Citation

If you use NPCAgent for your research, please cite it using the following BibTeX entry:

```bibtex
@misc{npcagent,
  author = {DigitalDreamer},
  title = {NPCAgent: NPC emergence by unseeded agent},
  year = {2026},
  publisher = {GitHub},
  journal = {GitHub repository},
  howpublished = {\url{https://github.com/PsychoSmiley/NPCAgent}}
}
```
