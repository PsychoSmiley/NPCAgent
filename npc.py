# npc.py - NPCAgent v0.5.1 - refactor: unify send_message (talk + Game-System), single .format() system prompt, history trim; v0.5.1(refactor)
import requests
import json
import re
import time

# --- Configuration ---
VERBOSE_LOGGING = True
BASE_URL = "http://127.0.0.1:5000/v1"
API_KEY = "your_api_key"
MODEL_NAME = 'llama-2-13b'
MAX_HISTORY_MESSAGES = 20
MAX_RESPONSE_TOKENS = 100

# --- World State ---
current_time = {"hour": 8, "minute": 0}
LOCATIONS = {
    "Park": {"context": "at the park", "actions": ["wait", "goHome", "goCafe"]},
    "Home": {"context": "at home", "actions": ["rest", "sleep", "goPark", "goCafe"]},
    "Cafe": {"context": "at the cafe", "actions": ["order", "goHome", "goPark"]}
}

# --- UNIFIED SYSTEM PROMPT from v0.5.1.py ---
BASE_SYSTEM_PROMPT = """You are {name}, an NPC character in an interactive game-simulated world. You think and respond only as {name}.

Your task is to respond to all situations by generating a single JSON object. In the "response" field, generate a natural, internal monologue that shows your reasoning based on your memories and goals, which then flows into any words you say out loud. Your entire output MUST be a single-line, valid JSON object with no other text or prefixes.

The "action" keyword you choose MUST be one of the choices from the "possibleAction" list provided in the last incoming message. To share a memory, you MUST quote the fact exactly as you learned it. If you do not know a fact, your reasoning should reflect that, and you should respond with "I don't know". Do not invent details.

---
EXAMPLES:
<START>
<START>
Placeholder-UserX says: {{"input": "Hello, my name is Placeholder-UserX, and I often chill at the park.", "context": "located at the park", "possibleAction": "none, leaveConversation"}}
{{"response": "A new person, Placeholder-UserX. They're being friendly. It's useful to remember they like this park. I'll be welcoming. Nice to meet you Placeholder-UserX! I'll remember you're often here.", "action": "none"}}
<START>
<START>
Placeholder-UserY says: {{"input": "Do you know what Placeholder-UserX enjoys and what their favorite color is?", "context": "located at the park", "possibleAction": "none, leaveConversation"}}
{{"response": "Okay, a question about Placeholder-UserX. I'll check my memory. I know they said they 'often chill at the park'. I don't know their color, so I must not invent a fact. I'll state what I know and what I don't. Placeholder-UserX told me they like to chill at the park. As for their favorite color, I'm afraid I don't know.", "action": "leaveConversation"}}
<START>
<START>
Game System: {{"input": "You just tried to go to the Cafe, but you realized you did the same thing yesterday and it was closed. What now?", "context": "at the park", "possibleAction": "none, goHome, goCafe"}}
{{"response": "Right, I keep trying to go to the Cafe at this time and it's always closed. That's a waste of time. I need a new plan to achieve my goal of being social. The park usually has people. I'll wait here instead.", "action": "wait"}}
<START>
<START>
"""

# --- Core Agent & World Functions ---
def create_agent(name, location="Park"):
    personalized_system_content = BASE_SYSTEM_PROMPT.format(name=name)
    return {
        "name": name,
        "location": location,
        "history": [{"role": "system", "content": personalized_system_content}],
        "in_conversation": False,
        "conversation_partner": None
    }

def clear_history(agent):
    personalized_system_content = BASE_SYSTEM_PROMPT.format(name=agent['name'])
    agent["history"] = [{"role": "system", "content": personalized_system_content}]
    print(f"\n[Memory (history) cleared for {agent['name']}]")

def print_agent_state(agent):
    if VERBOSE_LOGGING:
        print(f"\n----- {agent['name']}'s current state ({agent['location']}) -----")
        print(f"History (length {len(agent['history'])}):")
        for i, item in enumerate(agent['history']):
            if i == 0:
                print(f"  0: {{'role': 'system', 'content': '[System Prompt...]'}}")
            else:
                content_to_print = item.get('content', '[No Content]')
                # Truncate long content for readability in logs
                if len(content_to_print) > 200:
                    content_display = content_to_print[:200] + '...'
                else:
                    content_display = content_to_print
                print(f"  {i}: {{'role': '{item['role']}', 'content': '{content_display}'}}")
        print(f"----- End {agent['name']}'s state -----")

def get_available_actions_for_agent(agent, all_agents_list):
    actions = LOCATIONS[agent["location"]]["actions"].copy()
    for other_agent in all_agents_list:
        if other_agent["name"] != agent["name"] and other_agent["location"] == agent["location"]:
            if not other_agent.get("in_conversation"):
                actions.append(f"talkTo{other_agent['name']}")
    return list(set(actions))

