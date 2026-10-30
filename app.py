import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# THREE STEPS — staircase-structure research scanner
# Uses completed one-minute candles from Twelve Data.
# It is a research/alerting aid, not a guarantee of binary-option outcomes.

st.set_page_config(page_title="THREE STEPS", page_icon="📈", layout="wide")
ZAMBIA = ZoneInfo("Africa/Lusaka")
st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1450px;}
[data-testid="stMetric"] {background: #111827; border: 1px solid #263244; padding: 14px 16px; border-radius: 14px;}
[data-testid="stMetricLabel"] {color: #9ca3af;}
[data-testid="stMetricValue"] {font-weight: 750;}
.signal-card {background: linear-gradient(135deg,#111827,#172235); border:1px solid #334155;
border-radius:16px; padding:18px; margin:8px 0;}
.signal-call {border-left:5px solid #22c55e;}
.signal-put {border-left:5px solid #ef4444;}
.signal-wait {border-left:5px solid #64748b;}
.small-muted {color:#9ca3af;font-size:0.85rem;}
</style>
""", unsafe_allow_html=True)

PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD",
    "USD/CAD", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY",
]

st.title("📈 THREE STEPS")
st.caption("REAL FOREX  ·  1-MINUTE SCANNER  ·  ZAMBIA TIME")

# Refresh the clock display every second; this does not refresh market data.
st_autorefresh(interval=1000, key="three_steps_clock")

with st.sidebar:
    st.header("⚙️ SCANNER")
    api_key = st.text_input(
        "Twelve Data API key",
        value=st.secrets.get("TWELVE_DATA_API_KEY", os.getenv("TWELVE_DATA_API_KEY", "")),
        type="password",
        help="You can also store this as TWELVE_DATA_API_KEY in Streamlit Secrets.",
    )
    selected_pairs = st.multiselect("Currency pairs", PAIRS, default=["EUR/USD", "GBP/USD", "USD/JPY"])
    lookback = st.slider("History", 60, 300, 150, 10)
    pivot_strength = st.slider("Swing sensitivity", 2, 5, 2)
    min_steps = st.slider("Minimum steps", 3, 6, 3)
    max_pullback = st.slider("Pullback allowance (%)", 10, 80, 50, 5)
    expiry = st.selectbox("Outcome-check expiry", [1, 2, 3, 5], index=0, format_func=lambda x: f"{x} minute(s)")
    run_scan = st.button("🔍 SCAN NOW", type="primary", use_container_width=True)

def timing_panel():
    now = datetime.now(ZAMBIA)
    entry_time = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    expiry_time = entry_time + timedelta(minutes=1)
    prep_seconds = max(0, int((entry_time - now).total_seconds()))
    expiry_seconds = max(0, int((expiry_time - now).total_seconds()))
    a, b, c = st.columns(3)
    a.metric("PREPARE IN", f"{prep_seconds // 60:02d}:{prep_seconds % 60:02d}")
    b.metric("NEXT ENTRY WINDOW", entry_time.strftime("%H:%M:%S"))
    c.metric("1-MIN EXPIRY", expiry_time.strftime("%H:%M:%S"))
    st.caption(f"Zambia time: {now.strftime('%H:%M:%S')}  ·  Expiry countdown: {expiry_seconds // 60:02d}:{expiry_seconds % 60:02d}")

st.subheader("⏱️ TRADE TIMER")
timing_panel()
st.caption("Timer follows Zambia local time. Confirm the signal and live platform price before entry.")

def fetch_candles(symbol: str, key: str, outputsize: int) -> pd.DataFrame:
    url = "https://api.twelvedata.com/time_series"
    response = requests.get(
        url,
        params={
            "symbol": symbol,
            "interval": "1min",
            "outputsize": outputsize,
            "apikey": key,
            "format": "JSON",
            "timezone": "UTC",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if "values" not in payload:
        raise RuntimeError(payload.get("message", payload.get("code", "No candle data returned")))
    df = pd.DataFrame(payload["values"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce").dt.tz_convert("Africa/Lusaka")
    df = df.dropna(subset=["datetime", "open", "high", "low", "close"])
    return df.sort_values("datetime").reset_index(drop=True)

def confirmed_pivots(df: pd.DataFrame, strength: int):
    highs, lows = [], []
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    # Only pivots with all right-hand confirmation candles are used.
    for i in range(strength, len(df) - strength):
        if h[i] == max(h[i-strength:i+strength+1]) and (h[i-strength:i+strength+1] == h[i]).sum() == 1:
            highs.append((i, float(h[i])))
        if l[i] == min(l[i-strength:i+strength+1]) and (l[i-strength:i+strength+1] == l[i]).sum() == 1:
            lows.append((i, float(l[i])))
    return highs, lows

def staircase_analysis(df: pd.DataFrame, strength: int, minimum_steps: int, pullback_pct: int):
    if len(df) < max(30, strength * 4 + 10):
        return {"signal": "WAIT", "reason": "Not enough candles for confirmed swing analysis."}

    highs, lows = confirmed_pivots(df, strength)
    recent_highs = highs[-6:]
    recent_lows = lows[-6:]
    if len(recent_highs) < minimum_steps or len(recent_lows) < minimum_steps:
        return {"signal": "WAIT", "reason": "Not enough confirmed swing highs and lows yet."}

    hh = all(recent_highs[i][1] > recent_highs[i-1][1] for i in range(1, len(recent_highs)))
    hl = all(recent_lows[i][1] > recent_lows[i-1][1] for i in range(1, len(recent_lows)))
    lh = all(recent_highs[i][1] < recent_highs[i-1][1] for i in range(1, len(recent_highs)))
    ll = all(recent_lows[i][1] < recent_lows[i-1][1] for i in range(1, len(recent_lows)))

    close = df["close"]
    ema_fast = close.ewm(span=9, adjust=False).mean()
    ema_slow = close.ewm(span=21, adjust=False).mean()
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper, lower = mid + 2 * std, mid - 2 * std

    last = df.iloc[-1]
    previous = df.iloc[-2]
    recent_range = max(float(df["high"].tail(20).max() - df["low"].tail(20).min()), 1e-12)
    pullback_limit = recent_range * pullback_pct / 100.0

    # Pullback size is measured against the latest 8-bar directional excursion.
    up_excursion = float(df["high"].tail(8).max() - df["low"].tail(8).min())
    down_excursion = up_excursion
    bullish_resume = last["close"] > previous["high"] and last["close"] > ema_fast.iloc[-1]
    bearish_resume = last["close"] < previous["low"] and last["close"] < ema_fast.iloc[-1]
    bullish_context = hh and hl and ema_fast.iloc[-1] > ema_slow.iloc[-1] and close.iloc[-1] > mid.iloc[-1]
    bearish_context = lh and ll and ema_fast.iloc[-1] < ema_slow.iloc[-1] and close.iloc[-1] < mid.iloc[-1]

    # Do not treat a signal as fresh if it is already extended far from the fast EMA.
    extension = abs(float(last["close"] - ema_fast.iloc[-1]))
    typical_bar = float((df["high"] - df["low"]).tail(20).median())
    too_extended = typical_bar > 0 and extension > typical_bar * 2.5

    signal, reason = "WAIT", "No confirmed staircase resumption. Wait for clearer structure."
    if bullish_context and bullish_resume and not too_extended:
        signal = "CALL"
        reason = "Higher swing highs and lows, bullish short-term alignment, and a fresh upward resumption."
    elif bearish_context and bearish_resume and not too_extended:
        signal = "PUT"
        reason = "Lower swing highs and lows, bearish short-term alignment, and a fresh downward resumption."
    elif (bullish_context or bearish_context) and too_extended:
        reason = "Staircase is extended from the fast EMA; avoid chasing a late entry."
    elif hh or hl or lh or ll:
        reason = "Some directional swing progress exists, but the complete staircase/resumption conditions are not met."

    return {
        "signal": signal,
        "reason": reason,
        "last_close": float(last["close"]),
        "ema9": float(ema_fast.iloc[-1]),
        "ema21": float(ema_slow.iloc[-1]),
        "bb_mid": float(mid.iloc[-1]) if pd.notna(mid.iloc[-1]) else None,
        "bb_upper": float(upper.iloc[-1]) if pd.notna(upper.iloc[-1]) else None,
        "bb_lower": float(lower.iloc[-1]) if pd.notna(lower.iloc[-1]) else None,
        "swing_highs": recent_highs,
        "swing_lows": recent_lows,
        "confirmed_at": last["datetime"],
    }

def historical_outcomes(df: pd.DataFrame, strength: int, minimum_steps: int, pullback_pct: int, expiry_mins: int):
    # Conservative historical simulation: enter at the next candle open after a completed signal candle.
    # This avoids pretending the signal candle close was available before it completed.
    records = []
    warmup = max(50, strength * 4 + 15)
    for end in range(warmup, len(df) - expiry_mins - 1):
        window = df.iloc[:end+1].copy().reset_index(drop=True)
        result = staircase_analysis(window, strength, minimum_steps, pullback_pct)
        if result.get("signal") not in ("CALL", "PUT"):
            continue
        entry_row = df.iloc[end+1]
        expiry_row = df.iloc[end+1+expiry_mins]
        entry = float(entry_row["open"])
        finish = float(expiry_row["close"])
        win = finish > entry if result["signal"] == "CALL" else finish < entry
        records.append({
            "time": entry_row["datetime"],
            "direction": result["signal"],
            "entry": entry,
            "expiry_close": finish,
            "result": "WIN" if win else "NON-WIN",
        })
    return pd.DataFrame(records)

def chart_for(df: pd.DataFrame, title: str):
    view = df.tail(100).copy()
    close = view["close"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=view["datetime"], open=view["open"], high=view["high"],
        low=view["low"], close=view["close"], name="1-minute candles"
    ))
    fig.add_trace(go.Scatter(x=view["datetime"], y=ema9, name="EMA 9", line=dict(width=1)))
    fig.add_trace(go.Scatter(x=view["datetime"], y=ema21, name="EMA 21", line=dict(width=1)))
    fig.update_layout(title=title, height=420, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10))
    return fig

if run_scan:
    if not api_key:
        st.error("Enter your Twelve Data API key or add TWELVE_DATA_API_KEY to Streamlit Secrets.")
    elif not selected_pairs:
        st.warning("Select at least one currency pair.")
    else:
        results = []
        progress = st.progress(0)
        status = st.empty()
        for idx, pair in enumerate(selected_pairs):
            status.write(f"Scanning {pair}…")
            try:
                candles = fetch_candles(pair, api_key, lookback)
                analysis = staircase_analysis(candles, pivot_strength, min_steps, max_pullback)
                outcomes = historical_outcomes(candles, pivot_strength, min_steps, max_pullback, expiry)
                wins = int((outcomes["result"] == "WIN").sum()) if not outcomes.empty else 0
                total = len(outcomes)
                rate = (wins / total * 100) if total else None
                results.append({
                    "pair": pair, "candles": candles, "analysis": analysis,
                    "outcomes": outcomes, "wins": wins, "total": total, "rate": rate,
                })
            except Exception as exc:
                results.append({"pair": pair, "error": str(exc)})
            progress.progress((idx + 1) / len(selected_pairs))
        status.empty()
        st.session_state["scan_results"] = results
        st.session_state["scan_time"] = datetime.now(timezone.utc)

if "scan_results" in st.session_state:
    st.subheader("📡 SIGNALS PAD")
    scan_time = st.session_state.get("scan_time")
    if scan_time:
        st.caption(f"Last scan: {scan_time.astimezone(ZAMBIA).strftime('%d %b %Y · %H:%M:%S')} Zambia time")
    items = st.session_state["scan_results"]
    valid = [x for x in items if "error" not in x]
    calls = sum(x["analysis"]["signal"] == "CALL" for x in valid)
    puts = sum(x["analysis"]["signal"] == "PUT" for x in valid)
    waits = sum(x["analysis"]["signal"] == "WAIT" for x in valid)
    a, b, c = st.columns(3)
    a.metric("CALL", calls)
    b.metric("PUT", puts)
    c.metric("WAIT", waits)

    for item in items:
        if "error" in item:
            with st.container(border=True):
                st.error(f"{item['pair']}  ·  {item['error']}")
            continue
        result = item["analysis"]
        direction = result["signal"]
        css = "signal-call" if direction == "CALL" else "signal-put" if direction == "PUT" else "signal-wait"
        icon = "🟢" if direction == "CALL" else "🔴" if direction == "PUT" else "⚪"
        with st.container(border=True):
            left, middle, right = st.columns([1.1, 1.1, 1.8])
            left.markdown(f"### {item['pair']}")
            left.markdown(f"<div class='signal-card {css}'><h2>{icon} {direction}</h2><span class='small-muted'>THREE STEPS</span></div>", unsafe_allow_html=True)
            middle.metric("REFERENCE PRICE", f"{result['last_close']:.5f}" if result.get("last_close") else "—")
            middle.metric(f"{expiry}M HISTORY", f"{item['wins']}/{item['total']}" if item["total"] else "No samples")
            right.markdown("**SETUP**")
            right.write(result.get("reason", "—"))
            if direction in ("CALL", "PUT"):
                right.caption("Check the live Pocket Option price before entry.")
            with st.expander(f"Chart · {item['pair']}"):
                st.plotly_chart(chart_for(item["candles"], item["pair"]), use_container_width=True)
            if item["total"]:
                with st.expander("Past signal results"):
                    st.dataframe(item["outcomes"].tail(20), use_container_width=True, hide_index=True)

st.caption("Feed: Twelve Data  ·  App clock: Africa/Lusaka")
