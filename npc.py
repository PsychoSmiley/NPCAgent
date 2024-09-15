# npc.py - NPCAgent v0.3.0 - start function-call integration: JSON {response,action} I/O + possibleAction, bare-bone
import requests
import json

base_url = "http://127.0.0.1:5000/v1"
api_key = "your_api_key"

def create_agent(name, context):
    return {
        "name": name,
        "history": [{"role": "system", "content": context}],
    }

def send_message(prompt, speaking_agent, listening_agent, possible_actions):
    endpoint = '/chat/completions'
    url = f"{base_url}{endpoint}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    user_message = {
        "role": "user",
        "content": json.dumps({
            "input": prompt,
            "context": "located in the shop",
            "possibleAction": ", ".join(possible_actions)
        })
    }
    listening_agent["history"].append(user_message)

    print(f"\n----- Sending message to {listening_agent['name']} -----")
    print(f"History being sent:\n{json.dumps(listening_agent['history'], indent=2)}")

    data = {
        'model': 'gpt-4',
        'messages': listening_agent["history"],
        'max_tokens': 150,
        'temperature': 0.7,
        'top_p': 0.9,
        'stop': None,
        'presence_penalty': 0,
        'frequency_penalty': 0,
        'mode': 'chat',
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()
        print(f"Raw API Response for {listening_agent['name']}:\n{json.dumps(response_json, indent=2)}")

        assistant_message = response_json['choices'][0]['message']['content'].strip()
        listening_agent["history"].append({"role": "assistant", "content": assistant_message})

        # Parse the JSON response
        try:
            parsed_response = json.loads(assistant_message)
            return parsed_response["response"], parsed_response["action"]
        except json.JSONDecodeError:
            print(f"Warning: Could not parse JSON from response: {assistant_message}")
            return assistant_message, "none"

    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request: {e}")
        return "", "none"
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing JSON response: {e}")
        print("Response Text:", response.text)
        return "", "none"

def conv(agent1, agent2, initial_prompt, possible_actions):
    print(f"\n----- Starting conversation between {agent1['name']} and {agent2['name']} -----")
    print_agent_state(agent1)
    print_agent_state(agent2)

    response, action = send_message(initial_prompt, agent1, agent2, possible_actions)
    print(f"{agent2['name']}: {response} (Action: {action})")

    response, action = send_message(response, agent2, agent1, possible_actions)
    print(f"{agent1['name']}: {response} (Action: {action})")

    print(f"\n----- Conversation ended -----")
    print_agent_state(agent1)
    print_agent_state(agent2)

    return response, action

def print_agent_state(agent):
    print(f"\n----- {agent['name']}'s current state -----")
    print(f"History:\n{json.dumps(agent['history'], indent=2)}")

def clear_history(agent):
    agent["history"] = [agent["history"][0]]  # Keep only the system message

# Context for agents
context = '''You are an AI assistant in a game. Always introduce yourself when you first speak in a conversation. Only use the names provided in the conversation. Do not hallucinate new names. Always pay attention to who is speaking. Remember information shared in the conversation and use it to provide relevant responses. Respond in JSON format with "response" and "action" fields. Example: {"response": "Hello, how can I help?", "action": "none"}'''

# Create agents
Bob = create_agent("Bob", context)
Alice = create_agent("Alice", context)
Chloe = create_agent("Chloe", context)

# Conversation between Bob and Alice
prompt = "Hello Alice, my name is Bob, and my favorite color is dark red. What's your favorite season?"
possible_actions = ["none", "lightsOn", "bitcoinPrice"]
conv(Bob, Alice, prompt, possible_actions)

# Conversation between Chloe and Alice
prompt = "Hi Alice, I'm Chloe. Can you tell me something interesting about Bob?"
possible_actions = ["none", "lightsOff", "getCurrentMoney"]
conv(Chloe, Alice, prompt, possible_actions)

# Clear Alice's history
clear_history(Alice)

# Conversation between Bob and Chloe
prompt = "Hello Chloe, it's Bob. Did Alice tell you anything about me?"
possible_actions = ["none", "goHouse", "purchaseFood"]
conv(Bob, Chloe, prompt, possible_actions)

print("\n----- Final Agent States -----")
for agent in [Bob, Alice, Chloe]:
    print_agent_state(agent)
