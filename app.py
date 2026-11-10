# GHOST Protocol 3.0 Core Engine & Streamlit Dashboard

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
        page_icon="📈",
        layout="wide"
    )

    st.markdown("""
    <style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        max-width: 1450px;
    }
    [data-testid="stMetric"] {
        background: #111827;
        padding: 14px;
        border-radius: 12px;
        border: 1px solid #263244;
    }
    .signal-card {
        padding: 18px 20px;
        border-radius: 14px;
        background: #111827;
        border: 1px solid #334155;
        margin: 8px 0;
    }
    .signal-call { border-left: 6px solid #16a34a; }
    .signal-put { border-left: 6px solid #dc2626; }
    .signal-wait { border-left: 6px solid #64748b; }
    .small-muted {
        color: #94a3b8;
        font-size: 0.86rem;
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
    elif bearish_count > bearish_count:
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
# STREAMLIT DASHBOARD UI
# ============================================================
def main():
    if not STREAMLIT_AVAILABLE:
        print("Streamlit is required to run the dashboard.")
        return

    st.title("🛡️ GHOST PROTOCOL 3.0 — MARKET SIGNAL DESK")
    st.caption("Three-Step Staircase Engine • Buyer/Seller Story • Market Structure • Sakata Context")

    with st.sidebar:
        st.header("Control Panel")
        market_mode = st.selectbox("Market Feed", [GHOST_NAME, "Forex Engine (Twelve Data)"])
        refresh_rate = st.slider("Auto-Refresh (seconds)", 2, 30, 5)
        st.markdown("---")
        st.markdown("### Decision States")
        st.markdown("- `ENTRY READY` (Active Signal)\n- `CAUTION` (Risk Warnings)\n- `MARKET UNCLEAR` (Choppy)\n- `INVALIDATED` (Broken Setup)")

    # Data fetching & analysis
    ticks = None
    connection_status = "DISCONNECTED"
    
    if market_mode == GHOST_NAME:
        try:
            ticks = fetch_deriv_ticks(GHOST_SYMBOL, count=1200)
            connection_status = "CONNECTED (DERIV WS)"
        except Exception as e:
            st.error(f"Deriv Connection Error: {e}")
            connection_status = "FEED ERROR"
    else:
        st.info("Forex engine selected. Enter Twelve Data API key if querying live currency pairs.")
        # Fallback empty or mock dataframe if key is missing
        ticks = pd.DataFrame(columns=["datetime", "close"])

    analysis = ghost_protocol(ticks)

    # Top Metrics Bar
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Connection", connection_status)
    with col2:
        st.metric("Latest Price", fmt_price(analysis.get("price", 0)))
    with col3:
        st.metric("Decision State", analysis.get("state", "WAIT"))
    with col4:
        st.metric("Signal Action", analysis.get("signal", "WAIT"))

    st.markdown("---")

    # Main Dashboard Layout
    left_col, right_col = st.columns([2, 1])

    with left_col:
        st.subheader("📊 Market Intelligence & Story")
        
        state = analysis.get("state", "WAIT")
        reason = analysis.get("reason", "")
        
        if state == "ENTRY READY":
            st.success(f"**ENTRY READY ({analysis.get('signal')})**: {reason}")
        elif state == "CAUTION":
            st.warning(f"**CAUTION WARNING**: {reason}")
            for w in analysis.get("warnings", []):
                st.write(f"- ⚠️ {w}")
        elif state == "MARKET UNCLEAR":
            st.warning(f"**MARKET UNCLEAR**: {reason}")
        elif state == "INVALIDATED":
            st.error(f"**INVALIDATED**: {reason}")
        else:
            st.info(f"**Status [{state}]**: {reason}")

        # Buyer/Seller Story Card
        bs = analysis.get("buyer_seller", {})
        st.markdown(f"""
        <div class="signal-card">
            <h4>🧠 Buyer / Seller Behaviour Story</h4>
            <p><b>Dominant Control:</b> {bs.get('control', 'Analyzing...')}</p>
            <p class="small-muted">{bs.get('story', 'Awaiting candle metrics.')}</p>
        </div>
        """, unsafe_allow_html=True)

        # Market Structure & Sakata Context
        ms = analysis.get("market_structure", {})
        st.markdown(f"""
        <div class="signal-card">
            <h4>🏗️ Market Structure & Context</h4>
            <p><b>Trend / Bias:</b> {ms.get('trend', 'SIDEWAYS')} ({ms.get('label', '')})</p>
            <p class="small-muted">{ms.get('detail', '')}</p>
        </div>
        """, unsafe_allow_html=True)

        sakata = analysis.get("sakata_observations", [])
        if sakata:
            st.markdown("**Sakata / Homma Context Observations:**")
            for obs in sakata:
                st.write(f"- 📌 {obs}")

    with right_col:
        st.subheader("⚙️ Staircase Parameters")
        st.write(f"**Entry Reference (C1 Close):** {fmt_price(analysis.get('entry_point', 0))}")
        st.write(f"**Identified Pattern:** {analysis.get('pattern', 'Scanning...')}")
        st.write(f"**Tick Age:** {analysis.get('tick_age', 0):.1f}s")
        
        st.markdown("---")
        st.markdown("### Live Chart Preview")
        if ticks is not None and not ticks.empty:
            fig = go.Figure(go.Scatter(x=ticks["datetime"].tail(100), y=ticks["close"].tail(100), mode="lines", line=dict(color="#34d399", width=2)))
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="#111827", plot_bgcolor="#111827", font=dict(color="#f8fafc"))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.write("Awaiting live tick stream...")

if __name__ == "__main__":
    main()
