# npc.py - NPCAgent v0.9.2 - reproduction mod (askSexPossibleChild -> gestation -> parent-named birth) on generic mod seams; player-as-actor, circular economy, aging-death, diary v3, snapshot restore
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
MAX_CONV_TURNS = 8   # utterances per conversation, BOTH speakers count (8 = 4 lines each); the cap ends it with "(N turns, limit)"
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

# --- Reproduction Config ---
GESTATION_DAYS = 21            # ~9 months at 28-day years; pure countdown, nothing else happens until the due day
REPRODUCTION_HOME_ONLY = True  # True: askSexPossibleChild only offered in conversations at Home (courtship: invite -> walk home -> ask); False: any location
ADULT_AGE = 18                 # engine-side menu gate: both partners must be adults or the action is never offered (the model never sees an age check)

# --- World State ---
current_time = {"hour": 8, "minute": 0, "day": 1}
pending_notices = {}  # {agent_name: [one-time notices (deaths, earnings) to announce at the agent's next turn]}
pregnancies = []  # [{"parents": (asker, accepter), "due": day, "namer": accepter}] - one per PAIR (different pairings independent); no living parent -> culled
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

def capacity(a): return 100 - agent_age(a)   # energy ceiling; shrinks ~1/year as they age

def cafe_workers(all_agents, exclude=None):  # the on-shift set; working+chatting can't coexist (start_conv drops the job)
    return [a for a in all_agents if a is not exclude and a["location"] == "Cafe" and a.get("working")
            and not a.get("asleep") and not a.get("dead")]

def available_others(agent, all_agents):  # co-located, awake, alive, not chatting - the talkable set
    return [a for a in all_agents if a is not agent and a["location"] == agent["location"]
            and not a.get("in_conversation") and not a.get("asleep") and not a.get("dead")]

def notify(name, msg, tag=None):   # queue a one-time notice for that agent's next turn
    q = pending_notices.setdefault(name, [])
    # A later notice on the same SUBJECT supersedes the stale one. Several attempts inside one unflushed batch used to
    # arrive as "we failed" + "we are expecting" + "we are already expecting" in a single prompt, reading as contradiction.
    if tag: q[:] = [n for n in q if n[0] != tag]
    q.append((tag, msg))

def strip_think(t): return re.sub(r'<think>.*?</think>', '', t, flags=re.DOTALL | re.IGNORECASE) if '</think>' in t.lower() else t   # reasoning models leak <think>; no-closer skip avoids a quadratic scan

def diary_notes(agent):  # consolidated head + last 3 raw notes, for the wake/birth prompts
    # The head matters: consolidation puts the summary at index 0 and leaves 6 raw entries behind, so the diary is
    # always >=7 long and a bare [-3:] could NEVER reach index 0 again. Every summary the sim paid an LLM call for was
    # written and then shown to nobody - the agent's real memory horizon was 3 nights, not the whole diary.
    d = agent["diary"]
    if not d: return ""
    # only a real DIGEST earns the pinned slot. Before the first consolidation d[0] is just the oldest raw note, and
    # pinning that froze day 1 into every wake prompt for days 4-15 instead of letting it age out.
    shown = (d[:1] if d[0].get("span") else []) + d[-3:] if len(d) > 3 else d
    span = lambda e: f"D{e['span'][0]}-{e['span'][1]}" if e.get("span") else f"D{e['day']}"   # a 10-day digest must not claim to be one day
    return " Your notes: " + "; ".join(f"{span(e)}: {e['note']}" for e in shown) + "."

def fail(msg): print(f"-> Failed: {msg}"); return False, msg   # perform_action failure tail: teach the mechanic, charge nothing

def advance_time(minutes=30):
    global current_time
    # int(): sleep_remaining_hours is decremented by 0.5, so the all-asleep jump can pass a float in here. That made
    # every clock field a float and the next format_time() raised on ':02d' - a long run died at a random night.
    total = int(current_time["day"] * 1440 + current_time["hour"] * 60 + current_time["minute"] + minutes)
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

FALLBACK_RESPONSE = "Let me think about this carefully first."   # send_message's JSON-failure sentinel; give_birth treats it as no-name

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
    text = strip_think(raw_text)
    result = None
    for span in _iter_json_spans(text):  # keep the LAST valid {"response":...} (skips leaked reasoning/examples)
        try:
            parsed = json.loads(span)
        except (ValueError, RecursionError):   # JSONDecodeError is a ValueError, but deep nesting raises RecursionError and a
            continue                           # 4301-digit number raises a bare ValueError - both escaped and killed the run
        if isinstance(parsed, dict) and "response" in parsed:
            if not isinstance(parsed.get("action"), str):  # coerce null/number/list/missing -> "none"
                parsed["action"] = "none"
            if not isinstance(parsed.get("response"), str):  # coerce non-str response too, else a later note[:80] crashes the whole run
                parsed["response"] = str(parsed.get("response", ""))
            parsed["action"] = parsed["action"].strip()   # small models emit "goCafe "
            result = parsed
    if result is not None:
        return result   # dict; caller json.dumps once for the history string
    if VERBOSE_LOGGING:
        print(f"WARNING EXTRACTOR ({agent_name}): Could not extract JSON")
    return None

