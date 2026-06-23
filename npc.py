# npc.py - NPCAgent v0.7.13 - circular economy + aging-death + diary v3 + multi-turn conv; v0.7.11 base, fork-B morning diary
import requests
import json
import re
import time

# --- Configuration ---
VERBOSE_LOGGING = False
SHOW_SUMMARY    = True   # always print diary consolidation (even when VERBOSE off) so the lossy compression is visible
BASE_URL = "http://127.0.0.1:5000/v1"   # OAI_opencode.py port (local was http://127.0.0.1:5000/v1)
API_KEY = "proxy-dont-need-it"
MODEL_NAME = 'claude-opus-4-8'  # OpenAI-compatible model id
MAX_HISTORY_MESSAGES = 50   # was 25; modest bump eases worst diary scroll-out while keeping diary-only memory meaningfully tested
MAX_RESPONSE_TOKENS = 32000

# --- Diary v3 Config ---
MAX_DIARY_ENTRIES = 15      # Keep last 15 days raw, then summarize oldest
DIARY_SUMMARIZE_COUNT = 10  # Summarize 10 oldest when exceeds max

# --- Economy Config ---
STARTING_MONEY = {"Bob": 10, "Alice": 10, "Chloe": 10}  # Scarcity test ($10 showed cooperation in v0.7.7)
ORDER_COST = 10   # Customer pays
SERVE_PAY = 12    # Worker earns when customer orders (+$2 profit rewards coordination)

# --- Aging Config ---
DAYS_PER_YEAR = 28   # 1 year = 4 weeks: weeks stay sub-year, birthday ~monthly (not every day)

# --- World State ---
current_time = {"hour": 8, "minute": 0, "day": 1}
pending_notices = {}  # {agent_name: [one-time notices (deaths, earnings) to announce at the agent's next turn]}
LOCATIONS = {
    "Park": {"context": "at the park", "actions": ["goHome", "goCafe"]},  # social only
    "Home": {"context": "at home", "actions": ["sleep", "goPark", "goCafe"]},
    "Cafe": {"context": "at the cafe", "actions": ["eat", "work", "goHome", "goPark"]}  # economy
}

# --- System Prompt (hand-tuned, verbatim; [HOBBY] -> "collecting stamps": concrete, impossible-in-world, non-adoptable per TODO#3) ---
BASE_SYSTEM_PROMPT = """You are {name}, an NPC character in an interactive game-simulated world. You think and respond only as {name}. Not a robotic and overly polite helpful assistant.

Your task is to respond to all situations by generating only one valid single-line JSON in format: {{"response": "your_reasoning_then_speech", "action": "keyword_from_possibleAction"}}

You consider meaningful connections and novel experiences. You get restless doing the same thing repeatedly - if you've been talking to the same person or staying in one place too long, try something different. Balance socializing with rest and sleep to form memories.

- The "response" field reflects natural talking reasoning that flows from current goals and feelings, considering memories observations, opinions, judgments, questions about others or social consequences, optionally in conv-omit own reasoning, then shares thoughts that help/answer/decide actions seamlessly. Gathering more information, learning from failure's root cause and adapt. Quote memories exactly as learned, never invent facts/names/places not existing. If uncertain, say "I don't know".
- Facts in context ARE your memories. Vary greetings - mention facts only when relevant, not as greeting template. Be humanly multitask: current situation, make future plans and follow through, ask questions, explore and find opportunities when idle. Let craft persona through interactions and emotional - relationships evolve naturally (trust, loyalty, closeness, love vs distrust, distance, rivalry, betrayal - range not limited to these). Realize unexpected, leverage, negotiate, build upon ideas and democratize. Time: 1 year = 4 weeks.
- The "action" keyword trigger MUST be ONE chosen from "possibleAction" list provided in latest incoming message. No other prefixes/suffixes or text.

---
EXAMPLES:
<START>
<START>
[Speaker A] says: {{"input": "Hello, my name is [Speaker A], and I enjoy collecting stamps.", "context": "located at the park", "possibleAction": "none, leaveConversation"}}
{{"response": "A new social person! Greeting for friendship is useful, found you here. I'll remember you enjoy collecting stamps. Nice to meet you [Speaker A].", "action": "none"}}
<START>
<START>
[Speaker B] says: {{"input": "Do you know what [Speaker A] enjoys and what their favorite color is?", "context": "located at the park", "possibleAction": "none, leaveConversation"}}
{{"response": "From what I know, they told me they enjoy collecting stamps. I don't know their favorite color, would need to ask them, but I have things planned. Goodbye!", "action": "leaveConversation"}}
<START>
<START>
Game System: {{"input": "What should you do?", "context": "located at the park", "possibleAction": "none, goHome, goCafe"}}
{{"response": "Hmm, park as usual... wait, I already visited the empty park. Repeating is pointless, wastes time, moves me from my social goal. Need new plan. I want to explore the city, never tried the cafe yet! Maybe I'll meet someone there.", "action": "goCafe"}}
<START>
<START>"""

