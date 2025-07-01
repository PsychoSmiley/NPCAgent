# npc.py - NPCAgent v0.4.6 - open-world sim (time, locations, autonomous turns, Game-System prompts) + robust JSON extraction; v0.4.6-style reconstruction
import requests
import json
import re
import time

# --- Configuration ---
VERBOSE_LOGGING = True
BASE_URL = "http://127.0.0.1:5000/v1"
API_KEY = "your_api_key"
MODEL_NAME = 'llama-2-13b' # This will be overridden by the model you choose to run

# Time
current_time = {"hour": 8, "minute": 0}
def format_time(): return f"{current_time['hour']:02d}:{current_time['minute']:02d}"
def advance_time(minutes=30):
    if VERBOSE_LOGGING: print(f"--- Advancing time by {minutes} minutes ---")
    current_time["minute"] += minutes
    while current_time["minute"] >= 60:
        current_time["minute"] -= 60
        current_time["hour"] += 1
        if current_time["hour"] >= 24:
            current_time["hour"] = 0

# Locations
LOCATIONS = {
    "Park": {"context": "at the park", "actions": ["wait", "goHome", "goCafe"]},
    "Home": {"context": "at home", "actions": ["rest", "sleep", "goPark", "goCafe"]},
    "Cafe": {"context": "at the cafe", "actions": ["order", "goHome", "goPark"]}
}

# SYSTEM PROMPT (v0.4.6-style, with pure JSON agent response examples)
BASE_SYSTEM_PROMPT = """Context: You're in a game and Player to interact with NPC naturally. NPC answer and use action keywords below to trigger actions in json:
---
CRITICAL MEMORY RULE: When an incoming message (from '[Agent Name] says:' OR 'Game System:') provides a JSON object, and that JSON's "input" field contains a personal fact (e.g., "I like coffe"), you MUST remember their EXACT words to use or share later. If later asked about that person or fact, you MUST quote what they said from their "input" field. Do NOT invent details or add new. If you don't know, say "I don't know" in your response.
---
SINGLE-LINE JSON FORMAT ANSWER:
- Message format you receive (from '[Agent Name] says:' OR 'Game System:' prefix): {"input": "[what someone says, or a situation description]", "context": "[current location]", "possibleAction": "[action1, action2, ... ]"}
- Your response format (as the character you are playing): {"response": "[your reply, or quoting remembered facts if relevant]", "action": "[always ONE action from possibleAction list, or 'none' by default]"}
---
EXAMPLES:
<START>
<START>
UserX says: {"input": "Hello, my name is UserX, and I often chill at the park.", "context": "located at the park", "possibleAction": "none, leaveConversation"}
{"response": "Nice to meet you UserX! I'll remember you often come over here.", "action": "none"}
<START>
<START>
UserY says: {"input": "Do you know what UserX enjoys and what their favorite color is?", "context": "located at the park", "possibleAction": "none, leaveConversation"}
{"response": "UserX told me they like to chill at the park. I don't know which color and would need to ask them, but I have things planned. Goodbye!", "action": "leaveConversation"}
<START>
<START>
Game System: {"input": "What should you do?", "context": "located at the park", "possibleAction": "none, goHome, goCafe"}
{"response": "I want to explore the city; I've never explored the cafe yet! Maybe I'll meet someone.", "action": "goCafe"}
<START>
<START>"""

def create_agent(name, location="Park"):
    personalized_system_content = BASE_SYSTEM_PROMPT + \
                                  f"\n\n--- IMPORTANT INSTRUCTIONS FOR YOU, '{name}' ---\n" + \
                                  f"1. You ARE the character named '{name}'. All your thoughts and words are from '{name}'s perspective.\n" + \
                                  f"2. Your ENTIRE output for each turn MUST be a single, valid JSON object following the 'Your response format' shown above.\n" + \
                                  f"3. Do NOT include any prefixes like '{name} says:', 'Char:', or your name before the opening '{{' of your JSON response.\n" + \
                                  f"4. Do NOT add any text, dialogue, notes, '###' markers, or '<think>' tags before or after your single JSON object response.\n" + \
                                  f"5. When responding to 'Game System:', you are still '{name}' and must follow all these rules."
    return {
        "name": name,
        "location": location,
        "history": [{"role": "system", "content": personalized_system_content}],
        "in_conversation": False,
        "conversation_partner": None
    }