def turn_context(agent, all_agents=None):
    # Visible workers info - only an agent AT the cafe can see who's behind the counter (no remote omniscience)
    cafe_status = ""
    if all_agents and agent['location'] == 'Cafe':
        workers = [('you' if a is agent else a['name']) for a in cafe_workers(all_agents)]
        cafe_status = f" Cafe: {', '.join(workers)} working." if workers else " Cafe: no one working."
        # factual only: who's behind the counter (lets an eater know a worker is present). Co-presence = talkToX in the menu; pay = the earned-$ notice
    return f"located {LOCATIONS[agent['location']]['context']}, own ${agent['money']}, energy {agent['energy']}/{capacity(agent)}.{cafe_status} It's {format_time()}."

def record_prompt(agent, source_name, prompt_text, possible_actions, all_agents):
    """The incoming turn, appended identically for an LLM agent and a human one - so the player's POV exports too."""
    payload = {"input": prompt_text, "context": turn_context(agent, all_agents), "possibleAction": ", ".join(possible_actions)}
    agent["history"].append({"role": "user", "content": f"{source_name} says: {json.dumps(payload, ensure_ascii=False)}"})
    if VERBOSE_LOGGING: print(f"\n[TO {agent['name']}]: {agent['history'][-1]['content']}")
    if len(agent["history"]) > MAX_HISTORY_MESSAGES + 1:
        tail = agent["history"][-MAX_HISTORY_MESSAGES:]
        if tail and tail[0]["role"] == "assistant": tail = tail[1:]  # keep user/assistant alternation: the trim always landed on an assistant turn, and strict APIs reject a system->assistant opening
        agent["history"] = [agent["history"][0]] + tail

def player_input(prompt_text, source, agent, possible_actions, all_agents=None):
    """Human controller - same signature, contract and history record as send_message. Invalid/empty action -> 'none' (perform_action does not enforce the menu)."""
    source_name = source if isinstance(source, str) else source["name"]
    record_prompt(agent, source_name, prompt_text, possible_actions, all_agents)
    # System facts arrive glued to the front of the partner's line (see conv_turn), which buried "the job is open again"
    # mid-sentence inside their dialogue. Split them back out so a notice reads as a notice, not as something Bob said.
    pre, _, said = prompt_text.rpartition("\n")
    shown = prompt_text if source_name == "Game System" else f'{source_name}: "{said}"'  # who is talking to you, same as the LLM gets inside its payload
    if pre and source_name != "Game System": shown = f"  \x1b[2m{pre.strip()}\x1b[0m\n{shown}"
    # the menu lists `work` wherever you stand at the Cafe, so who holds the counter has to be visible BEFORE the attempt
    # rather than only in the failure it causes. turn_context already computes this for the LLM; the human never saw it.
    job = ""
    if all_agents and agent["location"] == "Cafe":
        busy = [("you" if a is agent else a["name"]) for a in cafe_workers(all_agents)]
        job = f" | {', '.join(busy)} working" if busy else " | counter free"
    status = f"  [{agent['name']}] ${agent['money']} | E{agent['energy']}/{capacity(agent)} | {agent['location']}{job} | {format_time()}\n"
    print(f"\n>>> YOUR TURN <<<\n{status}{shown}\n  possibleAction: {', '.join(possible_actions)}")
    resp = input("  response: \x1b[2m(optional)\x1b[0m").strip() or "..."
    tab  = f"\x00TAB:{','.join(possible_actions)}" if sys.platform == "emscripten" else ""  # browser harness strips the suffix into Tab-cycle completions
    act  = input(f"  action:   {tab}").strip()
    match = next((a for a in possible_actions if a.lower() == act.lower()), "none")
    agent["history"].append({"role": "assistant", "content": json.dumps({"response": resp, "action": match}, ensure_ascii=False)})
    return resp, match

def send_message(prompt_text, source, target_agent, possible_actions, all_agents=None):
    source_name = source if isinstance(source, str) else source["name"]
    record_prompt(target_agent, source_name, prompt_text, possible_actions, all_agents)

    raw = llm_post(target_agent["history"], label=target_agent['name'])
    parsed = extract_clean_json(raw, target_agent['name'])
    if parsed:
        target_agent["history"].append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        return parsed.get("response", ""), parsed.get("action", "none")

    print(f"[ERROR] {target_agent['name']}: Failed to extract valid JSON")
    fb = {"response": FALLBACK_RESPONSE, "action": "none"}
    target_agent["history"].append({"role": "assistant", "content": json.dumps(fb, ensure_ascii=False)})
    return fb["response"], fb["action"]

# --- Diary Functions ---
def manage_diary_entries(agent):
    """Summarize oldest entries when diary exceeds max - NO agent context needed"""
    if len(agent["diary"]) <= MAX_DIARY_ENTRIES:
        return

    old_entries = agent["diary"][:DIARY_SUMMARIZE_COUNT]
    remaining = agent["diary"][DIARY_SUMMARIZE_COUNT:]
    label = lambda e: f"Day{e['span'][0]}-{e['span'][1]}" if e.get("span") else f"Day{e['day']}"
    entries_text = "\n".join(f"{label(e)}: {e['note']}" for e in old_entries)   # feed the summariser the true range of a prior digest, not just its end day

    # Simple LLM call for summary (NO agent context - just summarization task)
    raw = llm_post([{"role": "user", "content": SUMMARIZE_NOTE_PROMPT.format(entries=entries_text)}],
                   max_tokens=1000, temperature=0.3, retries=1, timeout=60, label="Summary")  # 100 got eaten by reasoning models' <think> -> empty -> 10 days of memory silently wiped
    raw = strip_think(raw)  # this call bypasses extract_clean_json, so strip here
    summary = ' '.join(raw.split())  # single line

    # Keep the raw entries when the call produced nothing. It used to write "Various events occurred" over ten real
    # days, so one timeout or a reasoning model that spent its budget inside <think> destroyed the research subject -
    # and the log gave an analyst no way to tell a bad summariser from a failed HTTP call.
    if not summary:
        print(f"[DIARY] {agent['name']}: summariser returned nothing - keeping the raw entries, retry at next sleep")
        return

    last_day = old_entries[-1]['day']
    # earliest day the batch actually covers, not the first entry's own day: a prior digest stores day=<its END>, so
    # reading that as the new start amputated everything before it - D1-D10 plus ten more became D10-D19, not D1-D19
    first_day = old_entries[0].get("span", (old_entries[0]['day'],))[0]
    agent["diary"] = [{"day": last_day, "span": (first_day, last_day), "note": summary}] + remaining
    if SHOW_SUMMARY:
        print(f"[DIARY] {agent['name']} consolidated D{first_day}-{last_day}:")
        print(f"  BEFORE ({len(old_entries)} notes): {entries_text[:400]}")
        print(f"  AFTER  (1 note): {summary}")

