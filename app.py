# GHOST Protocol 3.0 - Desktop Trading Terminal UI (Unscrollable, Candlestick Chart, Split Layout)

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

    # Unscrollable Desktop Terminal CSS Styling
    st.markdown("""
    <style>
        /* Hide Streamlit Chrome */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* Lock body scroll and fit exact screen */
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #06090f;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            overflow: hidden !important;
            height: 100vh;
        }
        
        .block-container {
            padding: 0.5rem 1rem !important;
            max-width: 100% !important;
            height: 100vh;
            overflow: hidden !important;
            display: flex;
            flex-direction: column;
        }

        /* Terminal Header Bar */
        .term-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 8px 16px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .term-title {
            font-size: 1rem;
            font-weight: 800;
            color: #34d399;
            margin: 0;
            letter-spacing: 0.5px;
        }
        .term-sub {
            font-size: 0.7rem;
            color: #94a3b8;
            margin: 0;
        }

        /* Terminal Cards */
        .term-card {
            background: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 8px;
            padding: 10px 12px;
            margin-bottom: 6px;
        }
        .card-label {
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #94a3b8;
            font-weight: 700;
            margin-bottom: 2px;
        }

        /* Status Badges */
        .badge-ready {
            background: rgba(22, 163, 74, 0.25);
            border: 1px solid #16a34a;
            color: #4ade80;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.75rem;
        }
        .badge-caution {
            background: rgba(234, 179, 8, 0.25);
            border: 1px solid #ca8a04;
            color: #facc15;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.75rem;
        }
        .badge-unclear {
            background: rgba(220, 38, 38, 0.25);
            border: 1px solid #dc2626;
            color: #f87171;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.75rem;
        }
        .badge-wait {
            background: rgba(100, 116, 139, 0.25);
            border: 1px solid #475569;
            color: #cbd5e1;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.75rem;
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
    return f"{number:.5f}" if abs(number) < 100 else f"{number:.3f}"

def blank_result(reason, state="WAIT"):
    return {
        "signal": "WAIT",
        "state": state,
        "reason": reason
    }

# ============================================================
# ANALYSIS ENGINES
# ============================================================
def analyze_buyer_seller_story(completed):
    if completed is None or len(completed) < 3:
        return {"control": "NEUTRAL", "story": "Accumulating initial candles."}
    tail = completed.tail(5).reset_index(drop=True)
    bullish = sum(tail.close > tail.open)
    bearish = sum(tail.close < tail.open)
    if bullish >= 3:
        return {"control": "BUYERS", "story": "Buyers maintain progressive upward control."}
    elif bearish >= 3:
        return {"control": "SELLERS", "story": "Sellers maintain downward momentum."}
    return {"control": "BALANCED", "story": "Buyers and sellers balanced with alternating behaviour."}

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

def ghost_protocol(ticks, now=None):
    if ticks is None or ticks.empty:
        return blank_result("Waiting for tick data.", "WAIT")
        
    latest_price = float(ticks.close.iloc[-1])
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    latest_tick = pd.Timestamp(ticks.datetime.iloc[-1])
    tick_age = (now - latest_tick).total_seconds()
    
    base = {"signal": "WAIT", "state": "WAIT", "reason": "Scanning setup.", "price": latest_price}
    if tick_age > 15 or tick_age < -5:
        return {**base, "state": "FEED CHECK", "reason": f"Feed stale ({tick_age:.1f}s)."}
        
    series = ticks.set_index("datetime")["close"].sort_index(kind="stable")
    candles = series.resample("1min").ohlc().dropna().reset_index()
    if len(candles) < 3:
        return {**base, "state": "WAIT", "reason": "Collecting 1-min history."}
        
    current_minute = now.floor("min")
    completed = candles[candles.datetime < current_minute].reset_index(drop=True)
    if completed.empty:
        completed = candles.tail(3).reset_index(drop=True)
        
    is_choppy, chop_reason = detect_choppy_market(completed)
    bs = analyze_buyer_seller_story(completed)
    ms = analyze_market_structure(completed)
    
    base.update({"buyer_seller": bs, "market_structure": ms, "is_choppy": is_choppy})
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
            
            if not c2_confirmed or not price_valid:
                return {**base, "signal": "WAIT", "state": "INVALIDATED", "reason": "C2 close or C3 price validation failed.", "entry_point": c1_close, "pattern": "Staircase Step"}
                
            return {
                **base,
                "signal": direction,
                "state": "ENTRY READY",
                "reason": f"Staircase confirmed ({direction}). C2 closed beyond C1 close.",
                "entry_point": c1_close,
                "pattern": "Three-Step Staircase"
            }
            
    return {**base, "state": "SETUP DEVELOPING", "reason": "Analyzing staircase formation."}

# ============================================================
# DERIV CLIENT & DATA
# ============================================================
class DerivClient:
    def __init__(self, timeout=20):
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

# ============================================================
# DESKTOP TERMINAL LAYOUT (SPLIT SCREEN: CHART LEFT, SIGNAL PAD RIGHT)
# ============================================================
def main():
    if not STREAMLIT_AVAILABLE:
        return

    # Header
    st.markdown("""
    <div class="term-header">
        <div>
            <h1 class="term-title">🛡️ GHOST PROTOCOL 3.0 • TERMINAL</h1>
            <p class="term-sub">Volatility 100 (1s) Index • Unscrollable Desktop Edition</p>
        </div>
        <div>
            <span style="font-size:0.7rem; color:#34d399; background:rgba(52,211,153,0.1); padding:4px 10px; border-radius:10px; border:1px solid rgba(52,211,153,0.3);">🟢 LIVE STREAM</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    ticks = fetch_deriv_ticks(GHOST_SYMBOL, count=800)
    analysis = ghost_protocol(ticks)
    state = analysis.get("state", "WAIT")
    signal = analysis.get("signal", "WAIT")

    # Resample ticks into 1-minute OHLC candles for the original candlestick chart
    if not ticks.empty:
        candles = ticks.set_index("datetime")["close"].resample("1min").ohlc().dropna().tail(30).reset_index()
    else:
        candles = pd.DataFrame(columns=["datetime", "open", "high", "low", "close"])

    # Split Screen: Left = Live Candlestick Chart, Right = Signal Pad & Intelligence
    left_col, right_col = st.columns([1.6, 1])

    with left_col:
        st.markdown('<div class="term-card">', unsafe_allow_html=True)
        st.markdown('<div class="card-label">Live 1-Minute Candlestick Chart</div>', unsafe_allow_html=True)
        
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
                height=410,
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
        # Signal Pad Card
        badge_class = "badge-wait"
        if state == "ENTRY READY":
            badge_class = "badge-ready"
        elif state == "CAUTION":
            badge_class = "badge-caution"
        elif state == "MARKET UNCLEAR" or state == "INVALIDATED":
            badge_class = "badge-unclear"

        st.markdown(f"""
        <div class="term-card" style="text-align: center; padding: 12px;">
            <div class="card-label">Signal Pad & Decision State</div>
            <div style="margin: 6px 0;">
                <span class="{badge_class}">{state} ({signal})</span>
            </div>
            <div style="font-size: 1.5rem; font-weight: 800; color: #f8fafc; margin-top: 4px;">
                {fmt_price(analysis.get('price', 0))}
            </div>
            <div class="card-label">Live Price</div>
        </div>
        """, unsafe_allow_html=True)

        # Execution Logic & Reference
        st.markdown(f"""
        <div class="term-card">
            <div class="card-label">Execution Details</div>
            <div style="font-size: 0.78rem; color: #cbd5e1; margin-top: 2px;">
                <b>Reference (C1):</b> {fmt_price(analysis.get('entry_point', 0))}<br>
                <b>Pattern:</b> {analysis.get('pattern', 'Scanning...')}<br>
                <b>Reason:</b> {analysis.get('reason', '')}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Buyer / Seller Story Card
        bs = analysis.get("buyer_seller", {})
        st.markdown(f"""
        <div class="term-card">
            <div class="card-label">🧠 Buyer / Seller Story</div>
            <div style="font-size: 0.78rem; color: #34d399; font-weight: 700; margin-top: 2px;">
                Control: {bs.get('control', 'Analyzing...')}
            </div>
            <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 2px;">
                {bs.get('story', '')}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Market Structure Card
        ms = analysis.get("market_structure", {})
        st.markdown(f"""
        <div class="term-card">
            <div class="card-label">🏗️ Market Structure</div>
            <div style="font-size: 0.78rem; color: #38bdf8; font-weight: 700; margin-top: 2px;">
                Bias: {ms.get('trend', 'SIDEWAYS')}
            </div>
            <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 2px;">
                {ms.get('detail', '')}
            </div>
        </div>
        """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
