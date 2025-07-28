'''import slack
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response
from slackeventsapi import SlackEventAdapter

env_path= Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app=Flask(__name__)
slack_event_adapter = SlackEventAdapter(os.environ['SIGNING_SECRET'],'/slack/events',app)

client = slack.WebClient(token= os.environ['SLACK_TOKEN'])
BOT_ID = client.api_call("auth.test")['user_id']

message_counts = {}
welcome_messages = {}


class WelcomeMessage:
    START_TEXT = {
        'type' : 'section',
        'text' : {
            'type' : 'mrkdwn',
            'text' : (
                'Welcome to your financial advisor! \n\n'
                '*Get started by verifying that you are human!*'
            )
        }
    }
    DIVIDER = {'tyoe': 'divider'}


    def __init__(self,channel,user):
        self.channel = channel
        self.user = user
        self.icon_emoji = ':robot_face:'
        self.timestamp= '' 
        self.completed =False

    def get_message(self):
        return {
            'ts': self.timestamp,
            'channel': self.channel,
            'username': 'Welcome Robot!',
            'icon_emoji': self.icon_emoji,
            'blocks': [
                self.START_TEXT,
                self.DIVIDER,
                self._get_reaction_task()
            ]}
    
    def _get_reaction_task(self):
        checkmark = ':white_check_mark:'
        if not self.completed:
            checkmark = ':white_large_square:'

        text = f'{checkmark} *React to this message!*'
        return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}


def send_welcome_message(channel, user):
    if channel not in welcome_messages:
        welcome_messages[channel] = {}

    if user in welcome_messages[channel]:
        return

    welcome = WelcomeMessage(channel)
    message = welcome.get_message()
    response = client.chat_postMessage(**message)
    welcome.timestamp = response['ts']

    welcome_messages[channel][user] = welcome


@slack_event_adapter.on('message')
def message(payLoad):
    event = payLoad.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')

    if user_id is not None and BOT_ID != user_id:
        if user_id in message_counts:
            message_counts[user_id] += 1
        else:
            message_counts[user_id] = 1

        if text.lower() == 'start':
            send_welcome_message(f'@{user_id}', user_id)

@app.route('/message-count', methods= ['POST'])
def message_count():
    data = request.form
    user_id= data.get('user_id')
    channel_id = data.get('channel_id')
    message_count =message_counts.get(user_id,0)
    client.chat_postMessage(channel=channel_id, text= f"Message: {message_count}")
    return Response(), 200

if __name__ == "__main__":
    app.run(debug=True)
'''
'''
2

import slack
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response
from slackeventsapi import SlackEventAdapter
import string
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.DEBUG)

# Load environment variables
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Initialize Flask app and Slack client
app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(
    os.environ['SIGNING_SECRET'], '/slack/events', app)

client = slack.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = client.api_call("auth.test")['user_id']

message_counts = {}
welcome_messages = {}

BAD_WORDS = ['stupid', 'bitch', 'idiot']
COMPANIES = ['A', 'B', 'C']


class WelcomeMessage:
    START_TEXT = {
        'type': 'section',
        'text': {
            'type': 'mrkdwn',
            'text': (
                'Welcome to this awesome channel!\n\n'
                '*Get started by completing the tasks!*'
            )
        }
    }

    DIVIDER = {'type': 'divider'}

    def __init__(self, channel):
        self.channel = channel
        self.icon_emoji = ':robot_face:'
        self.timestamp = ''
        self.completed = False

    def get_message(self):
        return {
            'ts': self.timestamp,
            'channel': self.channel,
            'username': 'Welcome Robot!',
            'icon_emoji': self.icon_emoji,
            'blocks': [
                self.START_TEXT,
                self.DIVIDER,
                self._get_reaction_task()
            ]
        }

    def _get_reaction_task(self):
        checkmark = ':white_check_mark:'
        if not self.completed:
            checkmark = ':white_large_square:'

        text = f'{checkmark} *React to this message!*'
        return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}


def send_welcome_message(channel, user):
    if channel not in welcome_messages:
        welcome_messages[channel] = {}

    if user in welcome_messages[channel]:
        return

    welcome = WelcomeMessage(channel)
    message = welcome.get_message()
    response = client.chat_postMessage(**message)
    welcome.timestamp = response['ts']

    welcome_messages[channel][user] = welcome


def create_company_buttons(channel):
    buttons = [
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": company
            },
            "value": company,
            "action_id": f"select_company_{company.replace(' ', '_')}"
        } for company in COMPANIES
    ]

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Choose a company to query:"
            }
        },
        {
            "type": "actions",
            "elements": buttons
        }
    ]

    client.chat_postMessage(
        channel=channel,
        blocks=blocks,
        text="Select a company"
    )


def create_query_buttons(channel, company):
    try:
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Choose a financial metric to query for {company}:"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Profit"
                        },
                        "value": f"{company}_profit",
                        "action_id": f"query_profit_{company.replace(' ', '_')}"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Revenue"
                        },
                        "value": f"{company}_revenue",
                        "action_id": f"query_revenue_{company.replace(' ', '_')}"
                    }
                ]
            }
        ]

        response = client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=f"Select a query for {company}"
        )
        if not response['ok']:
            logging.error(f"Slack API Error: {response['error']}")
            return Response(f"Slack API Error: {response['error']}", status=500)

    except Exception as e:
        logging.error(f"Error creating query buttons: {e}")
        return Response(str(e), status=500)


def check_if_bad_words(message):
    msg = message.lower()
    msg = msg.translate(str.maketrans('', '', string.punctuation))

    return any(word in msg for word in BAD_WORDS)


@slack_event_adapter.on('message')
def message(payLoad):
    event = payLoad.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')

    if user_id is not None and BOT_ID != user_id:
        if user_id in message_counts:
            message_counts[user_id] += 1
        else:
            message_counts[user_id] = 1

        if text.lower() == 'start':
            send_welcome_message(f'@{user_id}', user_id)

        elif check_if_bad_words(text):
            ts = event.get('ts')
            client.chat_postMessage(
                channel=channel_id, thread_ts=ts, text="THAT IS A BAD WORD")

@slack_event_adapter.on('reaction_added')
def handle_reaction(payLoad):
    event = payLoad.get('event', {})
    channel_id = event.get('item', {}).get('channel')
    user_id = event.get('user')
    ts = event.get('item', {}).get('ts')

    if f'@{user_id}' not in welcome_messages:
        return

    welcome = welcome_messages[f'@{user_id}'][user_id]
    welcome.completed = True
    welcome.channel = channel_id
    message = welcome.get_message()
    updated_message = client.chat_update(**message)
    welcome.timestamp = updated_message['ts']
    create_company_buttons(welcome.channel)


@slack_event_adapter.on('block_actions')
def handle_block_actions(payLoad):
    logging.debug(f"Received block_actions payload: {payLoad}")
    actions = payLoad.get('actions', [])
    if not actions:
        logging.error("No actions found in payload")
        return Response("No actions found", status=400)

    action = actions[0]
    action_id = action.get('action_id')
    channel_id = payLoad.get('channel', {}).get('id')

    logging.debug(f"Action ID: {action_id}")
    logging.debug(f"Channel ID: {channel_id}")

    if action_id.startswith('select_company_'):
        selected_company = action.get('value')
        create_query_buttons(channel_id, selected_company)
        return Response(), 200

    return Response("Action not recognized", status=400)


if __name__ == "__main__":
    app.run(debug=True)
'''