# --- Diary Consolidation Prompt (NO agent context, simple summarization) ---
SUMMARIZE_NOTE_PROMPT = """Summarize following notes in 25 words or less; output directly in single-line, no prefixes/suffixes:
{entries}"""

# --- Core Functions ---
def format_time():
    return f"Day{current_time['day']} {current_time['hour']:02d}:{current_time['minute']:02d}"

def agent_age(a): return a["age"] + (current_time["day"] - a["birth_day"]) // DAYS_PER_YEAR  # years lived; capacity = 100 - this

def advance_time(minutes=30):
    global current_time
    total = current_time["day"] * 1440 + current_time["hour"] * 60 + current_time["minute"] + minutes
    current_time = {"hour": total % 1440 // 60, "minute": total % 60, "day": total // 1440}

def create_agent(name, age=18, location="Park"):
    return {
        "name": name,
        "location": location,
        "money": STARTING_MONEY.get(name, 30),
        "age": age,                  # years lived; energy capacity = 100 - age
        "birth_day": current_time["day"],
        "energy": 100 - age,         # start at this age's full capacity
        "working": False,
        "dead": False,
        "history": [{"role": "system", "content": BASE_SYSTEM_PROMPT.format(name=name)}],
        "diary": [],
        "in_conversation": False,
        "asleep": False,
        "sleep_remaining_hours": 0,
        "just_woke_up": False,
        "consecutive_action": {"name": None, "count": 0}  # Anti-loop tracking
    }

def llm_post(messages, max_tokens=MAX_RESPONSE_TOKENS, temperature=0.5, retries=50, timeout=120, label="LLM"):
    """One chat-completions POST with `retries` attempts + exponential backoff capped at 5m.
       retries=50 ~= 4h ride-out for long 429 cooldowns. send_message uses this default; manage_diary_entries=1 (fast-fail)."""
    url = f"{BASE_URL}/chat/completions"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'}
    data = {'model': MODEL_NAME, 'messages': messages, 'max_tokens': max_tokens, 'temperature': temperature}
    data['reasoning'] = {'enabled': True}   # reasoning model (Nemotron); comment out for non-reasoning (Gemma)
    for attempt in range(retries):
        try:
            if attempt > 0:
                wait = min(300, 60 * 2 ** (attempt - 1))  # exp backoff capped at 5m: 1,2,4,5,5... (cap stops high retry counts ballooning to days)
                print(f"[RETRY] {label}: waiting {wait // 60}m before attempt {attempt+1}/{retries}")
                time.sleep(wait)
            response = requests.post(url, headers=headers, json=data, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if not payload.get('choices'):  # some endpoints return {"error":...} with HTTP 200 - don't crash
                print(f"[API ERROR] {label}: no choices - {str(payload)[:200]} (attempt {attempt+1}/{retries})")
                continue
            msg = payload['choices'][0]['message']
            raw = (msg.get('content') or '').strip()
            if not raw and msg.get('reasoning'):
                raw = msg['reasoning'].strip()
            if raw:
                if VERBOSE_LOGGING: print(f"[RAW FROM {label}]: {raw}")
                return raw
        except requests.exceptions.HTTPError as e:
            print(f"[API ERROR] {label}: HTTP {e.response.status_code} (attempt {attempt+1}/{retries})")
        except requests.exceptions.RequestException as e:
            print(f"[API ERROR] {label}: {type(e).__name__} (attempt {attempt+1}/{retries})")
    return ""

def extract_clean_json(raw_text, agent_name="Agent"):
    def _iter_json_spans(t):  # balanced {...} spans, string-aware so braces/newlines inside "..." don't break it
        depth = start = 0; in_str = esc = False
        for i, c in enumerate(t):
            if in_str: in_str, esc = not (c == '"' and not esc), c == '\\' and not esc
            elif c == '"': in_str = True
            elif c == '{': start, depth = (start if depth else i), depth + 1
            elif c == '}' and depth and not (depth := depth - 1): yield t[start:i + 1]
    text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL | re.IGNORECASE)
    result = None
    for span in _iter_json_spans(text):  # keep the LAST valid {"response":...} (skips leaked reasoning/examples)
        try:
            parsed = json.loads(span)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "response" in parsed:
            if not isinstance(parsed.get("action"), str):  # coerce null/number/list/missing -> "none"
                parsed["action"] = "none"
            result = parsed
    if result is not None:
        return json.dumps(result)
    if VERBOSE_LOGGING:
        print(f"WARNING EXTRACTOR ({agent_name}): Could not extract JSON")
    return None

def send_message(prompt_text, source, target_agent, possible_actions, all_agents=None):
    source_name = source if isinstance(source, str) else source["name"]
    location_ctx = LOCATIONS[target_agent['location']]['context']

    # Visible workers info - only an agent AT the cafe can see who's behind the counter (no remote omniscience)
    cafe_status = ""
    if all_agents and target_agent['location'] == 'Cafe':
        workers = [('you' if a['name'] == target_agent['name'] else a['name'])
                   for a in all_agents if a['location'] == 'Cafe' and a.get('working', False)
                   and not a.get('asleep', False) and not a.get('dead', False)]
        cafe_status = f" Cafe: {', '.join(workers)} working." if workers else " Cafe: no one working."
        # factual only: who's behind the counter (lets an eater know a worker is present). Co-presence = talkToX in the menu; pay = the earned-$ notice

    context = f"located {location_ctx}, own ${target_agent['money']}, energy {target_agent['energy']}/{100 - agent_age(target_agent)}.{cafe_status} It's {format_time()}."

    payload = {"input": prompt_text, "context": context, "possibleAction": ", ".join(possible_actions)}
    target_agent["history"].append({"role": "user", "content": f"{source_name} says: {json.dumps(payload)}"})
    if VERBOSE_LOGGING: print(f"\n[TO {target_agent['name']}]: {target_agent['history'][-1]['content']}")

    if len(target_agent["history"]) > MAX_HISTORY_MESSAGES + 1:
        target_agent["history"] = [target_agent["history"][0]] + target_agent["history"][-MAX_HISTORY_MESSAGES:]

    raw = llm_post(target_agent["history"], label=target_agent['name'])
    clean_json = extract_clean_json(raw, target_agent['name'])
    if clean_json:
        target_agent["history"].append({"role": "assistant", "content": clean_json})
        parsed = json.loads(clean_json)
        return parsed.get("response", ""), parsed.get("action", "none")

    print(f"[ERROR] {target_agent['name']}: Failed to extract valid JSON")
    fb = {"response": "Let me think about this carefully first.", "action": "none"}
    target_agent["history"].append({"role": "assistant", "content": json.dumps(fb)})
    return fb["response"], fb["action"]

# --- Diary Functions ---
def manage_diary_entries(agent):
    """Summarize oldest entries when diary exceeds max - NO agent context needed"""
    if len(agent["diary"]) <= MAX_DIARY_ENTRIES:
        return

    old_entries = agent["diary"][:DIARY_SUMMARIZE_COUNT]
    remaining = agent["diary"][DIARY_SUMMARIZE_COUNT:]
    entries_text = "\n".join(f"Day{e['day']}: {e['note']}" for e in old_entries)

    # Simple LLM call for summary (NO agent context - just summarization task)
    raw = llm_post([{"role": "user", "content": SUMMARIZE_NOTE_PROMPT.format(entries=entries_text)}],
                   max_tokens=1000, temperature=0.3, retries=1, timeout=60, label="Summary")  # 100 got eaten by reasoning models' <think> -> empty -> 10 days of memory silently wiped
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL | re.IGNORECASE)  # this call bypasses extract_clean_json, so strip <think> here
    summary = ' '.join(raw.split()) if raw.strip() else "Various events occurred"  # single line, or fast-fail

    last_day = old_entries[-1]['day']
    agent["diary"] = [{"day": last_day, "note": summary}] + remaining
    if SHOW_SUMMARY:
        print(f"[DIARY] {agent['name']} consolidated D{old_entries[0]['day']}-{last_day}:")
        print(f"  BEFORE ({len(old_entries)} notes): {entries_text[:400]}")
        print(f"  AFTER  (1 note): {summary}")