def get_available_actions(agent, all_agents):
    if agent["in_conversation"]:
        return ["none", "leaveConversation"]

    actions = LOCATIONS[agent["location"]]["actions"].copy()
    actions += [f"talkTo{a['name']}" for a in available_others(agent, all_agents)]

    return list(dict.fromkeys(["none"] + actions))  # none first, then de-dup order-preserving (deterministic prompts)

def perform_action(agent, action, all_agents, response_text=""):
    """Execute actions with CIRCULAR ECONOMY - both order and work need partners"""
    print(f"-> {agent['name']} attempts: {action}")

    if action == "none":
        return True, None  # 0 energy cost for doing nothing
    # The general -1 action cost is charged ONCE in agent_turn, only when the action SUCCEEDS (failed attempts free);
    # talkTo is charged per-turn inside conv(); none/sleep are free.

    if action.startswith("talkTo"):
        target_name = action[len("talkTo"):]   # slice the prefix; replace-all mangles names containing it
        target = next((a for a in available_others(agent, all_agents) if a["name"] == target_name), None)  # availability folded in: no self-match zombie, no dead-namesake shadowing
        if target:
            start_conv(agent, target, response_text if response_text else f"Hello {target_name}.", all_agents=all_agents)
            return True, None
        return fail(f"{target_name} is not available to talk")

    elif action.startswith("go"):
        destination = action[len("go"):]
        if destination not in LOCATIONS:
            return fail(f"unknown location {destination}")
        if destination == agent["location"]:
            return fail(f"you are already at the {destination}")  # was accepted, and silently dropped the cafe job on the way
        agent["location"] = destination
        agent["working"] = False  # Stop working when leaving
        print(f"-> {agent['name']} moved to {destination}")
        return True, None

    elif action == "sleep":
        if agent["location"] != "Home":
            return fail("can only sleep at home")
        if not (current_time["hour"] >= 20 or current_time["hour"] < 8):   # bedtime 20:00 -> 08:00, wrapping past midnight
            return fail(f"can only sleep between 20:00 and 08:00 (it's {current_time['hour']:02d}:{current_time['minute']:02d})")
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
            return fail("can only eat at cafe")
        workers = cafe_workers(all_agents, exclude=agent)
        if not workers:
            return fail("You can't serve yourself! Need another person working here." if agent.get("working")
                        else "No one working. Someone must 'work' first.")
        if agent["money"] < ORDER_COST:
            return fail(f"can't afford (${ORDER_COST} needed, have ${agent['money']})")
        worker = workers[0]   # single worker enforced by the work-guard, so this is the sole server (deterministic)
        agent["money"] -= ORDER_COST
        agent["energy"] = min(agent["energy"] + 30, capacity(agent))  # +30 meal; the general -1 action cost is charged in agent_turn (net +29)
        worker["money"] += SERVE_PAY
        worker["working"] = False  # Served, need to work again
        notify(worker["name"],  # OBSERVABILITY: the worker's +$12 was silent/unattributed - surface the cause they could never see
               f"You earned ${SERVE_PAY} because {agent['name']} ordered a meal during your shift.")
        print(f"-> {agent['name']} ate (${ORDER_COST}, +30 energy). Balance: ${agent['money']}, Energy: {agent['energy']}/{capacity(agent)}")
        print(f"-> {worker['name']} served and earned ${SERVE_PAY}. Balance: ${worker['money']}")
        return True, None

    elif action == "work":
        # CIRCULAR: work at cafe, mark as available to serve
        if agent["location"] != "Cafe":
            return fail("can only work at cafe")
        busy = cafe_workers(all_agents, exclude=agent)
        if busy:  # only ONE worker at a time - the job is a scarce, contested role; others can 'eat' (order) instead
            return fail(f"{busy[0]['name']} is already working here - order (eat) instead")
        agent["working"] = True  # Now available to serve orders
        # (no takeover sweep here: the `busy` check above already proves nobody else holds the job. The old loop was
        #  unreachable - it differed from cafe_workers() only by asleep/dead, and a worker can be neither, since sleep
        #  needs Home and any go/start_conv clears `working`. Its notice has never fired in any log.)
        others_at_cafe = available_others(agent, all_agents)
        if others_at_cafe:
            print(f"-> {agent['name']} is working at cafe, ready to serve. (Earns ${SERVE_PAY} when someone orders)")
        else:
            print(f"-> {agent['name']} is working at cafe, but no customers here. Wait for someone or try something else.")
        return True, None

    elif action == "leaveConversation":
        if not agent.get("in_conversation"):
            return fail("you are not in a conversation")  # was logged as a real exit, polluting any count of social events
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
        notify(t["name"], death_msg)

