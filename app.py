# GHOST Protocol 3.0 - Desktop Trading Terminal UI (Fixed Timezone & Correct Entry/Expiry Window)

import os
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests

try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    websocket = None
    WEBSOCKET_AVAILABLE = False

TZ = ZoneInfo("Africa/Lusaka")
DERIV_PUBLIC_WS = "wss://api.derivws.com/trading/v1/options/ws/public"
GHOST_SYMBOL = "1HZ100V"
GHOST_NAME = "Volatility 100 (1s) Index"

if STREAMLIT_AVAILABLE:
    st.set_page_config(
        page_title="GHOST Protocol 3.0 Terminal",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

    st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #06090f;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            overflow: hidden !important;
            height: 100vh;
        }
        
        .block-container {
            padding: 0.4rem 0.8rem !important;
            max-width: 100% !important;
            height: 100vh;
            overflow: hidden !important;
            display: flex;
            flex-direction: column;
        }

        .term-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 6px 14px;
            margin-bottom: 5px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .term-title {
            font-size: 0.95rem;
            font-weight: 800;
            color: #34d399;
            margin: 0;
            letter-spacing: 0.5px;
        }
        
        .live-clock-pad {
            font-family: monospace;
            font-size: 1.15rem;
            font-weight: 800;
            color: #34d399;
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid #334155;
            padding: 4px 14px;
            border-radius: 8px;
            box-shadow: 0 0 10px rgba(52, 211, 153, 0.2);
        }

        .term-card {
            background: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 8px;
            padding: 8px 10px;
            margin-bottom: 5px;
        }
        .card-label {
            font-size: 0.62rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #94a3b8;
            font-weight: 700;
            margin-bottom: 2px;
        }

        .big-time-pad {
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 8px 10px;
            text-align: center;
        }
        .big-time-val {
            font-size: 1.35rem;
            font-weight: 800;
            font-family: monospace;
            margin: 2px 0;
        }
        .big-time-lbl {
            font-size: 0.62rem;
            font-weight: 700;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }

        .badge-ready {
            background: rgba(22, 163, 74, 0.25);
            border: 1px solid #16a34a;
            color: #4ade80;
            padding: 4px 10px;
            border-radius: 10px;
            font-weight: 800;
            font-size: 0.8rem;
        }
        .badge-caution {
            background: rgba(234, 179, 8, 0.25);
            border: 1px solid #ca8a04;
            color: #facc15;
            padding: 4px 10px;
            border-radius: 10px;
            font-weight: 800;
            font-size: 0.8rem;
        }
        .badge-unclear {
            background: rgba(220, 38, 38, 0.25);
            border: 1px solid #dc2626;
            color: #f87171;
            padding: 4px 10px;
            border-radius: 10px;
            font-weight: 800;
            font-size: 0.8rem;
        }
        .badge-wait {
            background: rgba(100, 116, 139, 0.25);
            border: 1px solid #475569;
            color: #cbd5e1;
            padding: 4px 10px;
            border-radius: 10px;
            font-weight: 800;
            font-size: 0.8rem;
        }
    </style>
    """, unsafe_allow_html=True)

def fmt_price(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if not pd.notna(number):
        return "Unavailable"
    return f"{number:.2f}" if abs(number) < 1000 else f"{number:.2f}"

def blank_result(reason, state="WAIT"):
    return {
        "signal": "WAIT",
        "state": state,
        "reason": reason
    }

def analyze_buyer_seller_story(completed):
    if completed is None or len(completed) < 3:
        return {"control": "NEUTRAL", "story": "Accumulating candles."}
    tail = completed.tail(5).reset_index(drop=True)
    bullish = sum(tail.close > tail.open)
    bearish = sum(tail.close < tail.open)
    if bullish >= 3:
        return {"control": "BUYERS", "story": "Buyers maintain upward control."}
    elif bearish >= 3:
        return {"control": "SELLERS", "story": "Sellers maintain downward momentum."}
    return {"control": "BALANCED", "story": "Buyers and sellers balanced."}

def detect_choppy_market(completed):
    if completed is None or len(completed) < 5:
        return False, "Orderly."
    tail = completed.tail(6).reset_index(drop=True)
    dirs = (tail.close > tail.open).astype(int).tolist()
    alt = sum(1 for i in range(1, len(dirs)) if dirs[i] != dirs[i-1])
    if alt >= 3:
        return True, "High candle alternation detected (choppy)."
    return False, "Orderly."

def analyze_market_structure(completed):
    if completed is None or len(completed) < 5:
        return {"trend": "SIDEWAYS", "detail": "Building structure."}
    net = completed.close.iloc[-1] - completed.open.iloc[0]
    if net > 0:
        return {"trend": "BULLISH", "detail": "Higher close sequence active."}
    elif net < 0:
        return {"trend": "BEARISH", "detail": "Lower close sequence active."}
    return {"trend": "SIDEWAYS", "detail": "Ranging market structure."}

def ghost_protocol(ticks, now_cat=None):
    if ticks is None or ticks.empty:
        return blank_result("Waiting for tick data.", "WAIT")
        
    latest_price = float(ticks.close.iloc[-1])
    if now_cat is None:
        now_cat = datetime.now(TZ)
        
    latest_tick = pd.Timestamp(ticks.datetime.iloc[-1])
    latest_tick_cat = latest_tick.tz_convert(TZ) if latest_tick.tzinfo else latest_tick.tz_localize("UTC").tz_convert(TZ)
    tick_age = (now_cat - latest_tick_cat).total_seconds()
    
    base = {"signal": "WAIT", "state": "WAIT", "reason": "Scanning setup.", "price": latest_price}
    if tick_age > 35 or tick_age < -15:
        return {**base, "state": "FEED CHECK", "reason": f"Feed stale ({tick_age:.1f}s)."}
        
    ticks_cat = ticks.copy()
    ticks_cat["datetime"] = ticks_cat["datetime"].dt.tz_convert(TZ) if ticks_cat["datetime"].dt.tz else ticks_cat["datetime"].dt.tz_localize("UTC").dt.tz_convert(TZ)
    
    series = ticks_cat.set_index("datetime")["close"].sort_index(kind="stable")
    candles = series.resample("1min").ohlc().dropna().reset_index()
    if len(candles) < 3:
        return {**base, "state": "WAIT", "reason": "Collecting 1-min history."}
        
    current_minute = now_cat.replace(second=0, microsecond=0)
    completed = candles[candles.datetime < current_minute].reset_index(drop=True)
    if completed.empty:
        completed = candles.tail(3).reset_index(drop=True)
        
    is_choppy, chop_reason = detect_choppy_market(completed)
    bs = analyze_buyer_seller_story(completed)
    ms = analyze_market_structure(completed)
    
    base.update({"buyer_seller": bs, "market_structure": ms, "is_choppy": is_choppy})
    
    next_minute = current_minute + timedelta(minutes=1)
    expiry_target = next_minute + timedelta(minutes=1)
    prep_seconds = max(0, int(60 - now_cat.second))

    base.update({
        "entry_time": next_minute.strftime("%H:%M:%S"),
        "expiry_time": expiry_target.strftime("%H:%M:%S"),
        "prep_countdown": prep_seconds
    })

    if is_choppy:
        return {**base, "signal": "WAIT", "state": "MARKET UNCLEAR", "reason": chop_reason}
        
    if len(completed) >= 3:
        c1 = completed.iloc[-2]
        c2 = completed.iloc[-1]
        prev_c1 = completed.iloc[-3]
        
        o, h, l, c = float(c1.open), float(c1.high), float(c1.low), float(c1.close)
        pc = float(prev_c1.close)
        
        direction = "CALL" if c > pc else "PUT" if c < pc else None
        if direction:
            c1_close = float(c1.close)
            c2_close = float(c2.close)
            c2_confirmed = (c2_close > c1_close) if direction == "CALL" else (c2_close < c1_close)
            price_valid = (latest_price > c1_close) if direction == "CALL" else (latest_price < c1_close)
            
            c1_time = pd.Timestamp(c1.datetime)
            signal_entry = c1_time + timedelta(minutes=2)
            signal_expiry = signal_entry + timedelta(minutes=1)
            
            base.update({
                "entry_time": signal_entry.strftime("%H:%M:%S"),
                "expiry_time": signal_expiry.strftime("%H:%M:%S"),
            })

            if not c2_confirmed or not price_valid:
                return {
                    **base, 
                    "signal": "WAIT", 
                    "state": "INVALIDATED", 
                    "reason": "C2 close or C3 price validation failed.", 
                    "entry_point": c1_close, 
                    "pattern": "Staircase Step"
                }
                
            return {
                **base,
                "signal": direction,
                "state": "ENTRY READY",
                "reason": f"Staircase confirmed ({direction}). C2 closed beyond C1 close.",
                "entry_point": c1_close,
                "pattern": "Three-Step Staircase"
            }
            
    return {
        **base, 
        "state": "SETUP DEVELOPING", 
        "reason": "Analyzing staircase formation (C1, C2, C3 active)."
    }

class DerivClient:
    def __init__(self, timeout=8):
        if not WEBSOCKET_AVAILABLE:
            raise RuntimeError("websocket-client not installed.")
        self.timeout = timeout
        self.ws = websocket.create_connection(DERIV_PUBLIC_WS, timeout=self.timeout)
        self.ws.settimeout(self.timeout)
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.ws.close()
        except:
            pass

def fetch_deriv_ticks(symbol, count=1000):
    if not WEBSOCKET_AVAILABLE:
        return pd.DataFrame(columns=["datetime", "close"])
    try:
        with DerivClient() as client:
            req = {"ticks_history": symbol, "adjust_start_time": 1, "count": count, "end": "latest", "style": "ticks"}
            client.ws.send(json.dumps(req))
            raw = client.ws.recv()
            data = json.loads(raw)
            history = data.get("history", {})
            prices = history.get("prices", [])
            times = history.get("times", [])
            df = pd.DataFrame({
                "datetime": pd.to_datetime(times, unit="s", utc=True),
                "close": pd.to_numeric(prices, errors="coerce")
            })
            return df.dropna().sort_values("datetime", kind="stable").reset_index(drop=True)
    except:
        return pd.DataFrame(columns=["datetime", "close"])

def main():
    if not STREAMLIT_AVAILABLE:
        return

    now_cat = datetime.now(TZ)
    
    st.markdown(f"""
    <div class="term-header">
        <div>
            <h1 class="term-title">🛡️ GHOST PROTOCOL 3.0 • TERMINAL</h1>
            <span style="font-size:0.68rem; color:#94a3b8;">Volatility 100 (1s) Index • CAT Timezone Synchronized</span>
        </div>
        <div style="display:flex; align-items:center; gap:10px;">
            <div id="liveClock" class="live-clock-pad">⏱️ {now_cat.strftime('%H:%M:%S')} CAT</div>
        </div>
    </div>
    <script>
        function updateClock() {
            const now = new Date();
            const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
            const cat = new Date(utc + (3600000 * 2));
            const hours = String(cat.getHours()).padStart(2, '0');
            const minutes = String(cat.getMinutes()).padStart(2, '0');
            const seconds = String(cat.getSeconds()).padStart(2, '0');
            const clockEl = document.getElementById('liveClock');
            if (clockEl) {
                clockEl.innerHTML = `⏱️ ${hours}:${minutes}:${seconds} CAT`;
            }
        }
        setInterval(updateClock, 1000);
    </script>
    """, unsafe_allow_html=True)

    ticks = fetch_deriv_ticks(GHOST_SYMBOL, count=800)
    analysis = ghost_protocol(ticks, now_cat=now_cat)
    state = analysis.get("state", "WAIT")
    signal = analysis.get("signal", "WAIT")

    if not ticks.empty:
        ticks_cat = ticks.copy()
        ticks_cat["datetime"] = ticks_cat["datetime"].dt.tz_convert(TZ) if ticks_cat["datetime"].dt.tz else ticks_cat["datetime"].dt.tz_localize("UTC").dt.tz_convert(TZ)
        candles = ticks_cat.set_index("datetime")["close"].resample("1min").ohlc().dropna().tail(30).reset_index()
    else:
        candles = pd.DataFrame(columns=["datetime", "open", "high", "low", "close"])

    left_col, right_col = st.columns([1.55, 1])

    with left_col:
        st.markdown('<div class="term-card">', unsafe_allow_html=True)
        st.markdown('<div class="card-label">Live 1-Minute Candlestick Chart (CAT Time)</div>', unsafe_allow_html=True)
        
        if not candles.empty:
            fig = go.Figure(data=[go.Candlestick(
                x=candles['datetime'],
                open=candles['open'],
                high=candles['high'],
                low=candles['low'],
                close=candles['close'],
                increasing_line_color='#34d399',
                decreasing_line_color='#ef4444'
            )])
            fig.update_layout(
                height=385,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="#0f172a",
                plot_bgcolor="#0f172a",
                font=dict(color="#94a3b8", size=10),
                xaxis=dict(showgrid=False, zeroline=False),
                yaxis=dict(showgrid=True, gridcolor="#1e293b", zeroline=False),
                xaxis_rangeslider_visible=False
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Awaiting tick feed for candlestick construction...")
        st.markdown('</div>', unsafe_allow_html=True)

    with right_col:
        badge_class = "badge-wait"
        if state == "ENTRY READY":
            badge_class = "badge-ready"
        elif state == "CAUTION":
            badge_class = "badge-caution"
        elif state == "MARKET UNCLEAR" or state == "INVALIDATED":
            badge_class = "badge-unclear"

        st.markdown(f"""
        <div class="term-card" style="text-align: center; padding: 8px;">
            <div class="card-label">Signal Pad & Decision State</div>
            <div style="margin: 3px 0;">
                <span class="{badge_class}">{state} ({signal})</span>
            </div>
            <div style="font-size: 1.4rem; font-weight: 800; color: #f8fafc; margin-top: 2px;">
                {fmt_price(analysis.get('price', 0))}
            </div>
        </div>
        """, unsafe_allow_html=True)

        prep_sec = analysis.get('prep_countdown', 0)
        t_col1, t_col2, t_col3 = st.columns(3)
        
        with t_col1:
            st.markdown(f"""
            <div class="big-time-pad">
                <div class="big-time-lbl">Entry Time</div>
                <div class="big-time-val" style="color: #38bdf8;">{analysis.get('entry_time', '--:--:--')}</div>
            </div>
            """, unsafe_allow_html=True)
            
        with t_col2:
            st.markdown(f"""
            <div class="big-time-pad">
                <div class="big-time-lbl">Expiry Time</div>
                <div class="big-time-val" style="color: #f43f5e;">{analysis.get('expiry_time', '--:--:--')}</div>
            </div>
            """, unsafe_allow_html=True)

        with t_col3:
            st.markdown(f"""
            <div class="big-time-pad" style="border-color: #34d399;">
                <div class="big-time-lbl" style="color: #34d399;">Prep Time</div>
                <div class="big-time-val" style="color: #34d399;">{prep_sec}s</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown(f"""
        <div class="term-card" style="margin-top: 4px;">
            <div style="font-size: 0.72rem; color: #cbd5e1; line-height: 1.3;">
                <b>C1 Ref Close:</b> {fmt_price(analysis.get('entry_point', 0))} | <b>Pattern:</b> {analysis.get('pattern', 'Scanning Three-Step...')}<br>
                <b>Reason:</b> {analysis.get('reason', '')}
            </div>
        </div>
        """, unsafe_allow_html=True)

        bs = analysis.get("buyer_seller", {})
        st.markdown(f"""
        <div class="term-card">
            <div class="card-label">🧠 Buyer / Seller Story (Active Engine)</div>
            <div style="font-size: 0.75rem; color: #34d399; font-weight: 700;">
                Control: {bs.get('control', 'Analyzing...')}
            </div>
            <div style="font-size: 0.7rem; color: #94a3b8;">
                {bs.get('story', '')}
            </div>
        </div>
        """, unsafe_allow_html=True)

    time.sleep(3)
    st.rerun()

if __name__ == "__main__":
    main()
