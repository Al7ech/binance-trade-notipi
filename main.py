import os
import time
import json
import logging
import sys
import traceback

import requests

from unicorn_binance_rest_api.manager import BinanceRestApiManager
from unicorn_binance_websocket_api.manager import BinanceWebSocketApiManager

logger = logging.getLogger()
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(stream=sys.stdout)
logger.addHandler(ch)
logging.getLogger('unicorn_binance_rest_api').setLevel(logging.WARNING)
logging.getLogger('unicorn_binance_websocket_api').setLevel(logging.WARNING)

def get_elem(lst, **kwargs):
    '''
    get first elem that matches kwargs
    '''
    for e in lst:
        for k, v in kwargs.items():
            if e.get(k) != v:
                break
        else:
            return e

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
testnet = os.getenv("TESTNET") == "true"
asset = os.getenv("ASSET")
symbol = os.getenv("SYMBOL")
user = os.getenv("USERNAME")
pw = os.getenv("PASSWORD")
endpoint = os.getenv("ENDPOINT")
exchange = "binance.com-futures-testnet" if testnet else "binance.com-futures"

logger.info("Loading balance & position...")
client = BinanceRestApiManager(api_key, api_secret, exchange=exchange, warn_on_update=False)

info = client.futures_account()
prev_balance = balance = float(get_elem(info['assets'], asset=asset).get('walletBalance', 0))
prev_position = position = float(get_elem(info['positions'], symbol=symbol).get('positionAmt', 0))

def callback(data):
    try:
        global balance, prev_balance, position, prev_position
        msg = json.loads(data)
        if msg['e'] == "ACCOUNT_UPDATE":
            if balance_info := get_elem(msg['a']['B'], a=asset):
                balance = float(balance_info.get('wb', 0))
            if position_info := get_elem(msg['a']['P'], s=symbol):
                position = float(position_info.get('pa', 0))

        if msg['e'] == "ORDER_TRADE_UPDATE":
            if msg['o']['X'] == "FILLED" and msg['o']['s'] == symbol:
                price = float(msg['o']['ap'])
                data = {
                    "title": "Binance trade detection", 
                    "content": f"{symbol[:3]}: {position:.3f}({position-prev_position:+.3f}) @ {price:.2f}\n{asset}: {balance:.2f} ({'▲' if prev_balance < balance else '▼'} {abs(balance-prev_balance):.2f}, {abs(balance/prev_balance-1):.2%})"
                }
                logger.info(data)
                r = requests.post(endpoint, json=data, auth=(user, pw))

                prev_balance = balance
                prev_position = position
    except Exception as e:
        logger.critical(str(e))
        logger.critical(traceback.format_exc())

logger.info("Initializing websockets...")
websocket = BinanceWebSocketApiManager(exchange=exchange, warn_on_update=False)
websocket.create_stream('arr', '!userData', api_key=api_key, api_secret=api_secret, process_stream_data=callback)

logger.info("Watching wallet...")
while True:
    time.sleep(60)