# --- Reproduction mod. Seams (add features here, core loops stay untouched): mod_conv_menu -> extra conv actions | mod_conv_action -> their effects | mod_turn_override -> claim a solo turn ---

# Conception is a COUNT, not a dice roll - the worn-out partner's energy sets how many attempts it takes. No RNG, so
# replay and rewind stay faithful; opaque enough that an agent has to notice the pattern instead of being told it.
# Energy carries age for free (capacity = 100 - age), so age 70 can never reach the top band and always needs three -
# fertility declines with age without a second rule. The requirement is re-read EVERY attempt, so eating makes earlier
# attempts count: try twice while starving, eat, try once more and it lands.
CONCEIVE_BANDS = ((67, 1), (34, 2), (0, 3))   # energy floor -> attempts needed; never more than 3
conception_tries = {}   # {sorted (nameA, nameB): attempts so far} - per PAIR and never reset by time, only by conceiving

def pair_key(a, b): return tuple(sorted((a["name"], b["name"])))

def tries_needed(a, b):   # the tired one governs: a couple is only as fertile as its weaker half
    e = min(a["energy"], b["energy"])
    return next(n for floor, n in CONCEIVE_BANDS if e >= floor)

def expecting(a, b):  # this exact pair's active pregnancy, else None; identity-based, a namesake child never matches
    return next((p for p in pregnancies if all(o is a or o is b for o in p["objs"])), None)

def mod_conv_menu(current, other, state):
    if state.get("sex_ask_from") == other["name"]:
        return ["acceptSexPossibleChild"]   # partner proposed - consent replaces ask
    # Pregnancy deliberately does NOT withhold this: sex is not only for conceiving, so an expecting pair keeps the
    # option. It simply cannot conceive twice, and mod_conv_action says so rather than failing mutely.
    if (state["turns"] < MAX_CONV_TURNS - 1   # a proposal needs the partner's NEXT turn to exist; offering it on the last one makes consent unreachable
            and agent_age(current) >= ADULT_AGE and agent_age(other) >= ADULT_AGE   # engine-side gate, the model never sees an age check
            and (not REPRODUCTION_HOME_ONLY or current["location"] == "Home")):
        return ["askSexPossibleChild"]
    return []

def mod_conv_action(current, other, state, action, acts):   # `action in acts` guards keep hallucinated keywords inert
    if action == "askSexPossibleChild" and action in acts:
        state["sex_ask_from"] = current["name"]   # one-shot: consent lives in the partner's next turn only
    elif action == "acceptSexPossibleChild" and action in acts:
        state.pop("sex_ask_from", None)
        # An expecting pair still goes ahead - sex is not only for conceiving - it just cannot conceive twice. Say that
        # plainly to both and to the screen: the old path refused mutely, so they kept renegotiating a settled pregnancy.
        pair = expecting(current, other)
        if pair:
            left = pair["due"] - current_time["day"]
            for me, them in ((current, other), (other, current)):
                notify(me["name"], f"You and {them['name']} already have a child on the way - due day {pair['due']}, {left} days from now.", tag=f"preg:{them['name']}")
            print(f"*** {other['name']} + {current['name']} - a child is already on the way, due day {pair['due']} ({left} days from now) ***")
            return   # no counter touched: a second pregnancy for one pair would fire two births
        # BOTH are told either way - a silent failure reads as the sim ignoring them. But the failure names how their
        # BODIES felt, never the counter: the energy link is for them to work out, which is the whole point of making it
        # a rule instead of a roll.
        key = pair_key(current, other)
        conception_tries[key] = conception_tries.get(key, 0) + 1
        if conception_tries[key] >= tries_needed(current, other):
            conception_tries.pop(key, None)
            due = current_time["day"] + GESTATION_DAYS
            pregnancies.append({"parents": (other["name"], current["name"]), "objs": (other, current), "due": due, "namer": current["name"]})   # accepter names; objs = identity, parents = display
            for me, them in ((current, other), (other, current)):
                # name the ONE who will be asked: only the accepter is prompted at birth, so "you two must agree on a
                # name" promised a joint deadline the sim never checks. Agreeing early is theirs to do, not a rule.
                who = "You" if me is current else current["name"]
                notify(me["name"], f"You and {them['name']} are expecting a child - it will be born on day {due}, {GESTATION_DAYS} days from now. {who} will name it at birth.", tag=f"preg:{them['name']}")
            print(f"*** {other['name']} + {current['name']} are expecting a child - due day {due} ({GESTATION_DAYS} days from now) ***")
        else:
            for me, them in ((current, other), (other, current)):
                notify(me["name"], f"You and {them['name']} tried to get a child and failed - your bodies felt too worn out for it.", tag=f"preg:{them['name']}")
            print(f"*** {other['name']} + {current['name']} tried to get a child and failed - too worn out ***")
    elif state.get("sex_ask_from") == other["name"] and action in acts:
        # A LEGITIMATE non-accept (none / leaveConversation) expires the ask; the refusal lives in their words, not a
        # stat. But `action in acts` matters: without it a fumbled keyword - the accepter emitting the ASKER's token
        # while saying a plain yes - silently consumed the proposal, and the engine read consent as a refusal.
        state.pop("sex_ask_from", None)

