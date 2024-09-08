# npc.py - NPCAgent v0.2.0 - more reliable: per-agent system prompt + multi-agent create_agent + turn-based two-way conv()
import requests
import json

base_url = "http://127.0.0.1:5000/v1"
api_key = "your_api_key"

def create_agent(name):
    return {
        "name": name,
        "history": [{"role": "system", "content": f"""You are {name}, an AI assistant.
Always introduce yourself as {name} when you first speak in a conversation.
Only use the names provided in the conversation. Do not hallucinate new names.
Always pay attention to who is speaking.
Remember information shared in the conversation and use it to provide relevant responses.
Do not respond as "User:". Respond as {name}:.
"""}],
    }

def send_message(prompt, speaking_agent, listening_agent_history):
    endpoint = '/chat/completions'
    url = f"{base_url}{endpoint}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    # Direct history modification (NO copy.deepcopy)
    conversation_history = listening_agent_history

    user_message = {"role": "user", "content": f"{speaking_agent['name']}: {prompt}"}
    conversation_history.append(user_message)

    # **Key Change:** Get the listening agent's name directly from the dictionary
    listening_agent_name = speaking_agent['name']  # Assuming speaking_agent is sending the message to the listening agent

    print(f"\n----- Sending message to {listening_agent_name} -----")
    print(f"History being sent:\n{json.dumps(conversation_history, indent=2)}")

    data = {
        'model': 'codestral-22B-v0.1-abliterated-v3-exl2',
        'messages': conversation_history,
        'max_tokens': 150,
        'temperature': 0.7,
        'top_p': 0.9,
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()

        response_json = response.json()
        print(f"Raw API Response for {listening_agent_name}:\n{json.dumps(response_json, indent=2)}")

        assistant_message = response_json['choices'][0]['message']['content'].strip()

        # Check for redundant introductions
        if not assistant_message.startswith(f"{speaking_agent['name']}: "):
            listening_agent_history.append({"role": "assistant", "content": assistant_message})

        return assistant_message
    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request: {e}")
        return ""
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing JSON response: {e}")
        print("Response Text:", response.text)
        return ""

def conv(agent1, agent2, initial_prompt):
    print(f"\n----- Starting conversation between {agent1['name']} and {agent2['name']} -----")
    print_agent_state(agent1)
    print_agent_state(agent2)

    response = send_message(initial_prompt, agent1, agent2["history"])
    print(f"{agent2['name']}: {response}")

    response = send_message(response, agent2, agent1["history"])
    print(f"{agent1['name']}: {response}")

    print(f"\n----- Conversation ended -----")
    print_agent_state(agent1)
    print_agent_state(agent2)

    return response

def print_agent_state(agent):
    print(f"\n----- {agent['name']}'s current state -----")
    print(f"History:\n{json.dumps(agent['history'], indent=2)}")

# Create agents
Bob = create_agent("Bob")
Alice = create_agent("Alice")
Chloe = create_agent("Chloe")

# Conversation between Bob and Alice
prompt = "Hello Alice, my name is Bob, and my favorite color is dark red. What's your favorite season?"
conv(Bob, Alice, prompt)

# Conversation between Chloe and Alice
prompt = "Hi Alice, I'm Chloe. Can you tell me something interesting about Bob?"
conv(Chloe, Alice, prompt)

# Conversation between Bob and Chloe
prompt = "Hello Chloe, it's Bob. Did Alice tell you anything about me?"
conv(Bob, Chloe, prompt)

print("\n----- Final Agent States -----")
for agent in [Bob, Alice, Chloe]:
    print_agent_state(agent)
