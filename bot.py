
import slack
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response
from slackeventsapi import SlackEventAdapter
import string
import logging
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import re
import json

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
user_states = {}  # Track user conversation state

BAD_WORDS = ['stupid', 'bitch', 'idiot']

# Fallback common ticker corrections for when search fails
TICKER_CORRECTIONS = {
    'APPL': 'AAPL',   # Common misspelling for Apple
    'GOOGL': 'GOOG',  # Both are valid but different share classes
    'AMZM': 'AMZN',   # Common misspelling for Amazon
}


class WelcomeMessage:
    START_TEXT = {
        'type': 'section',
        'text': {
            'type': 'mrkdwn',
            'text': (
                'Welcome to your financial advisor! \n\n'
                '*Get started by typing a company name to analyze!*'
            )
        }
    }

    DIVIDER = {'type': 'divider'}

    def __init__(self, channel):
        self.channel = channel
        self.icon_emoji = ':chart_with_upwards_trend:'
        self.timestamp = ''
        self.completed = False

    def get_message(self):
        return {
            'ts': self.timestamp,
            'channel': self.channel,
            'username': 'Finance Bot',
            'icon_emoji': self.icon_emoji,
            'blocks': [
                self.START_TEXT,
                self.DIVIDER,
                self._get_instruction_block()
            ]
        }

    def _get_instruction_block(self):
        text = "Type a company name (e.g., 'Apple', 'Microsoft', 'Tesla') to get financial information."
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
    user_states[user] = "awaiting_company"


def check_if_bad_words(message):
    msg = message.lower()
    msg = msg.translate(str.maketrans('', '', string.punctuation))
    return any(word in msg for word in BAD_WORDS)


def search_ticker_symbol(company_name):
    """
    Search for ticker symbol using multiple methods:
    1. Yahoo Finance ticker search
    2. MarketWatch search
    3. Direct finviz lookup
    4. Wikipedia search
    5. YFinance direct API
    """
    company_name = company_name.strip()
    
    # If input is already in ticker format (all caps, 1-5 letters), try it directly
    if company_name.isupper() and 1 <= len(company_name) <= 5:
        # Still verify it actually exists
        try:
            ticker = yf.Ticker(company_name)
            info = ticker.info
            if info and 'regularMarketPrice' in info and info['regularMarketPrice'] is not None:
                return company_name
        except:
            pass
    
    # Try Yahoo Finance API
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={company_name}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        data = json.loads(response.text)
        
        if 'quotes' in data and data['quotes']:
            for quote in data['quotes']:
                if 'symbol' in quote:
                    # Verify the ticker actually works
                    ticker = yf.Ticker(quote['symbol'])
                    if hasattr(ticker, 'info') and ticker.info and 'regularMarketPrice' in ticker.info:
                        return quote['symbol']
    except Exception as e:
        logging.error(f"Error in Yahoo Finance search: {e}")
    
    # Try MarketWatch search
    try:
        url = f"https://www.marketwatch.com/tools/quotes/lookup.asp?siteID=mktw&Lookup={company_name}&Country=us&Type=All"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the first result in the search table
        results = soup.select('table.results tr td:first-child a')
        if results:
            for result in results:
                ticker_candidate = result.text.strip()
                # Verify the ticker actually works
                ticker = yf.Ticker(ticker_candidate)
                if hasattr(ticker, 'info') and ticker.info and 'regularMarketPrice' in ticker.info:
                    return ticker_candidate
    except Exception as e:
        logging.error(f"Error in MarketWatch search: {e}")
    
    # Try finviz directly with company name as ticker
    try:
        # normalize to probable ticker format
        possible_ticker = ''.join(filter(str.isalpha, company_name)).upper()
        if 1 <= len(possible_ticker) <= 5:  # Valid ticker length
            ticker = yf.Ticker(possible_ticker)
            info = ticker.info
            if info and 'regularMarketPrice' in info and info['regularMarketPrice'] is not None:
                return possible_ticker
    except Exception as e:
        logging.error(f"Error in direct ticker check: {e}")
    
    # Try Wikipedia S&P 500 list
    try:
        sp500 = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')[0]
        company_match = sp500[sp500['Security'].str.contains(company_name, case=False)]
        if not company_match.empty:
            ticker_candidate = company_match.iloc[0]['Symbol']
            # Verify the ticker actually works
            ticker = yf.Ticker(ticker_candidate)
            if hasattr(ticker, 'info') and ticker.info and 'regularMarketPrice' in ticker.info:
                return ticker_candidate
    except Exception as e:
        logging.error(f"Error in Wikipedia search: {e}")
    
    # If company name is a common misspelling, correct it
    upper_name = company_name.upper()
    if upper_name in TICKER_CORRECTIONS:
        return TICKER_CORRECTIONS[upper_name]
    
    # Try using yfinance's search capability with the company name directly
    try:
        ticker = yf.Ticker(company_name)
        info = ticker.info
        if info and 'symbol' in info:
            return info['symbol']
    except Exception as e:
        logging.error(f"Error in yfinance direct search: {e}")
    
    # If all else fails, return None
    return None


