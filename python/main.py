import asyncio
import os
import json
from decimal import Decimal
from typing import Dict, Optional

import websockets
from rabbitx.rabbitx.client import Client as RabbitXClient
from rabbitx.rabbitx.const import *
from rabbitx.rabbitx.client.endpoints.order import OrderSide, OrderType

# Constants
BINANCE_WS_URL = "wss://fstream.binance.com/ws"
SYMBOL = "btcusdt"  # Lowercase for Binance WebSocket
RABBITX_SYMBOL = "BTCUSDT"  # Uppercase for RabbitX
ORDER_SIZE = Decimal("0.001")  # Adjust the order size as needed
PRICE_DECIMALS = 2  # Number of decimal places for price

# Load environment variables
RABBITX_API_KEY = os.getenv("RABBITX_API_KEY")
RABBITX_API_SECRET = os.getenv("RABBITX_API_SECRET")

class MarketMakingBot:
    def __init__(self):
        self.rabbitx_client = RabbitXClient(RABBITX_API_KEY, RABBITX_API_SECRET)
        self.current_orders: Dict[str, Optional[str]] = {"buy": None, "sell": None}
        self.current_prices: Dict[str, Optional[Decimal]] = {"bid": None, "ask": None}

    async def start(self):
        await self.connect_binance_ws()

    async def connect_binance_ws(self):
        async with websockets.connect(BINANCE_WS_URL) as websocket:
            subscribe_msg = {
                "method": "SUBSCRIBE",
                "params": [f"{SYMBOL}@bookTicker"],
                "id": 1
            }
            await websocket.send(json.dumps(subscribe_msg))
            
            while True:
                try:
                    response = await websocket.recv()
                    data = json.loads(response)
                    
                    if 'e' in data and data['e'] == 'bookTicker':
                        await self.handle_price_update(data)
                except Exception as e:
                    print(f"WebSocket error: {e}")
                    await asyncio.sleep(5)
                    await self.connect_binance_ws()

    async def handle_price_update(self, data):
        new_bid = Decimal(data['b']).quantize(Decimal(f"0.{'0' * PRICE_DECIMALS}"))
        new_ask = Decimal(data['a']).quantize(Decimal(f"0.{'0' * PRICE_DECIMALS}"))

        bid_changed = new_bid != self.current_prices["bid"]
        ask_changed = new_ask != self.current_prices["ask"]

        if bid_changed:
            self.current_prices["bid"] = new_bid
            print(f"New bid price: {new_bid}")
            await self.update_order(OrderSide.BUY, new_bid)

        if ask_changed:
            self.current_prices["ask"] = new_ask
            print(f"New ask price: {new_ask}")
            await self.update_order(OrderSide.SELL, new_ask)

    async def update_order(self, side: OrderSide, price: Decimal):
        order_key = side.value.lower()
        existing_order_id = self.current_orders[order_key]

        try:
            if existing_order_id:
                # Amend existing order
                amended_order = await self.rabbitx_client.amend_order(
                    symbol=RABBITX_SYMBOL,
                    order_id=existing_order_id,
                    price=price,
                    amount=ORDER_SIZE
                )
                print(f"Amended {side.value} order: {amended_order}")
            else:
                # Place new order
                new_order = await self.rabbitx_client.create_order(
                    symbol=RABBITX_SYMBOL,
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=price,
                    amount=ORDER_SIZE
                )
                self.current_orders[order_key] = new_order.id
                print(f"Placed new {side.value} order: {new_order}")
        except Exception as e:
            print(f"Error updating {side.value} order: {e}")
            # If there's an error, cancel the existing order and try to place a new one
            await self.cancel_and_place_new_order(side, price)

    async def cancel_and_place_new_order(self, side: OrderSide, price: Decimal):
        order_key = side.value.lower()
        existing_order_id = self.current_orders[order_key]

        if existing_order_id:
            try:
                await self.rabbitx_client.cancel_order(symbol=RABBITX_SYMBOL, order_id=existing_order_id)
                print(f"Cancelled {side.value} order: {existing_order_id}")
            except Exception as e:
                print(f"Error cancelling {side.value} order: {e}")

        try:
            new_order = await self.rabbitx_client.create_order(
                symbol=RABBITX_SYMBOL,
                side=side,
                order_type=OrderType.LIMIT,
                price=price,
                amount=ORDER_SIZE
            )
            self.current_orders[order_key] = new_order.id
            print(f"Placed new {side.value} order after cancellation: {new_order}")
        except Exception as e:
            print(f"Error placing new {side.value} order after cancellation: {e}")
            self.current_orders[order_key] = None

async def main():
    bot = MarketMakingBot()
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())