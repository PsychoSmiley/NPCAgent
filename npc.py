# npc.py - NPCAgent v0.3.2 - strip speaker-name label from a reply before relaying to the next agent
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
        "first_utterance": True
    }

def send_message(prompt, speaking_agent, listening_agent_history):
    endpoint = '/chat/completions'
    url = f"{base_url}{endpoint}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    conversation_history = listening_agent_history
    user_message = {"role": "user", "content": f"{speaking_agent['name']}: {prompt}"}
    conversation_history.append(user_message)
    listening_agent_name = speaking_agent['name']

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

        # Prepend the speaker's name ONLY if it's NOT already present
        if speaking_agent['name'] not in assistant_message:
            assistant_message = f"{speaking_agent['name']}: {assistant_message}"

        conversation_history.append({"role": "assistant", "content": assistant_message})
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

    # Reset the first_utterance flag ONLY if the agent hasn't spoken yet
    if agent1["first_utterance"]:
        agent1["first_utterance"] = False

    # Agent1 sends the initial prompt to Agent2
    response = send_message(initial_prompt, agent1, agent2["history"])
    print(f"{agent2['name']}: {response}")

    # Reset the first_utterance flag ONLY if the agent hasn't spoken yet
    if agent2["first_utterance"]:
        agent2["first_utterance"] = False

    # Agent2 responds to Agent1's message
    # Extract the message content, handling cases where the colon might be missing
    response_parts = response.split(":", 1)
    if len(response_parts) > 1:
        response_content = response_parts[1].strip()
    else:
        response_content = response_parts[0].strip()

    response = send_message(response_content, agent2, agent1["history"])

    # Only add the name prefix if it's the agent's FIRST utterance in this conversation
    if agent1["first_utterance"]:
        print(f"{agent1['name']}: {response}")
        agent1["first_utterance"] = False
    else:
        print(f"{response}")

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
