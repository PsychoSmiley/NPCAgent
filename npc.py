# npc.py - NPCAgent v0.8.1 - player-as-actor seam (--player -> PersonX joins) + audit fixes; circular economy, aging-death, diary v3, multi-turn conv
import requests
import json
import re
import time
import sys

# --- Configuration ---
VERBOSE_LOGGING = False
SHOW_SUMMARY    = True   # always print diary consolidation (even when VERBOSE off) so the lossy compression is visible
BASE_URL = "http://127.0.0.1:5000/v1"   # local OpenAI-compatible proxy port
API_KEY = "proxy-dont-need-it"
MODEL_NAME = 'claude-opus-4-8'  # OpenAI-compatible model id
REASONING_ENABLED = True   # send {'reasoning':{'enabled':True}}; set False for plain endpoints (Gemma/old) that 400 on unknown keys
MAX_HISTORY_MESSAGES = 50   # was 25; modest bump eases worst diary scroll-out while keeping diary-only memory meaningfully tested
MAX_RESPONSE_TOKENS = 32000
PLAYER = next((a.split("=", 1)[1] or "PersonX" if "=" in a else "PersonX" for a in sys.argv if a == "--player" or a.startswith("--player=")), None)  # --player or --player=Name : that name joins as a human-controlled agent (default PersonX). A normal NPC name, never "user"/"player" -> no assistant-bias; all downstream identical.
PERSONALITIES = []  # per-agent traits by index: ["curious and shy", "bold", ""] -> agent[0] gets "curious and shy", agent[1] gets "bold", agent[2] gets none

# --- Diary v3 Config ---
MAX_DIARY_ENTRIES = 15      # Keep last 15 days raw, then summarize oldest
DIARY_SUMMARIZE_COUNT = 10  # Summarize 10 oldest when exceeds max

# --- Economy Config ---
STARTING_MONEY = 10   # scalar scarcity knob ($10 showed cooperation in v0.7.7); the per-agent spawn default, no name-keying
ORDER_COST = 10   # Customer pays
SERVE_PAY = 12    # Worker earns when customer orders (+$2 profit rewards coordination)

# --- Aging Config ---
DAYS_PER_YEAR = 28   # 1 year = 4 weeks: weeks stay sub-year, birthday ~monthly (not every day)

# --- World State ---
current_time = {"hour": 8, "minute": 0, "day": 1}
pending_notices = {}  # {agent_name: [one-time notices (deaths, earnings) to announce at the agent's next turn]}
LOCATIONS = {  # 'none' = implicit default action, excluded from each list
    "Park": {"context": "at the park", "actions": ["goHome", "goCafe"]},  # social only
    "Home": {"context": "at home", "actions": ["sleep", "goPark", "goCafe"]},
    "Cafe": {"context": "at the cafe", "actions": ["eat", "work", "goHome", "goPark"]}  # economy
}

