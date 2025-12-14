import asyncio
import json
import time
import requests
from datetime import datetime
from collections import deque
import websockets

# ============================================
# SOZLAMALAR
# ============================================

BYBIT_API_KEY = "UNLnS5ZY8d3Q8Ppvj9"
BYBIT_API_SECRET = "6UMY931gUtJ0TG7CG3a3YjJbK2PvgZ3zekfx"
TELEGRAM_BOT_TOKEN = "8453486857:AAEIK0D3zWEn_OD00iU26xF-o3GwTr0HTuM"
TELEGRAM_CHAT_ID = "2147212708"

# ============================================
# SMART MONEY SOZLAMALARI
# ============================================

SYMBOL = "BTCUSDT"
TIMEFRAME_MINUTES = 5

# PREMIUM FILTRLAR
WHALE_ORDER_THRESHOLD = 50000  # $50,000+
MEGA_WHALE_THRESHOLD = 100000  # $100,000+
MIN_WHALE_ORDERS = 5
EXTREME_PRESSURE_THRESHOLD = 75
STOP_LOSS_PERCENT = 0.8
TAKE_PROFIT_PERCENT = 2.5
SIGNAL_COOLDOWN = 600

MIN_TOTAL_WHALE_VOLUME = 500000
ORDERBOOK_IMBALANCE_MIN = 2.5
CONSECUTIVE_WHALES = 3

# ============================================
# GLOBAL O'ZGARUVCHILAR
# ============================================

orderbook_data = {"bids": [], "asks": []}
last_signals = {}
stats = {
    "price": 0,
    "whale_buy_volume": 0,
    "whale_sell_volume": 0,
    "whale_orders": 0,
    "mega_whales": 0,
    "smart_money_direction": "NEUTRAL"
}

# Telegram message ID lar - edit qilish uchun
telegram_message_ids = {
    "buy_whales": None,
    "sell_whales": None,
    "status": None
}

# ============================================
# TELEGRAM FUNKSIYALARI
# ============================================

