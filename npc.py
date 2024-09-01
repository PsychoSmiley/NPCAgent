# npc.py - NPCAgent v0.1.0 - bare-bone: OpenAI-compatible chat over a persisted history + in-place history-rewrite memory test
import requests
import json

base_url = "http://127.0.0.1:5000/v1"
api_key = "your_api_key"

# Initialize history outside the function to persist across calls
history = []

def send_message(prompt,
                 model="gpt-4",
                 max_tokens=100,
                 temperature=0.7,
                 top_p=0.9,
                 stop=None,
                 presence_penalty=0,
                 frequency_penalty=0,
                 context="Bot Name is Bob.",
                 user_bio=None,
                 instruction_template=None,
                 mode='chat-instruct',
                 character=None,
                 return_history=False):

    endpoint = '/chat/completions'
    url = f"{base_url}{endpoint}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    # Add context as system message if it's not already in history
    if not history or history[0]['role'] != 'system':
        history.insert(0, {"role": "system", "content": context})

    # Add user message to history
    history.append({"role": "user", "content": prompt})

    data = {
        'model': model,
        'messages': history,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'top_p': top_p,
        'stop': stop,
        'presence_penalty': presence_penalty,
        'frequency_penalty': frequency_penalty,
        'mode': mode # instruct, chat, chat-instruct
    }

    if character is not None:
        data["character"] = character
    if instruction_template is not None:
        data["instruction_template"] = instruction_template

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()

        response_json = response.json()
        print("Raw API Response:", response_json)

        assistant_message = response_json['choices'][0]['message']['content'].strip()
        history.append({"role": "assistant", "content": assistant_message})

        if return_history:
            return history
        else:
            return assistant_message
    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request: {e}")
        return "" if not return_history else []
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing JSON response: {e}")
        print("Response Text:", response.text)
        return "" if not return_history else []

# Clear history before starting
history.clear()

# Initial question
response = send_message("What is my name?")
print("Response:", response)

# Say the name is Alex
response = send_message("My name is Alex!")
print("Response:", response)

# Modify the history (replace "Alex" with "Noxy")
for i, message in enumerate(history):
    if message["role"] == "user" and "My name is Alex" in message["content"]:
        history[i]["content"] = "My name is Noxy!"
        break

print("\nModified History:")
for message in history:
    print(f"{message['role']}: {message['content']}")

# Test if the modified name is remembered
response = send_message("What is my name again?")
print("Response:", response)


# Test if the modified name is remembered
response = send_message("What your name?")
print("Response:", response)