def get_company_info(ticker_symbol):
    """
    function for getting company info using its tckr symbol
    """
    try:
        # misspelling
        if ticker_symbol in TICKER_CORRECTIONS:
            ticker_symbol = TICKER_CORRECTIONS[ticker_symbol]
            
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        
        # Validate that we have actual data
        if not info or 'regularMarketPrice' not in info or info['regularMarketPrice'] is None:
            return f"Could not find complete data for ticker {ticker_symbol}"
        
        # Get historical data for 52-week high/low
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        hist = ticker.history(start=start_date, end=end_date)
        
        if hist.empty:
            return f"Could not find historical data for ticker {ticker_symbol}"
        
        # Prepare the information blocks
        company_name = info.get('shortName', ticker_symbol)
        
        # Basic price information
        current_price = info.get('regularMarketPrice', info.get('currentPrice', 'N/A'))
        prev_close = info.get('regularMarketPreviousClose', info.get('previousClose', 'N/A'))
        open_price = info.get('regularMarketOpen', info.get('open', 'N/A'))
        day_low = info.get('regularMarketDayLow', info.get('dayLow', 'N/A'))
        day_high = info.get('regularMarketDayHigh', info.get('dayHigh', 'N/A'))
        
        # 52-week information
        week_52_low = info.get('fiftyTwoWeekLow', round(hist['Low'].min(), 2))
        week_52_high = info.get('fiftyTwoWeekHigh', round(hist['High'].max(), 2))
        
        # Volume information
        volume = info.get('regularMarketVolume', info.get('volume', 'N/A'))
        avg_volume = info.get('averageDailyVolume10Day', info.get('averageVolume', 'N/A'))
        
        # Circuit limits (typically not directly available, approximating)
        # Most exchanges have limits like 5-20% depending on the security and market
        if isinstance(current_price, (int, float)):
            lower_circuit = round(current_price * 0.9, 2)  # Assuming 10% limit
            upper_circuit = round(current_price * 1.1, 2)  # Assuming 10% limit
        else:
            lower_circuit = 'N/A'
            upper_circuit = 'N/A'
        
        # Fundamentals
        market_cap = info.get('marketCap', 'N/A')
        if isinstance(market_cap, (int, float)) and market_cap > 1000000:
            market_cap = f"${market_cap/1000000000:.2f}B"
        
        pe_ratio = info.get('trailingPE', 'N/A')
        eps = info.get('trailingEps', 'N/A')
        dividend_yield = info.get('dividendYield', 'N/A')
        if isinstance(dividend_yield, (int, float)):
            dividend_yield = f"{dividend_yield * 100:.2f}%"
        
        # Financial summaries
        revenue = info.get('totalRevenue', 'N/A')
        if isinstance(revenue, (int, float)) and revenue > 1000000:
            revenue = f"${revenue/1000000000:.2f}B"
            
        profit_margins = info.get('profitMargins', 'N/A')
        if isinstance(profit_margins, (int, float)):
            profit_margins = f"{profit_margins * 100:.2f}%"
        
        # Format the response
        response = f"*Financial Information for {company_name} ({ticker_symbol})*\n\n"
        
        # Price Section
        response += "*Price Information:*\n"
        response += f"• Current Price: ${current_price if isinstance(current_price, (int, float)) else current_price}\n"
        response += f"• Previous Close: ${prev_close if isinstance(prev_close, (int, float)) else prev_close}\n"
        response += f"• Open Price: ${open_price if isinstance(open_price, (int, float)) else open_price}\n"
        response += f"• Today's Range: ${day_low if isinstance(day_low, (int, float)) else day_low} - ${day_high if isinstance(day_high, (int, float)) else day_high}\n"
        response += f"• 52-Week Range: ${week_52_low if isinstance(week_52_low, (int, float)) else week_52_low} - ${week_52_high if isinstance(week_52_high, (int, float)) else week_52_high}\n\n"
        
        # Volume Section
        response += "*Volume Information:*\n"
        response += f"• Volume: {volume:,} shares\n" if isinstance(volume, (int, float)) else f"• Volume: {volume}\n"
        response += f"• Average Volume: {avg_volume:,} shares\n\n" if isinstance(avg_volume, (int, float)) else f"• Average Volume: {avg_volume}\n\n"
        
        # Circuit Limits
        response += "*Circuit Limits:*\n"
        response += f"• Lower Circuit: ${lower_circuit}\n"
        response += f"• Upper Circuit: ${upper_circuit}\n\n"
        
        # Fundamentals
        response += "*Fundamentals:*\n"
        response += f"• Market Cap: {market_cap}\n"
        response += f"• P/E Ratio: {pe_ratio}\n"
        response += f"• EPS (TTM): ${eps}\n"
        response += f"• Dividend Yield: {dividend_yield}\n\n"
        
        # Financial Summaries
        response += "*Financial Summary:*\n"
        response += f"• Revenue (TTM): {revenue}\n"
        response += f"• Profit Margin: {profit_margins}\n"
        
        return response
        
    except Exception as e:
        logging.error(f"Error getting company info: {e}")
        return f"Error fetching financial data for {ticker_symbol}. Please check if the ticker symbol is correct."