def mod_turn_override(agent, all_agents, announce=""):  # True = turn consumed; runs after conv routing, so a birth never interrupts mid-chat
    cull_orphan_pregnancies()
    preg = next((p for p in pregnancies if current_time["day"] >= p["due"] and any(o is agent for o in p["objs"])), None)
    if preg:
        namer = next((o for o in (preg["objs"][1], preg["objs"][0]) if not o.get("dead")), None)   # accepter names, survivor fallback
        if namer is agent:
            give_birth(agent, preg, all_agents, announce); return True
    return False

def cull_orphan_pregnancies():
    for p in pregnancies[:]:
        if all(o.get("dead") for o in p["objs"]):   # identity: a living namesake can't keep a dead couple's countdown alive
            pregnancies.remove(p); print(f"*** The child of {p['parents'][0]} and {p['parents'][1]} will never be born - both parents are gone ***")

def give_birth(agent, preg, all_agents, announce=""):  # due-day naming via the NORMAL pipeline (full history+diary in context), then the child spawns at Home
    agent["just_woke_up"] = False   # birth consumes the wake turn; notes surface here
    other = next(o for o in preg["objs"] if o is not agent)["name"]
    notes = diary_notes(agent)
    living = [a["name"] for a in all_agents if not a.get("dead")]
    prompt = f"Your child with {other} is born today!{announce}{notes} Give the newborn's name: answer with one single word, the name."
    name = ""
    for attempt in (1, 2):
        response, action = (player_input(prompt, "Game System", agent, ["none"], all_agents) if agent.get("player")
                            else send_message(prompt, "Game System", agent, ["none"]))
        print(f"{agent['name']}: \"{response}\" (Action: {action})")
        if (response or "").strip() == FALLBACK_RESPONSE: response = ""   # the JSON-failure sentinel is not a name
        words = re.findall(r"[A-Za-z]+", response or "")
        cand = (words[0] if len(words) == 1 else words[-1] if (words and attempt == 2) else "").capitalize()  # retry tolerates "her name is Zoe" -> last word
        if cand and cand not in living:   # dead names honorable, living ones collide
            name = cand; break
        prompt = ("A living person already carries that name - pick another. " if cand and cand in living else "") + "Answer with ONLY the name: one single word."
    placeholder = not name
    if placeholder:
        name = f"Kid{current_time['day']}"
        while name in living: name += "x"   # same-day twin placeholders stay unique
    child = create_agent(name, 0, "Home")  # DELIBERATE: keeps STARTING_MONEY. $0 would force parents to convert their
    # entire +$2-per-meal margin into the child, and that margin is already thin - birth would become a suicide pact.
    all_agents.append(child)   # full agent from breath one
    pregnancies.remove(preg)
    born = (f"No name was given, so the child is called {name}" if placeholder else f"{name} was born today") + \
           f" - child of {preg['parents'][0]} and {preg['parents'][1]}."
    for a in all_agents:   # public like a death - both parents always learn the name
        if not a.get("dead") and a["name"] != name:
            notify(a["name"], born)
    pending_notices.pop(name, None)   # a dead namesake's mail dies with them
    notify(name, f"You were born today by {preg['parents'][0]} and {preg['parents'][1]}. Live your life!")
    print(f"*** BIRTH: {born} ***")

def start_conv(agent1, agent2, opening_text, record_opening=False, all_agents=None):
    """Open a conversation - sets state, doesn't run turns. Each agent advances it on THEIR regular turn via conv_turn().
       This way other agents keep acting while two people talk (no 8-turn freeze)."""
    print(f"\n===== {agent1['name']} <-> {agent2['name']} =====")
    for a in (agent1, agent2):  # work XOR chat: joining a conversation means leaving the counter, you can't hold both
        if a.get("working"):
            a["working"] = False
            notify(a["name"], "You left the cafe counter to chat - the job is open again.")
    agent1["in_conversation"] = True
    agent2["in_conversation"] = True
    state = {"speakers": [agent1, agent2], "next": 1, "turns": 0, "msg": opening_text, "all_agents": all_agents}
    agent1["conv_state"] = state
    agent2["conv_state"] = state
    if record_opening:
        agent1["history"].append({"role": "assistant", "content": json.dumps({"response": opening_text, "action": "none"}, ensure_ascii=False)})
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
    acts = ["none", "leaveConversation"] + mod_conv_menu(current, other, state)   # mod seam: features append their keywords
    # System facts first, the partner's actual words LAST: the reply must answer what was just said, and the tail of a
    # prompt is where attention is strongest - the same reason diary notes live at the end of history.
    pre = take_wake(current) + take_notices(current)
    msg = (pre.strip() + "\n" + state["msg"]) if pre else state["msg"]   # newline, not a space: player_input splits here to show a notice as its own line instead of inside the speaker's quote
    response, action = (player_input(msg, other, current, acts, state["all_agents"]) if current.get("player")
                        else send_message(msg, other, current, acts))   # the LLM gets the speaker inside the payload; the player needs it on screen
    # An off-menu keyword here is inert by design (see mod_conv_action), but it PRINTED identically to an executed
    # open-world action, and only a following "-> X attempts:" line told them apart. Two separate log readers took it
    # for a dropped action and reported an engine bug. Name it inline instead - display only, nothing else changes.
    print(f"{current['name']}: \"{response}\" (Action: {action}{'' if action in acts else ' - ignored, not offered in conversation'})")
    mod_conv_action(current, other, state, action, acts)   # mod seam: feature effects
    state["turns"] += 1
    state["msg"] = response
    state["next"] = 1 - idx
    if action == "leaveConversation" or state["turns"] >= MAX_CONV_TURNS:
        if response:  # the conversation-ending line was displayed but never delivered (state dies before the listener's turn) - queue it, partings carry key info (departures, plans, agreements)
            notify(other["name"], f'{current["name"]} said before parting: "{response}"')
        end_conv(state, hit_limit=(state["turns"] >= MAX_CONV_TURNS and action != "leaveConversation"))

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