def print_agent_state(agent):
    if VERBOSE_LOGGING:
        print(f"\n----- {agent['name']}'s current state ({agent['location']}) -----")
        print(f"In Conversation: {agent['in_conversation']} (with {agent.get('conversation_partner', 'None')})")
        print(f"History (length {len(agent['history'])}):")
        for i, item in enumerate(agent['history']):
            if item['role'] == 'system' and len(item['content']) > 300 and i == 0:
                 print(f"  {i}: {{'role': '{item['role']}', 'content': '[System Prompt - Truncated for brevity]'}}")
            else:
                content_to_print = item.get('content', '')
                try:
                    escaped_content = json.dumps(content_to_print)
                    print(f"  {i}: {{'role': '{item['role']}', 'content': {escaped_content}}}")
                except TypeError:
                     print(f"  {i}: {{'role': '{item['role']}', 'content': '[Unserializable Content]'}}")
        print(f"----- End {agent['name']}'s state -----")

def extract_clean_json_for_history(raw_text, agent_name_for_debug="Agent"):
    cleaned_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL | re.IGNORECASE)
    cleaned_text = re.sub(r'</?think[^>]*>', '', cleaned_text, flags=re.IGNORECASE)
    lines = cleaned_text.split('\n')
    potential_json_lines = []
    for line_content in lines:
        line = line_content.strip()
        possible_prefixes = [f"{agent_name_for_debug} says:", f"{agent_name_for_debug}:", "Char:", "Alice:", "Bob:", "Chloe:"]
        stripped_line = line
        for prefix in possible_prefixes:
            if stripped_line.startswith(prefix):
                stripped_line = stripped_line[len(prefix):].strip()
                break
        if not stripped_line or stripped_line.startswith('###') or stripped_line.startswith("```"):
            continue
        if stripped_line.startswith('{') and stripped_line.endswith('}'):
            potential_json_lines.append(stripped_line)
        elif '{' in stripped_line and '}' in stripped_line:
            potential_json_lines.append(stripped_line)
    for json_str_candidate in potential_json_lines:
        try:
            start = json_str_candidate.find('{')
            end = json_str_candidate.rfind('}') + 1
            if start != -1 and end > start:
                json_str = json_str_candidate[start:end]
                parsed = json.loads(json_str)
                if "response" in parsed and "action" in parsed:
                    return json.dumps(parsed)
        except (json.JSONDecodeError, TypeError):
            if VERBOSE_LOGGING: print(f"DEBUG EXTRACTOR ({agent_name_for_debug}): JSONDecodeError on candidate: '{json_str_candidate}'")
            continue
    try:
        json_match = re.search(r'\{\s*"response":\s*".*?",\s*"action":\s*".*?"\s*\}', cleaned_text, flags=re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            json.loads(json_str)
            return json_str
    except json.JSONDecodeError:
        pass
    if VERBOSE_LOGGING: print(f"WARNING EXTRACTOR ({agent_name_for_debug}): Could not extract clean JSON from raw: <<<{raw_text}>>>")
    return None

def parse_response_from_clean_json(clean_json_string, agent_name_for_debug="Agent"):
    try:
        parsed = json.loads(clean_json_string)
        return parsed.get("response", ""), parsed.get("action", "none")
    except Exception as e:
        if VERBOSE_LOGGING: print(f"ERROR PARSING CLEAN JSON ({agent_name_for_debug}): {e} on string: <<<{clean_json_string}>>>")
        return f"Error parsing internal JSON for {agent_name_for_debug}", "none"

def send_message(prompt_text, speaking_agent, listening_agent, possible_actions):
    url = f"{BASE_URL}/chat/completions"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'}
    context_str = f"located {LOCATIONS[listening_agent['location']]['context']}"
    actions_str = ", ".join(possible_actions)
    message_payload_obj = {"input": prompt_text, "context": context_str, "possibleAction": actions_str}
    message_payload_str = json.dumps(message_payload_obj)
    user_content_for_llm = f"{speaking_agent['name']} says: {message_payload_str}"
    user_message_to_append = {"role": "user", "content": user_content_for_llm}
    listening_agent["history"].append(user_message_to_append)
    print(f"\n[TO {listening_agent['name']} ({listening_agent['location']})]: {user_content_for_llm}")
    if VERBOSE_LOGGING:
        print(f"--- History for {listening_agent['name']} now length {len(listening_agent['history'])} (Full dump in print_agent_state) ---")
    data = {
        'model': MODEL_NAME, 'messages': listening_agent["history"],
        'max_tokens': 4000, 'temperature': 0.5
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()
        raw_assistant_message = response_json['choices'][0]['message']['content'].strip()
        print(f"[RAW FROM {listening_agent['name']}]: {raw_assistant_message}")
        clean_json_for_history = extract_clean_json_for_history(raw_assistant_message, listening_agent['name'])
        if clean_json_for_history:
            listening_agent["history"].append({"role": "assistant", "content": clean_json_for_history})
            return parse_response_from_clean_json(clean_json_for_history, listening_agent['name'])
        else:
            error_response = f"[{listening_agent['name']} output unparseable: {raw_assistant_message[:50]}...]"
            fallback_json_content = json.dumps({"response": error_response, "action": "none"})
            listening_agent["history"].append({"role": "assistant", "content": fallback_json_content})
            print(f"WARNING ({listening_agent['name']}): Storing fallback due to parsing failure of raw output.")
            return error_response, "none"
    except requests.exceptions.RequestException as e:
        print(f"[NETWORK ERROR sending to {listening_agent['name']}]: {e}")
        return "Network error occurred", "none"
    except (KeyError, IndexError) as e:
        print(f"[API RESPONSE ERROR for {listening_agent['name']}]: {e}. Response: {response.text if 'response' in locals() else 'No response object'}")
        return "API response format error", "none"
    except Exception as e:
        print(f"[UNEXPECTED ERROR sending to {listening_agent['name']}]: {e}")
        return "Unexpected error", "none"

def system_interaction(prompt_text, agent, current_world_actions):
    url = f"{BASE_URL}/chat/completions"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'}
    context_str = f"located {LOCATIONS[agent['location']]['context']}"
    actions_str = ", ".join(current_world_actions)
    message_payload_obj = {"input": prompt_text, "context": context_str, "possibleAction": actions_str}
    message_payload_str = json.dumps(message_payload_obj)
    user_content_for_llm = f"Game System: {message_payload_str}"
    user_message_to_append = {"role": "user", "content": user_content_for_llm}
    agent["history"].append(user_message_to_append)
    print(f"\n[GAME SYSTEM INTERACTION FOR {agent['name']} ({agent['location']})]: {user_content_for_llm}")
    if VERBOSE_LOGGING:
        print(f"--- History for {agent['name']} (System Interaction) now length {len(agent['history'])} ---")
    data = {
        'model': MODEL_NAME, 'messages': agent["history"],
        'max_tokens': 4000, 'temperature': 0.5
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()
        raw_assistant_message = response_json['choices'][0]['message']['content'].strip()
        print(f"[RAW FROM {agent['name']} (Game System Interaction)]: {raw_assistant_message}")
        clean_json_for_history = extract_clean_json_for_history(raw_assistant_message, agent['name'])
        if clean_json_for_history:
            agent["history"].append({"role": "assistant", "content": clean_json_for_history})
            return parse_response_from_clean_json(clean_json_for_history, agent['name'])
        else:
            error_response = f"[{agent['name']} output unparseable: {raw_assistant_message[:50]}...]"
            fallback_json_content = json.dumps({"response": error_response, "action": "none"})
            agent["history"].append({"role": "assistant", "content": fallback_json_content})
            print(f"WARNING ({agent['name']}): Storing fallback due to parsing failure for system interaction.")
            return error_response, "none"
    except Exception as e:
        print(f"[ERROR in system_interaction for {agent['name']}]: {e}")
        return "Error in system interaction", "none"

def conv(agent1, agent2, initial_prompt_text):
    print(f"\n===== {agent1['name']} talks to {agent2['name']} =====")
    if VERBOSE_LOGGING: print_agent_state(agent1); print_agent_state(agent2)

    agent1["in_conversation"] = True; agent1["conversation_partner"] = agent2["name"]
    agent2["in_conversation"] = True; agent2["conversation_partner"] = agent1["name"]

    conversation_actions = ["none", "leaveConversation"]

    response_agent2, action_agent2 = send_message(initial_prompt_text, agent1, agent2, conversation_actions)
    print(f"{agent2['name']} (to {agent1['name']}): {response_agent2} (Action: {action_agent2})")
    if VERBOSE_LOGGING: print_agent_state(agent2)

    if action_agent2 != "leaveConversation":
        response_agent1, action_agent1 = send_message(response_agent2, agent2, agent1, conversation_actions)
        print(f"{agent1['name']} (to {agent2['name']}): {response_agent1} (Action: {action_agent1})")
        if VERBOSE_LOGGING: print_agent_state(agent1)

        if action_agent1 == "leaveConversation":
            print(f"→ {agent1['name']} chose to leave the conversation.")
    else:
        print(f"→ {agent2['name']} chose to leave the conversation.")
        final_message_payload = {"input": response_agent2, "context": f"at {LOCATIONS[agent1['location']]['context']}", "possibleAction": "none"}
        user_message_to_append = {"role": "user", "content": f"{agent2['name']} says: {json.dumps(final_message_payload)}"}
        agent1["history"].append(user_message_to_append)
        print(f"[INFO] {agent1['name']}'s history updated with {agent2['name']}'s final words.")

    agent1["in_conversation"] = False; agent1["conversation_partner"] = None
    agent2["in_conversation"] = False; agent2["conversation_partner"] = None

    print(f"----- Conversation between {agent1['name']} and {agent2['name']} ended -----")
    if VERBOSE_LOGGING: print_agent_state(agent1); print_agent_state(agent2)

# --- FIX IS HERE: The `clear_history` function typo is corrected ---
def clear_history(agent):
    if agent["history"]:
        personalized_system_content = BASE_SYSTEM_PROMPT + \
                                  f"\n\n--- IMPORTANT INSTRUCTIONS FOR YOU, '{agent['name']}' ---\n" + \
                                  f"1. You ARE the character named '{agent['name']}'. All your thoughts and words are from '{agent['name']}'s perspective.\n" + \
                                  f"2. Your ENTIRE output for each turn MUST be a single, valid JSON object following the 'Your response format' shown above.\n" + \
                                  f"3. Do NOT include any prefixes like '{agent['name']} says:', 'Char:', or your name before the opening '{{' of your JSON response.\n" + \
                                  f"4. Do NOT add any text, dialogue, notes, or '###' markers before or after your single JSON object response.\n" + \
                                  f"5. When responding to 'Game System:', you are still '{agent['name']}' and must follow all these rules."
        agent["history"] = [{"role": "system", "content": personalized_system_content}]
    print(f"\n[Memory (history) cleared for {agent['name']}]")
    if VERBOSE_LOGGING: print_agent_state(agent)
# --- END OF FIX ---

def perform_action(agent, action_keyword, all_agents_list):
    print(f"→ {agent['name']} attempts action: {action_keyword}")
    if action_keyword.startswith("go"):
        if agent["in_conversation"]:
            print(f"→ {agent['name']} cannot move while in conversation.")
            return False
        destination = action_keyword.replace("go", "")
        if destination in LOCATIONS:
            agent["location"] = destination
            print(f"→ {agent['name']} moved to {destination}.")
            return True
        else:
            print(f"→ {agent['name']} tried to go to invalid location: {destination}")
            return False
    elif action_keyword == "leaveConversation":
        # The logic to set in_conversation to False is now handled robustly inside conv()
        if agent["in_conversation"]:
            print(f"→ {agent['name']} indicates leaving conversation.")
        else:
             print(f"→ {agent['name']} chose leaveConversation but was not in one.")
        return True
    elif action_keyword in ["rest", "sleep", "wait", "order", "none"]:
        if action_keyword != "none": print(f"→ {agent['name']} performs: {action_keyword}")
        return True
    else:
        print(f"→ {agent['name']} chose unknown or unhandled action: {action_keyword}")
        return False

def get_available_actions_for_agent(current_agent, all_agents_list):
    if current_agent["in_conversation"]:
        return ["none", "leaveConversation"]
    else:
        actions = LOCATIONS[current_agent["location"]]["actions"].copy()
        for other_agent in all_agents_list:
            if other_agent["name"] != current_agent["name"] and \
               other_agent["location"] == current_agent["location"] and \
               not other_agent["in_conversation"]:
                actions.append(f"talkTo{other_agent['name']}")
        return list(set(actions))

def run_simulation(num_steps=3):
    script_name = __file__ if '__file__' in globals() else 'v0.4.6_clean_history.py'
    print(f"=== {script_name} FREE OPEN-WORLD SIMULATION ===\n")
    Bob = create_agent("Bob", "Park")
    Alice = create_agent("Alice", "Park")
    Chloe = create_agent("Chloe", "Cafe")
    all_agents = [Bob, Alice, Chloe]

    print("--- Seeding initial memory: Bob tells Alice about 'dark red' ---")
    conv(Bob, Alice, "Hello Alice, my name is Bob, and my favorite color is dark red. What's your favorite season?")
    if VERBOSE_LOGGING: print_agent_state(Alice)
    advance_time(5)
    print("--- End of initial memory seeding ---")

    for step in range(num_steps):
        current_time_str = format_time()
        print(f"\n\n\n--- World Step {step + 1}/{num_steps} | Time: {current_time_str} ---")
        for agent in all_agents:
            if agent["in_conversation"]:
                if VERBOSE_LOGGING: print(f"Skipping {agent['name']}'s independent world turn; in conversation with {agent.get('conversation_partner', 'unknown')}.")
                continue
            print(f"\n-- {agent['name']}'s Independent Turn ({agent['location']}) --")
            if VERBOSE_LOGGING: print_agent_state(agent)
            available_actions = get_available_actions_for_agent(agent, all_agents)
            situation_prompt = f"It is {current_time_str}. You are {agent['name']} currently at {LOCATIONS[agent['location']]['context']}. "
            people_here = [p['name'] for p in all_agents if p['location'] == agent['location'] and p['name'] != agent['name'] and not p['in_conversation']]
            if people_here: situation_prompt += "You see " + ", ".join(people_here) + " here. "
            else: situation_prompt += "You don't see anyone else around right now. "
            situation_prompt += "What do you want to do?"
            response_text, chosen_action = system_interaction(situation_prompt, agent, available_actions)
            print(f"{agent['name']} (thinking): \"{response_text}\" (Chosen Action: {chosen_action})")
            if chosen_action.startswith("talkTo"):
                target_name = chosen_action.replace("talkTo", "")
                target_agent = next((a for a in all_agents if a["name"] == target_name), None)
                if target_agent and target_agent["location"] == agent["location"] and \
                   not target_agent["in_conversation"] and not agent["in_conversation"]:
                    opening_line = response_text if response_text.strip() and not response_text.startswith("[") else f"Hello {target_name}, it's {agent['name']}. How are you doing?"
                    conv(agent, target_agent, opening_line)
                else:
                    print(f"→ {agent['name']} tried to talk to {target_name}, but they are not available/here. Defaulting to 'wait'.")
                    perform_action(agent, "wait", all_agents)
            else:
                perform_action(agent, chosen_action, all_agents)
            if VERBOSE_LOGGING: print_agent_state(agent)
        advance_time(15)

    print("\n\n----- FINAL AGENT STATES AFTER SIMULATION -----")
    for agent_obj in all_agents:
        print_agent_state(agent_obj)
    print("\n=== SIMULATION COMPLETE ===")

if __name__ == "__main__":
    Bob_s = create_agent("Bob", "Park")
    Alice_s = create_agent("Alice", "Park")
    Chloe_s = create_agent("Chloe", "Park")

    print(f"=== {__file__} SCRIPTED INFORMATION FLOW TEST ===\n")
    # Set the global model name for this specific test if needed, or modify send_message to accept it.
    # For now, we assume MODEL_NAME is set to the desired model for the test.

    conv(Bob_s, Alice_s, "Hello Alice, my name is Bob, and my favorite color is dark red. What's your favorite season?")
    advance_time()
    conv(Chloe_s, Alice_s, "Hi Alice, I'm Chloe. Can you tell me something interesting about Bob?")
    advance_time()
    clear_history(Alice_s)
    advance_time()
    conv(Bob_s, Chloe_s, "Hello Chloe, it's Bob. Did Alice tell you anything about me?")
    print("\n--- End of SCRIPTED INFORMATION FLOW TEST ---\n")

    # The open-world simulation can be run separately if desired
    print("\n--- Starting OPEN-WORLD SIMULATION ---\n")
    run_simulation(num_steps=3)