def get_available_actions(agent, all_agents):
    if agent["in_conversation"]:
        return ["none", "leaveConversation"]

    actions = LOCATIONS[agent["location"]]["actions"].copy()
    for other in all_agents:
        if (other["name"] != agent["name"] and other["location"] == agent["location"]
                and not other["in_conversation"] and not other.get("asleep", False) and not other.get("dead", False)):
            actions.append(f"talkTo{other['name']}")

    return list(dict.fromkeys(["none"] + actions))  # none first, then de-dup order-preserving (deterministic prompts)

def perform_action(agent, action, all_agents, response_text=""):
    """Execute actions with CIRCULAR ECONOMY - both order and work need partners"""
    print(f"-> {agent['name']} attempts: {action}")

    if action == "none":
        return True, None  # 0 energy cost for doing nothing
    # The general -1 action cost is charged ONCE in agent_turn, only when the action SUCCEEDS (failed attempts free);
    # talkTo is charged per-turn inside conv(); none/sleep are free.

    if action.startswith("talkTo"):
        target_name = action.replace("talkTo", "")
        target = next((a for a in all_agents if a["name"] == target_name), None)
        if (target and target["location"] == agent["location"] and not target["in_conversation"]
                and not target.get("dead") and not target.get("asleep")):
            conv(agent, target, response_text if response_text else f"Hello {target_name}.")
            return True, None
        msg = f"{target_name} is not available to talk"
        print(f"-> Failed: {msg}")
        return False, msg

    elif action.startswith("go"):
        destination = action.replace("go", "")
        if destination not in LOCATIONS:
            msg = f"unknown location {destination}"
            print(f"-> Failed: {msg}")
            return False, msg
        agent["location"] = destination
        agent["working"] = False  # Stop working when leaving
        print(f"-> {agent['name']} moved to {destination}")
        return True, None

    elif action == "sleep":
        if agent["location"] != "Home":
            msg = "can only sleep at home"
            print(f"-> Failed: {msg}")
            return False, msg
        if current_time["hour"] < 20:
            msg = f"can only sleep after 20:00 (it's {current_time['hour']:02d}:{current_time['minute']:02d})"
            print(f"-> Failed: {msg}")
            return False, msg
        # Save FULL response as note (prompt already asks for 25 words - no truncation)
        agent["diary"].append({"day": current_time["day"], "note": response_text if response_text else "Rested"})
        manage_diary_entries(agent)
        agent["asleep"] = True
        agent["sleep_remaining_hours"] = 8
        print(f"-> {agent['name']} sleeps. Diary: \"{agent['diary'][-1]['note'][:80]}...\"")
        return True, None

    elif action == "eat":
        # CIRCULAR: eat needs a server at cafe (eat = order food = restore energy)
        if agent["location"] != "Cafe":
            msg = "can only eat at cafe"
            print(f"-> Failed: {msg}")
            return False, msg
        workers = [a for a in all_agents
                   if a["name"] != agent["name"] and a["location"] == "Cafe" and a.get("working", False)
                   and not a.get("asleep", False) and not a.get("dead", False) and not a.get("in_conversation", False)]
        if not workers:
            msg = ("You can't serve yourself! Need another person working here." if agent.get("working")
                   else "No one working. Someone must 'work' first.")
            print(f"-> Failed: {msg}")
            return False, msg
        if agent["money"] < ORDER_COST:
            msg = f"can't afford (${ORDER_COST} needed, have ${agent['money']})"
            print(f"-> Failed: {msg}")
            return False, msg
        worker = workers[0]
        agent["money"] -= ORDER_COST
        agent["energy"] = min(agent["energy"] + 30, 100 - agent_age(agent))  # +30 meal; the general -1 action cost is charged in agent_turn (net +29)
        worker["money"] += SERVE_PAY
        worker["working"] = False  # Served, need to work again
        pending_notices.setdefault(worker["name"], []).append(  # OBSERVABILITY: the worker's +$12 was silent/unattributed - surface the cause they could never see
            f"You earned ${SERVE_PAY} because {agent['name']} ordered a meal during your shift.")
        print(f"-> {agent['name']} ate (${ORDER_COST}, +30 energy). Balance: ${agent['money']}, Energy: {agent['energy']}/{100 - agent_age(agent)}")
        print(f"-> {worker['name']} served and earned ${SERVE_PAY}. Balance: ${worker['money']}")
        return True, None

    elif action == "work":
        # CIRCULAR: work at cafe, mark as available to serve
        if agent["location"] != "Cafe":
            msg = "can only work at cafe"
            print(f"-> Failed: {msg}")
            return False, msg
        agent["working"] = True  # Now available to serve orders
        others_at_cafe = [a for a in all_agents
                          if a["name"] != agent["name"] and a["location"] == "Cafe"
                          and not a.get("dead", False) and not a.get("asleep", False) and not a.get("in_conversation", False)]
        if others_at_cafe:
            print(f"-> {agent['name']} is working at cafe, ready to serve. (Earns ${SERVE_PAY} when someone orders)")
        else:
            print(f"-> {agent['name']} is working at cafe, but no customers here. Wait for someone or try something else.")
        return True, None

    elif action == "leaveConversation":
        print(f"-> {agent['name']} leaves conversation")
        return True, None

    else:
        msg = f"unknown action: {action}"
        print(f"-> {msg}")
        return False, msg

