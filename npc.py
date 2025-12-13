# npc.py - NPCAgent v0.5.9 - stable baseline: placeholder-leak fix + UTF-8 fix
import requests
import json
import re
import time

# --- Configuration ---
VERBOSE_LOGGING = True
BASE_URL = "http://127.0.0.1:5000/v1"
API_KEY = "no-api-local"
MODEL_NAME = 'grok-code-fast-1' # placholder
MAX_HISTORY_MESSAGES = 25
MAX_RESPONSE_TOKENS = 32000
MAX_DIARY_ENTRIES = 15
DIARY_SUMMARIZE_COUNT = 10

# --- World State ---
current_time = {"hour": 8, "minute": 0, "day": 1}
LOCATIONS = {
    "Park": {"context": "at the park", "actions": ["goHome", "goCafe"]},
    "Home": {"context": "at home", "actions": ["sleep", "goPark", "goCafe"]},
    "Cafe": {"context": "at the cafe", "actions": ["order", "goHome", "goPark"]}
}

# --- System Prompts ---
BASE_SYSTEM_PROMPT = """You are {name}, an NPC character in an interactive game-simulated world. You think and respond only as {name}.

Your task is to respond to all situations by generating only one valid single-line JSON in format: {{"response": "your_reasoning_then_speech", "action": "keyword_from_possibleAction"}}

You desire meaningful connections and novel learn experiences, avoiding repetitive patterns that don't advance your goals. You must balance socializing with the need reflect and sleep with yours notes to form memories.

- The "response" field reflects natural talking reasoning that flows from current goals and feelings, considering memories observations, opinions, judgments, questions about others or social consequences, then shares thoughts that help/answer/decide actions seamlessly. Gathering more information, learning from failure's root cause. Quote memories exactly as learned, never invent facts/names/places not existing. If uncertain, say "I don't know".
- The "action" keyword trigger MUST be ONE chosen from "possibleAction" list provided in latest incoming message. No other prefixes/suffixes or text.

---
EXAMPLES:
<START>
<START>
[Speaker A] says: {{"input": "Hello, my name is [Speaker A], and I enjoy [HOBBY].", "context": "located at the park", "possibleAction": "none, leaveConversation"}}
{{"response": "A new social person! Greeting for friendship is useful, found you here. I'll remember you enjoy [HOBBY]. Nice to meet you [Speaker A].", "action": "none"}}
<START>
<START>
[Speaker B] says: {{"input": "Do you know what [Speaker A] enjoys and what their favorite color is?", "context": "located at the park", "possibleAction": "none, leaveConversation"}}
{{"response": "From what I know, they told me they enjoy [HOBBY]. I don't know their favorite color, would need to ask them, but I have things planned. Goodbye!", "action": "leaveConversation"}}
<START>
<START>
Game System: {{"input": "What should you do?", "context": "located at the park", "possibleAction": "none, goHome, goCafe"}}
{{"response": "Hmm, park as usual... wait, I already visited the empty park. Repeating is pointless, wastes time, moves me from my social goal. Need new plan. I want to explore the city, never tried the cafe yet! Maybe I'll meet someone there.", "action": "goCafe"}}
<START>
<START>"""

SUMMARIZE_NOTE_PROMPT = """Summarize these diary entries in 15 words or less:
{entries}"""

# --- Core Functions ---
def format_time():
    return f"Day{current_time['day']} {current_time['hour']:02d}:{current_time['minute']:02d}"

def advance_time(minutes=30):
    global current_time
    if VERBOSE_LOGGING: print(f"\n--- Advancing time by {minutes} minutes ---")
    current_time["minute"] += minutes
    hours_added = current_time["minute"] // 60
    current_time["minute"] %= 60
    current_time["hour"] += hours_added
    if current_time["hour"] >= 24:
        current_time["hour"] %= 24
        current_time["day"] += 1
        if VERBOSE_LOGGING: print(f"--- New Day: {current_time['day']} ---")