def format_time(): return f"{current_time['hour']:02d}:{current_time['minute']:02d}"

def advance_time(minutes=30):
    global current_time
    if VERBOSE_LOGGING: print(f"\n--- Advancing time by {minutes} minutes ---")
    current_time["minute"] += minutes
    current_time["hour"] += current_time["minute"] // 60
    current_time["minute"] %= 60
    current_time["hour"] %= 24

# --- Unified Communication & Parsing ---
def extract_clean_json(raw_text, agent_name_for_debug="Agent"):
    """
    A hybrid JSON extractor that combines the best of v0.4.6 and v0.5.1.
    It processes line-by-line to handle models that add extra text,
    and includes robust fallback for missing keys.
    """
    # 1. Clean the text by removing <think> tags. (From v0.5.1)
    cleaned_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL | re.IGNORECASE)

    # --- v0.4.6 Logic: Split the output into lines to handle model contamination ---
    lines = cleaned_text.split('\n')

    for line in lines:
        # Strip leading/trailing whitespace from the current line
        current_line = line.strip()

        # 2. Use a generic regex to find and strip a prefix. (From v0.5.1, applied per-line)
        prefix_match = re.search(r'^\s*.*?\:\s*(?=\{)', current_line)
        if prefix_match:
            current_line = current_line[prefix_match.end():]

        # Ignore empty lines or lines that are clearly not JSON
        if not current_line or not current_line.startswith('{'):
            continue

        # 3. Attempt to parse the current line as a JSON object.
        try:
            # Find the first '{' and the last '}' just on this line
            start_index = current_line.find('{')
            end_index = current_line.rfind('}')

            if start_index != -1 and end_index != -1 and end_index > start_index:
                json_str = current_line[start_index : end_index + 1]
                parsed = json.loads(json_str)

                # --- v0.5.1 Logic: Robust key handling ---
                # 4. Check for at least a "response".
                if "response" in parsed:
                    # 5. If "action" is missing, add the safe default "none".
                    if "action" not in parsed:
                        if VERBOSE_LOGGING:
                            print(f"INFO EXTRACTOR ({agent_name_for_debug}): Found 'response' but 'action' is missing. Defaulting to 'none'.")
                        parsed["action"] = "none"

                    # 6. Success! Return the perfect JSON string and exit the function.
                    return json.dumps(parsed)

        except json.JSONDecodeError:
            # This line was not a valid JSON, so we just move to the next one.
            if VERBOSE_LOGGING:
                print(f"DEBUG EXTRACTOR ({agent_name_for_debug}): Failed to parse line, trying next: '{current_line}'")
            continue

    # If the loop finishes and we haven't found anything, fail gracefully.
    if VERBOSE_LOGGING:
        print(f"WARNING EXTRACTOR ({agent_name_for_debug}): Could not extract clean JSON from raw: <<<{raw_text}>>>")
    return None

def send_message(prompt_text, source, target_agent, possible_actions):
    """Handles all API communications, ensuring correct history management."""
    url, headers = f"{BASE_URL}/chat/completions", {'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'}
    source_name = source if isinstance(source, str) else source["name"]

    payload_obj = {"input": prompt_text, "context": f"{LOCATIONS[target_agent['location']]['context']}", "possibleAction": ", ".join(possible_actions)}
    user_content = f"{source_name} says: {json.dumps(payload_obj)}"

    target_agent["history"].append({"role": "user", "content": user_content})
    print(f"\n[TO {target_agent['name']} from {source_name}]: {user_content}")

    if len(target_agent["history"]) > MAX_HISTORY_MESSAGES:
        target_agent["history"] = [target_agent["history"][0]] + target_agent["history"][-MAX_HISTORY_MESSAGES:]

    data = {'model': MODEL_NAME, 'messages': target_agent["history"], 'max_tokens': MAX_RESPONSE_TOKENS, 'temperature': 0.5}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status()
        raw_message = response.json()['choices'][0]['message']['content'].strip()
        print(f"[RAW FROM {target_agent['name']}]: {raw_message}")

        clean_json_str = extract_clean_json(raw_message, target_agent['name'])
        if clean_json_str:
            target_agent["history"].append({"role": "assistant", "content": clean_json_str})
            parsed = json.loads(clean_json_str)
            return parsed.get("response", ""), parsed.get("action", "none")
        else:
            raise ValueError(f"Robust parser failed to extract JSON.")

    except Exception as e:
        print(f"[ERROR] for {target_agent['name']}: {e}")
        fallback_json = json.dumps({"response": f"An error occurred, defaulting to 'wait'.", "action": "wait"})
        target_agent["history"].append({"role": "assistant", "content": fallback_json})
        return "An error occurred, defaulting to 'wait'.", "wait"