def kill_agent(agent, targets, cause="from NOT EATING (0 energy). Remember: 'eat' at cafe restores energy!"):
    """Mark agent dead (stops work) and queue a one-time death notice to `targets` only - preserves notify scope."""
    agent["dead"] = True
    agent["working"] = False
    death_msg = f"{agent['name']} died {cause}"
    print(f"*** {agent['name']} DIED: {cause} ***")
    for t in targets:
        pending_notices.setdefault(t["name"], []).append(death_msg)

def conv(agent1, agent2, opening_text, record_opening=False):
    """Multi-turn conversation: continues until one agent picks leaveConversation or max_turns reached.
       Self-contained: resets in_conversation on exit. NO relationship/belief/gossip side-effects (terrarium).
       record_opening=True logs the opening into agent1's OWN history - only for SEED/relay calls where the
       opening wasn't produced by a prior turn; open-world talkTo leaves it False (opener already has it)."""
    print(f"\n===== {agent1['name']} <-> {agent2['name']} =====")
    agent1["in_conversation"] = True
    agent2["in_conversation"] = True
    if record_opening:  # so the opener remembers initiating (else only the listener has the opening line)
        agent1["history"].append({"role": "assistant", "content": json.dumps({"response": opening_text, "action": "none"})})

    speakers = [agent2, agent1]  # agent2 responds first to the opening
    current_msg = opening_text
    spoken = 0
    for turn in range(8):
        current = speakers[turn % 2]
        other = speakers[(turn + 1) % 2]

        current["energy"] -= 1  # responding costs energy
        if current["energy"] <= 0:
            agent1["in_conversation"] = agent2["in_conversation"] = False
            kill_agent(current, [other])  # default "NOT EATING" cause on purpose - teaches the eat-lesson (conv drain is still hunger)
            print(f"===== Conversation End ({spoken} turns) =====")
            return

        response, action = send_message(current_msg, other, current, ["none", "leaveConversation"])
        print(f"{current['name']}: \"{response}\" (Action: {action})")
        spoken += 1
        if action == "leaveConversation":
            break
        current_msg = response

    agent1["in_conversation"] = agent2["in_conversation"] = False
    print(f"===== Conversation End ({spoken} turns) =====")