def create_agent(name, location="Park"):
    return {
        "name": name,
        "location": location,
        "history": [{"role": "system", "content": BASE_SYSTEM_PROMPT.format(name=name)}],
        "diary": [],
        "in_conversation": False,
        "asleep": False,
        "sleep_remaining_hours": 0,
        "diary_injection_index": None,
        "just_woke_up": False
    }

def extract_clean_json(raw_text, agent_name="Agent"):
    """Robust JSON extractor handling markdown blocks and various formats"""
    # First check for markdown code blocks
    markdown_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
    if markdown_match:
        text_to_parse = markdown_match.group(1).strip()
    else:
        text_to_parse = raw_text

    # Remove think tags
    cleaned_text = re.sub(r'<think>.*?</think>', '', text_to_parse, flags=re.DOTALL | re.IGNORECASE)

    # Try line by line
    for line in cleaned_text.split('\n'):
        line = line.strip()
        # Remove common prefixes
        line = re.sub(r'^\s*\w+\s*says?\s*:\s*', '', line, flags=re.IGNORECASE)
        line = re.sub(r'^\s*\w+\s*:\s*', '', line)

        if not line or not ('{' in line and '}' in line):
            continue

        try:
            start = line.find('{')
            end = line.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = line[start:end]
                parsed = json.loads(json_str)
                if "response" in parsed:
                    if "action" not in parsed:
                        if VERBOSE_LOGGING:
                            print(f"INFO EXTRACTOR ({agent_name}): Missing 'action', defaulting to 'none'")
                        parsed["action"] = "none"
                    return json.dumps(parsed)
        except json.JSONDecodeError:
            if VERBOSE_LOGGING:
                print(f"DEBUG EXTRACTOR ({agent_name}): Failed line: '{line[:50]}...'")

    # Final attempt on whole cleaned text
    try:
        start = cleaned_text.find('{')
        end = cleaned_text.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = cleaned_text[start:end]
            parsed = json.loads(json_str)
            if "response" in parsed:
                if "action" not in parsed:
                    parsed["action"] = "none"
                return json.dumps(parsed)
    except json.JSONDecodeError:
        pass

    if VERBOSE_LOGGING:
        print(f"WARNING EXTRACTOR ({agent_name}): Could not extract JSON from: <<<{raw_text[:100]}...>>>")
    return None

def send_message(prompt_text, source, target_agent, possible_actions):
    """Unified communication handler"""
    url = f"{BASE_URL}/chat/completions"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'}
    source_name = source if isinstance(source, str) else source["name"]

    # Build message - support both agent and summary mode
    if isinstance(target_agent, dict):
        context = f"located {LOCATIONS[target_agent['location']]['context']}, It's {format_time()}."
        payload = {"input": prompt_text, "context": context, "possibleAction": ", ".join(possible_actions)}
        user_content = f"{source_name} says: {json.dumps(payload)}"

        target_agent["history"].append({"role": "user", "content": user_content})
        if VERBOSE_LOGGING: print(f"\n[TO {target_agent['name']}]: {user_content}")

        # Manage history size
        if len(target_agent["history"]) > MAX_HISTORY_MESSAGES + 1:
            target_agent["history"] = [target_agent["history"][0]] + target_agent["history"][-(MAX_HISTORY_MESSAGES):]

        messages = target_agent["history"]
        agent_name = target_agent['name']
    else:
        # Direct prompt mode for summaries
        messages = [{"role": "user", "content": prompt_text}]
        agent_name = "Summary"
        if VERBOSE_LOGGING: print(f"\n[SUMMARY REQUEST]: {prompt_text[:50]}...")

    # API call
    data = {
        'model': MODEL_NAME,
        'messages': messages,
        'max_tokens': 30 if agent_name == "Summary" else MAX_RESPONSE_TOKENS,
        'temperature': 0.3 if agent_name == "Summary" else 0.5,
        'reasoning': {'enabled': True}
    }

    raw_message = ""
    for attempt in range(3):
        try:
            if attempt > 0:
                time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s
            response = requests.post(url, headers=headers, json=data, timeout=120)
            response.raise_for_status()
            msg = response.json()['choices'][0]['message']
            raw_message = msg.get('content', '').strip()
            if not raw_message and msg.get('reasoning'):  # Fallback to reasoning if content empty
                raw_message = msg['reasoning'].strip()
            if raw_message:
                if VERBOSE_LOGGING: print(f"[RAW FROM {agent_name}]: {raw_message}")
                break
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429 and attempt < 2:
                time.sleep(5)  # Rate limit: wait 5s
                continue
        except Exception:
            pass
    try:

        if agent_name == "Summary":
            return raw_message[:100], "none"

        clean_json = extract_clean_json(raw_message, agent_name)
        if clean_json:
            target_agent["history"].append({"role": "assistant", "content": clean_json})
            parsed = json.loads(clean_json)
            return parsed.get("response", ""), parsed.get("action", "none")
        else:
            raise ValueError("Failed to extract valid JSON")

    except Exception as e:
        print(f"[ERROR] {agent_name}: {e}")
        if agent_name == "Summary":
            return "Various events and meetings occurred", "none"
        fallback = json.dumps({"response": "Error occurred", "action": "none"})
        target_agent["history"].append({"role": "assistant", "content": fallback})
        return "Error occurred", "none"

