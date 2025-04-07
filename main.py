import os
import json
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Splunk HEC settings
SPLUNK_HEC_URL = os.getenv("SPLUNK_HEC_URL")
SPLUNK_TOKEN = os.getenv("SPLUNK_TOKEN")
WEBEX_ACCESS_TOKEN = os.getenv("WEBEX_ACCESS_TOKEN")
BOT_EMAIL = os.getenv("BOT_EMAIL")
FLASK_API = os.getenv("FLASK_API")

headers = {
    "Authorization": f"Splunk {SPLUNK_TOKEN}",
    "Content-Type": "application/json"
}

# Webex API endpoint
WEBEX_API_URL = "https://webexapis.com/v1/messages"
WEBEX_WEBHOOK_API_URL = "https://webexapis.com/v1/webhooks"


def send_to_splunk(data):
    """Send data to Splunk"""
    payload = {
        "event": data,
        "sourcetype": "Agricultural_Bot_Data",
        "index": "agriculture"
    }

    try:
        response = requests.post(SPLUNK_HEC_URL, headers=headers, json=payload, verify=False, timeout=5)
        if response.status_code == 200:
            print(f"Successfully indexed: {data}")
            return True
        else:
            print(f"Error sending to Splunk: {response.content}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Splunk request failed: {e}")
        return False


def create_webex_webhook():
    """Check if the Webex webhook exists, if not, create it"""
    try:
        response = requests.get(
            WEBEX_WEBHOOK_API_URL,
            headers={"Authorization": f"Bearer {WEBEX_ACCESS_TOKEN}"},
            timeout=5
        )

        if response.status_code == 200:
            webhooks = response.json().get("items", [])

            # Check if the webhook already exists
            for webhook in webhooks:
                if webhook['name'] == "Agriculture Webex Webhook":
                    print("Webhook already exists.")
                    return

            # Webhook doesn't exist, create it
            data = {
                "name": "Agriculture Webex Webhook",
                "targetUrl": FLASK_API,
                "resource": "messages",
                "event": "created"
            }

            create_response = requests.post(
                WEBEX_WEBHOOK_API_URL,
                headers={
                    "Authorization": f"Bearer {WEBEX_ACCESS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json=data,
                timeout=5
            )

            if create_response.status_code == 200:
                print("Webhook successfully created.")
            else:
                print(f"Failed to create webhook: {create_response.status_code}, {create_response.content}")
        else:
            print(f"Failed to list webhooks: {response.status_code}, {response.content}")
    except requests.exceptions.RequestException as e:
        print(f"Webex webhook request failed: {e}")


def get_message_text(message_id, access_token):
    """Fetch the actual message content from Webex"""
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://webexapis.com/v1/messages/{message_id}"

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json().get("text")
        else:
            print(f"Failed to fetch message: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Message fetch failed: {e}")
        return None


@app.route("/webex-webhook", methods=["POST"])
def webex_webhook():
    data = request.json

    message_id = data.get("data", {}).get("id")
    room_id = data.get("data", {}).get("roomId")
    person_email = data.get("data", {}).get("personEmail")

    if not message_id or not room_id or not person_email:
        return jsonify({"error": "Invalid payload received"}), 400

    # Ignore messages sent by the bot itself
    if person_email == BOT_EMAIL:
        return jsonify({"status": "Bot's own message, ignoring"}), 200

    # Get the actual message text from Webex
    message_text = get_message_text(message_id, WEBEX_ACCESS_TOKEN)

    if message_text:
        print("Message received:", message_text)

        # Load crop descriptions from local JSON file
        with open("crops.json", "r") as f:
            crop_data = json.load(f)

        # Normalize user message for matching
        user_input = message_text.strip().lower()

        # Check if the user input matches a known crop
        if user_input in crop_data:
            response_text = f"{user_input.capitalize()} Info: {crop_data[user_input]}"
        else:
            response_text = (f"Sorry, I don't have data on '{message_text}'. Try asking about corn, rice, wheat, "
                             f"avocado, or potatoes.")

        # Send back response to user on Webex
        send_webex_message(room_id, response_text)

        # Send full payload to Splunk
        payload = {
            "message": message_text,
            "roomId": room_id,
            "user": person_email,
            "raw": data
        }
        send_to_splunk(payload)

        return jsonify({"status": "Message processed and response sent"}), 200
    else:
        return jsonify({"error": "Could not fetch message"}), 500


def send_webex_message(room_id, text):
    """Send message back to Webex room"""
    message_data = {
        "roomId": room_id,
        "text": text
    }

    try:
        response = requests.post(
            WEBEX_API_URL,
            headers={"Authorization": f"Bearer {WEBEX_ACCESS_TOKEN}"},
            json=message_data,
            timeout=5
        )

        if response.status_code == 200:
            print(f"Message sent to Webex: {text}")
        else:
            print(f"Error sending message to Webex: {response.content}")
    except requests.exceptions.RequestException as e:
        print(f"Webex message send failed: {e}")


if __name__ == "__main__":
    # Avoid duplicate execution due to Flask's auto-reloader
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or os.environ.get("FLASK_ENV") != "development":
        create_webex_webhook()

    # Run Flask app
    app.run(debug=False, host="0.0.0.0", port=5000)