@slack_event_adapter.on('message')
def message(payLoad):
    event = payLoad.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')
    ts = event.get('ts')

    if user_id is not None and BOT_ID != user_id:
        if user_id in message_counts:
            message_counts[user_id] += 1
        else:
            message_counts[user_id] = 1

        if text.lower() == 'start':
            send_welcome_message(channel_id, user_id)
            return

        elif check_if_bad_words(text):
            client.chat_postMessage(
                channel=channel_id, thread_ts=ts, text="Please keep conversations professional.")
            return

        # For any text, assume it might be a company name or ticker
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=ts,
            text="Looking up financial information for your company. Please wait..."
        )
        
        # ticker symbol look up
        ticker = search_ticker_symbol(text)
        
        if ticker:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=ts,
                text=f"Found ticker: {ticker}. Fetching financial data..."
            )
            
            # getting company info
            info = get_company_info(ticker)
            client.chat_postMessage(
                channel=channel_id,
                text=info
            )
        else:
            client.chat_postMessage(
                channel=channel_id,
                text=f"Sorry, I couldn't find a ticker symbol for '{text}'. Please try another company name or check the spelling."
            )


@slack_event_adapter.on('reaction_added')
def handle_reaction(payLoad):
    event = payLoad.get('event', {})
    channel_id = event.get('item', {}).get('channel')
    user_id = event.get('user')

    if channel_id in welcome_messages and user_id in welcome_messages[channel_id]:
        welcome = welcome_messages[channel_id][user_id]
        welcome.completed = True
        message = welcome.get_message()
        updated_message = client.chat_update(**message)
        welcome.timestamp = updated_message['ts']
        
        # Prompt for company name
        client.chat_postMessage(
            channel=channel_id,
            text="Please type a company name to get financial information."
        )


@app.route('/message-count', methods=['POST'])
def message_count():
    data = request.form
    user_id = data.get('user_id')
    channel_id = data.get('channel_id')
    message_count = message_counts.get(user_id, 0)
    client.chat_postMessage(channel=channel_id, text=f"Message: {message_count}")
    return Response(), 200


if __name__ == "__main__":
    app.run(debug=True)