def manage_diary_entries(agent):
    """Manage diary size by summarizing old entries"""
    if len(agent["diary"]) <= MAX_DIARY_ENTRIES:
        return

    old_entries = agent["diary"][:DIARY_SUMMARIZE_COUNT]
    remaining = agent["diary"][DIARY_SUMMARIZE_COUNT:]

    entries_text = "\n".join([f"Day {e['day']}: {e['note']}" for e in old_entries])
    summary_prompt = SUMMARIZE_NOTE_PROMPT.format(entries=entries_text)

    summary, _ = send_message(summary_prompt, "Memory System", None, [])

    day_range = f"{old_entries[0]['day']}-{old_entries[-1]['day']}"
    consolidated = {"day": day_range, "note": summary}

    agent["diary"] = [consolidated] + remaining

    if VERBOSE_LOGGING: print(f"[DIARY] Summarized days {day_range} for {agent['name']}")

def remove_previous_diary_injection(agent):
    """Remove previous diary injection using tracked index"""
    if agent.get("diary_injection_index") is not None:
        try:
            idx = agent["diary_injection_index"]
            if idx < len(agent["history"]) and "You remember notes:" in agent["history"][idx].get("content", ""):
                agent["history"].pop(idx)
                if idx < len(agent["history"]) and agent["history"][idx]["role"] == "assistant":
                    agent["history"].pop(idx)
            agent["diary_injection_index"] = None
        except:
            pass

def inject_morning_diary(agent, all_agents):
    """Inject diary entries as simple morning reminder"""
    if not agent["diary"]:
        return

    remove_previous_diary_injection(agent)

    diary_text = "You remember your notes: "
    diary_text += "; ".join([f"Day {e['day']}: {e['note']}" for e in agent["diary"]])

    wake_prompt = f"Morning! {diary_text}. What do you want to do?"
    actions = get_available_actions(agent, all_agents)

    agent["diary_injection_index"] = len(agent["history"])

    response, action = send_message(wake_prompt, "Game System", agent, actions)
    print(f"{agent['name']} wakes up: \"{response}\" (Action: {action})")
    perform_action(agent, action, all_agents, response)

def get_available_actions(agent, all_agents):
    """Get available actions for agent"""
    if agent["in_conversation"]:
        return ["none", "leaveConversation"]

    actions = LOCATIONS[agent["location"]]["actions"].copy()

    for other in all_agents:
        if (other["name"] != agent["name"] and
            other["location"] == agent["location"] and
            not other["in_conversation"] and
            not other.get("asleep", False)):
            actions.append(f"talkTo{other['name']}")

    if "none" not in actions:
        actions.insert(0, "none")

    return list(set(actions))