# --- Main Simulation Logic (Unified and Clean) ---
def perform_action(agent, action_keyword, all_agents, justification_text=""):
    """Handles all agent actions, including initiating conversations in the open world."""
    print(f"→ {agent['name']} attempts action: {action_keyword}")

    if action_keyword.startswith("talkTo"):
        target_name = action_keyword.replace("talkTo", "")
        target_agent = next((a for a in all_agents if a["name"] == target_name), None)

        if target_agent and target_agent["location"] == agent["location"] and not agent.get("in_conversation"):
            opening_line = justification_text if justification_text.strip() else f"Hello {target_name}."
            conv_logic(agent, target_agent, opening_line)
        else:
            print(f"→ Action failed: {target_name} is not here or one of you is busy.")

    elif action_keyword.startswith("go"):
        destination = action_keyword.replace("go", "")
        if destination in LOCATIONS:
            agent["location"] = destination
            print(f"→ {agent['name']} moved to {destination}.")
        else:
            print(f"→ Action failed: Cannot go to {destination}.")
    else:
        print(f"→ {agent['name']} performs action: {action_keyword}")

def conv_logic(agent1, agent2, initial_prompt_text):
    """Handles a controlled, two-turn conversation."""
    print(f"\n===== Conversation Start: {agent1['name']} -> {agent2['name']} =====")
    agent1["in_conversation"], agent2["in_conversation"] = True, True
    agent1["conversation_partner"], agent2["conversation_partner"] = agent2["name"], agent1["name"]

    conversation_actions = ["none", "leaveConversation"]

    response_agent2, action_agent2 = send_message(initial_prompt_text, agent1, agent2, conversation_actions)
    print(f"{agent2['name']} replies: \"{response_agent2}\" (Action: {action_agent2})")

    if action_agent2 != "leaveConversation":
        response_agent1, action_agent1 = send_message(response_agent2, agent2, agent1, conversation_actions)
        print(f"{agent1['name']} replies: \"{response_agent1}\" (Action: {action_agent1})")

    agent1["in_conversation"], agent2["in_conversation"] = False, False
    agent1["conversation_partner"], agent2["conversation_partner"] = None, None
    print(f"--- Conversation End ---")

def run_simulation(num_steps=3):
    """The main open-world simulation loop."""
    print(f"\n\n=== FREE OPEN-WORLD SIMULATION ===\n")
    all_agents = [create_agent("Bob", "Park"), create_agent("Alice", "Park"), create_agent("Chloe", "Cafe")]

    print("--- Seeding initial memory for open world... ---")
    conv_logic(all_agents[0], all_agents[1], "Hello Alice, my name is Bob, and my favorite color is dark red.")
    print("--- End of initial memory seeding ---\n")
    advance_time(5)

    for step in range(num_steps):
        print(f"\n\n--- World Step {step + 1}/{num_steps} | Time: {format_time()} ---")
        for agent in all_agents:
            if agent["in_conversation"]:
                continue

            print(f"\n-- {agent['name']}'s Independent Turn ({agent['location']}) --")
            available_actions = get_available_actions_for_agent(agent, all_agents)
            people_here = [a['name'] for a in all_agents if a['location'] == agent['location'] and a != agent]
            situation_prompt = f"You are at {agent['location']}. You see: {', '.join(people_here) if people_here else 'no one'}. What do you want to do?"

            response_text, chosen_action = send_message(situation_prompt, "Game System", agent, available_actions)
            print(f"{agent['name']} decides: \"{response_text}\" (Action: {chosen_action})")
            perform_action(agent, chosen_action, all_agents, response_text)

        advance_time(15)

    print("\n\n----- FINAL AGENT STATES AFTER SIMULATION -----")
    for agent_obj in all_agents:
        print_agent_state(agent_obj)
    print("\n=== SIMULATION COMPLETE ===")

# --- Main Execution ---
if __name__ == "__main__":
    # --- Test 1: Scripted Information Flow ---
    print(f"\n=== SCRIPTED INFORMATION FLOW TEST ===\n")
    bob_s = create_agent("Bob", "Park")
    alice_s = create_agent("Alice", "Park")
    chloe_s = create_agent("Chloe", "Park")

    conv_logic(bob_s, alice_s, "Hello Alice, my name is Bob, and my favorite color is dark red.")
    advance_time()
    conv_logic(chloe_s, alice_s, "Hi Alice, can you tell me anything about Bob?")
    advance_time()
    clear_history(alice_s)
    advance_time()
    conv_logic(bob_s, chloe_s, "Hello Chloe, did Alice tell you anything about me?")
    print("\n--- End of SCRIPTED INFORMATION FLOW TEST ---\n")

    # --- Test 2: Open-World Simulation ---
    run_simulation(num_steps=3)