def send_or_edit_telegram(message, message_type):
    """Telegram xabarni yuborish yoki edit qilish"""
    try:
        url_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
        
        # Agar message ID mavjud bo'lsa - edit qilish
        if telegram_message_ids[message_type] is not None:
            url = f"{url_base}/editMessageText"
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": telegram_message_ids[message_type],
                "text": message,
                "parse_mode": "Markdown"
            }
        else:
            # Yangi xabar yuborish
            url = f"{url_base}/sendMessage"
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            }
        
        response = requests.post(url, json=data, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            # Yangi xabar bo'lsa, message_id ni saqlash
            if telegram_message_ids[message_type] is None:
                telegram_message_ids[message_type] = result["result"]["message_id"]
            return True
        else:
            # Edit xato bo'lsa, yangi xabar yuborish
            if "message is not modified" not in response.text:
                print(f"⚠️ Telegram: {response.text[:100]}")
            return False
    
    except Exception as e:
        print(f"❌ Telegram xato: {e}")
        return False

def format_price_range(orders):
    """Narx oralig'ini formatlash"""
    if not orders:
        return "Ma'lumot yo'q"
    
    prices = [o["price"] for o in orders]
    min_price = min(prices)
    max_price = max(prices)
    
    return f"${min_price:,.2f} - ${max_price:,.2f}"

def send_whale_summary(whale_buys, whale_sells, current_price):
    """Whale orderlarni umumiy xabar qilish"""
    
    # BUY WHALES xabari
    if whale_buys:
        mega_buys = [w for w in whale_buys if w["type"] == "MEGA"]
        regular_buys = [w for w in whale_buys if w["type"] == "WHALE"]
        
        total_buy_volume = sum(w["usd"] for w in whale_buys)
        buy_price_range = format_price_range(whale_buys)
        
        # Top 5 eng katta orderlar
        top_buys = sorted(whale_buys, key=lambda x: x["usd"], reverse=True)[:5]
        top_list = "\n".join([
            f"  • ${w['price']:,.2f} → ${w['usd']:,.0f}"
            for w in top_buys
        ])
        
        buy_message = f"""
🟢 *BUY WHALES AKTIV* 🐳

📊 *UMUMIY:*
• Whale Orders: {len(whale_buys)}
• Mega Whales: {len(mega_buys)} ($100k+)
• Regular Whales: {len(regular_buys)} ($50k+)

💰 *VOLUME:*
• Umumiy: ${total_buy_volume:,.0f}

📍 *NARX ORALIQLARI:*
• Range: {buy_price_range}
• Joriy narx: ${current_price:,.2f}

🎯 *TOP 5 ENG KATTA:*
{top_list}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        send_or_edit_telegram(buy_message.strip(), "buy_whales")
    
    # SELL WHALES xabari
    if whale_sells:
        mega_sells = [w for w in whale_sells if w["type"] == "MEGA"]
        regular_sells = [w for w in whale_sells if w["type"] == "WHALE"]
        
        total_sell_volume = sum(w["usd"] for w in whale_sells)
        sell_price_range = format_price_range(whale_sells)
        
        # Top 5 eng katta orderlar
        top_sells = sorted(whale_sells, key=lambda x: x["usd"], reverse=True)[:5]
        top_list = "\n".join([
            f"  • ${w['price']:,.2f} → ${w['usd']:,.0f}"
            for w in top_sells
        ])
        
        sell_message = f"""
🔴 *SELL WHALES AKTIV* 🐳

📊 *UMUMIY:*
• Whale Orders: {len(whale_sells)}
• Mega Whales: {len(mega_sells)} ($100k+)
• Regular Whales: {len(regular_sells)} ($50k+)

💰 *VOLUME:*
• Umumiy: ${total_sell_volume:,.0f}

📍 *NARX ORALIQLARI:*
• Range: {sell_price_range}
• Joriy narx: ${current_price:,.2f}

🎯 *TOP 5 ENG KATTA:*
{top_list}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        send_or_edit_telegram(sell_message.strip(), "sell_whales")

def send_premium_signal(signal_type, price, stop_loss, take_profit, whale_count, mega_whale_count, 
                       total_whale_volume, pressure, imbalance_ratio, whale_levels):
    """Trading signal - yangi xabar (edit qilinmaydi)"""
    emoji = "🟢" if signal_type == "LONG" else "🔴"
    whale_emoji = "🐳" * min(mega_whale_count, 5)
    
    if mega_whale_count >= 3 and pressure >= 80:
        confidence = "⭐⭐⭐⭐⭐ MAKSIMAL"
    elif mega_whale_count >= 2 and pressure >= 75:
        confidence = "⭐⭐⭐⭐ JUDA YUQORI"
    elif mega_whale_count >= 1 and pressure >= 75:
        confidence = "⭐⭐⭐ YUQORI"
    else:
        confidence = "⭐⭐ YAXSHI"
    
    risk = abs(price - stop_loss) / price * 100
    reward = abs(take_profit - price) / price * 100
    rr_ratio = reward / risk if risk > 0 else 0
    
    message = f"""
{whale_emoji} *TRADING SIGNAL* {whale_emoji}
{emoji} *{signal_type}* {emoji}

💰 *Entry:* ${price:,.2f}
🎯 *Take Profit:* ${take_profit:,.2f} (+{reward:.2f}%)
🛡 *Stop Loss:* ${stop_loss:,.2f} (-{risk:.2f}%)
📊 *Risk/Reward:* 1:{rr_ratio:.2f}

━━━━━━━━━━━━━━━━━━━━
🐋 *WHALE TAHLIL:*
• Whale Orders: {whale_count}
• Mega Whales: {mega_whale_count}
• Whale Volume: ${total_whale_volume:,.0f}
• Pressure: {pressure:.1f}%
• Imbalance: {imbalance_ratio:.2f}x

🎯 *Whale Levels:*
{whale_levels}

⚡ *Ishonch:* {confidence}
━━━━━━━━━━━━━━━━━━━━

⏰ {datetime.now().strftime('%H:%M:%S')}
📈 {SYMBOL} | M{TIMEFRAME_MINUTES}
"""
    
    # Signal xabari YANGI yuboriladi (edit qilinmaydi)
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message.strip(),
            "parse_mode": "Markdown"
        }
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"❌ Signal yuborishda xato: {e}")

# ============================================
# SMART MONEY TAHLIL
# ============================================