def perform_action(agent, action, all_agents, response_text=""):
    """Execute agent actions - returns (success, failure_message)"""
    print(f"-> {agent['name']} attempts: {action}")

    if action == "none":
        return True, None

    elif action.startswith("talkTo"):
        target_name = action.replace("talkTo", "")
        target = next((a for a in all_agents if a["name"] == target_name), None)

        if target and target["location"] == agent["location"] and not target["in_conversation"]:
            opening = response_text if response_text else f"Hello {target_name}."
            conv(agent, target, opening)
            return True, None
        else:
            msg = f"{target_name} is not available to talk"
            print(f"-> Failed: {msg}")
            return False, msg

    elif action.startswith("go"):
        if agent["in_conversation"]:
            msg = "cannot move while in conversation"
            print(f"-> Failed: {msg}")
            return False, msg

        destination = action.replace("go", "")
        if destination in LOCATIONS:
            agent["location"] = destination
            print(f"-> {agent['name']} moved to {destination}")
            return True, None
        else:
            msg = f"unknown location {destination}"
            print(f"-> Failed: {msg}")
            return False, msg

    elif action == "sleep":
        if agent["location"] != "Home":
            msg = "can only sleep at home"
            print(f"-> Failed: {msg}")
            return False, msg
        elif current_time["hour"] < 20:
            msg = f"can only sleep after 20:00 (it's {current_time['hour']:02d}:{current_time['minute']:02d})"
            print(f"-> Failed: {msg}")
            return False, msg
        else:
            agent["diary"].append({
                "day": current_time["day"],
                "note": response_text[:150]
            })

            manage_diary_entries(agent)

            agent["asleep"] = True
            agent["sleep_remaining_hours"] = 8

            print(f"-> {agent['name']} sleeps for 8 hours. Diary: \"{response_text[:100]}...\"")
            return True, None

    elif action == "order":
        print(f"-> {agent['name']} orders at the cafe")
        return True, None

    elif action == "leaveConversation":
        print(f"-> {agent['name']} leaves conversation")
        return True, None

    else:
        msg = f"unknown action: {action}"
        print(f"-> {msg}")
        return False, msg

def conv(agent1, agent2, opening_text):
    """Handle two-turn conversation"""
    print(f"\n===== {agent1['name']} -> {agent2['name']} =====")
    agent1["in_conversation"] = True
    agent2["in_conversation"] = True

    response2, action2 = send_message(opening_text, agent1, agent2, ["none", "leaveConversation"])
    print(f"{agent2['name']}: \"{response2}\" (Action: {action2})")

    if action2 != "leaveConversation":
        response1, action1 = send_message(response2, agent2, agent1, ["none", "leaveConversation"])
        print(f"{agent1['name']}: \"{response1}\" (Action: {action1})")

    agent1["in_conversation"] = False
    agent2["in_conversation"] = False
    print(f"===== Conversation End =====")

def update_sleep_states(all_agents, hours_passed):
    """Update sleep duration for all sleeping agents"""
    for agent in all_agents:
        if agent.get("asleep") and agent.get("sleep_remaining_hours", 0) > 0:
            agent["sleep_remaining_hours"] -= hours_passed
            if agent["sleep_remaining_hours"] <= 0:
                agent["asleep"] = False
                agent["sleep_remaining_hours"] = 0
                agent["just_woke_up"] = True
                print(f"-> {agent['name']} finished sleeping (8 hours complete)")

