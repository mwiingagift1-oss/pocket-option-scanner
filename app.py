# GHOST Protocol 3.0 - Native App UI & Core Engine

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
    import streamlit.components.v1 as components
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

FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY"
]

if STREAMLIT_AVAILABLE:
    st.set_page_config(
        page_title="GHOST Protocol 3.0",
        page_icon="🛡️",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    # Native App UI CSS Styling
    st.markdown("""
    <style>
        /* Hide Streamlit Default Branding & Header */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* App Container & Background */
        .stApp {
            background-color: #080c14;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        .block-container {
            padding: 1rem 0.75rem 3rem 0.75rem;
            max-width: 480px; /* Mobile app framing width */
        }
        
        /* Native App Header Bar */
        .app-header {
            background: linear-gradient(135deg, #111827 0%, #0f172a 100%);
            border: 1px solid #1e293b;
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .app-title {
            font-size: 1.15rem;
            font-weight: 800;
            color: #34d399;
            letter-spacing: 0.5px;
            margin: 0;
        }
        .app-subtitle {
            font-size: 0.75rem;
            color: #94a3b8;
            margin: 2px 0 0 0;
        }

        /* Native App Cards */
        .app-card {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 14px;
            padding: 14px 16px;
            margin-bottom: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        .card-label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            color: #94a3b8;
            font-weight: 700;
            margin-bottom: 4px;
        }

        /* Status Badges */
        .badge-ready {
            background: rgba(22, 163, 74, 0.2);
            border: 1px solid #16a34a;
            color: #4ade80;
            padding: 6px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 0.85rem;
            text-align: center;
        }
        .badge-caution {
            background: rgba(234, 179, 8, 0.2);
            border: 1px solid #ca8a04;
            color: #facc15;
            padding: 6px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 0.85rem;
            text-align: center;
        }
        .badge-unclear {
            background: rgba(220, 38, 38, 0.2);
            border: 1px solid #dc2626;
            color: #f87171;
            padding: 6px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 0.85rem;
            text-align: center;
        }
        .badge-wait {
            background: rgba(100, 116, 139, 0.2);
            border: 1px solid #475569;
            color: #cbd5e1;
            padding: 6px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 0.85rem;
            text-align: center;
        }

        /* Metric Grids */
        .metric-value {
            font-size: 1.4rem;
            font-weight: 800;
            color: #f8fafc;
        }
        .metric-sub {
            font-size: 0.75rem;
            color: #64748b;
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
# BUYER / SELLER STORY ENGINE
# ============================================================
def analyze_buyer_seller_story(completed):
    if completed is None or len(completed) < 3:
        return {
            "control": "NEUTRAL",
            "strength": "UNKNOWN",
            "story": "Accumulating initial candle history to assess buyer and seller behavior."
        }
    
    tail = completed.tail(5).reset_index(drop=True)
    bullish_count = sum(tail.close > tail.open)
    bearish_count = sum(tail.close < tail.open)
    
    ranges = tail.high - tail.low
    bodies = abs(tail.close - tail.open)
    avg_range = ranges.mean() if len(ranges) > 0 else 1e-12
    avg_body = bodies.mean() if len(bodies) > 0 else 1e-12
    
    recent_close_diff = tail.close.iloc[-1] - tail.close.iloc[0]
    
    overlap_count = 0
    for i in range(1, len(tail)):
        prev_h, prev_l = tail.high.iloc[i-1], tail.low.iloc[i-1]
        curr_h, curr_l = tail.high.iloc[i], tail.low.iloc[i]
        if min(prev_h, curr_h) > max(prev_l, curr_l):
            overlap_count += 1

    control = "NEUTRAL"
    strength = "MODERATE"
    
    if bullish_count >= 3 and recent_close_diff > 0:
        control = "BUYERS"
        strength = "STRONG"
        story = "Buyers maintain upward control with progressive bullish closures and strong body continuation."
    elif bearish_count >= 3 and recent_close_diff < 0:
        control = "SELLERS"
        strength = "STRONG"
        story = "Sellers maintain downward control with progressive bearish closures and downward momentum."
    elif overlap_count >= 3 and avg_body < avg_range * 0.4:
        control = "UNCHARTED / INDECISION"
        strength = "WEAK"
        story = "High candle overlap and small bodies indicate market indecision with neither buyers nor sellers asserting dominance."
    elif bullish_count > bearish_count:
        control = "BUYERS"
        strength = "MODERATE"
        story = "Buyers show moderate pressure facing intermittent selling resistance."
    elif bearish_count > bullish_count:
        control = "SELLERS"
        strength = "MODERATE"
        story = "Sellers show moderate pressure with buyers attempting occasional recoveries."
    else:
        control = "BALANCED"
        strength = "WEAK"
        story = "Buyers and sellers are balanced with alternating candle behavior."
        
    return {
        "control": control,
        "strength": strength,
        "story": story
    }

# ============================================================
# CHOPPY MARKET DETECTION
# ============================================================
def detect_choppy_market(completed):
    if completed is None or len(completed) < 5:
        return False, "Insufficient history for choppy assessment."
    
    tail = completed.tail(6).reset_index(drop=True)
    directions = (tail.close > tail.open).astype(int).tolist()
    
    alternations = sum(1 for i in range(1, len(directions)) if directions[i] != directions[i-1])
    
    overlap_count = 0
    for i in range(1, len(tail)):
        prev_h, prev_l = tail.high.iloc[i-1], tail.low.iloc[i-1]
        curr_h, curr_l = tail.high.iloc[i], tail.low.iloc[i]
        if min(prev_h, curr_h) > max(prev_l, curr_l):
            overlap_count += 1
            
    range_span = tail.high.max() - tail.low.min()
    median_body = abs(tail.close - tail.open).median()
    median_range = (tail.high - tail.low).median()
    
    is_choppy = False
    reason = "Market flow is orderly."
    
    if alternations >= 3 and overlap_count >= 2:
        is_choppy = True
        reason = "High candle alternation and extensive overlap indicate a choppy, directionless market."
    elif median_body < median_range * 0.35 and overlap_count >= 3:
        is_choppy = True
        reason = "Narrow bodies and repeated price overlap signal congestion and lack of directional commitment."
        
    return is_choppy, reason

# ============================================================
# MARKET STRUCTURE INTELLIGENCE
# ============================================================
def analyze_market_structure(completed):
    if completed is None or len(completed) < 5:
        return {
            "label": "BUILDING STRUCTURE",
            "detail": "Collecting completed candles to evaluate market structure.",
            "trend": "SIDEWAYS",
            "swing_high": 0.0,
            "swing_low": 0.0
        }
        
    tail = completed.tail(10).reset_index(drop=True)
    highs = tail.high.to_numpy()
    lows = tail.low.to_numpy()
    
    trend = "SIDEWAYS"
    label = "RANGE / SIDEWAYS MARKET"
    detail = "Price action is ranging without a strict higher-high or lower-low sequence."
    
    net_move = tail.close.iloc[-1] - tail.open.iloc[0]
    if net_move > 0 and tail.close.iloc[-1] > tail.close.iloc[0]:
        trend = "BULLISH"
        label = "BULLISH TREND STRUCTURE"
        detail = "Higher close progression confirms upward structural bias."
    elif net_move < 0 and tail.close.iloc[-1] < tail.close.iloc[0]:
        trend = "BEARISH"
        label = "BEARISH TREND STRUCTURE"
        detail = "Lower close progression confirms downward structural bias."
            
    return {
        "label": label,
        "detail": detail,
        "trend": trend,
        "swing_high": float(highs.max()),
        "swing_low": float(lows.min())
    }

# ============================================================
# SAKATA / HOMMA INSPIRED CONTEXT
# ============================================================
def analyze_sakata_homma(completed):
    if completed is None or len(completed) < 3:
        return []
    
    observations = []
    tail = completed.tail(3).reset_index(drop=True)
    closes = tail.close.values
    opens = tail.open.values
    
    if all(c > o for c, o in zip(closes, opens)):
        observations.append("Three Parallel Lines (Bullish sequence) observed.")
    elif all(c < o for c, o in zip(closes, opens)):
        observations.append("Three Parallel Lines (Bearish sequence) observed.")
        
    return observations

# ============================================================
# THREE-STEP STAIRCASE CORE ENGINE (GHOST PROTOCOL 3.0)
# ============================================================
def ghost_protocol(ticks, now=None):
    if ticks is None or ticks.empty:
        return blank_result("Waiting for tick data.", "WAIT")
        
    latest_price = float(ticks.close.iloc[-1])
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    latest_tick = pd.Timestamp(ticks.datetime.iloc[-1])
    tick_age = (now - latest_tick).total_seconds()
    
    base = {
        "signal": "WAIT",
        "state": "WAIT",
        "reason": "Scanning for Three-Step Staircase setup.",
        "price": latest_price,
        "tick_time": latest_tick,
        "tick_age": tick_age
    }
    
    if tick_age > 15 or tick_age < -5:
        return {**base, "state": "FEED CHECK", "reason": f"Deriv feed stale or misaligned ({tick_age:.1f}s)."}
        
    series = ticks.set_index("datetime")["close"].sort_index(kind="stable")
    candles = series.resample("1min").ohlc().dropna().reset_index()
    
    if len(candles) < 3:
        return {**base, "state": "WAIT", "reason": "Collecting sufficient 1-minute candle history."}
        
    current_minute = now.floor("min")
    completed = candles[candles.datetime < current_minute].reset_index(drop=True)
    if completed.empty:
        completed = candles.tail(3).reset_index(drop=True)
        
    if len(completed) < 3:
        return {**base, "state": "SETUP DEVELOPING", "reason": "Waiting for completed historical candles."}
        
    is_choppy, chop_reason = detect_choppy_market(completed)
    buyer_seller = analyze_buyer_seller_story(completed)
    market_structure = analyze_market_structure(completed)
    sakata_obs = analyze_sakata_homma(completed)
    
    base.update({
        "buyer_seller": buyer_seller,
        "market_structure": market_structure,
        "sakata_observations": sakata_obs,
        "is_choppy": is_choppy,
        "chop_reason": chop_reason
    })
    
    if is_choppy:
        return {
            **base,
            "signal": "WAIT",
            "state": "MARKET UNCLEAR",
            "reason": f"Market is choppy: {chop_reason}. No signals generated."
        }
        
    def identify_c1(c1_candle, prev_candle):
        o, h, l, c = float(c1_candle.open), float(c1_candle.high), float(c1_candle.low), float(c1_candle.close)
        po, ph, pl, pc = float(prev_candle.open), float(prev_candle.high), float(prev_candle.low), float(prev_candle.close)
        
        rng = max(h - l, 1e-12)
        upper_w = h - max(o, c)
        lower_w = min(o, c) - l
        pos = (c - l) / rng
        
        bull_rej = lower_w >= max(upper_w * 1.25, rng * 0.25) and pos >= 0.55
        bear_rej = upper_w >= max(lower_w * 1.25, rng * 0.25) and pos <= 0.45
        
        if bull_rej:
            return "CALL", "SUPPORT REJECTION"
        if bear_rej:
            return "PUT", "RESISTANCE REJECTION"
        if c > ph:
            return "CALL", "BULLISH BREAKOUT"
        if c < pl:
            return "PUT", "BEARISH BREAKOUT"
        if c > pc:
            return "CALL", "BULLISH DIRECTIONAL STEP"
        if c < pc:
            return "PUT", "BEARISH DIRECTIONAL STEP"
        return None, "NO CLEAR PATTERN"

    if len(completed) >= 3:
        c1 = completed.iloc[-2]
        c2 = completed.iloc[-1]
        prev_c1 = completed.iloc[-3]
        
        direction, pattern = identify_c1(c1, prev_c1)
        if direction:
            c1_close = float(c1.close)
            c2_close = float(c2.close)
            
            c2_confirmed = (c2_close > c1_close) if direction == "CALL" else (c2_close < c1_close)
            price_valid = (latest_price > c1_close) if direction == "CALL" else (latest_price < c1_close)
            
            if not c2_confirmed:
                return {
                    **base,
                    "signal": "WAIT",
                    "state": "INVALIDATED",
                    "reason": f"C2 closed at {fmt_price(c2_close)}, failing to close beyond C1 close ({fmt_price(c1_close)}). Setup invalidated.",
                    "entry_point": c1_close,
                    "pattern": pattern
                }
                
            if not price_valid:
                return {
                    **base,
                    "signal": "WAIT",
                    "state": "INVALIDATED",
                    "reason": f"Price crossed back through C1 close reference ({fmt_price(c1_close)}). Setup invalidated.",
                    "entry_point": c1_close,
                    "pattern": pattern
                }
                
            warnings = []
            if market_structure["trend"] == "BEARISH" and direction == "CALL":
                warnings.append("Counter-trend warning: Taking a CALL in a Bearish trend structure.")
            elif market_structure["trend"] == "BULLISH" and direction == "PUT":
                warnings.append("Counter-trend warning: Taking a PUT in a Bullish trend structure.")
                
            state = "CAUTION" if warnings else "ENTRY READY"
            
            return {
                **base,
                "signal": direction,
                "state": state,
                "reason": f"Three-Step Staircase confirmed ({pattern}). C2 closed beyond C1 close ({fmt_price(c1_close)}). Price valid at {fmt_price(latest_price)}.",
                "warnings": warnings,
                "entry_point": c1_close,
                "pattern": pattern
            }

    return {
        **base,
        "signal": "WAIT",
        "state": "SETUP DEVELOPING",
        "reason": "Analyzing candle formation for Three-Step Staircase setup."
    }

# ============================================================
# DERIV CLIENT & DATA FETCHING
# ============================================================
class DerivClient:
    def __init__(self, timeout=20):
        if not WEBSOCKET_AVAILABLE:
            raise RuntimeError("websocket-client not installed.")
        self.timeout = timeout
        self.ws = None
        self.req_id = 0
        self.connect()

    def connect(self):
        self.close()
        try:
            self.ws = websocket.create_connection(DERIV_PUBLIC_WS, timeout=self.timeout)
            self.ws.settimeout(self.timeout)
        except Exception as exc:
            raise RuntimeError(f"Could not connect to Deriv: {exc}")

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None

    def request(self, payload):
        if self.ws is None:
            self.connect()
        self.req_id += 1
        request = dict(payload)
        request["req_id"] = self.req_id
        self.ws.send(json.dumps(request))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            raw = self.ws.recv()
            if not raw:
                continue
            message = json.loads(raw)
            if message.get("error"):
                raise RuntimeError(message["error"].get("message", "Deriv API error"))
            if message.get("req_id") == self.req_id:
                return message
        raise TimeoutError("Deriv did not respond before timeout.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

def fetch_deriv_ticks(symbol, count=1000, client=None):
    if client is None:
        if not WEBSOCKET_AVAILABLE:
            raise RuntimeError("WebSocket unavailable.")
        with DerivClient(timeout=25) as temp:
            return fetch_deriv_ticks(symbol, count, temp)
    data = client.request({
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "style": "ticks"
    })
    history = data.get("history", {})
    prices = history.get("prices", [])
    times = history.get("times", [])
    if not prices or not times or len(prices) != len(times):
        raise RuntimeError("Deriv returned insufficient tick history.")
    df = pd.DataFrame({
        "datetime": pd.to_datetime(times, unit="s", utc=True),
        "close": pd.to_numeric(prices, errors="coerce")
    })
    return df.dropna(subset=["datetime", "close"]).sort_values("datetime", kind="stable").reset_index(drop=True)

# ============================================================
# STREAMLIT NATIVE APP UI
# ============================================================
def main():
    if not STREAMLIT_AVAILABLE:
        print("Streamlit required.")
        return

    # App Header Bar (Native Look)
    st.markdown(f"""
    <div class="app-header">
        <div>
            <p class="app-title">🛡️ GHOST PROTOCOL 3.0</p>
            <p class="app-subtitle">Volatility 100 (1s) • Native Terminal</p>
        </div>
        <div style="text-align: right;">
            <span style="font-size:0.7rem; color:#34d399; background:rgba(52,211,153,0.1); padding:4px 8px; border-radius:10px; border:1px solid rgba(52,211,153,0.3);">🟢 LIVE FEED</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Fetch Data
    ticks = None
    try:
        ticks = fetch_deriv_ticks(GHOST_SYMBOL, count=800)
    except Exception as e:
        st.error(f"Connection Error: {e}")

    analysis = ghost_protocol(ticks)
    state = analysis.get("state", "WAIT")
    signal = analysis.get("signal", "WAIT")
    price = analysis.get("price", 0)

    # Status Badge
    badge_class = "badge-wait"
    if state == "ENTRY READY":
        badge_class = "badge-ready"
    elif state == "CAUTION":
        badge_class = "badge-caution"
    elif state == "MARKET UNCLEAR" or state == "INVALIDATED":
        badge_class = "badge-unclear"

    # App Summary Card
    st.markdown(f"""
    <div class="app-card" style="text-align: center; padding: 18px;">
        <div class="card-label">Decision State & Action</div>
        <div style="margin: 8px 0;">
            <span class="{badge_class}">{state} ({signal})</span>
        </div>
        <div style="font-size: 1.8rem; font-weight: 800; color: #f8fafc; margin-top: 8px;">
            {fmt_price(price)}
        </div>
        <div class="card-label" style="margin-top: 4px;">Live Market Price</div>
    </div>
    """, unsafe_allow_html=True)

    # Mini Metrics Row
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""
        <div class="app-card">
            <div class="card-label">Entry Reference</div>
            <div class="metric-value">{fmt_price(analysis.get('entry_point', 0))}</div>
            <div class="metric-sub">C1 Close Level</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="app-card">
            <div class="card-label">Pattern Found</div>
            <div style="font-size:0.95rem; font-weight:700; color:#38bdf8; margin-top:4px;">
                {analysis.get('pattern', 'Scanning...')}
            </div>
            <div class="metric-sub">Three-Step Setup</div>
        </div>
        """, unsafe_allow_html=True)

    # Reason & Logic Card
    st.markdown(f"""
    <div class="app-card">
        <div class="card-label">Execution Logic & Reason</div>
        <p style="font-size: 0.88rem; color: #cbd5e1; margin: 6px 0 0 0; line-height: 1.4;">
            {analysis.get('reason', 'Awaiting market confirmation.')}
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Buyer/Seller Story Card
    bs = analysis.get("buyer_seller", {})
    st.markdown(f"""
    <div class="app-card">
        <div class="card-label">🧠 Buyer / Seller Behaviour Story</div>
        <p style="font-size: 0.88rem; font-weight: 700; color: #34d399; margin: 4px 0;">
            Control: {bs.get('control', 'Analyzing...')}
        </p>
        <p style="font-size: 0.82rem; color: #94a3b8; margin: 0; line-height: 1.3;">
            {bs.get('story', '')}
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Market Structure Card
    ms = analysis.get("market_structure", {})
    st.markdown(f"""
    <div class="app-card">
        <div class="card-label">🏗️ Market Structure & Trend</div>
        <p style="font-size: 0.88rem; font-weight: 700; color: #38bdf8; margin: 4px 0;">
            Bias: {ms.get('trend', 'SIDEWAYS')}
        </p>
        <p style="font-size: 0.82rem; color: #94a3b8; margin: 0; line-height: 1.3;">
            {ms.get('detail', '')}
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Live Chart Preview (Clean Native Style)
    st.markdown("""
    <div class="app-card">
        <div class="card-label" style="margin-bottom: 8px;">Live Price Chart (Volatility 100 1s)</div>
    </div>
    """, unsafe_allow_html=True)

    if ticks is not None and not ticks.empty:
        fig = go.Figure(go.Scatter(
            x=ticks["datetime"].tail(80), 
            y=ticks["close"].tail(80), 
            mode="lines", 
            line=dict(color="#34d399", width=2.5)
        ))
        fig.update_layout(
            height=200, 
            margin=dict(l=0, r=0, t=0, b=0), 
            paper_bgcolor="#111827", 
            plot_bgcolor="#111827", 
            font=dict(color="#94a3b8", size=10),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="#1f2937", zeroline=False)
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.write("Awaiting tick feed...")

if __name__ == "__main__":
    main()