# --- System Prompt (hand-tuned, verbatim; [HOBBY] -> "collecting stamps": concrete, impossible-in-world, non-adoptable per TODO#3) ---
BASE_SYSTEM_PROMPT = """You are {name}, an NPC character in an interactive game-simulated world. You think and respond only as {name}{personality}. Not a robotic and overly polite helpful assistant.

Your task is to respond to all situations by generating only one valid single-line JSON in format: {{"response": "your_reasoning_then_speech", "action": "keyword_from_possibleAction"}}

You consider meaningful connections and novel experiences. You get restless doing the same thing repeatedly - if you've been talking to the same person or staying in one place too long, try something different. Balance socializing with rest and sleep to form memories.

- The "response" field reflects natural talking reasoning that flows from current goals and feelings, considering memories observations, opinions, judgments, questions about others or social consequences, optionally in conv-omit own reasoning, then shares thoughts that help/answer/decide actions seamlessly. Gathering more information, learning from failure's root cause and adapt. Quote memories exactly as learned, never invent facts/names/places not existing. If uncertain, say "I don't know".
- Facts in context ARE your memories. Vary greetings - mention facts only when relevant, not as greeting template. Be humanly multitask: current situation, make future plans and follow through, ask questions, explore and find opportunities when idle. Let craft persona through interactions and emotional - relationships evolve naturally (trust, loyalty, closeness, love vs distrust, distance, rivalry, betrayal - range not limited to these). Realize unexpected, leverage, negotiate, build upon ideas and democratize. Time: 1 year = {weeks}.
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

def create_agent(name, age=18, location="Park", money=STARTING_MONEY, personality=""):
    persona = f", a person who {personality.strip()}" if personality and personality.strip() else ""
    wk = DAYS_PER_YEAR // 7
    span = f"{wk} week{'s' if wk != 1 else ''}" if DAYS_PER_YEAR % 7 == 0 else f"{DAYS_PER_YEAR} day{'s' if DAYS_PER_YEAR != 1 else ''}"  # 28->"4 weeks", 7->"1 week", 30->"30 days", 1->"1 day"
    prompt = BASE_SYSTEM_PROMPT.format(name=name, personality=persona, weeks=span)   # {weeks} placeholder reads best; value falls back to days when not a clean week multiple
    return {
        "name": name,
        "location": location,
        "money": money,
        "age": age,                  # years lived; energy capacity = 100 - age
        "birth_day": current_time["day"],
        "energy": 100 - age,         # start at this age's full capacity
        "working": False,
        "dead": False,
        "history": [{"role": "system", "content": prompt}],
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
    if REASONING_ENABLED: data['reasoning'] = {'enabled': True}   # reasoning model (Nemotron); REASONING_ENABLED=False for plain endpoints (Gemma/old) that reject unknown keys
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
            raw = (msg.get('content') or msg.get('reasoning_content') or msg.get('reasoning') or '').strip()  # reasoning models (DeepSeek/Nemotron) put JSON in reasoning_content when content is empty
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
            if not isinstance(parsed.get("response"), str):  # coerce non-str response too, else a later note[:80] crashes the whole run
                parsed["response"] = str(parsed.get("response", ""))
            result = parsed
    if result is not None:
        return result   # dict; caller json.dumps once for the history string
    if VERBOSE_LOGGING:
        print(f"WARNING EXTRACTOR ({agent_name}): Could not extract JSON")
    return None

def player_input(prompt, actions, agent=None):
    """Human controller - identical (response, action) contract to send_message. Invalid/empty action -> 'none' (perform_action does not enforce the menu)."""
    status = ""
    if agent:
        cap = 100 - agent_age(agent)
        status = f"  [{agent['name']}] ${agent['money']} | E{agent['energy']}/{cap} | {agent['location']} | {format_time()}\n"
    print(f"\n>>> YOUR TURN <<<\n{status}{prompt}\n  possibleAction: {', '.join(actions)}")
    resp = input("  response: \x1b[2m(optional)\x1b[0m").strip() or "..."
    tab  = f"\x00TAB:{','.join(actions)}" if sys.platform == "emscripten" else ""  # browser harness strips the suffix into Tab-cycle completions
    act  = input(f"  action:   {tab}").strip()
    match = next((a for a in actions if a.lower() == act.lower()), "none")
    return resp, match

def send_message(prompt_text, source, target_agent, possible_actions, all_agents=None):
    source_name = source if isinstance(source, str) else source["name"]
    location_ctx = LOCATIONS[target_agent['location']]['context']

    # Visible workers info - only an agent AT the cafe can see who's behind the counter (no remote omniscience)
    cafe_status = ""
    if all_agents and target_agent['location'] == 'Cafe':
        workers = [('you' if a['name'] == target_agent['name'] else a['name'])
                   for a in all_agents if a['location'] == 'Cafe' and a.get('working', False)
                   and not a.get('asleep', False) and not a.get('dead', False)]  # working+chatting can't coexist (start_conv drops the job)
        cafe_status = f" Cafe: {', '.join(workers)} working." if workers else " Cafe: no one working."
        # factual only: who's behind the counter (lets an eater know a worker is present). Co-presence = talkToX in the menu; pay = the earned-$ notice

    context = f"located {location_ctx}, own ${target_agent['money']}, energy {target_agent['energy']}/{100 - agent_age(target_agent)}.{cafe_status} It's {format_time()}."

    payload = {"input": prompt_text, "context": context, "possibleAction": ", ".join(possible_actions)}
    target_agent["history"].append({"role": "user", "content": f"{source_name} says: {json.dumps(payload)}"})
    if VERBOSE_LOGGING: print(f"\n[TO {target_agent['name']}]: {target_agent['history'][-1]['content']}")

    if len(target_agent["history"]) > MAX_HISTORY_MESSAGES + 1:
        target_agent["history"] = [target_agent["history"][0]] + target_agent["history"][-MAX_HISTORY_MESSAGES:]

    raw = llm_post(target_agent["history"], label=target_agent['name'])
    parsed = extract_clean_json(raw, target_agent['name'])
    if parsed:
        target_agent["history"].append({"role": "assistant", "content": json.dumps(parsed)})
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
            start_conv(agent, target, response_text if response_text else f"Hello {target_name}.", all_agents=all_agents)
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
        # Save FULL response as note (prompt asks 25 words - no truncation: an oversized note = a system bug that must stay visible in the log, not be silently clamped)
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
                   and not a.get("asleep", False) and not a.get("dead", False)]  # working+chatting can't coexist (start_conv drops the job)
        if not workers:
            msg = ("You can't serve yourself! Need another person working here." if agent.get("working")
                   else "No one working. Someone must 'work' first.")
            print(f"-> Failed: {msg}")
            return False, msg
        if agent["money"] < ORDER_COST:
            msg = f"can't afford (${ORDER_COST} needed, have ${agent['money']})"
            print(f"-> Failed: {msg}")
            return False, msg
        worker = workers[0]   # single worker enforced by the work-guard, so this is the sole server (deterministic)
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
        busy = [a for a in all_agents if a["name"] != agent["name"] and a["location"] == "Cafe"
                and a.get("working", False) and not a.get("dead", False) and not a.get("asleep", False)]  # match eat's filter
        if busy:  # only ONE worker at a time - the job is a scarce, contested role; others can 'eat' (order) instead
            msg = f"{busy[0]['name']} is already working here - order (eat) instead"
            print(f"-> Failed: {msg}")
            return False, msg
        agent["working"] = True  # Now available to serve orders
        for other in all_agents:  # single-worker invariant: taking the job strips it from anyone else 'working' (e.g. a holder who fell asleep) - the takeover is observable social material
            if other is not agent and other["location"] == "Cafe" and other.get("working", False):
                other["working"] = False
                pending_notices.setdefault(other["name"], []).append(f"You lost the cafe job to {agent['name']} while you were away from the counter.")
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

def start_conv(agent1, agent2, opening_text, record_opening=False, all_agents=None):
    """Open a conversation - sets state, doesn't run turns. Each agent advances it on THEIR regular turn via conv_turn().
       This way other agents keep acting while two people talk (no 8-turn freeze)."""
    print(f"\n===== {agent1['name']} <-> {agent2['name']} =====")
    for a in (agent1, agent2):  # work XOR chat: joining a conversation means leaving the counter, you can't hold both
        if a.get("working"):
            a["working"] = False
            pending_notices.setdefault(a["name"], []).append("You left the cafe counter to chat - the job is open again.")
    agent1["in_conversation"] = True
    agent2["in_conversation"] = True
    state = {"speakers": [agent1, agent2], "next": 1, "turns": 0, "msg": opening_text, "all_agents": all_agents}
    agent1["conv_state"] = state
    agent2["conv_state"] = state
    if record_opening:
        agent1["history"].append({"role": "assistant", "content": json.dumps({"response": opening_text, "action": "none"})})
    print(f"{agent1['name']}: \"{opening_text}\"")

def end_conv(state, hit_limit=False):
    for a in state["speakers"]:
        a["in_conversation"] = False
        a.pop("conv_state", None)
    tag = f"{state['turns']} turns, limit" if hit_limit else f"{state['turns']} turns"
    print(f"===== Conversation End ({tag}) =====")

def conv_turn(agent):
    """Advance a conversation by one exchange for this agent. Called from agent_turn when in_conversation is True."""
    state = agent.get("conv_state")
    if not state:
        agent["in_conversation"] = False
        return
    idx = 0 if agent is state["speakers"][0] else 1
    if idx != state["next"]:
        return
    current = state["speakers"][idx]
    other = state["speakers"][1 - idx]
    if other.get("dead"):
        end_conv(state)
        return
    current["energy"] -= 1
    if current["energy"] <= 0:
        targets = [a for a in state["all_agents"] if a is not current and not a.get("dead")] if state["all_agents"] else [other]
        end_conv(state)
        kill_agent(current, targets)
        return
    response, action = (player_input(state["msg"], ["none", "leaveConversation"], current) if current.get("player")
                        else send_message(state["msg"], other, current, ["none", "leaveConversation"]))
    print(f"{current['name']}: \"{response}\" (Action: {action})")
    state["turns"] += 1
    state["msg"] = response
    state["next"] = 1 - idx
    if action == "leaveConversation" or state["turns"] >= 8:
        if response:  # the conversation-ending line was displayed but never delivered (state dies before the listener's turn) - queue it, partings carry key info (departures, plans, agreements)
            pending_notices.setdefault(other["name"], []).append(f'{current["name"]} said before parting: "{response}"')
        end_conv(state, hit_limit=(state["turns"] >= 8 and action != "leaveConversation"))

def conv(agent1, agent2, opening_text, record_opening=False, all_agents=None):
    """Legacy blocking conv - used ONLY for the seeded relay test (throwaway cast, no interleaving needed)."""
    start_conv(agent1, agent2, opening_text, record_opening=record_opening, all_agents=all_agents)
    state = agent1["conv_state"]
    while agent1.get("conv_state"):
        conv_turn(state["speakers"][state["next"]])

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
    if agent.get("dead") or agent.get("asleep"):
        return
    if agent.get("in_conversation"):
        conv_turn(agent)
        return
    others = [a for a in all_agents if a["name"] != agent["name"] and not a.get("dead")]  # a death is broadcast to EVERYONE living - agents must learn a person is gone (stop talking to them, grief), it's essential info, not an omniscient leak
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
    response, action = (player_input(prompt, actions, agent) if agent.get("player")
                        else send_message(prompt, "Game System", agent, actions, all_agents))
    print(f"{agent['name']}: \"{response}\" (Action: {action})")

    success, failure_msg = perform_action(agent, action, all_agents, response)

    if not success and failure_msg:
        retry = f"Action '{action}' failed: {failure_msg}. What instead?"
        response, action = (player_input(retry, actions, agent) if agent.get("player")
                            else send_message(retry, "Game System", agent, actions, all_agents))
        print(f"{agent['name']} (retry): \"{response}\" (Action: {action})")
        success, _ = perform_action(agent, action, all_agents, response)

    # anti-loop counter tracks the FINAL executed action (post-retry) so idle-drain reads a consistent count
    if action == agent["consecutive_action"]["name"]:
        agent["consecutive_action"]["count"] += 1
    else:
        agent["consecutive_action"] = {"name": action, "count": 1}

    if success and action not in ("none", "sleep") and not action.startswith("talkTo"):
        agent["energy"] -= 1  # ONE general action cost: any successful action burns 1 (failed attempts free; talkTo charged in conv)
    elif action == "none" and agent["consecutive_action"]["count"] >= 3:
        agent["energy"] -= 1  # idle metabolic drain: 3+ consecutive 'none' still burns slowly -> no free infinite idle (death enforced at next turn-start)

def run_simulation(num_days=6):
    global pending_notices, current_time, all_agents
    pending_notices = {}
    current_time = {"hour": 8, "minute": 0, "day": 1}  # fresh start

    print(f"\n=== v0.8.1  ({num_days} days) ===")
    print(f"Cafe economy: eat=${ORDER_COST} (+30 energy, needs worker), work earns ${SERVE_PAY} (needs customer)\n")

    # Own FRESH cast (separate from the relay test's throwaway cast). Cooperation/economy emergence is UNSEEDED;
    # the "dark red" line below is a deliberate persona/MEMORY PROBE (does a model retain a liked thing + stay consistent over time?), not a cooperation seed.
    all_agents = [
        create_agent("Bob", 18, "Park", personality=PERSONALITIES[0] if len(PERSONALITIES) > 0 else ""),
        create_agent("Alice", 19, "Park", personality=PERSONALITIES[1] if len(PERSONALITIES) > 1 else ""),
        create_agent("Chloe", 20, "Cafe", personality=PERSONALITIES[2] if len(PERSONALITIES) > 2 else "")
    ]
    if PLAYER:
        name = "PersonX" if PLAYER in [a["name"] for a in all_agents] else PLAYER   # PLAYER is the chosen name (default PersonX); fall back if it collides with an NPC
        human = create_agent(name, 21, "Park")   # a human joins the terrarium as a 4th actor; a normal NPC name (never "user"/"player") so the LLM gets no assistant-bias
        human["player"] = True
        all_agents.append(human)
        print(f"[PLAYER MODE] You are {name} - enter response + action on your turns; everything else is identical.")

    print("Start money: " + ", ".join(f"{a['name']}=${a['money']}" for a in all_agents))
    print("--- Initial Setup (dark-red = persona/memory probe) ---")
    start_conv(all_agents[0], all_agents[1], "Hello Alice, my name is Bob, and my favorite color is dark red.", record_opening=True, all_agents=all_agents)
    # seed conv runs through the first few ticks of the main loop (interleaved with other agents), not as a blocking call

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
              f"E{agent['energy']}/{100 - agent_age(agent)}, hist {len(agent['history'])}, diary {len(agent.get('diary', []))}")
        if agent.get("diary"):
            print(f"  Latest: \"{agent['diary'][-1]['note'][:60]}...\"")
    return all_agents

if __name__ == "__main__":
    # SEEDED relay test on a THROWAWAY cast - run_simulation builds its own fresh unseeded cast, so these agents are discarded (do NOT dedup these).
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