def take_notices(agent):
    """Flush this agent's queued one-time notices into a prompt fragment.
    Conversation turns MUST flush them too. When only the open-world turn did, anything raised mid-conversation - a
    conception, an earning, a death - waited for the conversation to end, so the only way to learn the outcome of your
    own action was to leave or hit the turn cap."""
    queued = pending_notices.get(agent["name"])
    if not queued:
        return ""
    pending_notices[agent["name"]] = []
    return " Announce: " + " ".join(m for _, m in queued)

def take_wake(agent):
    """Consume the wake flag for a turn spent inside a conversation.
    A partner can open a conversation on the very turn an agent wakes, and the greeting used to sit on the flag until
    the next OPEN-WORLD turn - printing "You just wake-up" an hour and several turns after actually waking. The diary
    notes ride along, because they are the only memory injection of the day and dropping them would cost real recall."""
    if not agent.get("just_woke_up"):
        return ""
    agent["just_woke_up"] = False
    print(f"\n{agent['name']} wakes up (mid-conversation):")
    return f" You just woke up, Day {current_time['day']}.{diary_notes(agent)}"

def agent_turn(agent, all_agents):
    """One agent's full decision turn - handles wake-up, normal, and late-night prompts via one shared send/act tail."""
    if agent.get("dead") or agent.get("asleep"):
        return
    if agent.get("in_conversation"):
        conv_turn(agent)
        return
    others = [a for a in all_agents if a is not agent and not a.get("dead")]  # a death is broadcast to EVERYONE living - agents must learn a person is gone (stop talking to them, grief), it's essential info, not an omniscient leak
    if agent_age(agent) >= 100:                                     # death by old age (capacity = 100 - age hits 0)
        kill_agent(agent, others, cause=f"of old age at {agent_age(agent)}")
        return
    agent["energy"] = min(agent["energy"], capacity(agent))  # capacity shrinks ~1/year as they age
    if agent["energy"] <= 0:
        kill_agent(agent, others)
        return

    # One-time announcements for this agent - deaths AND earning attributions (applies to wake-up turns too)
    announce = take_notices(agent)

    if mod_turn_override(agent, all_agents, announce):   # mod seam: a mod may claim this whole turn (e.g. due-day birth)
        return

    if agent.get("just_woke_up"):
        agent["just_woke_up"] = False
        print(f"\n{agent['name']} wakes up:")
        notes = diary_notes(agent)  # diary + age shown ONCE at wake (fork B), not every turn; ages out of history naturally
        prompt = f"You just wake-up, Day {current_time['day']}!{announce} [{agent['name']} ({agent_age(agent)} yo)],{notes} What do you want to do?"
    else:
        print(f"\n{agent['name']}'s turn ({agent['location']}, ${agent['money']}):")
        if agent["location"] == "Home" and (current_time["hour"] >= 20 or current_time["hour"] < 8):   # same window as the sleep gate, or an agent up at 03:00 is never offered bed
            prompt = f"It's late.{announce} Sleep now? If yes, response = future reminder (25 words max): key facts (exact quotes) learned from others, critical events (why), tomorrow's priority (real actions only). Skip obvious context."
        elif agent["location"] != "Home" and (current_time["hour"] >= 21 or current_time["hour"] < 8):
            prompt = f"It's getting late.{announce} What do you want to do?"
        else:
            prompt = f"What do you want to do?{announce}"

    if agent["consecutive_action"]["count"] >= 6:
        prompt += " (You've repeated this action many times - try something different)"

    actions = get_available_actions(agent, all_agents)
    response, action = (player_input(prompt, "Game System", agent, actions, all_agents) if agent.get("player")
                        else send_message(prompt, "Game System", agent, actions, all_agents))
    print(f"{agent['name']}: \"{response}\" (Action: {action})")

    success, failure_msg = perform_action(agent, action, all_agents, response)

    if not success and failure_msg:
        retry = f"Action '{action}' failed: {failure_msg}. What instead?"
        response, action = (player_input(retry, "Game System", agent, actions, all_agents) if agent.get("player")
                            else send_message(retry, "Game System", agent, actions, all_agents))
        print(f"{agent['name']} (retry): \"{response}\" (Action: {action})")
        success, _ = perform_action(agent, action, all_agents, response)

    # anti-loop counter tracks the FINAL executed action (post-retry) so idle-drain reads a consistent count
    if action == agent["consecutive_action"]["name"]:
        agent["consecutive_action"]["count"] += 1
    else:
        agent["consecutive_action"] = {"name": action, "count": 1}

    if success and action not in ("none", "sleep") and not action.startswith("talkTo"):
        agent["energy"] -= 1  # ONE general action cost: any successful action burns 1 (talkTo charged in conv)
        # DELIBERATE: failed attempts stay FREE. Charging for failure teaches agents not to try, which kills the
        # exploration the whole terrarium depends on. An agent can idle its way to death via the 'none' drain below.
    elif action == "none" and agent["consecutive_action"]["count"] >= 3:
        agent["energy"] -= 1  # idle metabolic drain: 3+ consecutive 'none' still burns slowly -> no free infinite idle (death enforced at next turn-start)