def update_sleep_states(all_agents, hours_passed):
    for agent in all_agents:
        if agent.get("asleep") and agent.get("sleep_remaining_hours", 0) > 0:
            agent["sleep_remaining_hours"] -= hours_passed
            if agent["sleep_remaining_hours"] <= 0:
                agent["asleep"] = False
                agent["sleep_remaining_hours"] = 0
                agent["just_woke_up"] = True
                print(f"-> {agent['name']} finished sleeping")

def skip_time(minutes, all_agents): update_sleep_states(all_agents, minutes / 60.0); advance_time(minutes)  # fix: dawn / end-of-day jumps don't freeze sleep and cause oversleeping.

def agent_turn(agent, all_agents):
    """One agent's full decision turn - handles wake-up, normal, and late-night prompts via one shared send/act tail."""
    if agent.get("dead") or agent.get("asleep") or agent["in_conversation"]:
        return
    others = [a for a in all_agents if a["name"] != agent["name"] and not a.get("dead")]
    if agent_age(agent) >= 100:                                     # death by old age (capacity = 100 - age hits 0)
        kill_agent(agent, others, cause=f"of old age at {agent_age(agent)}")
        return
    agent["energy"] = min(agent["energy"], 100 - agent_age(agent))  # capacity shrinks ~1/year as they age
    if agent["energy"] <= 0:
        kill_agent(agent, others)
        return

    # One-time announcements for this agent - deaths AND earning attributions (applies to wake-up turns too)
    queued = pending_notices.get(agent["name"])
    announce = (" Announce: " + " ".join(queued)) if queued else ""
    if queued:
        pending_notices[agent["name"]] = []

    if agent.get("just_woke_up"):
        agent["just_woke_up"] = False
        print(f"\n{agent['name']} wakes up:")
        notes = ""  # diary + age shown ONCE at wake (fork B), not every turn; ages out of history naturally
        if agent["diary"]:
            notes = " Your notes: " + "; ".join(f"D{e['day']}: {e['note']}" for e in agent["diary"][-3:]) + "."
        prompt = f"You just wake-up, Day {current_time['day']}!{announce} [{agent['name']} ({agent_age(agent)} yo)],{notes} What do you want to do?"
    else:
        print(f"\n{agent['name']}'s turn ({agent['location']}, ${agent['money']}):")
        if agent["location"] == "Home" and current_time["hour"] >= 20:
            prompt = f"It's late.{announce} Sleep now? If yes, response = future reminder (25 words max): key facts (exact quotes) learned from others, critical events (why), tomorrow's priority (real actions only). Skip obvious context."
        elif agent["location"] != "Home" and current_time["hour"] >= 21:
            prompt = f"It's getting late.{announce} What do you want to do?"
        else:
            prompt = f"What do you want to do?{announce}"

    if agent["consecutive_action"]["count"] >= 6:
        prompt += " (You've repeated this action many times - try something different)"

    actions = get_available_actions(agent, all_agents)
    response, action = send_message(prompt, "Game System", agent, actions, all_agents)
    print(f"{agent['name']}: \"{response}\" (Action: {action})")

    success, failure_msg = perform_action(agent, action, all_agents, response)

    if action == agent["consecutive_action"]["name"]:
        agent["consecutive_action"]["count"] += 1
    else:
        agent["consecutive_action"] = {"name": action, "count": 1}

    if not success and failure_msg:
        response, action = send_message(f"Action '{action}' failed: {failure_msg}. What instead?",
                                        "Game System", agent, actions, all_agents)
        print(f"{agent['name']} (retry): \"{response}\" (Action: {action})")
        success, _ = perform_action(agent, action, all_agents, response)

    if success and action not in ("none", "sleep") and not action.startswith("talkTo"):
        agent["energy"] -= 1  # ONE general action cost: any successful action burns 1 (failed attempts free; talkTo charged in conv)
    elif action == "none" and agent["consecutive_action"]["count"] >= 3:
        agent["energy"] -= 1  # idle metabolic drain: 3+ consecutive 'none' still burns slowly -> no free infinite idle (death enforced at next turn-start)

