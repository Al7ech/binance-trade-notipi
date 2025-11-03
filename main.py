import os
import json
import logging
import sys
import traceback
import asyncio

import aiohttp
from binance import AsyncClient, BinanceSocketManager

logger = logging.getLogger()
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(stream=sys.stdout)
logger.addHandler(ch)

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


async def main():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    testnet = os.getenv("TESTNET") == "true"
    asset = os.getenv("ASSET")
    symbol = os.getenv("SYMBOL")
    user = os.getenv("USERNAME")
    pw = os.getenv("PASSWORD")
    endpoint = os.getenv("ENDPOINT")

    if not all([api_key, api_secret, asset, symbol, endpoint]):
        logger.critical("Missing required environment variables. Please check .env/template.env")
        sys.exit(1)

    prev_balance = 0.0
    balance = 0.0
    prev_position = 0.0
    position = 0.0

    while True:
        client = None
        try:
            logger.info("Initializing client & loading balance/position...")
            client = await AsyncClient.create(api_key=api_key, api_secret=api_secret, testnet=testnet)

            info = await client.futures_account()
            prev_balance = balance = float(get_elem(info['assets'], asset=asset).get('walletBalance', 0))
            prev_position = position = float(get_elem(info['positions'], symbol=symbol).get('positionAmt', 0))

            bsm = BinanceSocketManager(client)
            # Futures user data stream
            user_stream = bsm.futures_user_socket()

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as http_session:
                logger.info("Starting user data websocket stream...")
                async with user_stream as stream:
                    while True:
                        msg = await stream.recv()
                        try:
                            if isinstance(msg, (bytes, str)):
                                msg = json.loads(msg)

                            # ACCOUNT_UPDATE: update wallet balance and position
                            if msg.get('e') == "ACCOUNT_UPDATE":
                                if (b_info := get_elem(msg['a'].get('B', []), a=asset)) is not None:
                                    balance = float(b_info.get('wb', 0))
                                if (p_info := get_elem(msg['a'].get('P', []), s=symbol)) is not None:
                                    position = float(p_info.get('pa', 0))

                            # ORDER_TRADE_UPDATE: send notification when filled for our symbol
                            if msg.get('e') == "ORDER_TRADE_UPDATE":
                                o = msg.get('o', {})
                                if o.get('X') == "FILLED" and o.get('s') == symbol:
                                    prefix = "🟢" if prev_balance < balance else "🔴"
                                    price = float(o.get('ap', 0))
                                    data = {
                                        "title": f"{prefix} Binance trade detection",
                                        "content": f"{symbol[:3]}: {position:.3f}({position-prev_position:+.3f}) @ {price:.2f}\n{asset}: {balance:.2f} ({'▲' if prev_balance < balance else '▼'} {abs(balance-prev_balance):.2f}, {abs(balance/prev_balance-1):.2%})"
                                    }
                                    logger.info(data)

                                    auth = aiohttp.BasicAuth(user, pw) if user and pw else None
                                    try:
                                        async with http_session.post(endpoint, json=data, auth=auth) as resp:
                                            await resp.text()
                                    except Exception as post_err:
                                        logger.error(f"POST failed: {post_err}")

                                    prev_balance = balance
                                    prev_position = position
                        except Exception as inner_exc:
                            logger.critical(str(inner_exc))
                            logger.critical(traceback.format_exc())

        except Exception as e:
            logger.error(f"Websocket/client error: {e}")
            logger.debug(traceback.format_exc())
            # no manual sleep; rely on built-in reconnect or immediate restart
        finally:
            if client is not None:
                try:
                    await client.close_connection()
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