# --- Snapshot restore: seed the world from a saved archive envelope when the run's event log is gone ---
# A replay log re-DERIVES the world by re-running recorded replies through npc.py; a snapshot IS the world, so
# nothing is re-simulated. Everything below reads the envelope the browser harness already builds/uploads.
LOC_BY_CTX = {v["context"]: k for k, v in LOCATIONS.items()}   # "at home" -> "Home"; derived, so a mod's new location parses for free
SNAP_ROLES = {"system": "system", "human": "user", "gpt": "assistant"}   # the export's inverse: ShareGPT -> history roles
SNAP_STATE = re.compile(r"own \$(-?\d+), energy (-?\d+)/(\d+)")   # turn_context's money + energy/capacity
SNAP_CLOCK = re.compile(r"It's Day(\d+) (\d+):(\d+)")

def snap_num(v, fallback):  # an envelope is a file people SHARE: a null, a string or a list where a number belongs must not take the run down
    try: return int(v)
    except (TypeError, ValueError): return fallback

def snap_map(env, key): return env[key] if isinstance(env, dict) and isinstance(env.get(key), dict) else {}

def snap_rows(env):  # the sharegpt rows, shape-checked once for both readers below
    return [r for r in env["sharegpt"] if isinstance(r, dict)] if isinstance(env, dict) and isinstance(env.get("sharegpt"), list) else []

def snap_context(conv):
    """The agent's OWN context line, off its LAST incoming message. The envelope stores no location/energy/clock
       fields, but turn_context wrote all three into every prompt, so they survive inside the history."""
    for m in reversed(conv if isinstance(conv, list) else []):
        if not isinstance(m, dict) or m.get("from") != "human" or not isinstance(m.get("value"), str): continue
        try: payload = json.loads(m["value"][m["value"].index("{"):])   # "<speaker> says: {json}" - a speaker name can't contain '{'
        except ValueError: continue   # index() raises it too when there is no brace at all
        if isinstance(payload, dict) and isinstance(payload.get("context"), str): return payload["context"]
    return ""

def snapshot_clock(env):
    """Latest clock in the file. Agents can be mid-conversation at different timestamps, so the MAX is the real 'now';
       the envelope's own day is only a fallback, because a save at a day boundary stamps the day that just closed."""
    marks = (SNAP_CLOCK.search(snap_context(a.get("conversations"))) for a in snap_rows(env))
    best = max((tuple(int(g) for g in m.groups()) for m in marks if m), default=None)
    return {"day": best[0], "hour": best[1], "minute": best[2]} if best else {"day": max(1, snap_num(env.get("day") if isinstance(env, dict) else 1, 1)), "hour": 8, "minute": 0}

def restore_agent(name, conv, stats, diary):
    conv = [m for m in conv if isinstance(m, dict)] if isinstance(conv, list) else []
    ctx = snap_context(conv)
    st = SNAP_STATE.search(ctx)
    age = snap_num(stats.get("age"), 100 - int(st.group(3)) if st else 18)   # stats is authoritative; the context line is one turn stale. Capacity IS 100-age, the only other place age is written
    loc = next((k for c, k in LOC_BY_CTX.items() if f"located {c}," in ctx), "Park")
    a = create_agent(name, age, loc, snap_num(stats.get("money"), int(st.group(1)) if st else STARTING_MONEY))   # birth_day = the restored day: the birthday PHASE is unrecoverable, so the next one falls a full year out
    if st: a["energy"] = min(int(st.group(2)), capacity(a))
    a["dead"] = bool(stats.get("dead"))
    a["diary"] = [dict(e) for e in diary if isinstance(e, dict)] if isinstance(diary, list) else []
    hist = [{"role": SNAP_ROLES[m["from"]], "content": m["value"]} for m in conv
            if m.get("from") in SNAP_ROLES and isinstance(m.get("value"), str)]
    if hist: a["history"] = hist if hist[0]["role"] == "system" else a["history"] + hist   # keep a system head: a history opening on a user turn is rejected by strict APIs
    return a