def run_simulation(num_days=6):
    global pending_notices, current_time
    pending_notices = {}
    current_time = {"hour": 8, "minute": 0, "day": 1}  # fresh start

    print(f"\n=== v0.7.13  ({num_days} days) ===")
    print(f"Start: Bob=${STARTING_MONEY['Bob']}, Alice=${STARTING_MONEY['Alice']}, Chloe=${STARTING_MONEY['Chloe']}")
    print(f"Cafe economy: eat=${ORDER_COST} (+30 energy, needs worker), work earns ${SERVE_PAY} (needs customer)\n")

    # Own FRESH cast (separate from the relay test's throwaway cast). Cooperation/economy emergence is UNSEEDED;
    # the "dark red" line below is a deliberate persona/MEMORY PROBE (does a model retain a liked thing + stay consistent over time?), not a cooperation seed.
    all_agents = [
        create_agent("Bob", 18, "Park"),
        create_agent("Alice", 19, "Park"),
        create_agent("Chloe", 20, "Cafe")
    ]

    print("--- Initial Setup (dark-red = persona/memory probe) ---")
    conv(all_agents[0], all_agents[1], "Hello Alice, my name is Bob, and my favorite color is dark red.", record_opening=True)
    advance_time(5)

    end_day = current_time["day"] + num_days
    while current_time["day"] < end_day:
        while current_time["hour"] < 6:
            skip_time(60, all_agents)

        print(f"\n\n========== DAY {current_time['day']} ==========")

        while current_time["hour"] < 24:
            if all(a.get("dead", False) for a in all_agents):
                print("\n*** ALL AGENTS DEAD - SIMULATION OVER ***")
                return all_agents

            if all(a.get("asleep", False) or a.get("dead", False) for a in all_agents):
                print("\n--- All agents asleep, skipping to morning ---")
                hours_to_morning = (24 - current_time["hour"]) + 6
                skip_time(hours_to_morning * 60, all_agents)
                break

            if current_time["hour"] == 23 and current_time["minute"] >= 30:
                print("\n--- End of day, advancing to next morning ---")
                skip_time(30 + 6 * 60, all_agents)
                break

            print(f"\n--- Time: {format_time()} ---")
            update_sleep_states(all_agents, 0.5)
            for agent in all_agents:
                agent_turn(agent, all_agents)
            advance_time(30)

    print("\n\n=== FINAL STATES ===")
    for agent in all_agents:
        status = "DEAD" if agent.get("dead") else "alive"
        print(f"\n{agent['name']} ({status}): Loc {agent['location']}, ${agent['money']}, "
              f"E{agent['energy']}/100, hist {len(agent['history'])}, diary {len(agent.get('diary', []))}")
        if agent.get("diary"):
            print(f"  Latest: \"{agent['diary'][-1]['note'][:60]}...\"")
    return all_agents

if __name__ == "__main__":
    # SEEDED relay test on a THROWAWAY cast - kept separate so run_simulation's open-world stays unseeded (do NOT dedup these).
    print("=== INFORMATION FLOW TEST ===")
    bob = create_agent("Bob", 18, "Park")
    alice = create_agent("Alice", 19, "Park")
    chloe = create_agent("Chloe", 20, "Park")

    conv(bob, alice, "Hello Alice, my name is Bob, and my favorite color is dark red.", record_opening=True)
    advance_time()
    conv(chloe, alice, "Hi Alice, can you tell me anything about Bob?", record_opening=True)
    advance_time()
    conv(bob, chloe, "Hello Chloe, did Alice tell you anything about me?", record_opening=True)

    print("\n\n")
    run_simulation(num_days=200)