def analyze_smart_money():
    """Smart Money orderbook tahlili"""
    global stats
    
    if not orderbook_data["bids"] or not orderbook_data["asks"]:
        return
    
    bids = orderbook_data["bids"][:50]
    asks = orderbook_data["asks"][:50]
    
    whale_buy_orders = []
    whale_sell_orders = []
    mega_whale_count = 0
    total_whale_buy_volume = 0
    total_whale_sell_volume = 0
    
    # BID tahlili
    for i, (price_str, volume_str) in enumerate(bids):
        price = float(price_str)
        volume = float(volume_str)
        usd_value = price * volume
        
        if usd_value >= WHALE_ORDER_THRESHOLD:
            whale_buy_orders.append({
                "price": price,
                "volume": volume,
                "usd": usd_value,
                "position": i,
                "type": "MEGA" if usd_value >= MEGA_WHALE_THRESHOLD else "WHALE"
            })
            total_whale_buy_volume += usd_value
            
            if usd_value >= MEGA_WHALE_THRESHOLD:
                mega_whale_count += 1
    
    # ASK tahlili
    for i, (price_str, volume_str) in enumerate(asks):
        price = float(price_str)
        volume = float(volume_str)
        usd_value = price * volume
        
        if usd_value >= WHALE_ORDER_THRESHOLD:
            whale_sell_orders.append({
                "price": price,
                "volume": volume,
                "usd": usd_value,
                "position": i,
                "type": "MEGA" if usd_value >= MEGA_WHALE_THRESHOLD else "WHALE"
            })
            total_whale_sell_volume += usd_value
            
            if usd_value >= MEGA_WHALE_THRESHOLD:
                mega_whale_count += 1
    
    total_whale_volume = total_whale_buy_volume + total_whale_sell_volume
    
    if total_whale_volume > 0:
        whale_buy_pressure = (total_whale_buy_volume / total_whale_volume) * 100
        whale_sell_pressure = (total_whale_sell_volume / total_whale_volume) * 100
    else:
        whale_buy_pressure = 50
        whale_sell_pressure = 50
    
    if total_whale_sell_volume > 0:
        imbalance_ratio = total_whale_buy_volume / total_whale_sell_volume
    else:
        imbalance_ratio = 999 if total_whale_buy_volume > 0 else 1
    
    if whale_buy_pressure >= 70:
        smart_direction = "BULLISH 🟢"
    elif whale_sell_pressure >= 70:
        smart_direction = "BEARISH 🔴"
    else:
        smart_direction = "NEUTRAL ⚪"
    
    current_price = float(asks[0][0]) if asks else 0
    stats.update({
        "price": current_price,
        "whale_buy_volume": total_whale_buy_volume,
        "whale_sell_volume": total_whale_sell_volume,
        "whale_orders": len(whale_buy_orders) + len(whale_sell_orders),
        "mega_whales": mega_whale_count,
        "smart_money_direction": smart_direction
    })
    
    # Whale summary yuborish (edit bo'ladi)
    send_whale_summary(whale_buy_orders, whale_sell_orders, current_price)
    
    # Konsolga chiqarish
    print(f"\r💰 ${current_price:,.2f} | 🐋 {len(whale_buy_orders)+len(whale_sell_orders)} | "
          f"🐳 {mega_whale_count} | {smart_direction} | "
          f"🟢 {whale_buy_pressure:.0f}% 🔴 {whale_sell_pressure:.0f}%", end="", flush=True)
    
    # PREMIUM signal generatsiya
    generate_premium_signal(
        current_price, 
        whale_buy_orders, 
        whale_sell_orders,
        whale_buy_pressure,
        whale_sell_pressure,
        total_whale_volume,
        imbalance_ratio
    )