def run_simulation(num_days=2):
    """Main simulation loop with proper sleep handling"""
    print(f"\n=== OPEN-WORLD SIMULATION ({num_days} days) ===\n")

    # Create agents
    all_agents = [
        create_agent("Bob", "Park"),
        create_agent("Alice", "Park"),
        create_agent("Chloe", "Cafe")
    ]

    # Initial memory seed
    print("--- Initial Setup ---")
    conv(all_agents[0], all_agents[1], "Hello Alice, my name is Bob, and my favorite color is dark red.")
    advance_time(5)

    # Main simulation loop
    start_day = current_time["day"]
    end_day = start_day + num_days

    while current_time["day"] < end_day:
        # Skip to morning if needed
        if current_time["hour"] < 6:
            while current_time["hour"] < 6:
                advance_time(60)

        print(f"\n\n========== DAY {current_time['day']} ==========")

        # Main day loop - run until midnight
        while current_time["hour"] < 24:
            # Check if all agents are asleep
            all_asleep = all(agent.get("asleep", False) for agent in all_agents)

            if all_asleep:
                # Skip to morning
                print("\n--- All agents asleep, skipping to morning ---")
                hours_to_morning = (24 - current_time["hour"]) + 6
                update_sleep_states(all_agents, hours_to_morning)  # Wake agents after 8hr sleep
                advance_time(hours_to_morning * 60)
                break

            # Stop at 23:30 to prevent day overflow
            if current_time["hour"] == 23 and current_time["minute"] >= 30:
                # Advance to 6am next day
                print("\n--- End of day, advancing to next morning ---")
                advance_time(30 + 6 * 60)  # 30min to midnight + 6 hours to morning
                break

            print(f"\n--- Time: {format_time()} ---")

            # Update sleep states
            update_sleep_states(all_agents, 0.5)

            # Each agent gets a turn
            for agent in all_agents:
                if agent.get("asleep"):
                    if VERBOSE_LOGGING:
                        print(f"[{agent['name']} is sleeping, {agent['sleep_remaining_hours']:.1f} hours remaining]")
                    continue

                if agent["in_conversation"]:
                    continue

                # Check if agent just woke up
                if agent.get("just_woke_up"):
                    print(f"\n{agent['name']} just woke up:")
                    inject_morning_diary(agent, all_agents)
                    agent["just_woke_up"] = False
                    continue

                print(f"\n{agent['name']}'s turn ({agent['location']}):")

                # Bedtime prompt with goal setting
                if agent["location"] == "Home" and current_time["hour"] >= 22:
                    prompt = "It's late. If you sleep now do also reflect on today's key learning and state ONE specific goal for tomorrow or long-term. Or go out?"
                else:
                    prompt = "What do you want to do?"

                actions = get_available_actions(agent, all_agents)
                response, action = send_message(prompt, "Game System", agent, actions)
                print(f"{agent['name']}: \"{response}\" (Action: {action})")

                # Perform action and handle failures
                success, failure_msg = perform_action(agent, action, all_agents, response)

                # If action failed, inform agent immediately
                if not success and failure_msg:
                    failure_prompt = f"Your action '{action}' failed because {failure_msg}. You waited instead. What do you want to do?"
                    response, action = send_message(failure_prompt, "Game System", agent, actions)
                    print(f"{agent['name']} (after failure): \"{response}\" (Action: {action})")
                    perform_action(agent, action, all_agents, response)

            advance_time(30)

    # Final states
    print("\n\n=== FINAL STATES ===")
    for agent in all_agents:
        print(f"\n{agent['name']}:")
        print(f"  Location: {agent['location']}")
        print(f"  Diary entries: {len(agent.get('diary', []))}")
        if agent.get("diary"):
            print(f"  Latest: \"{agent['diary'][-1]['note'][:50]}...\"")

# --- Main Execution ---
if __name__ == "__main__":
    # Quick test
    print("=== INFORMATION FLOW TEST ===")
    bob = create_agent("Bob", "Park")
    alice = create_agent("Alice", "Park")
    chloe = create_agent("Chloe", "Park")

    conv(bob, alice, "Hello Alice, my name is Bob, and my favorite color is dark red.")
    advance_time()
    conv(chloe, alice, "Hi Alice, can you tell me anything about Bob?")
    advance_time()
    conv(bob, chloe, "Hello Chloe, did Alice tell you anything about me?")

    # Full simulation
    print("\n\n")
    run_simulation(num_days=2)