def restore_cast(env):
    """Rebuild the cast + clock from an archive envelope. Sets current_time, returns the agents."""
    global current_time
    current_time = snapshot_clock(env)
    stats, diaries = snap_map(env, "stats"), snap_map(env, "diaries")
    rows = {}
    for row in snap_rows(env):   # a dead parent and the newborn named after them share an id, and stats/diaries
        if row.get("id"): rows[row["id"]] = row   # already collapsed onto the LAST of them - restore the one those stats describe
    agents = [restore_agent(n, r.get("conversations"), snap_map(stats, n), diaries.get(n)) for n, r in rows.items()]
    for a, r in zip(agents, rows.values()):
        if r.get("by") == "human": a["player"] = True   # newer envelopes mark the human's row; older ones need --player
    for name in stats:   # the export drops anyone who never completed an exchange (a newborn) - they still exist
        if name not in rows: agents.append(restore_agent(name, None, snap_map(stats, name), diaries.get(name)))
    if PLAYER and not any(a.get("player") for a in agents):
        human = next((a for a in agents if a["name"] == PLAYER), None)
        if not human:   # a name nobody carries JOINS the restored world, exactly as a fresh run adds a 4th actor
            human = create_agent(PLAYER, 21, "Park"); agents.append(human)
            print(f"[RESTORE] {PLAYER} is not in this snapshot - joining as a new actor.")
        human["player"] = True
    # Rebuild the due-day countdowns. Stored by NAME (an object cannot be serialised), so re-bind to the restored
    # objects here - `objs` is what expecting() and give_birth() match on, and identity is what stops a namesake child
    # from inheriting its parents' pregnancy.
    conception_tries.clear()
    for k, v in (env.get("tries") or {}).items() if isinstance(env, dict) else []:
        parts = tuple(sorted(str(k).split("|")))
        if len(parts) == 2 and snap_num(v, 0) > 0: conception_tries[parts] = snap_num(v, 0)
    by_name = {a["name"]: a for a in agents}
    for pr in (env.get("pregnancies") or []) if isinstance(env, dict) else []:
        names = list(pr.get("parents") or [])
        objs = tuple(by_name[n] for n in names if n in by_name)
        if len(objs) == 2 and snap_num(pr.get("due"), 0) > 0:
            pregnancies.append({"parents": tuple(names), "objs": objs,
                                "due": snap_num(pr.get("due"), 0), "namer": pr.get("namer") or names[-1]})
    print(f"\n--- STATE RESTORE: {len(agents)} agents, resuming at {format_time()} ---")
    print("    This is saved STATE, not a replay - nothing before this point is re-simulated.")
    for a in agents:
        print(f"    {a['name']}{' [you]' if a.get('player') else ''}: {'DEAD' if a['dead'] else a['location']}, ${a['money']}, "
              f"E{a['energy']}/{capacity(a)}, age {agent_age(a)}, hist {len(a['history'])}, diary {len(a['diary'])}")
    print(f"    Not in a snapshot, so reset: open conversations, sleep, cafe shifts, birthday phase."
          + (f" Carried over: {len(pregnancies)} pregnancy(ies)." if pregnancies else ""))
    return agents

def run_simulation(num_days=6, snapshot=None):
    global pending_notices, current_time, all_agents   # all_agents MUST stay global: the browser harness reads npc.all_agents for history export and the archive envelope
    pending_notices = {}
    pregnancies.clear()   # in-place: no global decl needed, mods keep their module ref
    current_time = {"hour": 8, "minute": 0, "day": 1}  # fresh start

    print(f"\n=== v0.9.2  ({num_days} days) ===")
    print(f"Cafe economy: eat=${ORDER_COST} (+30 energy, needs worker), work earns ${SERVE_PAY} (needs customer)\n")

    if snapshot:
        all_agents = restore_cast(snapshot)   # sets the clock too, so end_day below counts forward from the saved day
    else:
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
        # Dawn is only skipped when there is nobody awake to spend it. An agent who chose to stay up owns those hours -
        # the night is theirs, and skipping it deleted whatever they were in the middle of.
        while current_time["hour"] < 6 and all(a.get("asleep", False) or a.get("dead", False) for a in all_agents):
            skip_time(60, all_agents)

        print(f"\n\n========== DAY {current_time['day']} ==========")
        day_started = current_time["day"]

        while current_time["hour"] < 24:
            if all(a.get("dead", False) for a in all_agents):
                print("\n*** ALL AGENTS DEAD - SIMULATION OVER ***")
                return all_agents

            if all(a.get("asleep", False) or a.get("dead", False) for a in all_agents):
                # Skip to the FIRST waking, not the last. Sleep is 8h from whenever you lay down, so a 21:00 sleeper is
                # due at 05:00 and a 23:00 sleeper at 07:00 - taking the longest held the early riser under for two
                # extra hours and woke the whole cast on one synchronised alarm. Whoever is due first wakes, acts, and
                # the rest keep sleeping through the ordinary ticks.
                soonest = min((a.get("sleep_remaining_hours", 0) for a in all_agents
                               if a.get("asleep") and not a.get("dead")), default=0)
                soonest = max(0.5, soonest)   # never 0: a zero skip would spin this branch forever
                print(f"\n--- Everyone asleep, skipping {soonest:g}h to the first waking ---")
                skip_time(soonest * 60, all_agents)
                if current_time["day"] != day_started:
                    break        # crossed midnight: let the outer loop open the new day
                continue         # same day, someone is up now - carry on ticking

            # Midnight ends the day only as BOOKKEEPING - the outer loop opens the next one and play continues from
            # 00:00. This used to force-skip 6.5 hours at 23:30 whether anyone was awake or not, so two agents talking
            # at 23:00 lost their whole night mid-sentence and woke at 06:00 with the conversation still open.
            if current_time["day"] != day_started:
                break

            print(f"\n--- Time: {format_time()} ---")
            update_sleep_states(all_agents, 0.5)
            # DELIBERATE: fixed order, never rotated. Rotation would be chaos the model cannot perceive or reason
            # about, and the monopoly it 'fixes' is the point - whoever holds the only income role holds LEVERAGE over
            # everyone who needs to eat. That asymmetry is where blackmail can emerge from; do not schedule it away.
            for agent in all_agents:
                agent_turn(agent, all_agents)
            advance_time(30)

    print("\n\n=== FINAL STATES ===")
    for agent in all_agents:
        status = "DEAD" if agent.get("dead") else "alive"
        print(f"\n{agent['name']} ({status}): Loc {agent['location']}, ${agent['money']}, "
              f"E{agent['energy']}/{capacity(agent)}, hist {len(agent['history'])}, diary {len(agent.get('diary', []))}")
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