def generate_premium_signal(price, whale_buys, whale_sells, buy_pressure, sell_pressure, 
                           total_volume, imbalance):
    """PREMIUM signal generatsiya"""
    current_time = time.time()
    
    whale_buy_count = len(whale_buys)
    whale_sell_count = len(whale_sells)
    mega_whale_buys = sum(1 for w in whale_buys if w["type"] == "MEGA")
    mega_whale_sells = sum(1 for w in whale_sells if w["type"] == "MEGA")
    
    consecutive_buys = sum(1 for w in whale_buys if w["position"] < CONSECUTIVE_WHALES)
    consecutive_sells = sum(1 for w in whale_sells if w["position"] < CONSECUTIVE_WHALES)
    
    # LONG signal
    if (buy_pressure >= EXTREME_PRESSURE_THRESHOLD and
        whale_buy_count >= MIN_WHALE_ORDERS and
        total_volume >= MIN_TOTAL_WHALE_VOLUME and
        imbalance >= ORDERBOOK_IMBALANCE_MIN and
        consecutive_buys >= CONSECUTIVE_WHALES):
        
        if "LONG" not in last_signals or (current_time - last_signals["LONG"]) >= SIGNAL_COOLDOWN:
            stop_loss = price * (1 - STOP_LOSS_PERCENT / 100)
            take_profit = price * (1 + TAKE_PROFIT_PERCENT / 100)
            
            top_whales = sorted(whale_buys, key=lambda x: x["usd"], reverse=True)[:5]
            whale_levels = "\n".join([
                f"• ${w['price']:,.2f} - ${w['usd']:,.0f} ({w['type']})"
                for w in top_whales
            ])
            
            print(f"\n\n🟢🟢🟢 PREMIUM LONG SIGNAL 🟢🟢🟢")
            send_premium_signal(
                "LONG", price, stop_loss, take_profit,
                whale_buy_count, mega_whale_buys, total_volume,
                buy_pressure, imbalance, whale_levels
            )
            last_signals["LONG"] = current_time
    
    # SHORT signal
    elif (sell_pressure >= EXTREME_PRESSURE_THRESHOLD and
          whale_sell_count >= MIN_WHALE_ORDERS and
          total_volume >= MIN_TOTAL_WHALE_VOLUME and
          imbalance <= (1 / ORDERBOOK_IMBALANCE_MIN) and
          consecutive_sells >= CONSECUTIVE_WHALES):
        
        if "SHORT" not in last_signals or (current_time - last_signals["SHORT"]) >= SIGNAL_COOLDOWN:
            stop_loss = price * (1 + STOP_LOSS_PERCENT / 100)
            take_profit = price * (1 - TAKE_PROFIT_PERCENT / 100)
            
            top_whales = sorted(whale_sells, key=lambda x: x["usd"], reverse=True)[:5]
            whale_levels = "\n".join([
                f"• ${w['price']:,.2f} - ${w['usd']:,.0f} ({w['type']})"
                for w in top_whales
            ])
            
            print(f"\n\n🔴🔴🔴 PREMIUM SHORT SIGNAL 🔴🔴🔴")
            send_premium_signal(
                "SHORT", price, stop_loss, take_profit,
                whale_sell_count, mega_whale_sells, total_volume,
                sell_pressure, 1/imbalance if imbalance > 0 else 0, whale_levels
            )
            last_signals["SHORT"] = current_time

# ============================================
# WEBSOCKET
# ============================================

async def handle_websocket_message(msg):
    """WebSocket xabarlarini qayta ishlash"""
    try:
        data = json.loads(msg)
        
        if "topic" in data and "orderbook" in data["topic"]:
            if "data" in data:
                orderbook_data["bids"] = data["data"].get("b", [])
                orderbook_data["asks"] = data["data"].get("a", [])
                analyze_smart_money()
    
    except Exception as e:
        print(f"\n❌ Xato: {e}")

async def websocket_client():
    """Bybit WebSocket ulanish"""
    uri = "wss://stream.bybit.com/v5/public/linear"
    
    while True:
        try:
            print(f"\n🔌 WebSocket ulanmoqda...")
            async with websockets.connect(uri, ping_interval=20) as ws:
                print(f"✅ WebSocket ulandi!")
                
                # Status xabari
                status_msg = f"""
🤖 *SMART MONEY BOT AKTIV* ✅

📊 *SOZLAMALAR:*
• Symbol: {SYMBOL}
• Timeframe: M{TIMEFRAME_MINUTES}
• Whale: ${WHALE_ORDER_THRESHOLD:,}+
• Mega Whale: ${MEGA_WHALE_THRESHOLD:,}+
• Min Volume: ${MIN_TOTAL_WHALE_VOLUME:,}
• Pressure: {EXTREME_PRESSURE_THRESHOLD}%+

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                send_or_edit_telegram(status_msg.strip(), "status")
                
                subscribe_msg = {
                    "op": "subscribe",
                    "args": [f"orderbook.50.{SYMBOL}"]
                }
                await ws.send(json.dumps(subscribe_msg))
                print(f"📊 Tahlil boshlandi...\n")
                
                async for message in ws:
                    await handle_websocket_message(message)
        
        except websockets.exceptions.ConnectionClosed:
            print("\n⚠️ Qayta ulanish...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"\n❌ Xato: {e}")
            await asyncio.sleep(5)

# ============================================
# ASOSIY
# ============================================

async def main():
    print("=" * 70)
    print("🐳 SMART MONEY BOT - MESSAGE EDIT VERSION")
    print("=" * 70)
    print(f"📈 {SYMBOL} | M{TIMEFRAME_MINUTES}")
    print(f"🐋 Whale: ${WHALE_ORDER_THRESHOLD:,}+ | 🐳 Mega: ${MEGA_WHALE_THRESHOLD:,}+")
    print("=" * 70)
    print("\n✅ 2 ta xabar edit bo'ladi: BUY whales va SELL whales")
    print("✅ Trading signallar YANGI xabar sifatida keladi\n")
    
    await websocket_client()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⛔ Bot to'xtatildi")
    except Exception as e:
        print(f"\n❌ Xato: {e}")