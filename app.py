import os
import json
import time
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

try:
    import websocket
except ImportError:
    websocket = None


# ============================================================
# CONFIGURATION
# ============================================================

TZ = ZoneInfo("Africa/Lusaka")
DERIV_PUBLIC_WS = "wss://api.derivws.com/trading/v1/options/ws/public"

GHOST_SYMBOL = "1HZ100V"
GHOST_NAME = "Volatility 100 (1s) Index"

FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY"
]

st.set_page_config(
    page_title="GHOST Protocol 4.6 Adaptive Zone Intelligence",
    page_icon="📡",
    layout="wide"
)

st.markdown("""
<style>
:root{color-scheme:dark}
/* Never clip the app: shorter laptop displays must be able to scroll. */
html,body,[data-testid="stAppViewContainer"],[data-testid="stMain"]{height:auto;min-height:100%;overflow-x:hidden;overflow-y:auto}

.stApp{background:radial-gradient(ellipse at 15% 0%,#38205f 0%,#1b102d 44%,#09070f 100%);color:#ffffff;min-height:100vh}
.block-container{max-width:100%;height:auto;min-height:100vh;overflow:visible;padding:0.35rem .75rem .75rem}
[data-testid="stSidebar"]{background:#160d24;border-right:1px solid #713c9d}
[data-testid="stMetric"]{background:linear-gradient(145deg,#32194c,#21142f);border:1px solid #7546a0;padding:9px 12px;border-radius:13px;min-height:88px}
[data-testid="stMetricLabel"]{color:#eadcf7!important;font-weight:800;letter-spacing:.08em}
[data-testid="stMetricValue"]{color:#f6f8ff!important;font-weight:900}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:#33477d!important;border-radius:14px}
.ghost-hero{background:linear-gradient(105deg,#421b66,#70264f 68%,#26143d);border:1px solid #a45bd0;border-radius:12px;padding:7px 15px;margin:0 0 5px;box-shadow:0 5px 18px #03081788}
.ghost-kicker{color:#f0d9ff;letter-spacing:2.2px;font-size:10px;font-weight:900}
.ghost-title{color:#fff;font-size:23px;font-weight:950;letter-spacing:.02em;margin:1px 0}
.ghost-sub{color:#fff0f7;font-size:12px}
.signal-card{padding:6px 9px;border-radius:14px;background:linear-gradient(145deg,#32194c,#21142f);border:1px solid #7546a0;margin:4px 0 10px}
.signal-call{border-left:6px solid #2878ff}.signal-put{border-left:6px solid #ff334f}.signal-wait{border-left:6px solid #9a5bc8}
.brain-card{background:linear-gradient(145deg,#29143d,#381b43);border:1px solid #7546a0;border-radius:9px;padding:5px 7px;margin:2px 0}
.brain-name{color:#edcfff;font-size:10px;font-weight:900;letter-spacing:1.2px}
.brain-state{color:#fff;font-size:12px;font-weight:850;margin:3px 0}
.brain-detail{color:#f0e8f5;font-size:9px;line-height:1.25}
.small-muted{color:#b3c0df;font-size:.78rem}
h1,h2,h3{letter-spacing:-.02em;color:#f7f8ff}
[data-testid="stPlotlyChart"]{border:1px solid #7546a0;border-radius:10px;overflow:hidden;background:#0d1530;margin-bottom:0!important}
[data-testid="stMainBlockContainer"]{padding-top:.35rem;overflow:visible}
section[data-testid="stMain"]{overflow-x:hidden;overflow-y:visible}
/* Let tab labels wrap instead of hiding the last intelligence panels. */
[data-testid="stTabs"] [role="tablist"]{flex-wrap:wrap;gap:3px;white-space:normal}
[data-testid="stTabs"] button[role="tab"]{flex:1 1 auto;white-space:normal;min-height:34px}
/* Avoid horizontal clipping of wide Streamlit widgets. */
[data-testid="stHorizontalBlock"]{min-width:0}
[data-testid="column"]{min-width:0}
div[data-testid="stHorizontalBlock"]{gap:.55rem}
.stButton>button{border-radius:11px;border:1px solid #b66bd5;background:linear-gradient(90deg,#7026a6,#b02c55);color:white;font-weight:850;min-height:42px}
.stButton>button:hover{border-color:#a8b8ff;color:white;box-shadow:0 0 14px #536be866}
[data-testid="stTabs"] button{font-size:11px!important;font-weight:800!important;padding:4px 8px!important}
[data-testid="stMetric"]{padding:5px 7px!important;min-height:62px!important}
[data-testid="stMetricValue"]{font-size:1.15rem!important}
[data-testid="stVerticalBlock"]{gap:.35rem!important}
/* High-contrast controls: readable on Android, desktop and both app themes. */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stCaptionContainer"], label, label p,
[data-testid="stRadio"] p, [data-testid="stCheckbox"] p,
[data-testid="stSelectbox"] label, [data-testid="stMultiSelect"] label,
[data-testid="stSlider"] label, [data-testid="stTextInput"] label,
[data-testid="stNumberInput"] label {color:#f4f6ff!important}
[data-testid="stSidebar"]{background:#111a32!important}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] [data-testid="stRadio"] label,
[data-testid="stSidebar"] [data-testid="stRadio"] p,
[data-testid="stSidebar"] label p {color:#ffffff!important;font-weight:750!important}
[data-baseweb="select"]>div,[data-baseweb="input"]>div,
[data-baseweb="textarea"]>div{background:#17213d!important;border-color:#52649a!important;color:#ffffff!important}
[data-baseweb="select"] input,[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea{color:#ffffff!important}
[data-baseweb="popover"]{background:#17213d!important;color:#ffffff!important}
[role="listbox"], [role="option"], [data-baseweb="menu"]{background:#17213d!important;color:#ffffff!important}
[role="option"] *{color:#ffffff!important}
[data-testid="stSelectbox"] div, [data-testid="stRadio"] div{color:#ffffff}
[data-testid="stRadio"] [role="radiogroup"] label{background:#182342;border:1px solid #465b91;border-radius:9px;padding:7px 9px;margin:2px}
[data-testid="stRadio"] [role="radiogroup"] label p{color:#ffffff!important}
.stApp, .stApp p, .stApp span, .stApp label, .stApp li{color:#f3f5ff}
.ghost-zone-status{border:1px solid #4764a8;background:linear-gradient(100deg,#1b2344,#2b1740);border-radius:11px;padding:9px 12px;color:#fff;margin:5px 0}
.signal-prepared{border-left:6px solid #4d8dff}

@media(max-width:1100px){
  .block-container{padding:.45rem .55rem .8rem}
  .ghost-title{font-size:21px}
  [data-testid="stTabs"] button[role="tab"]{font-size:10px!important;padding:4px 5px!important}
}
@media(max-width:700px){
  .block-container{padding:.35rem .4rem .8rem}
  .ghost-title{font-size:19px}
  .ghost-sub{font-size:10px}
  [data-testid="stMetric"]{padding:5px 6px!important;min-height:56px!important}
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="ghost-hero"><div class="ghost-kicker">ZONE INTELLIGENCE · ONE DECISION</div><div class="ghost-title">👻 GHOST PROTOCOL 4.6</div><div class="ghost-sub">SUPPORT / RESISTANCE · PREDICTIVE ENTRY · EXPERIENCE LEARNING</div></div>
""", unsafe_allow_html=True)

# ============================================================
# SHARED HELPERS
# ============================================================

def now_cat():
    return datetime.now(TZ)


def as_cat(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("Africa/Lusaka")


def fmt_price(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if not pd.notna(number):
        return "Unavailable"
    return f"{number:.5f}" if abs(number) < 100 else f"{number:.3f}"


def blank_result(reason):
    return {
        "signal": "WAIT",
        "reason": reason
    }


def get_secret_api_key():
    """Read the optional Twelve Data key without crashing if Secrets is absent."""
    try:
        secret_value = st.secrets.get("TWELVE_DATA_API_KEY", "")
    except Exception:
        secret_value = ""
    return secret_value or os.getenv("TWELVE_DATA_API_KEY", "")


# ============================================================
# FOREX ENGINE — ZONE-BASED SIGNALS
# ============================================================

def fetch_forex(symbol, key, count):
    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": symbol,
            "interval": "1min",
            "outputsize": count + 3,
            "apikey": key,
            "format": "JSON",
            "timezone": "UTC"
        },
        timeout=20
    )
    response.raise_for_status()
    payload = response.json()

    if "values" not in payload:
        raise RuntimeError(
            payload.get("message", "Twelve Data returned no candles")
        )

    df = pd.DataFrame(payload["values"])
    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["datetime"] = pd.to_datetime(
        df["datetime"], utc=True, errors="coerce"
    )

    df = (
        df.dropna(subset=["datetime", "open", "high", "low", "close"])
        .sort_values("datetime")
        .reset_index(drop=True)
    )

    cutoff = pd.Timestamp.now(tz="UTC").floor("min")
    return (
        df[df.datetime < cutoff]
        .tail(count)
        .reset_index(drop=True)
    )


def confirmed_pivots(df, strength):
    highs, lows = [], []
    high_values = df.high.to_numpy()
    low_values = df.low.to_numpy()

    for i in range(strength, len(df) - strength):
        high_window = high_values[i-strength:i+strength+1]
        low_window = low_values[i-strength:i+strength+1]

        if (
            high_values[i] == high_window.max()
            and (high_window == high_values[i]).sum() == 1
        ):
            highs.append((i, float(high_values[i])))

        if (
            low_values[i] == low_window.min()
            and (low_window == low_values[i]).sum() == 1
        ):
            lows.append((i, float(low_values[i])))

    return highs, lows


def three_steps(df, strength=2, min_steps=3, pullback_pct=50):
    if len(df) < 50:
        return blank_result("Waiting for enough completed candles.")

    highs, lows = confirmed_pivots(df, strength)
    hs = highs[-min_steps:]
    ls = lows[-min_steps:]

    if len(hs) < min_steps or len(ls) < min_steps:
        return blank_result("Waiting for confirmed swing structure.")

    bullish = (
        all(hs[i][1] > hs[i-1][1] for i in range(1, len(hs)))
        and all(ls[i][1] > ls[i-1][1] for i in range(1, len(ls)))
    )
    bearish = (
        all(hs[i][1] < hs[i-1][1] for i in range(1, len(hs)))
        and all(ls[i][1] < ls[i-1][1] for i in range(1, len(ls)))
    )

    close = df.close
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    middle = close.rolling(20).mean()
    deviation = close.rolling(20).std()

    last = df.iloc[-1]
    previous = df.iloc[-2]
    median_range = float((df.high - df.low).tail(20).median())
    extension = abs(float(last.close - ema9.iloc[-1]))

    tail = df.tail(12)
    move = float(tail.high.max() - tail.low.min())
    recent_pullback = (
        float(tail.high.max() - tail.close.iloc[-1])
        if bullish
        else float(tail.close.iloc[-1] - tail.low.min())
    )
    pullback_ok = (
        move <= 0
        or recent_pullback <= move * (pullback_pct / 100)
    )
    late = median_range > 0 and extension > 2.5 * median_range

    call = (
        bullish
        and ema9.iloc[-1] > ema21.iloc[-1]
        and last.close > middle.iloc[-1]
        and last.close > previous.high
        and pullback_ok
        and not late
    )
    put = (
        bearish
        and ema9.iloc[-1] < ema21.iloc[-1]
        and last.close < middle.iloc[-1]
        and last.close < previous.low
        and pullback_ok
        and not late
    )

    signal = "CALL" if call else "PUT" if put else "WAIT"
    reason = (
        "Confirmed higher highs and higher lows with upward resumption."
        if call else
        "Confirmed lower highs and lower lows with downward resumption."
        if put else
        "No fresh confirmed staircase entry. Wait; do not chase."
    )

    return {
        "signal": signal,
        "reason": reason,
        "price": float(last.close),
        "candle_time": last.datetime,
        "ema9": float(ema9.iloc[-1]),
        "ema21": float(ema21.iloc[-1]),
        "upper": float((middle + 2 * deviation).iloc[-1]),
        "lower": float((middle - 2 * deviation).iloc[-1]),
        "highs": hs,
        "lows": ls
    }


# ============================================================
# ZONE REACTION INTELLIGENCE — ONE DECISION
# ============================================================
def zone_reaction_analysis(candles, live_price=None, structure_candles=None, higher_candles=None, forming_candle=None):
    """Find nearby support/resistance zones and score the market's reaction.

    Uses completed OHLC candles plus the latest live price. Zone reactions are
    primary; named candle patterns and the old staircase are contextual evidence.
    """
    empty = {"support": None, "resistance": None, "support_zone": None,
             "resistance_zone": None, "candidate": "WAIT", "candidate_score": 0.0,
             "support_score": 0.0, "resistance_score": 0.0,
             "state": "COLLECTING", "reason": "Collecting completed candles."}
    if candles is None or len(candles) < 25:
        return empty
    d = candles.copy().reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["open", "high", "low", "close"])
    if len(d) < 25:
        return empty
    price = float(live_price) if live_price is not None and pd.notna(live_price) else float(d.close.iloc[-1])
    # Build structural zones from completed 5m and 10m candles. The 1m chart
    # supplies reaction/entry evidence only; its individual pivots must not
    # create a fresh major zone for every small candle swing.
    def median_range(frame, fallback):
        if frame is None or len(frame) < 5:
            return fallback
        rr = (pd.to_numeric(frame.high, errors="coerce") - pd.to_numeric(frame.low, errors="coerce")).dropna().tail(30)
        return max(float(rr.median()), fallback) if len(rr) else fallback

    floor = max(abs(price) * 0.00002, 1e-9)
    one_min_range = float((d.high.astype(float) - d.low.astype(float)).tail(30).median())
    one_min_range = max(one_min_range, floor)
    range_5m = median_range(structure_candles, one_min_range * 3.0)
    range_10m = median_range(higher_candles, range_5m * 1.8)
    atr = max(range_5m, floor)  # distances are expressed in structural 5m units
    tolerance = max(range_5m * 0.38, range_10m * 0.12, floor)
    cluster_radius = max(range_5m * 0.55, range_10m * 0.16, floor)
    zone_half = max(range_5m * 0.28, range_10m * 0.10, floor)

    low_levels, high_levels = [], []
    sources = [(structure_candles, 2, 3.0), (higher_candles, 1, 2.0)]
    # Fallback only when higher-timeframe history is unavailable.
    if all(frame is None or len(frame) < 12 for frame, _, _ in sources):
        sources = [(d, 3, 0.75)]
    for frame, strength, weight in sources:
        if frame is None or len(frame) < max(12, strength * 2 + 5):
            continue
        frame = frame.copy().reset_index(drop=True)
        try:
            ph, pl = confirmed_pivots(frame, strength)
            low_levels.extend((float(v), weight) for _, v in pl[-80:])
            high_levels.extend((float(v), weight) for _, v in ph[-80:])
        except Exception:
            continue

    def cluster_levels(levels):
        """Merge nearby pivots into one price zone; reward multi-TF agreement."""
        groups = []
        for level, weight in sorted(levels, key=lambda item: item[0]):
            if not groups or level - groups[-1]["weighted_price"] / groups[-1]["weight"] > cluster_radius:
                groups.append({"weighted_price": level * weight, "weight": weight, "levels": [level], "score": weight})
            else:
                g = groups[-1]
                g["weighted_price"] += level * weight
                g["weight"] += weight
                g["levels"].append(level)
                g["score"] += weight
        for g in groups:
            g["center"] = g["weighted_price"] / g["weight"]
            g["count"] = len(g["levels"])
            g["low"] = min(g["levels"]) - zone_half
            g["high"] = max(g["levels"]) + zone_half
        return groups

    low_clusters, high_clusters = cluster_levels(low_levels), cluster_levels(high_levels)
    # A support candidate is a structural low below/near price or a broken
    # resistance now acting as support. Resistance is the mirrored case.
    support_groups = [g for g in low_clusters if g["center"] <= price + tolerance]
    resistance_groups = [g for g in high_clusters if g["center"] >= price - tolerance]
    broken_res_groups = [g for g in high_clusters if g["center"] < price and price-g["center"] <= atr*2.5]
    broken_sup_groups = [g for g in low_clusters if g["center"] > price and g["center"]-price <= atr*2.5]
    support_groups += broken_res_groups
    resistance_groups += broken_sup_groups

    def choose_group(groups, side):
        if not groups:
            return None
        # Prefer the nearest credible structural cluster, with multi-pivot and
        # multi-timeframe agreement breaking ties rather than a lone pivot.
        return min(groups, key=lambda g: (abs(price-g["center"])/max(1.0, g["score"]**0.18), -g["count"]))

    support_group = choose_group(support_groups, "support")
    resistance_group = choose_group(resistance_groups, "resistance")
    support = support_group["center"] if support_group else float(d.low.tail(60).min())
    resistance = resistance_group["center"] if resistance_group else float(d.high.tail(60).max())
    support_levels = support_group["levels"] if support_group else [support]
    resistance_levels = resistance_group["levels"] if resistance_group else [resistance]
    support_band = (min(support_levels) - zone_half, max(support_levels) + zone_half)
    resistance_band = (min(resistance_levels) - zone_half, max(resistance_levels) + zone_half)
    # A recently broken structural level is retained as a role-reversal candidate.
    broken_resistance = [g["center"] for g in broken_res_groups]
    broken_support = [g["center"] for g in broken_sup_groups]

    recent = d.tail(8).reset_index(drop=True)
    if forming_candle is not None:
        live_bar = pd.Series(forming_candle)
        prev = recent.iloc[-1]
        last = live_bar
        reaction_rows = pd.concat([recent, pd.DataFrame([live_bar])], ignore_index=True)
    else:
        last = recent.iloc[-1]
        prev = recent.iloc[-2]
        reaction_rows = recent
    o, h, l, c = map(float, (last.open, last.high, last.low, last.close))
    body = abs(c-o)
    span = max(h-l, 1e-12)
    lower_wick = min(o,c)-l
    upper_wick = h-max(o,c)
    close_location = (c-l)/span
    bullish = c > o
    bearish = c < o
    bull_rejection = lower_wick >= max(body*0.55, span*0.18) and close_location >= 0.56
    bear_rejection = upper_wick >= max(body*0.55, span*0.18) and close_location <= 0.44
    bull_engulf = (float(prev.close) < float(prev.open) and bullish and o <= float(prev.close) and c >= float(prev.open))
    bear_engulf = (float(prev.close) > float(prev.open) and bearish and o >= float(prev.close) and c <= float(prev.open))

    support_dist = abs(price-support)/atr
    resistance_dist = abs(resistance-price)/atr
    support_near = support_dist <= 1.35
    resistance_near = resistance_dist <= 1.35
    # Count distinct 1m reactions against the full structural band, not candle
    # proximity to a single pivot price. Consecutive candles in one visit count once.
    def count_zone_visits(frame, band, side):
        if frame is None or len(frame) == 0:
            return 0
        vals = frame.tail(240)
        touched = (vals.low.astype(float) <= band[1]) & (vals.high.astype(float) >= band[0])
        visits, inside = 0, False
        for hit in touched.tolist():
            if hit and not inside:
                visits += 1
            inside = bool(hit)
        return visits
    support_touches = count_zone_visits(d, support_band, "support")
    resistance_touches = count_zone_visits(d, resistance_band, "resistance")
    recent_support_touch = bool((reaction_rows.low.tail(4).astype(float).sub(support).abs() <= tolerance*2.5).any())
    recent_resistance_touch = bool((reaction_rows.high.tail(4).astype(float).sub(resistance).abs() <= tolerance*2.5).any())
    support_reaction = recent_support_touch and support_dist <= 2.5 and (bull_rejection or bull_engulf or (bullish and close_location >= 0.60))
    resistance_reaction = recent_resistance_touch and resistance_dist <= 2.5 and (bear_rejection or bear_engulf or (bearish and close_location <= 0.40))

    # Zone scores are cumulative evidence, not rigid candle-pattern gates.
    s_score = 0.0
    r_score = 0.0
    if support_near: s_score += max(0.35, 1.35 - support_dist*0.65)
    if resistance_near: r_score += max(0.35, 1.35 - resistance_dist*0.65)
    if bull_rejection: s_score += 0.85
    if bear_rejection: r_score += 0.85
    if support_reaction: s_score += 0.85
    if resistance_reaction: r_score += 0.85
    if bull_engulf: s_score += 0.90
    if bear_engulf: r_score += 0.90
    if bullish: s_score += 0.45
    if bearish: r_score += 0.45
    if close_location >= 0.68: s_score += 0.35
    if close_location <= 0.32: r_score += 0.35
    if float(last.close) > float(prev.close): s_score += 0.25
    if float(last.close) < float(prev.close): r_score += 0.25
    s_score += min(support_touches, 3)*0.12
    r_score += min(resistance_touches, 3)*0.12

    # A decisive close beyond a zone, or a successful role-reversal retest,
    # can be an opportunity even when the old rejection logic is irrelevant.
    last_close = float(last.close)
    prev_close = float(prev.close)
    up_break_level = max(broken_resistance) if broken_resistance else None
    down_break_level = min(broken_support) if broken_support else None
    breakout_up = (up_break_level is not None and last_close > up_break_level + atr*0.12 and prev_close <= up_break_level + atr*0.12)
    breakout_down = (down_break_level is not None and last_close < down_break_level - atr*0.12 and prev_close >= down_break_level - atr*0.12)
    retest_up = (up_break_level is not None and any(abs(float(x)-up_break_level) <= tolerance*2 for x in reaction_rows.low.tail(4)) and last_close > up_break_level)
    retest_down = (down_break_level is not None and any(abs(float(x)-down_break_level) <= tolerance*2 for x in reaction_rows.high.tail(4)) and last_close < down_break_level)
    if breakout_up: s_score += 1.15
    if breakout_down: r_score += 1.15
    if retest_up: s_score += 0.85
    if retest_down: r_score += 0.85

    # Avoid inventing a zone signal in the middle of an unstructured range.
    support_event = support_near or support_reaction or breakout_up or retest_up
    resistance_event = resistance_near or resistance_reaction or breakout_down or retest_down
    candidate, score, state = "WAIT", 0.0, "BETWEEN ZONES"
    if support_event and s_score >= 2.05 and s_score >= r_score + 0.25:
        candidate, score = "CALL", s_score
        state = "SUPPORT REACTION" if (support_near or support_reaction) else "RESISTANCE BREAK / SUPPORT RETEST"
    elif resistance_event and r_score >= 2.05 and r_score >= s_score + 0.25:
        candidate, score = "PUT", r_score
        state = "RESISTANCE REACTION" if (resistance_near or resistance_reaction) else "SUPPORT BREAK / RESISTANCE RETEST"
    elif support_near and resistance_near:
        state = "BETWEEN / OVERLAPPING ZONES"
    elif support_near:
        state = "SUPPORT TEST · REACTION NOT PROVEN"
    elif resistance_near:
        state = "RESISTANCE TEST · REACTION NOT PROVEN"

    # Chart bands preserve the whole clustered structural area.
    support_zone = {"low": support_band[0], "high": support_band[1], "center": support,
                    "touches": support_touches, "pivot_count": len(support_levels),
                    "distance_atr": round(support_dist, 2), "timeframe_basis": "5m + 10m"}
    resistance_zone = {"low": resistance_band[0], "high": resistance_band[1], "center": resistance,
                       "touches": resistance_touches, "pivot_count": len(resistance_levels),
                       "distance_atr": round(resistance_dist, 2), "timeframe_basis": "5m + 10m"}
    reason = (f"{state}; support evidence {s_score:.2f}, resistance evidence {r_score:.2f}; "
              f"support distance {support_dist:.2f} ATR, resistance distance {resistance_dist:.2f} ATR.")
    return {"support": support, "resistance": resistance,
            "support_zone": support_zone, "resistance_zone": resistance_zone,
            "candidate": candidate, "candidate_score": score,
            "support_score": s_score, "resistance_score": r_score,
            "support_touches": support_touches, "resistance_touches": resistance_touches,
            "support_near": support_near, "resistance_near": resistance_near,
            "recent_support_touch": recent_support_touch, "recent_resistance_touch": recent_resistance_touch,
            "support_reaction": support_reaction, "resistance_reaction": resistance_reaction,
            "breakout_up": breakout_up, "breakout_down": breakout_down,
            "retest_up": retest_up, "retest_down": retest_down,
            "bull_rejection": bull_rejection, "bear_rejection": bear_rejection,
            "bull_engulfing": bull_engulf, "bear_engulfing": bear_engulf,
            "atr": atr, "state": state, "reason": reason, "price": price}


def four_brain_decision(candles, staircase_result, strength=2, min_steps=3,
                        pullback_pct=50, learned_weights=None,
                        structure_candles=None, forming_candle=None):
    """Unified zone-first decision. Candle formations are supporting evidence, never vetoes."""
    base = dict(staircase_result or {})
    if base.get("stage") == "FEED CHECK":
        base.update({"signal": "WAIT", "candidate_direction": "WAIT", "reason": base.get("reason", "Live feed needs attention."),
                     "brains": {}, "fusion": {"state": "FEED CHECK"}})
        return base
    if candles is None or len(candles) < 30:
        base.update({"signal": "WAIT", "stage": "COLLECTING DATA", "reason": "Collecting completed candles for zone analysis.",
                     "brains": {}, "fusion": {"state": "COLLECTING"}})
        return base
    d = candles.copy().reset_index(drop=True)
    structure = structure_candles.copy().reset_index(drop=True) if structure_candles is not None else aggregate_timeframe(d, 5)
    higher = aggregate_timeframe(d, 10)
    live_price = base.get("price", d.close.iloc[-1])
    zones = zone_reaction_analysis(d, live_price, structure, higher, forming_candle=forming_candle)
    sr = {"support": zones.get("support"), "resistance": zones.get("resistance"),
          "support_zone": zones.get("support_zone"), "resistance_zone": zones.get("resistance_zone"),
          "note": "Clustered 5m/10m structural zones; 1m candles supply reaction and entry evidence; role reversals included."}
    bible = candle_bible_analysis(d)
    patterns = [str(x).upper() for x in bible.get("patterns", [])]
    sakata = homma_sakata_analysis(d)
    observations = [str(x).upper() for x in sakata.get("observations", [])]
    stairs = base.get("signal", "WAIT")
    if stairs not in ("CALL", "PUT"):
        stairs = "WAIT"
    zone_direction = zones.get("candidate", "WAIT")
    candle_direction = "CALL" if zones.get("bull_rejection") or zones.get("bull_engulfing") else "PUT" if zones.get("bear_rejection") or zones.get("bear_engulfing") else "WAIT"
    regime = detect_market_regime(d)
    candidate = zone_direction
    learned_weights = learned_weights or {}
    def _weight(name):
        try: return max(0.85, min(1.15, float(learned_weights.get(name, 1.0))))
        except (TypeError, ValueError): return 1.0
    zone_weight = _weight("ZONE REACTION")
    structure_weight = _weight("MARKET STRUCTURE")
    candle_weight = _weight("CANDLE BEHAVIOUR")
    regime_weight = _weight("MARKET REGIME")
    score = float(zones.get("candidate_score", 0.0)) * zone_weight
    # Staircase, candle and regime contribute weighted evidence; none can veto a valid zone reaction.
    if candidate == "CALL" and stairs == "CALL": score += 0.25 * structure_weight
    if candidate == "PUT" and stairs == "PUT": score += 0.25 * structure_weight
    if candidate == "CALL" and candle_direction == "CALL": score += 0.20 * candle_weight
    if candidate == "PUT" and candle_direction == "PUT": score += 0.20 * candle_weight
    if candidate == "CALL" and regime.get("tag") == "TrendingBull": score += 0.15 * regime_weight
    if candidate == "PUT" and regime.get("tag") == "TrendingBear": score += 0.15 * regime_weight
    # A strong opposite candle is a warning, not an automatic veto.
    opposing_warning = (candidate == "CALL" and zones.get("bear_engulfing")) or (candidate == "PUT" and zones.get("bull_engulfing"))
    if opposing_warning: score -= 0.45
    approved = candidate in ("CALL", "PUT") and score >= 2.05
    signal = candidate if approved else "WAIT"
    votes = {
        "ZONE REACTION": {"vote": zone_direction, "score": round(float(zones.get("candidate_score", 0)), 2), "weight": zone_weight, "role": "Primary · support/resistance behaviour", "detail": zones.get("reason", "No zone reaction")},
        "MARKET STRUCTURE": {"vote": stairs, "score": round(0.25 * structure_weight if stairs == candidate and approved else 0, 2), "weight": structure_weight, "role": "Context · swing and close structure", "detail": "Staircase is context, not a mandatory entry pattern."},
        "CANDLE BEHAVIOUR": {"vote": candle_direction, "score": round(0.20 * candle_weight if candle_direction == candidate and approved else 0, 2), "weight": candle_weight, "role": "Evidence · wick, engulfing and close location", "detail": ", ".join(patterns) if patterns else "No named pattern required."},
        "MARKET REGIME": {"vote": "CALL" if regime.get("tag") == "TrendingBull" else "PUT" if regime.get("tag") == "TrendingBear" else "WAIT", "score": round(0.15 * regime_weight if ((candidate == "CALL" and regime.get("tag") == "TrendingBull") or (candidate == "PUT" and regime.get("tag") == "TrendingBear")) and approved else 0, 2), "weight": regime_weight, "role": "Context · adaptive market condition", "detail": regime.get("tag", "UNKNOWN")},
    }
    base.update({"signal": signal, "candidate_direction": candidate if approved else "WAIT",
                 "stage": "ZONE OPPORTUNITY" if approved else "ZONE MONITORING",
                 "price": float(live_price), "brains": votes,
                 "brain_votes": {"CALL": sum(v["vote"] == "CALL" for v in votes.values()), "PUT": sum(v["vote"] == "PUT" for v in votes.values())},
                 "brain_scores": {"CALL": score if signal == "CALL" else 0, "PUT": score if signal == "PUT" else 0},
                 "candle_bible": bible, "sakata": sakata, "support_resistance": sr,
                 "zone_analysis": zones, "market_regime": regime,
                 "three_steps_result": {"signal": stairs},
                 "fusion": {"state": "OPPORTUNITY FOUND" if approved else "MONITORING", "total_score": round(score, 2),
                            "threshold": 2.05, "opposing_warning": bool(opposing_warning),
                            "block_reasons": [] if approved else [zones.get("reason", "No qualified zone reaction yet.")]},
                 "reason": (f"Zone opportunity identified · {zones.get('state')} · evidence {score:.2f}. Preparing a timed entry." if approved else zones.get("reason", "Monitoring support and resistance.")),
                 "entry_point": float(live_price) if approved else None,
                 "zone_id": (f"{candidate}|{round(float(zones.get('support' if candidate == 'CALL' else 'resistance') or 0), 3)}" if approved else None),
                 "supporting_brains": [k for k,v in votes.items() if v["vote"] == signal] if approved else []})
    return base

def assess_market_structure_risk(structure, direction):
    """Return a soft warning when recent structure presses against the setup."""
    pressure = structure.get("opposing_pressure")
    if direction == "CALL" and pressure == "BEARISH":
        return [
            "Recent market structure shows bearish pressure against this bullish setup. "
            "Check whether the move is a pullback or a confirmed break of the prior swing low."
        ]
    if direction == "PUT" and pressure == "BULLISH":
        return [
            "Recent market structure shows bullish pressure against this bearish setup. "
            "Check whether the move is a pullback or a confirmed break of the prior swing high."
        ]
    return []


def candle_bible_analysis(candles):
    """Contextual candle-pattern reader. Patterns are observations, never entry authority."""
    if candles is None or len(candles) < 3:
        return {"patterns": [], "bias": "INSUFFICIENT DATA", "note": "Need at least three completed candles."}
    d = candles.tail(3).reset_index(drop=True)
    a, b, c = [r for _, r in d.iterrows()]
    def parts(r):
        o,h,l,cl = map(float, (r.open,r.high,r.low,r.close))
        span=max(h-l,1e-12)
        return o,h,l,cl,span,abs(cl-o),(h-max(o,cl)),(min(o,cl)-l),(cl-l)/span
    o1,h1,l1,c1,ra,ba,ua,la,pa=parts(a)
    o2,h2,l2,c2,rb,bb,ub,lb,pb=parts(b)
    o3,h3,l3,c3,rc,bc,uc,lc,pc=parts(c)
    patterns=[]
    # Current candle formations
    if bc <= rc*0.12:
        patterns.append("DOJI / INDECISION")
    if lb >= max(bb*2.0, rc*0.45) and pc >= .62:
        patterns.append("HAMMER-LIKE LOWER REJECTION")
    if ub >= max(bb*2.0, rc*0.45) and pc <= .38:
        patterns.append("SHOOTING-STAR-LIKE UPPER REJECTION")
    if c2 < o2 and c3 > o3 and o3 <= c2 and c3 >= o2:
        patterns.append("BULLISH ENGULFING")
    if c2 > o2 and c3 < o3 and o3 >= c2 and c3 <= o2:
        patterns.append("BEARISH ENGULFING")
    if c1 > o1 and c2 > o2 and c3 > o3 and c3 > c2 > c1:
        patterns.append("THREE WHITE SOLDIERS-LIKE ADVANCE")
    if c1 < o1 and c2 < o2 and c3 < o3 and c3 < c2 < c1:
        patterns.append("THREE BLACK CROWS-LIKE DECLINE")
    # Harami: current body contained by previous body
    if min(o3,c3) > min(o2,c2) and max(o3,c3) < max(o2,c2):
        patterns.append("HARAMI / MOMENTUM PAUSE")
    # Piercing line / dark cloud cover
    if c2 < o2 and c3 > o3 and o3 < c2 and c3 > (o2 + c2) / 2 and c3 < o2:
        patterns.append("PIERCING LINE (BULLISH REVERSAL CANDIDATE)")
    if c2 > o2 and c3 < o3 and o3 > c2 and c3 < (o2 + c2) / 2 and c3 > o2:
        patterns.append("DARK CLOUD COVER (BEARISH REVERSAL CANDIDATE)")
    # Morning / evening star: three-candle body sequence with a small middle body.
    mid_small = bb <= max(ra, rc) * 0.35
    if c1 < o1 and mid_small and c3 > o3 and c3 > (o1 + c1) / 2:
        patterns.append("MORNING STAR-LIKE REVERSAL")
    if c1 > o1 and mid_small and c3 < o3 and c3 < (o1 + c1) / 2:
        patterns.append("EVENING STAR-LIKE REVERSAL")
    if h3 < h2 and l3 > l2:
        patterns.append("INSIDE BAR / COMPRESSION")
    if h3 > h2 and l3 < l2:
        patterns.append("OUTSIDE BAR / RANGE EXPANSION")
    if bc >= rc * 0.88 and pc >= .9:
        patterns.append("BULLISH MARUBOZU-LIKE CLOSE")
    if bc >= rc * 0.88 and pc <= .1:
        patterns.append("BEARISH MARUBOZU-LIKE CLOSE")
    bias = "BULLISH CONTEXT" if pc > .65 and c3 > o3 else "BEARISH CONTEXT" if pc < .35 and c3 < o3 else "MIXED / INDECISION"
    return {"patterns": patterns or ["NO HIGH-CONFIDENCE CLASSIC PATTERN"], "bias": bias,
            "note": "Candlestick names are approximate OHLC pattern matches. Candle Bible is one of four independent voting brains; evidence must be reviewed in context."}


def homma_sakata_analysis(candles):
    """Conservative Sakata-inspired pattern observations; no forced pattern labels."""
    if candles is None or len(candles) < 20:
        return {"observations": [], "state": "COLLECTING HISTORY"}
    d=candles.tail(40).reset_index(drop=True)
    highs=d.high.astype(float); lows=d.low.astype(float); closes=d.close.astype(float)
    obs=[]
    # Three mountains: three separated swing peaks with intervening declines
    peaks=[]
    for i in range(2,len(d)-2):
        if highs.iloc[i] >= max(highs.iloc[i-2:i+3]) and (highs.iloc[i-2:i+3] == highs.iloc[i]).sum()==1:
            peaks.append((i,float(highs.iloc[i])))
    if len(peaks)>=3:
        p=peaks[-3:]
        if p[1][0]-p[0][0]>=2 and p[2][0]-p[1][0]>=2:
            vals=[x[1] for x in p]
            if max(vals)-min(vals) <= max(vals)*0.003:
                obs.append("THREE MOUNTAINS CANDIDATE — repeated resistance area")
    # Three rivers: three distinct troughs near a common support region
    troughs=[]
    for i in range(2,len(d)-2):
        if lows.iloc[i] <= min(lows.iloc[i-2:i+3]) and (lows.iloc[i-2:i+3] == lows.iloc[i]).sum()==1:
            troughs.append((i,float(lows.iloc[i])))
    if len(troughs)>=3:
        t=troughs[-3:]; vals=[x[1] for x in t]
        if t[1][0]-t[0][0]>=2 and t[2][0]-t[1][0]>=2 and max(vals)-min(vals)<=max(vals)*0.003:
            obs.append("THREE RIVERS CANDIDATE — repeated support area")
    # Three methods: impulse, 1-3 countertrend candles contained in impulse range, continuation close
    if len(d)>=6:
        x=d.tail(6).reset_index(drop=True)
        first=x.iloc[0]; last=x.iloc[-1]; middle=x.iloc[1:5]
        impulse_up=float(first.close)>float(first.open) and float(last.close)>float(last.open)
        impulse_down=float(first.close)<float(first.open) and float(last.close)<float(last.open)
        contained=(float(middle.high.max())<=max(float(first.open),float(first.close),float(last.open),float(last.close)) + abs(float(first.close)-float(first.open))*0.5
                   and float(middle.low.min())>=min(float(first.open),float(first.close),float(last.open),float(last.close)) - abs(float(first.close)-float(first.open))*0.5)
        if impulse_up and contained and float(last.close)>float(middle.high.max()): obs.append("THREE METHODS BULLISH CANDIDATE")
        if impulse_down and contained and float(last.close)<float(middle.low.min()): obs.append("THREE METHODS BEARISH CANDIDATE")
    # Three Parallel Lines: three consecutive directional bodies with progressive closes.
    if len(d) >= 3:
        q = d.tail(3).reset_index(drop=True)
        q_up = all(float(r.close) > float(r.open) for _, r in q.iterrows())
        q_down = all(float(r.close) < float(r.open) for _, r in q.iterrows())
        q_closes = q.close.astype(float).tolist()
        q_opens = q.open.astype(float).tolist()
        if q_up and q_closes[0] < q_closes[1] < q_closes[2] and q_opens[0] < q_opens[1] < q_opens[2]:
            obs.append("THREE PARALLEL LINES — BULLISH CANDIDATE (three rising bodies)")
        elif q_down and q_closes[0] > q_closes[1] > q_closes[2] and q_opens[0] > q_opens[1] > q_opens[2]:
            obs.append("THREE PARALLEL LINES — BEARISH CANDIDATE (three falling bodies)")
        # Three Gaps: three successive non-overlapping gaps in one direction.
        if len(d) >= 4:
            g = d.tail(4).reset_index(drop=True)
            up_gaps = all(float(g.iloc[i].low) > float(g.iloc[i-1].high) for i in range(1,4))
            down_gaps = all(float(g.iloc[i].high) < float(g.iloc[i-1].low) for i in range(1,4))
            if up_gaps:
                obs.append("THREE GAPS UP — RARE EXHAUSTION-RISK CANDIDATE; VERIFY CONTEXT")
            elif down_gaps:
                obs.append("THREE GAPS DOWN — RARE EXHAUSTION-RISK CANDIDATE; VERIFY CONTEXT")
    return {"observations": obs or ["No confirmed Sakata formation in the available sample"],
            "state": "PATTERN CONTEXT ONLY",
            "note": "Sakata labels are conservative OHLC candidates. Gaps and parallel-line formations are uncommon in continuous synthetic markets; Sakata contributes a vote but is never treated as proof."}


def support_resistance_analysis(candles, lookback=80):
    if candles is None or len(candles)<10: return {"support":None,"resistance":None,"note":"Collecting swing history."}
    d=candles.tail(lookback).reset_index(drop=True)
    highs,lows=confirmed_pivots(d,2)
    price=float(d.close.iloc[-1])
    resist=[v for _,v in highs if v>=price]
    support=[v for _,v in lows if v<=price]
    return {"support":max(support) if support else None,
            "resistance":min(resist) if resist else None,
            "note":"Nearest confirmed pivot levels; context only, not staircase vetoes."}


# ============================================================
# DERIV PUBLIC WEBSOCKET CLIENT
# ============================================================

class DerivClient:
    def __init__(self, timeout=20):
        if websocket is None:
            raise RuntimeError(
                "Install websocket-client before connecting to Deriv."
            )
        self.timeout = timeout
        self.ws = None
        self.req_id = 0
        self.last_activity = time.monotonic()
        self.connect()

    def connect(self):
        self.close()
        try:
            self.ws = websocket.create_connection(
                DERIV_PUBLIC_WS,
                timeout=self.timeout
            )
            self.ws.settimeout(self.timeout)
            self.last_activity = time.monotonic()
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
            self.last_activity = time.monotonic()

            if message.get("error"):
                error = message["error"]
                raise RuntimeError(
                    error.get("message", "Deriv API error")
                )

            if message.get("req_id") == self.req_id:
                return message

        raise TimeoutError(
            "Deriv did not respond before the request timed out."
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class DerivLiveFeed:
    """Persistent public Deriv tick subscription with bounded history and reconnects."""
    def __init__(self, symbol, seed_ticks=None, max_ticks=30000):
        if websocket is None:
            raise RuntimeError("websocket-client is required for the live Deriv feed.")
        from collections import deque
        import threading
        self.symbol = symbol
        self.max_ticks = max_ticks
        self._ticks = deque(maxlen=max_ticks)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._app = None
        self._connected = False
        self._last_message = None
        self._last_error = None
        self._reconnects = 0
        if seed_ticks is not None and not seed_ticks.empty:
            for row in seed_ticks[["datetime", "close"]].itertuples(index=False):
                self._ticks.append({"datetime": pd.Timestamp(row.datetime), "close": float(row.close)})

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        import threading
        self._thread = threading.Thread(target=self._run, name=f"DerivFeed-{self.symbol}", daemon=True)
        self._thread.start()
        return self

    def _on_open(self, ws):
        self._connected = True
        self._last_error = None
        ws.send(json.dumps({"ticks": self.symbol, "subscribe": 1}))

    def _on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
            if msg.get("error"):
                self._last_error = msg["error"].get("message", "Deriv stream error")
                return
            tick = msg.get("tick")
            if not tick:
                return
            epoch = tick.get("epoch")
            quote = tick.get("quote")
            if epoch is None or quote is None:
                return
            item = {"datetime": pd.to_datetime(int(epoch), unit="s", utc=True), "close": float(quote)}
            with self._lock:
                # Ignore duplicate/out-of-order tick events, but retain same-second distinct quotes.
                if self._ticks and item["datetime"] < self._ticks[-1]["datetime"]:
                    return
                if self._ticks and item["datetime"] == self._ticks[-1]["datetime"] and item["close"] == self._ticks[-1]["close"]:
                    return
                self._ticks.append(item)
            self._last_message = time.time()
        except Exception as exc:
            self._last_error = f"Could not parse Deriv tick: {exc}"

    def _on_error(self, ws, error):
        self._connected = False
        self._last_error = str(error)

    def _on_close(self, ws, code, message):
        self._connected = False

    def _run(self):
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._app = websocket.WebSocketApp(
                    DERIV_PUBLIC_WS,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._app.run_forever(ping_interval=25, ping_timeout=10)
            except Exception as exc:
                self._last_error = str(exc)
            self._connected = False
            if self._stop.is_set():
                break
            self._reconnects += 1
            self._stop.wait(delay)
            delay = min(delay * 1.7, 30.0)

    def snapshot(self):
        with self._lock:
            rows = list(self._ticks)
        return pd.DataFrame(rows, columns=["datetime", "close"])

    def status(self):
        age = None if self._last_message is None else max(0.0, time.time() - self._last_message)
        return {"connected": self._connected, "last_tick_age": age, "last_error": self._last_error, "reconnects": self._reconnects}

    def stop(self):
        self._stop.set()
        try:
            if self._app is not None:
                self._app.close()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


# ============================================================
# DERIV SYMBOL DISCOVERY AND TICK HISTORY
# ============================================================

def deriv_symbols(client):
    data = client.request({"active_symbols": "brief"})
    raw_symbols = data.get("active_symbols", [])
    normalized = []

    for item in raw_symbols:
        row = dict(item)
        symbol = (
            row.get("underlying_symbol")
            or row.get("symbol")
            or ""
        )
        name = (
            row.get("underlying_symbol_name")
            or row.get("display_name")
            or row.get("name")
            or symbol
        )
        if symbol:
            row["symbol"] = symbol
            row["display_name"] = name
            normalized.append(row)

    return normalized


def fetch_deriv_candle_history(symbol, count=5000, client=None, granularity=60):
    """Fetch historical completed 1-minute OHLC candles for deep MTF context."""
    if client is None:
        with DerivClient(timeout=25) as temporary:
            return fetch_deriv_candle_history(symbol, count, temporary, granularity)
    data = client.request({
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": min(int(count), 5000),
        "end": "latest",
        "style": "candles",
        "granularity": int(granularity)
    })
    rows = data.get("candles", [])
    if not rows:
        raise RuntimeError("Deriv returned no historical 1-minute candles.")
    frame = pd.DataFrame(rows)
    frame["datetime"] = pd.to_datetime(frame["epoch"], unit="s", utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["datetime", "open", "high", "low", "close"])
    return frame[["datetime", "open", "high", "low", "close"]].sort_values("datetime").drop_duplicates("datetime").reset_index(drop=True)


def fetch_deriv_mtf_history(symbol, client):
    """Fetch native Deriv candles so daily/4h baselines do not depend on 1m history depth."""
    specs = {"15m": (900, 300), "1h": (3600, 240), "4h": (14400, 120), "1d": (86400, 90)}
    histories, errors = {}, {}
    for label, (granularity, count) in specs.items():
        try:
            histories[label] = fetch_deriv_candle_history(symbol, count, client, granularity)
        except Exception as exc:
            histories[label] = pd.DataFrame(columns=["datetime", "open", "high", "low", "close"])
            errors[label] = str(exc)
    return histories, errors


def merge_candle_history(live_candles, historical_candles):
    """Historical 1m candles plus live tick-derived updates; live wins per minute."""
    frames = [x for x in (historical_candles, live_candles) if x is not None and not x.empty]
    if not frames:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close"])
    merged = pd.concat(frames, ignore_index=True)
    merged["datetime"] = pd.to_datetime(merged["datetime"], utc=True, errors="coerce")
    merged = merged.dropna(subset=["datetime", "open", "high", "low", "close"])
    return merged.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)


def fetch_deriv_ticks(symbol, count=4500, client=None):
    if client is None:
        with DerivClient(timeout=25) as temporary:
            return fetch_deriv_ticks(symbol, count, temporary)

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

    # Keep multiple ticks sharing the same second: they may contain
    # important intrasecond price movement for OHLC construction.
    df = (
        df.dropna(subset=["datetime", "close"])
        .sort_values("datetime", kind="stable")
        .reset_index(drop=True)
    )

    if len(df) < 900:
        raise RuntimeError(
            "Not enough tick history for multi-timeframe analysis."
        )

    return df


# ============================================================
# GHOST CANDLE CONSTRUCTION
# ============================================================

def ticks_to_candles(ticks):
    series = (
        ticks.set_index("datetime")["close"]
        .sort_index(kind="stable")
    )
    candles = series.resample("1min").ohlc()
    return candles.dropna().reset_index()


def aggregate_timeframe(one_minute, minutes):
    data = one_minute.set_index("datetime").copy()
    data["_observed"] = 1
    result = data.resample(
        f"{minutes}min",
        label="left",
        closed="left"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "_observed": "sum"
    }).dropna().reset_index().rename(columns={"_observed": "observed_minutes"})

    now = pd.Timestamp.now(tz="UTC").floor("min")
    result = result[
        (result.datetime + pd.Timedelta(minutes=minutes) <= now)
        & (result.observed_minutes >= minutes)
    ]
    return result.drop(columns=["observed_minutes"]).reset_index(drop=True)



def identify_candle_one(c1, previous):
    """Identify C1 from closing-price staircase structure, never candle size.

    Bullish C1: close steps above the previous close and its low does not break
    the previous low. Bearish C1 is the mirrored condition. This is only a
    trigger candidate; C2 must still close beyond the C1 close.
    """
    try:
        c1_close, prev_close = float(c1.close), float(previous.close)
        c1_low, prev_low = float(c1.low), float(previous.low)
        c1_high, prev_high = float(c1.high), float(previous.high)
    except (AttributeError, TypeError, ValueError):
        return None, "Invalid candle data"
    if c1_close > prev_close:
        return "CALL", "BULLISH THREE-STEP C1 · higher closing-price step"
    if c1_close < prev_close:
        return "PUT", "BEARISH THREE-STEP C1 · lower closing-price step"
    return None, "No closing-price staircase trigger"


def analyze_market_structure(candles):
    """Describe recent close/swing pressure as context; never invent a signal."""
    if candles is None or len(candles) < 6:
        return {"state": "COLLECTING", "opposing_pressure": None,
                "detail": "Need at least six completed candles for structure context."}
    d = candles.tail(12).reset_index(drop=True)
    closes = d.close.astype(float)
    highs = d.high.astype(float)
    lows = d.low.astype(float)
    up_closes = sum(closes.iloc[i] > closes.iloc[i-1] for i in range(1, len(closes)))
    down_closes = sum(closes.iloc[i] < closes.iloc[i-1] for i in range(1, len(closes)))
    higher_lows = sum(lows.iloc[i] > lows.iloc[i-1] for i in range(1, len(lows)))
    lower_highs = sum(highs.iloc[i] < highs.iloc[i-1] for i in range(1, len(highs)))
    pressure = None
    if up_closes >= 7 and higher_lows >= 6:
        pressure = "BULLISH"
    elif down_closes >= 7 and lower_highs >= 6:
        pressure = "BEARISH"
    return {"state": "STRUCTURE READ", "opposing_pressure": pressure,
            "up_closes": int(up_closes), "down_closes": int(down_closes),
            "higher_lows": int(higher_lows), "lower_highs": int(lower_highs),
            "detail": "Recent completed-candle close and swing structure; context only."}


def assess_candle3_risk(completed, direction, c2, live_price):
    """Return only clear C3 invalidation/exhaustion warnings, not size filters."""
    warnings = []
    if completed is None or len(completed) < 3:
        return warnings
    try:
        c1_close = float(completed.iloc[-2].close)
        c2_close = float(c2.close)
        live_price = float(live_price)
        # Hard invalidation is handled by ghost_protocol before this function.
        # Here only warn when the C2 candle itself is unusually extended versus
        # its recent range; candle size does not decide direction.
        recent_ranges = (completed.high.astype(float) - completed.low.astype(float)).tail(20)
        typical = float(recent_ranges.median()) if len(recent_ranges) else 0.0
        c2_range = float(c2.high) - float(c2.low)
        if typical > 0 and c2_range > 3.5 * typical:
            warnings.append("Candle 2 range is unusually expanded; avoid chasing the move.")
        if direction == "CALL" and live_price <= c1_close:
            warnings.append("Candle 3 is no longer above the C1 close.")
        elif direction == "PUT" and live_price >= c1_close:
            warnings.append("Candle 3 is no longer below the C1 close.")
    except (TypeError, ValueError, AttributeError, IndexError):
        warnings.append("Candle 3 risk context could not be fully evaluated.")
    return warnings


def ghost_protocol(ticks):
    """Evaluate the Three-Step sequence as one independent intelligence input."""
    if ticks is None or ticks.empty:
        return {"signal": "WAIT", "stage": "FEED CHECK", "reason": "Waiting for Deriv tick data."}

    ticks = ticks.copy()
    ticks["datetime"] = pd.to_datetime(ticks["datetime"], utc=True, errors="coerce")
    ticks["close"] = pd.to_numeric(ticks["close"], errors="coerce")
    ticks = ticks.dropna(subset=["datetime", "close"]).sort_values("datetime", kind="stable")
    if ticks.empty:
        return {"signal": "WAIT", "stage": "FEED CHECK", "reason": "No valid tick observations."}

    latest_price = float(ticks.close.iloc[-1])
    now = pd.Timestamp.now(tz="UTC")
    latest_tick = pd.Timestamp(ticks.datetime.iloc[-1])
    tick_age = (now - latest_tick).total_seconds()
    base = {"signal": "WAIT", "stage": "SCANNING", "reason": "Waiting for a valid C1 → C2 → C3 sequence.",
            "price": latest_price, "tick_time": latest_tick, "tick_age": tick_age}
    if tick_age > 8 or tick_age < -2:
        return {**base, "stage": "FEED CHECK", "reason": f"Deriv feed is stale or time-misaligned ({tick_age:.1f}s)."}

    candles = ticks_to_candles(ticks)
    current_minute = now.floor("min")
    completed = candles[candles.datetime + pd.Timedelta(minutes=1) <= current_minute].reset_index(drop=True)
    forming = candles[(candles.datetime == current_minute)]
    if forming.empty or len(completed) < 3:
        return {**base, "reason": "Waiting for a current candle and at least three completed candles."}

    market_structure = analyze_market_structure(completed)
    candle_age = (now - current_minute).total_seconds()
    base.update({"market_structure": market_structure, "candle_time": current_minute, "candle_age": candle_age})

    # FIRST: test whether the last two completed candles are C1 and C2,
    # making the currently forming candle C3. This must precede C2 detection.
    c1, c2, previous = completed.iloc[-2], completed.iloc[-1], completed.iloc[-3]
    c1_time, c2_time, previous_time = map(pd.Timestamp, (c1.datetime, c2.datetime, previous.datetime))
    c1_direction, c1_pattern = identify_candle_one(c1, previous)
    c3_sequence = (
        c1_direction is not None
        and previous_time == c1_time - pd.Timedelta(minutes=1)
        and c2_time == c1_time + pd.Timedelta(minutes=1)
        and current_minute == c1_time + pd.Timedelta(minutes=2)
    )
    if c3_sequence:
        c1_close, c2_close = float(c1.close), float(c2.close)
        c2_confirmed = c2_close > c1_close if c1_direction == "CALL" else c2_close < c1_close
        c3_valid = latest_price > c1_close if c1_direction == "CALL" else latest_price < c1_close
        base.update({"pattern": c1_pattern, "entry_point": c1_close, "candle1_time": c1_time,
                     "candle2_close": c2_close, "entry_time": current_minute})
        if not c2_confirmed:
            return {**base, "stage": "INVALIDATED", "reason": "Candle 2 did not CLOSE beyond Candle 1 close. Staircase invalidated; no entry."}
        if not c3_valid:
            return {**base, "stage": "INVALIDATED", "reason": "Candle 3 crossed back through Candle 1 close. Staircase invalidated; no entry."}
        warnings = assess_candle3_risk(completed, c1_direction, c2, latest_price)
        warnings.extend(assess_market_structure_risk(market_structure, c1_direction))
        if warnings:
            return {**base, "signal": c1_direction, "stage": "CAUTION",
                    "reason": "C1/C2 confirmation exists, but soft risk warnings require caution. This is NOT ENTRY READY.",
                    "warnings": warnings, "stage_detail": "STAIRCASE VALID — CAUTION"}
        return {**base, "signal": c1_direction, "stage": "ENTRY READY", "warnings": [],
                "reason": f"Candle 2 closed beyond Candle 1 close and Candle 3 remains on the valid side of {fmt_price(c1_close)}. Manual {c1_direction} entry window.",
                "stage_detail": "C2 CLOSED — C3 ENTRY WINDOW"}

    # SECOND: current candle is C2 and the latest completed candle may be C1.
    c1, previous = completed.iloc[-1], completed.iloc[-2]
    c1_time = pd.Timestamp(c1.datetime)
    direction, pattern = identify_candle_one(c1, previous)
    consecutive = pd.Timestamp(previous.datetime) == c1_time - pd.Timedelta(minutes=1)
    if direction and consecutive and current_minute == c1_time + pd.Timedelta(minutes=1):
        c1_close = float(c1.close)
        beyond = latest_price > c1_close if direction == "CALL" else latest_price < c1_close
        base.update({"pattern": pattern, "entry_point": c1_close, "candle1_time": c1_time})
        if beyond:
            return {**base, "stage": "SETUP DEVELOPING", "reason": f"{pattern} identified. Candle 2 is temporarily beyond C1 close but has NOT closed. No directional signal yet.",
                    "entry_time": current_minute + pd.Timedelta(minutes=1), "countdown": max(0, int(60-candle_age))}
        return {**base, "stage": "CANDLE 2 WAITING", "reason": f"{pattern} found. Waiting for Candle 2 to move beyond C1 close at {fmt_price(c1_close)}."}

    return {**base, "stage": "SCANNING", "reason": "No valid consecutive C1/C2/C3 sequence at this moment. Continue observing."}


# ============================================================
# GHOST 4.6 — REGIME, ZONE INTELLIGENCE, OUTCOME JOURNAL AND RISK GUARDS
# ============================================================
def detect_market_regime(candles):
    """Completed-candle regime estimate; synthetic tick count is never called volume."""
    if candles is None or len(candles) < 40:
        return {"tag": "UNKNOWN", "adx": None, "atr_state": "UNKNOWN", "slope": 0.0}
    d = candles.copy().reset_index(drop=True)
    high, low, close = d.high.astype(float), d.low.astype(float), d.close.astype(float)
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    up = high.diff(); down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = tr.rolling(14).mean()
    plus_di = 100 * plus_dm.rolling(14).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(14).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
    adx = float(dx.rolling(14).mean().iloc[-1]) if pd.notna(dx.rolling(14).mean().iloc[-1]) else 0.0
    ma = close.ewm(span=20, adjust=False).mean()
    slope = float((ma.iloc[-1]-ma.iloc[-6]) / max(float(atr.iloc[-1]), 1e-12))
    recent = float(atr.iloc[-5:].mean()) if atr.iloc[-5:].notna().any() else 0.0
    prior = float(atr.iloc[-25:-5].mean()) if atr.iloc[-25:-5].notna().any() else recent
    expanding = recent > prior * 1.10 if prior > 0 else False
    contracting = recent < prior * 0.90 if prior > 0 else False
    if adx > 25 and slope > 0.15: tag = "TrendingBull"
    elif adx > 25 and slope < -0.15: tag = "TrendingBear"
    elif adx < 20 and expanding: tag = "RangeVolatile"
    elif adx < 20 and contracting: tag = "LowVolumeChop"
    else: tag = "TRANSITIONAL"
    return {"tag": tag, "adx": adx, "atr_state": "EXPANDING" if expanding else "CONTRACTING" if contracting else "STABLE", "slope": slope}


def init_trade_journal():
    with _learning_connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS ghost_trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            market TEXT NOT NULL, instrument TEXT NOT NULL, direction TEXT NOT NULL,
            fingerprint TEXT NOT NULL, regime TEXT NOT NULL, trigger_type TEXT,
            confirmation TEXT, outcome TEXT NOT NULL, notes TEXT DEFAULT ''
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ghost_trade_fp ON ghost_trade_journal(instrument,fingerprint,regime,created_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS ghost_risk_pauses (
            instrument TEXT PRIMARY KEY, pause_until TEXT NOT NULL, reason TEXT NOT NULL
        )""")


def setup_fingerprint(result, regime):
    brains = (result or {}).get("brains", {})
    sr = brains.get("ZONE REACTION", {})
    cb = brains.get("CANDLE BEHAVIOUR", {})
    hs = brains.get("MARKET STRUCTURE", {})
    stamp = (result or {}).get("candle_time")
    try:
        hour = pd.Timestamp(stamp).hour
    except Exception:
        hour = now_cat().hour
    bucket = "00-05" if hour < 5 else "05-10" if hour < 10 else "10-14" if hour < 14 else "14-18" if hour < 18 else "18-24"
    return "|".join([str((result or {}).get("signal", "WAIT")), str(sr.get("score", 0)), str(cb.get("detail", "").split(";")[0]), str(hs.get("vote", "WAIT")), bucket, str(regime)])


def journal_trade_outcome(market, instrument, result, outcome, regime="UNKNOWN", notes=""):
    if outcome not in ("WIN", "LOSS", "VOID"):
        raise ValueError("Outcome must be WIN, LOSS or VOID")
    init_trade_journal()
    fp = setup_fingerprint(result, regime)
    with _learning_connect() as conn:
        conn.execute("INSERT INTO ghost_trade_journal(created_at,market,instrument,direction,fingerprint,regime,trigger_type,confirmation,outcome,notes) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (now_cat().isoformat(), market, instrument, (result or {}).get("signal", "WAIT"), fp, regime,
             (result or {}).get("brains", {}).get("ZONE REACTION", {}).get("detail", ""),
             (result or {}).get("brains", {}).get("MARKET STRUCTURE", {}).get("vote", "WAIT"), outcome, notes[:500]))
    return fp


def trade_risk_profile(instrument, fingerprint, regime):
    init_trade_journal()
    with _learning_connect() as conn:
        rows = conn.execute("SELECT outcome,fingerprint,regime FROM ghost_trade_journal WHERE instrument=? AND outcome IN ('WIN','LOSS') ORDER BY id DESC LIMIT 200", (instrument,)).fetchall()
        fp_rows = [r for r in rows if r["fingerprint"] == fingerprint and r["regime"] == regime]
        consecutive = 0
        for row in fp_rows:
            if row["outcome"] == "LOSS": consecutive += 1
            else: break
        instrument_losses = 0
        for row in rows:
            if row["outcome"] == "LOSS": instrument_losses += 1
            else: break
        group = conn.execute("SELECT outcome FROM ghost_trade_journal WHERE instrument=? AND fingerprint=? AND regime=? AND outcome IN ('WIN','LOSS') ORDER BY id DESC LIMIT 50", (instrument, fingerprint, regime)).fetchall()
    n = len(group); wins = sum(r["outcome"] == "WIN" for r in group)
    reliability = (wins / n) if n else None
    size_cap = 1.0
    if consecutive >= 5: size_cap = 0.25
    elif consecutive >= 3: size_cap = 0.50
    if regime == "LowVolumeChop": size_cap = min(size_cap, 0.25)
    pause_until = None
    if instrument_losses >= 5: pause_until = now_cat() + timedelta(hours=4)
    elif instrument_losses >= 3: pause_until = now_cat() + timedelta(hours=1)
    if pause_until:
        with _learning_connect() as conn:
            conn.execute("INSERT INTO ghost_risk_pauses(instrument,pause_until,reason) VALUES(?,?,?) ON CONFLICT(instrument) DO UPDATE SET pause_until=excluded.pause_until,reason=excluded.reason", (instrument, pause_until.isoformat(), f"{instrument_losses} consecutive instrument losses"))
    with _learning_connect() as conn:
        pause = conn.execute("SELECT pause_until,reason FROM ghost_risk_pauses WHERE instrument=?", (instrument,)).fetchone()
    paused = False; pause_reason = ""
    if pause:
        try:
            until = as_cat(pause["pause_until"]).to_pydatetime()
            paused = now_cat() < until
            pause_reason = pause["reason"] if paused else ""
        except Exception:
            pass
    return {"samples": n, "wins": wins, "win_rate": reliability, "size_cap": size_cap,
            "fingerprint_losses": consecutive, "instrument_losses": instrument_losses,
            "paused": paused, "pause_reason": pause_reason}


def apply_trade_safety(result, market, instrument, candles):
    """Risk layer can only downgrade an existing signal, never create one."""
    result = dict(result or {})
    regime = detect_market_regime(candles)
    result["market_regime"] = regime
    if result.get("signal") not in ("CALL", "PUT"):
        return result
    fp = setup_fingerprint(result, regime["tag"])
    risk = trade_risk_profile(instrument, fp, regime["tag"])
    result["trade_risk"] = risk
    if risk["paused"]:
        result.update({"signal": "WAIT", "stage": "RISK PAUSE", "reason": "GHOST risk pause: " + risk["pause_reason"]})
    elif risk["size_cap"] < 1:
        result["fusion"] = dict(result.get("fusion", {}), size_tier=min(float(result.get("fusion", {}).get("size_tier", 1.0)), risk["size_cap"]))
        result["reason"] += f" · Risk size cap {risk['size_cap']:.0%} from recent losses/regime."
    return result


# ============================================================
# SIGNAL TIMER AND RECORD
# ============================================================


# ============================================================
# GHOST LEARNING MEMORY — EVERY SCAN, INCLUDING WAIT STATES
# ============================================================


# ============================================================
# EXPERIENCE-LEARNING MODEL — WALK-FORWARD, EXPLAINABLE
# ============================================================
FEATURE_NAMES = (
    "three_steps_vote", "candle_bible_vote", "homma_sakata_vote", "support_resistance_vote",
    "call_score", "put_score", "score_margin",
    "body_fraction", "upper_wick_fraction", "lower_wick_fraction", "close_location",
    "return_1_atr", "return_3_atr", "return_5_atr", "ema_spread_atr",
    "support_distance_atr", "resistance_distance_atr",
    "candle_pattern_bias", "sakata_pattern_bias", "hour_sin", "hour_cos",
    "zone_support_evidence", "zone_resistance_evidence", "zone_support_nearness", "zone_resistance_nearness"
)


def _vote_number(value):
    return 1.0 if value == "CALL" else -1.0 if value == "PUT" else 0.0


def build_learning_features(result, candles=None):
    """Build a fixed, causal feature vector from the snapshot and completed candles only."""
    result = result or {}
    brains = result.get("brains") or {}
    votes = [_vote_number((brains.get(name) or {}).get("vote", "WAIT")) for name in
             ("ZONE REACTION", "MARKET STRUCTURE", "CANDLE BEHAVIOUR", "MARKET REGIME")]
    scores = result.get("brain_scores") or (result.get("fusion") or {}).get("scores") or {}
    call_score = float(scores.get("CALL", 0) or 0)
    put_score = float(scores.get("PUT", 0) or 0)
    vals = []
    if candles is not None and len(candles) >= 6:
        d = candles.copy().reset_index(drop=True)
        last = d.iloc[-1]
        close = float(last.close)
        span = max(float(last.high) - float(last.low), 1e-12)
        atr = float((d.high - d.low).tail(20).mean())
        atr = max(atr, abs(close) * 1e-8, 1e-12)
        body = float(last.close) - float(last.open)
        upper = float(last.high) - max(float(last.open), float(last.close))
        lower = min(float(last.open), float(last.close)) - float(last.low)
        close_loc = (close - float(last.low)) / span
        returns = []
        for n in (1, 3, 5):
            prev = float(d.close.iloc[-1-n])
            returns.append((close - prev) / atr)
        ema9 = float(d.close.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(d.close.ewm(span=21, adjust=False).mean().iloc[-1])
        sr = result.get("support_resistance") or {}
        support = sr.get("support")
        resistance = sr.get("resistance")
        sd = (close - float(support)) / atr if support is not None else 10.0
        rd = (float(resistance) - close) / atr if resistance is not None else 10.0
        try:
            stamp = pd.Timestamp(last.datetime)
            hour = stamp.hour + stamp.minute / 60.0
        except Exception:
            hour = now_cat().hour
        patterns = " ".join(str(x).upper() for x in (result.get("candle_bible") or {}).get("patterns", []))
        sakata = " ".join(str(x).upper() for x in (result.get("sakata") or {}).get("observations", []))
        candle_bias = 1.0 if any(x in patterns for x in ("BULLISH", "HAMMER", "MORNING STAR")) else -1.0 if any(x in patterns for x in ("BEARISH", "SHOOTING", "EVENING STAR")) else 0.0
        sakata_bias = 1.0 if "BULLISH" in sakata else -1.0 if "BEARISH" in sakata else 0.0
        vals = [body/span, upper/span, lower/span, close_loc, *returns,
                (ema9-ema21)/atr, max(-10,min(10,sd)), max(-10,min(10,rd)),
                candle_bias, sakata_bias, np.sin(2*np.pi*hour/24), np.cos(2*np.pi*hour/24)]
    else:
        vals = [0.0] * 14
    zone = result.get("zone_analysis") or {}
    sz = zone.get("support_zone") or {}
    rz = zone.get("resistance_zone") or {}
    zone_features = [
        min(5.0, float(zone.get("support_score", 0) or 0)),
        min(5.0, float(zone.get("resistance_score", 0) or 0)),
        max(-10.0, min(10.0, float(sz.get("distance_atr", 10) or 10))),
        max(-10.0, min(10.0, float(rz.get("distance_atr", 10) or 10))),
    ]
    vector = np.asarray(votes + [call_score, put_score, call_score-put_score] + vals + zone_features, dtype=float)
    if vector.size != len(FEATURE_NAMES):
        vector = np.resize(vector, len(FEATURE_NAMES))
    return np.nan_to_num(vector, nan=0.0, posinf=0.0, neginf=0.0).tolist()


def train_experience_model(market, instrument, db_path=None, minimum_samples=250):
    """Fit regularized logistic regression on older data and validate on a later holdout."""
    init_learning_db(db_path)
    with _learning_connect(db_path) as conn:
        rows = conn.execute("""SELECT id,features,outcome FROM observations
            WHERE market=? AND instrument=? AND outcome IN ('UP','DOWN') AND features IS NOT NULL
            ORDER BY observed_at,id""", (market, instrument)).fetchall()
    parsed = []
    for row in rows:
        try:
            x = json.loads(row["features"])
            if len(x) == len(FEATURE_NAMES):
                parsed.append((np.asarray(x, dtype=float), 1.0 if row["outcome"] == "UP" else 0.0))
        except Exception:
            continue
    n = len(parsed)
    model = {"ready": False, "samples": n, "minimum_samples": minimum_samples,
             "training_examples": 0, "validation_examples": 0,
             "balanced_accuracy": None, "validation_accuracy": None,
             "majority_baseline": None, "probability_up": None,
             "status": "COLLECTING EXPERIENCE", "feature_names": list(FEATURE_NAMES)}
    if n < minimum_samples:
        model["status"] = f"COLLECTING · {n}/{minimum_samples} resolved examples"
        return model
    X = np.vstack([p[0] for p in parsed])
    y = np.asarray([p[1] for p in parsed], dtype=float)
    split = max(int(n * 0.8), n - 200)
    split = min(max(split, 100), n - 50)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]
    if min(np.sum(y_train == 0), np.sum(y_train == 1), np.sum(y_val == 0), np.sum(y_val == 1)) < 8:
        model["status"] = "NOT TRAINABLE · outcome classes are too imbalanced"
        return model
    mean = X_train.mean(axis=0)
    scale = X_train.std(axis=0)
    scale[scale < 1e-8] = 1.0
    A = np.clip((X_train-mean)/scale, -8, 8)
    B = np.clip((X_val-mean)/scale, -8, 8)
    A = np.column_stack([np.ones(len(A)), A])
    B = np.column_stack([np.ones(len(B)), B])
    w = np.zeros(A.shape[1], dtype=float)
    for _ in range(500):
        z = np.clip(A @ w, -25, 25)
        p = 1.0 / (1.0 + np.exp(-z))
        grad = (A.T @ (p-y_train))/len(y_train)
        grad[1:] += 0.02*w[1:]
        w -= 0.08*grad
    pv = 1.0/(1.0+np.exp(-np.clip(B@w,-25,25)))
    pred = (pv >= 0.5).astype(float)
    accuracy = float(np.mean(pred == y_val))
    recalls = []
    for cls in (0.0, 1.0):
        mask = y_val == cls
        recalls.append(float(np.mean(pred[mask] == cls)))
    balanced = float(np.mean(recalls))
    majority = max(float(np.mean(y_val == 0)), float(np.mean(y_val == 1)))
    trusted = balanced >= 0.53 and accuracy >= majority + 0.01
    if balanced >= 0.60 and accuracy >= majority + 0.03:
        reliability = "STRONGER VALIDATION"
    elif trusted:
        reliability = "DEVELOPING · PASSES MINIMUM VALIDATION"
    else:
        reliability = "WEAK VALIDATION · RULES REMAIN IN CONTROL"

    trained_through_id = int(rows[split-1]["id"])
    validated_at = datetime.now(TZ).isoformat()
    with _learning_connect(db_path) as conn:
        conn.execute("""INSERT OR IGNORE INTO experience_validation_history
            (market,instrument,trained_through_id,validated_at,samples,training_examples,
             validation_examples,validation_accuracy,balanced_accuracy,majority_baseline,
             validation_down,validation_up)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (market, instrument, trained_through_id, validated_at, n, len(y_train), len(y_val),
             accuracy, balanced, majority, int(np.sum(y_val == 0)), int(np.sum(y_val == 1))))
        history_rows = conn.execute("""SELECT validated_at,samples,training_examples,
            validation_examples,validation_accuracy,balanced_accuracy,majority_baseline
            FROM experience_validation_history WHERE market=? AND instrument=?
            ORDER BY validated_at DESC LIMIT 20""", (market, instrument)).fetchall()
    history = [dict(row) for row in reversed(history_rows)]
    model.update({"ready": trusted, "samples": n, "training_examples": len(y_train),
                  "validation_examples": len(y_val), "validation_down": int(np.sum(y_val == 0)),
                  "validation_up": int(np.sum(y_val == 1)), "validation_accuracy": accuracy,
                  "balanced_accuracy": balanced, "majority_baseline": majority,
                  "reliability": reliability, "status": "VALIDATED MODEL · " + reliability,
                  "weights": w.tolist(), "mean": mean.tolist(), "scale": scale.tolist(),
                  "trained_through_id": trained_through_id, "validation_history": history})
    return model


def predict_experience(model, features):
    if not model or not model.get("ready"):
        return None
    x = np.asarray(features, dtype=float)
    mean = np.asarray(model["mean"], dtype=float)
    scale = np.asarray(model["scale"], dtype=float)
    scale[scale < 1e-8] = 1.0
    a = np.concatenate([[1.0], np.clip((x-mean)/scale, -8, 8)])
    w = np.asarray(model["weights"], dtype=float)
    return float(1.0/(1.0+np.exp(-np.clip(a@w,-25,25))))


def apply_experience_gate(result, model, candles=None):
    """AI is a cautious meta-filter, never an invented standalone signal."""
    result = dict(result or {})
    features = build_learning_features(result, candles)
    probability = predict_experience(model, features)
    model_view = {k:v for k,v in (model or {}).items() if k not in ("weights","mean","scale")}
    model_view["probability_up"] = probability
    model_view["feature_schema"] = "GHOST_4_6_ZONE_V1"
    result["experience_ai"] = model_view
    candidate = result.get("signal")
    if probability is not None and candidate in ("CALL","PUT"):
        agrees = probability >= 0.58 if candidate == "CALL" else probability <= 0.42
        if not agrees:
            result["signal"] = "WAIT"
            result["stage"] = "AI DISAGREEMENT / WAIT"
            result["reason"] = (f"Zone-reaction candidate {candidate} did not pass GHOST's validated experience model "
                                f"(estimated UP probability {probability:.0%}). Candidate cancelled.")
    return result


LEARNING_DB = os.getenv("GHOST_DB_PATH", "ghost_learning.sqlite3")
BRAIN_NAMES = ("ZONE REACTION", "MARKET STRUCTURE", "CANDLE BEHAVIOUR", "MARKET REGIME")


@contextmanager
def _learning_connect(db_path=None):
    conn = sqlite3.connect(db_path or LEARNING_DB, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_learning_db(db_path=None):
    with _learning_connect(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL, instrument TEXT NOT NULL, candle_key TEXT NOT NULL,
            observed_at TEXT NOT NULL, reference_price REAL NOT NULL,
            brain_votes TEXT NOT NULL, brain_scores TEXT NOT NULL,
            state TEXT NOT NULL, evidence TEXT NOT NULL,
            resolved_at TEXT, future_price REAL, outcome TEXT, features TEXT,
            UNIQUE(market, instrument, candle_key)
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(observations)").fetchall()}
        if "features" not in columns:
            conn.execute("ALTER TABLE observations ADD COLUMN features TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_pending ON observations(market,instrument,resolved_at,observed_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS experience_validation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL, instrument TEXT NOT NULL,
            trained_through_id INTEGER NOT NULL, validated_at TEXT NOT NULL,
            samples INTEGER NOT NULL, training_examples INTEGER NOT NULL,
            validation_examples INTEGER NOT NULL, validation_accuracy REAL NOT NULL,
            balanced_accuracy REAL NOT NULL, majority_baseline REAL NOT NULL,
            validation_down INTEGER NOT NULL, validation_up INTEGER NOT NULL,
            UNIQUE(market,instrument,trained_through_id)
        )""")


def record_learning_observation(market, instrument, result, db_path=None, observed_at=None, candles=None):
    """Store one completed-candle snapshot per instrument, even when GHOST says WAIT."""
    if not isinstance(result, dict):
        return False
    price = result.get("price")
    if price is None:
        price = result.get("entry_point")
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False
    stamp = observed_at or now_cat()
    if hasattr(stamp, "isoformat"):
        stamp_text = stamp.isoformat()
    else:
        stamp_text = str(stamp)
    candle_key = str(result.get("candle_time") or stamp_text[:16])
    brains = result.get("brains") or {}
    votes = {name: str((brains.get(name) or {}).get("vote", "WAIT")) for name in BRAIN_NAMES}
    scores = result.get("brain_scores") or (result.get("fusion") or {}).get("scores") or {}
    features = build_learning_features(result, candles)
    evidence = {
        "reason": result.get("reason", ""),
        "stage": result.get("stage", "SCANNING"),
        "patterns": (result.get("candle_bible") or {}).get("patterns", []),
        "sakata": (result.get("sakata") or {}).get("observations", []),
        "support_resistance": result.get("support_resistance", {}),
        "three_steps": result.get("three_steps_result", {}),
        "fusion_state": (result.get("fusion") or {}).get("state", "UNKNOWN"),
    }
    init_learning_db(db_path)
    with _learning_connect(db_path) as conn:
        cur = conn.execute("""INSERT OR IGNORE INTO observations
            (market,instrument,candle_key,observed_at,reference_price,brain_votes,brain_scores,state,evidence,features)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (market, instrument, candle_key, stamp_text, price,
             json.dumps(votes), json.dumps(scores), str(result.get("stage", "SCANNING")),
             json.dumps(evidence, default=str), json.dumps(features)))
        inserted = cur.rowcount > 0
    if inserted and supabase_cloud_enabled():
        result_sync = sync_learning_cloud(db_path, upload=True, download=False)
        if not result_sync.get("ok"):
            st.session_state["ghost_cloud_sync_result"] = result_sync
    return inserted


def resolve_learning_observations(market, instrument, current_price, db_path=None, now=None, horizon_seconds=60):
    """Label old observations using only a later observed price, never future data at scan time."""
    try:
        current_price = float(current_price)
    except (TypeError, ValueError):
        return 0
    now = now or now_cat()
    now_dt = as_cat(now).to_pydatetime() if not isinstance(now, datetime) else as_cat(now).to_pydatetime()
    init_learning_db(db_path)
    updated = 0
    with _learning_connect(db_path) as conn:
        rows = conn.execute("""SELECT id,observed_at,reference_price FROM observations
            WHERE market=? AND instrument=? AND resolved_at IS NULL""", (market, instrument)).fetchall()
        for row in rows:
            try:
                created = as_cat(row["observed_at"]).to_pydatetime()
            except Exception:
                continue
            if (now_dt - created).total_seconds() < horizon_seconds:
                continue
            ref = float(row["reference_price"])
            delta = current_price - ref
            # Ignore movements too small to distinguish from quote noise.
            threshold = max(abs(ref) * 0.00002, 1e-8)
            outcome = "UP" if delta > threshold else "DOWN" if delta < -threshold else "FLAT"
            conn.execute("UPDATE observations SET resolved_at=?,future_price=?,outcome=? WHERE id=?",
                         (now_dt.isoformat(), current_price, outcome, row["id"]))
            updated += 1
    if updated and supabase_cloud_enabled():
        result_sync = sync_learning_cloud(db_path, upload=True, download=False)
        if not result_sync.get("ok"):
            st.session_state["ghost_cloud_sync_result"] = result_sync
    return updated


def learning_profile(market, instrument, db_path=None, minimum_samples=30):
    """Transparent empirical calibration. No adaptation until enough out-of-sample labels exist."""
    init_learning_db(db_path)
    stats = {name: {"samples": 0, "wins": 0, "accuracy": None, "multiplier": 1.0} for name in BRAIN_NAMES}
    with _learning_connect(db_path) as conn:
        rows = conn.execute("SELECT brain_votes,outcome FROM observations WHERE market=? AND instrument=? AND outcome IN ('UP','DOWN')",
                            (market, instrument)).fetchall()
    for row in rows:
        try:
            votes = json.loads(row["brain_votes"])
        except Exception:
            continue
        outcome = row["outcome"]
        for name in BRAIN_NAMES:
            vote = votes.get(name, "WAIT")
            if vote not in ("CALL", "PUT"):
                continue
            item = stats[name]
            item["samples"] += 1
            if (vote == "CALL" and outcome == "UP") or (vote == "PUT" and outcome == "DOWN"):
                item["wins"] += 1
    multipliers = {}
    for name, item in stats.items():
        n = item["samples"]
        if n:
            accuracy = item["wins"] / n
            item["accuracy"] = accuracy
        if n >= minimum_samples:
            # Conservative shrinkage around neutral; cap influence at +/-10%.
            smoothed = (item["wins"] + 10.0) / (n + 20.0)
            multiplier = max(0.90, min(1.10, 1.0 + (smoothed - 0.5) * 0.40))
            item["multiplier"] = round(multiplier, 3)
        multipliers[name] = item["multiplier"]
    return {"stats": stats, "multipliers": multipliers,
            "resolved_observations": len(rows), "minimum_samples": minimum_samples}


def learning_export_bytes(db_path=None):
    import csv
    import io
    init_learning_db(db_path)
    with _learning_connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM observations ORDER BY observed_at").fetchall()
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([dict(row) for row in rows])
    return out.getvalue().encode("utf-8")


def import_learning_csv(file_bytes, db_path=None):
    """Restore a previously exported GHOST experience CSV without duplicating rows."""
    import csv
    import io
    required = {"market", "instrument", "candle_key", "observed_at", "reference_price",
                "brain_votes", "brain_scores", "state", "evidence"}
    text = file_bytes.decode("utf-8-sig") if isinstance(file_bytes, bytes) else str(file_bytes)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("This file is not a compatible GHOST learning-history export.")
    init_learning_db(db_path)
    imported = 0
    with _learning_connect(db_path) as conn:
        for row in reader:
            cur = conn.execute("""INSERT OR IGNORE INTO observations
                (market,instrument,candle_key,observed_at,reference_price,brain_votes,brain_scores,state,evidence,resolved_at,future_price,outcome,features)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row.get("market"), row.get("instrument"), row.get("candle_key"), row.get("observed_at"),
                 float(row.get("reference_price") or 0), row.get("brain_votes") or "{}", row.get("brain_scores") or "{}",
                 row.get("state") or "SCANNING", row.get("evidence") or "{}", row.get("resolved_at") or None,
                 float(row["future_price"]) if row.get("future_price") not in (None, "") else None,
                 row.get("outcome") or None, row.get("features") or None))
            imported += max(0, cur.rowcount)
    return imported


# ============================================================
# SUPABASE CLOUD LEARNING PERSISTENCE
# ============================================================
def _supabase_config():
    try:
        url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
        key = str(st.secrets.get("SUPABASE_KEY", "")).strip()
    except Exception:
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_KEY", "").strip()
    return url, key


def supabase_cloud_enabled():
    url, key = _supabase_config()
    return bool(url and key)


def sync_learning_cloud(db_path=None, *, upload=True, download=True):
    """Two-way SQLite/Supabase sync; restore and merge cloud rows before uploading."""
    url, key = _supabase_config()
    if not (url and key):
        return {"ok": False, "message": "Supabase credentials are not configured.", "uploaded": 0, "downloaded": 0}
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}
    endpoint = f"{url}/rest/v1/observations"
    uploaded = downloaded = 0
    try:
        init_learning_db(db_path)

        # IMPORTANT: restore first. A local pending copy can contain NULL outcome/features
        # while the cloud copy already has the resolved learning result. Downloading first
        # and merging with COALESCE prevents the subsequent upsert from erasing that result.
        if download:
            read_headers = dict(headers)
            read_headers["Prefer"] = "count=exact"
            response = requests.get(endpoint, params={"select": "*", "order": "id.asc", "limit": 1000},
                                    headers=read_headers, timeout=25)
            response.raise_for_status()
            remote_rows = response.json()
            with _learning_connect(db_path) as conn:
                for row in remote_rows:
                    conn.execute("""INSERT INTO observations
                        (market,instrument,candle_key,observed_at,reference_price,brain_votes,brain_scores,state,evidence,resolved_at,future_price,outcome,features)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(market,instrument,candle_key) DO UPDATE SET
                        resolved_at=COALESCE(excluded.resolved_at, observations.resolved_at),
                        future_price=COALESCE(excluded.future_price, observations.future_price),
                        outcome=COALESCE(excluded.outcome, observations.outcome),
                        features=COALESCE(excluded.features, observations.features)""",
                        (row.get("market"), row.get("instrument"), row.get("candle_key"),
                         row.get("observed_at"), row.get("reference_price"), row.get("brain_votes") or "{}",
                         row.get("brain_scores") or "{}", row.get("state") or "SCANNING",
                         row.get("evidence") or "{}", row.get("resolved_at"), row.get("future_price"),
                         row.get("outcome"), row.get("features")))
                    downloaded += 1

        # Upload only after cloud history has been merged into SQLite.
        # `uploaded` is rows submitted/upserted, not necessarily brand-new cloud rows.
        if upload:
            with _learning_connect(db_path) as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM observations ORDER BY id").fetchall()]
            for start in range(0, len(rows), 200):
                batch = rows[start:start + 200]
                if not batch:
                    continue
                response = requests.post(endpoint, params={"on_conflict": "market,instrument,candle_key"},
                                         headers=headers, json=batch, timeout=25)
                response.raise_for_status()
                uploaded += len(batch)

        return {"ok": True, "message": "Cloud sync successful.", "uploaded": uploaded, "downloaded": downloaded}
    except Exception as exc:
        return {"ok": False, "message": f"Supabase sync failed: {exc}", "uploaded": uploaded, "downloaded": downloaded}


def cloud_learning_count():
    url, key = _supabase_config()
    if not (url and key):
        return None
    try:
        response = requests.get(f"{url}/rest/v1/observations",
                                params={"select": "id", "limit": 1},
                                headers={"apikey": key, "Authorization": f"Bearer {key}",
                                         "Prefer": "count=exact"}, timeout=15)
        response.raise_for_status()
        content_range = response.headers.get("Content-Range", "")
        return int(content_range.rsplit("/", 1)[-1]) if "/" in content_range else None
    except Exception:
        return None


# Restore cloud history at the start of each Streamlit session, then upload any local-only rows.
if not st.session_state.get("ghost_cloud_initial_sync_done", False):
    _cloud_sync_result = sync_learning_cloud(upload=True, download=True)
    st.session_state["ghost_cloud_initial_sync_done"] = True
    st.session_state["ghost_cloud_sync_result"] = _cloud_sync_result


# ============================================================
# PREDICTIVE SCHEDULED-ENTRY GATE
# ============================================================

def apply_preparation_gate(result, market, instrument, expiry=1, prep_seconds=60):
    """Prepare a future entry at least prep_seconds ahead, then verify at entry."""
    result = dict(result or {})
    pending_all = st.session_state.setdefault("ghost_pending_candidates", {})
    key = f"{market}|{instrument}"
    now_utc = pd.Timestamp.now(tz="UTC")
    candidate = result.get("signal") if result.get("signal") in ("CALL", "PUT") else None
    if result.get("stage") in ("FEED CHECK", "INVALIDATED", "RISK PAUSE", "AI DISAGREEMENT / WAIT") or candidate is None:
        pending_all.pop(key, None)
        return result

    zone_id = str(result.get("zone_id") or f"{candidate}|{result.get('candle_time', '')}")
    pending = pending_all.get(key)
    same_candidate = pending and pending.get("direction") == candidate and pending.get("zone_id") == zone_id
    if same_candidate:
        entry_utc = pd.Timestamp(pending["entry_time"])
        if entry_utc.tzinfo is None:
            entry_utc = entry_utc.tz_localize("UTC")
    else:
        # Stronger zone reactions can target the next minute; developing
        # reactions get two minutes for another candle of evidence.
        evidence_score = float((result.get("fusion") or {}).get("total_score", 0) or 0)
        adaptive_lead = 60 if evidence_score >= 3.5 else 120
        required_notice = max(int(prep_seconds), adaptive_lead)
        earliest = now_utc + pd.Timedelta(seconds=required_notice)
        next_boundary = now_utc.floor("min") + pd.Timedelta(minutes=1)
        if (next_boundary - now_utc).total_seconds() < required_notice:
            next_boundary = earliest.ceil("min")
        entry_utc = next_boundary
        pending = {"direction": candidate, "zone_id": zone_id,
                   "entry_time": entry_utc.isoformat(), "created_at": now_utc.isoformat(),
                   "entry_issued": False}
        pending_all[key] = pending

    seconds_to_entry = (entry_utc - now_utc).total_seconds()
    result["candidate_direction"] = candidate
    result["scheduled_entry_time"] = as_cat(entry_utc).to_pydatetime()
    result["entry_time"] = as_cat(entry_utc).to_pydatetime()
    result["preparation_seconds"] = max(0, int(seconds_to_entry))
    result["entry_notice_rule"] = "Minimum 60 seconds; developing reactions receive a 120-second preparation window."
    if seconds_to_entry > 0:
        result.update({"signal": "WAIT", "stage": "PREPARE",
                       "reason": f"{candidate} opportunity prepared for {as_cat(entry_utc).strftime('%H:%M:%S')} CAT. Market will be rechecked before entry."})
        return result

    elapsed = abs(seconds_to_entry)
    if elapsed <= 15:
        if not pending.get("entry_issued", False):
            pending["entry_issued"] = True
            pending_all[key] = pending
        result.update({"signal": candidate, "stage": "ENTRY READY",
                       "entry_point": float(result.get("price")) if result.get("price") is not None else result.get("entry_point"),
                       "reason": f"Scheduled {candidate} entry time reached at {as_cat(entry_utc).strftime('%H:%M:%S')} CAT. Conditions rechecked; manual entry only."})
        return result
    pending_all.pop(key, None)
    result.update({"signal": "WAIT", "stage": "MISSED ENTRY WINDOW",
                   "reason": "The scheduled entry window passed. GHOST will wait for a fresh zone opportunity rather than issue a late signal."})
    return result

def build_signal_record(market, instrument, result, expiry=1):
    created = now_cat()
    entry_value = result.get("entry_time")
    if entry_value is not None:
        entry = as_cat(entry_value).to_pydatetime()
    else:
        entry = created
    expiration = entry + timedelta(minutes=expiry)

    return {
        "market": market,
        "instrument": instrument,
        "direction": result["signal"],
        "reason": result["reason"],
        "stage": result.get("stage", "ENTRY READY"),
        "pattern": result.get("pattern", ""),
        "entry_point": result.get("entry_point"),
        "signal_created": created.isoformat(),
        "candle_time": as_cat(result["candle_time"]).isoformat(),
        "candle1_time": str(result.get("candle1_time", "")),
        "reference_price": result.get("price"),
        "entry_time": entry.isoformat(),
        "expiry_time": expiration.isoformat(),
        "expiry_minutes": expiry,
        "status": "PREPARE" if result.get("stage") == "PREPARE" else "ENTRY WINDOW"
    }


def build_preparation_record(market, instrument, result, expiry=1):
    """Neutral preparation clock: no CALL/PUT before Candle 2 has closed."""
    entry_value = result.get("entry_time")
    if entry_value is None:
        return None
    entry = as_cat(entry_value).to_pydatetime()
    created = now_cat()
    if entry <= created:
        return None
    return {
        "market": market, "instrument": instrument, "direction": "WAIT",
        "reason": result.get("reason", "Candidate is being prepared; no entry yet."),
        "candidate_direction": result.get("candidate_direction", "WAIT"),
        "stage": "PREPARE", "pattern": result.get("pattern", ""),
        "entry_point": result.get("entry_point"),
        "signal_created": created.isoformat(),
        "candle_time": as_cat(result.get("candle_time", created)).isoformat(),
        "candle1_time": str(result.get("candle1_time", "")),
        "reference_price": result.get("price"),
        "entry_time": entry.isoformat(),
        "expiry_time": (entry + timedelta(minutes=expiry)).isoformat(),
        "expiry_minutes": expiry, "status": "PREPARATION"
    }


def show_signal_pad(signal):
    """Prominent prepared/actionable signal with exact CAT entry clock."""
    if not signal:
        st.markdown("<div class='signal-card signal-wait'><h2>SCANNING ZONES</h2><div class='small-muted'>Monitoring support, resistance and live market reaction. No qualified entry is prepared yet.</div></div>", unsafe_allow_html=True)
        return
    now = now_cat()
    entry = datetime.fromisoformat(signal["entry_time"])
    expiry = datetime.fromisoformat(signal["expiry_time"])
    if entry.tzinfo is None: entry = entry.replace(tzinfo=TZ)
    if expiry.tzinfo is None: expiry = expiry.replace(tzinfo=TZ)
    if now >= expiry:
        st.markdown("<div class='signal-card signal-wait'><h2>SCANNING FOR NEXT OPPORTUNITY</h2><div class='small-muted'>Previous signal window expired.</div></div>", unsafe_allow_html=True)
        return
    prepared = signal.get("stage") == "PREPARE" or signal.get("status") == "PREPARATION"
    if prepared and now >= entry:
        st.markdown("<div class='signal-card signal-wait'><h2>ENTRY RECHECK REQUIRED</h2><div class='small-muted'>The scheduled time arrived, but GHOST has not confirmed the live conditions. Do not enter from an unverified preparation.</div></div>", unsafe_allow_html=True)
        return
    if not prepared and now >= entry + timedelta(seconds=15):
        st.markdown("<div class='signal-card signal-wait'><h2>ENTRY WINDOW CLOSED</h2><div class='small-muted'>The 15-second manual entry window has passed. Waiting for a fresh opportunity.</div></div>", unsafe_allow_html=True)
        return
    direction = signal.get("candidate_direction", "WAIT") if prepared else signal.get("direction", "WAIT")
    if now < entry:
        status = "PREPARED · COUNTDOWN"
        remaining = max(0, int((entry-now).total_seconds()))
    else:
        status = "ENTRY WINDOW · VERIFY MARKET"
        remaining = max(0, int((expiry-now).total_seconds()))
    css = "signal-call" if direction == "CALL" else "signal-put" if direction == "PUT" else "signal-wait"
    label = "RISE / CALL" if direction == "CALL" else "FALL / PUT" if direction == "PUT" else "SCANNING"
    entry_label = entry.strftime("%H:%M:%S")
    st.markdown(
        f"<div class='signal-card {css}'><div class='small-muted'>GHOST 4.6 · {signal.get('instrument','')}</div>"
        f"<h1 style='font-size:30px;margin:2px 0'>{label}</h1><div><b>{status}</b></div>"
        f"<div style='font-size:15px;margin-top:6px'>SCHEDULED ENTRY · <b>{entry_label} CAT</b></div>"
        f"<div class='small-muted'>{signal.get('reason','')}</div></div>",
        unsafe_allow_html=True
    )
    a, b, c = st.columns(3)
    a.metric("COUNTDOWN", f"{remaining//60:02d}:{remaining%60:02d}")
    b.metric("ENTRY (CAT)", entry.strftime("%H:%M:%S"))
    c.metric("EXPIRY (CAT)", expiry.strftime("%H:%M:%S"))


# ============================================================
# CHARTS
# ============================================================

def chart(df, title, levels=None):
    view = df.tail(110).copy()
    fig = go.Figure(go.Candlestick(
        x=view.datetime, open=view.open, high=view.high, low=view.low, close=view.close,
        name="LIVE 1M", increasing=dict(line=dict(color="#16c784",width=1),fillcolor="#16c784"),
        decreasing=dict(line=dict(color="#ea3943",width=1),fillcolor="#ea3943")
    ))
    if levels:
        support=levels.get("support") if isinstance(levels,dict) else None
        resistance=levels.get("resistance") if isinstance(levels,dict) else None
        sz = levels.get("support_zone") if isinstance(levels,dict) else None
        rz = levels.get("resistance_zone") if isinstance(levels,dict) else None
        if sz and sz.get("low") is not None and sz.get("high") is not None:
            fig.add_hrect(y0=float(sz["low"]), y1=float(sz["high"]), fillcolor="#2878ff", opacity=0.16, line_width=0,
                          annotation_text="SUPPORT ZONE", annotation_position="bottom right")
        elif support is not None:
            fig.add_hline(y=float(support),line_dash="dot",line_color="#2878ff",line_width=1.4,annotation_text="SUPPORT",annotation_position="bottom right")
        if rz and rz.get("low") is not None and rz.get("high") is not None:
            fig.add_hrect(y0=float(rz["low"]), y1=float(rz["high"]), fillcolor="#a45bd0", opacity=0.16, line_width=0,
                          annotation_text="RESISTANCE ZONE", annotation_position="top right")
        elif resistance is not None:
            fig.add_hline(y=float(resistance),line_dash="dot",line_color="#a45bd0",line_width=1.4,annotation_text="RESISTANCE",annotation_position="top right")
    fig.update_layout(
        title=dict(text=title,font=dict(size=15,color="#ffffff")),
        height=340, paper_bgcolor="#111a32", plot_bgcolor="#111a32",
        font=dict(color="#ffffff",family="Arial"),
        xaxis_rangeslider_visible=False,
        margin=dict(l=8,r=8,t=42,b=8),
        xaxis=dict(showgrid=True,gridcolor="#26375d",zerolinecolor="#4764a8",rangeslider=dict(visible=False),tickfont=dict(color="#dbe5ff")),
        yaxis=dict(showgrid=True,gridcolor="#26375d",side="right",zerolinecolor="#4764a8",tickfont=dict(color="#dbe5ff")),
        showlegend=False
    )
    return fig


# ============================================================
# SIDEBAR CONTROLS
# ============================================================

with st.sidebar:
    st.header("GHOST CONTROL DECK")

    market = st.radio(
        "Market engine",
        [
            "Pocket Option Forex · ZONE INTELLIGENCE",
            "Deriv Synthetics · GHOST PROTOCOL"
        ],
        index=1,
        key="ghost_market_engine"
    )
    st.markdown("<div class='ghost-zone-status'><b>4.6 INTELLIGENCE</b><br>Zone reactions · Predictive entry · CAT clock</div>", unsafe_allow_html=True)
    if market.startswith("Pocket"):
        old_feed = st.session_state.pop("deriv_live_feed", None)
        st.session_state.pop("deriv_live_symbol", None)
        st.session_state.pop("deriv_historical_candles", None)
        st.session_state.pop("deriv_mtf_history", None)
        st.session_state.pop("deriv_mtf_errors", None)
        if old_feed is not None:
            old_feed.stop()

    expiry = st.selectbox(
        "Signal expiry",
        [1, 2, 3, 5],
        index=0,
        format_func=lambda n: f"{n} minute(s)"
    )

    candles_count = st.slider(
        "Forex candles to analyze",
        80, 300, 160, 20
    )

    auto_refresh = st.checkbox(
        "Refresh dashboard automatically",
        value=True
    )
    auto_scan = st.checkbox(
        "Automatically scan",
        value=True
    )
    if st.button("STOP DERIV LIVE STREAM", use_container_width=True):
        old_feed = st.session_state.pop("deriv_live_feed", None)
        st.session_state.pop("deriv_live_symbol", None)
        st.session_state.pop("deriv_historical_candles", None)
        st.session_state.pop("deriv_mtf_history", None)
        st.session_state.pop("deriv_mtf_errors", None)
        st.session_state["stop_stream_requested"] = True
        if old_feed is not None:
            old_feed.stop()
        st.session_state.pop("deriv_output", None)
        st.session_state.pop("active_signal", None)
        st.success("Deriv stream stopped and active signal cleared.")

    st.caption(
        "Deriv keeps a persistent live tick subscription; the dashboard refreshes every 2 seconds. "
        "Forex scans once per minute."
    )
    st.divider()

    if market.startswith("Pocket"):
        api_key = st.text_input(
            "Twelve Data API key",
            value=get_secret_api_key(),
            type="password"
        )
        pairs = st.multiselect(
            "Forex pairs",
            FOREX_PAIRS,
            default=FOREX_PAIRS
        )
        chart_pair = st.selectbox("Chart instrument", pairs or FOREX_PAIRS, key="ghost_chart_pair")
        pivot_strength = st.slider("Swing confirmation", 2, 4, 2)
        min_steps = st.slider("Minimum staircase steps", 3, 5, 3)
        pullback_pct = st.slider(
            "Maximum pullback (%)", 20, 70, 50, 5
        )
        scan = st.button(
            "SCAN FOREX",
            type="primary",
            use_container_width=True
        )
    else:
        st.markdown("**GHOST market**")
        st.write(GHOST_NAME)
        st.caption(f"Deriv symbol target: {GHOST_SYMBOL}")
        scan = st.button(
            "CONNECT & SCAN GHOST",
            type="primary",
            use_container_width=True
        )
        st.caption(
            "Public Deriv market data only. No account login, "
            "password, App ID or trade execution is used."
        )


# ============================================================
# AUTO REFRESH AND SCAN SCHEDULER
# ============================================================

if st.session_state.pop("stop_stream_requested", False):
    auto_scan = False

# A slightly slower UI refresh reduces visible redraw/flicker while keeping
# the persistent Deriv tick subscription running between dashboard updates.
# The analysis scheduler below remains unchanged.
if auto_refresh:
    st_autorefresh(interval=2000, key="desk_clock")

now = now_cat()
st.caption(
    f"LOCAL TIME · {now.strftime('%A, %d %B %Y · %H:%M:%S CAT')}"
)

scan_interval = 2 if market.startswith("Deriv") else 60
scan_slot = int(time.time() // scan_interval)
last_slot = st.session_state.get("last_auto_scan_slot")

auto_scan_due = auto_scan and scan_slot != last_slot
pending_prefix = "GHOST PROTOCOL|" if market.startswith("Deriv") else "GHOST ZONE FOREX|"
pending_due = any(
    key.startswith(pending_prefix)
    and now_cat() >= datetime.fromisoformat(item.get("entry_at", now_cat().isoformat()))
    for key, item in st.session_state.get("ghost_pending_candidates", {}).items()
)
run_scan = bool(scan or auto_scan_due or pending_due)

if run_scan:
    if auto_scan_due:
        st.session_state["last_auto_scan_slot"] = scan_slot

    if market.startswith("Pocket"):
        if not api_key:
            st.error(
                "Add your Twelve Data key in the sidebar "
                "or Streamlit Secrets."
            )
        elif not pairs:
            st.warning("Select at least one Forex pair.")
        else:
            output = []
            progress = st.progress(0)
            note = st.empty()

            for i, pair in enumerate(pairs):
                note.write(f"Scanning {pair}...")
                try:
                    df = fetch_forex(pair, api_key, candles_count)
                    result = three_steps(
                        df, pivot_strength, min_steps, pullback_pct
                    )
                    profile = learning_profile("FOREX", pair)
                    result = four_brain_decision(df, result, pivot_strength, min_steps, pullback_pct,
                                                 learned_weights=profile["multipliers"], structure_candles=aggregate_timeframe(df, 5))
                    result["learning_profile"] = profile
                    record_learning_observation("FOREX", pair, result, candles=df)
                    resolve_learning_observations("FOREX", pair, result.get("price"))
                    model_key = f"FOREX|{pair}|GHOST_4_6_ZONE_V1"
                    model_cache = st.session_state.setdefault("ghost_experience_models", {})
                    if model_key not in model_cache or int(time.time()) - model_cache[model_key].get("cached_at", 0) >= 60:
                        trained = train_experience_model("FOREX", pair)
                        model_cache[model_key] = {**trained, "cached_at": int(time.time())}
                    result = apply_experience_gate(result, model_cache[model_key], df)
                    result = apply_preparation_gate(result, "GHOST ZONE FOREX", pair, expiry)
                    if result.get("stage") == "ENTRY READY" and result.get("signal") in ("CALL", "PUT"):
                        st.session_state["ghost_last_candidate"] = {"market": "FOREX", "instrument": pair, "result": result, "regime": (result.get("market_regime") or {}).get("tag", "UNKNOWN")}
                    output.append({
                        "instrument": pair,
                        "df": df,
                        "result": result
                    })
                except Exception as exc:
                    output.append({
                        "instrument": pair,
                        "error": str(exc)
                    })

                progress.progress((i + 1) / len(pairs))

            note.empty()
            st.session_state["scan_output"] = output
            st.session_state["scan_market"] = "forex"

            candidates = [
                item for item in output
                if item.get("result", {}).get("signal") in ("CALL", "PUT")
                and item.get("result", {}).get("stage") == "ENTRY READY"
            ]
            preparing = [
                item for item in output
                if item.get("result", {}).get("stage") == "PREPARE"
            ]

            if candidates:
                chosen = max(candidates, key=lambda item: item["result"].get("candle_time", ""))
                existing = st.session_state.get("active_signal")
                same_active = (existing and existing.get("market") == "GHOST ZONE FOREX"
                               and existing.get("instrument") == chosen["instrument"]
                               and existing.get("direction") == chosen["result"].get("signal")
                               and str(existing.get("candle_time", "")) == str(chosen["result"].get("candle_time", "")))
                if not same_active:
                    st.session_state["active_signal"] = build_signal_record(
                        "GHOST ZONE FOREX", chosen["instrument"], chosen["result"], expiry)
            elif preparing:
                chosen = max(preparing, key=lambda item: item["result"].get("candle_time", ""))
                prep = build_preparation_record(
                    "GHOST ZONE FOREX", chosen["instrument"], chosen["result"], expiry)
                if prep is not None:
                    st.session_state["active_signal"] = prep
            else:
                active = st.session_state.get("active_signal")
                if active and active.get("market") == "GHOST ZONE FOREX":
                    st.session_state.pop("active_signal", None)

    else:
        try:
            with st.spinner("Starting or refreshing the persistent Deriv public tick stream..."):
                existing_feed = st.session_state.get("deriv_live_feed")
                existing_symbol = st.session_state.get("deriv_live_symbol")
                if existing_feed is None or existing_symbol != GHOST_SYMBOL:
                    if existing_feed is not None:
                        existing_feed.stop()
                    with DerivClient(timeout=25) as deriv:
                        symbols = deriv_symbols(deriv)
                        selected = next((item for item in symbols if item.get("symbol") == GHOST_SYMBOL), None)
                        if selected is None:
                            raise RuntimeError(f"{GHOST_SYMBOL} was not found in Deriv's active-symbol list.")
                        seed = fetch_deriv_ticks(selected["symbol"], 5000, deriv)
                        historical_candles = fetch_deriv_candle_history(selected["symbol"], 5000, deriv, 60)
                        mtf_history, mtf_errors = fetch_deriv_mtf_history(selected["symbol"], deriv)
                    feed = DerivLiveFeed(GHOST_SYMBOL, seed_ticks=seed).start()
                    st.session_state["deriv_live_feed"] = feed
                    st.session_state["deriv_live_symbol"] = GHOST_SYMBOL
                    st.session_state["deriv_historical_candles"] = historical_candles
                    st.session_state["deriv_mtf_history"] = mtf_history
                    st.session_state["deriv_mtf_errors"] = mtf_errors
                else:
                    feed = existing_feed
                ticks = feed.snapshot()
                feed_status = feed.status()
                if ticks.empty or len(ticks) < 120:
                    raise RuntimeError("Deriv stream is starting; waiting for sufficient initial tick history.")
                result = ghost_protocol(ticks)
                candles = merge_candle_history(ticks_to_candles(ticks), st.session_state.get("deriv_historical_candles"))
                closed_brain_candles = candles.copy()
                closed_brain_candles["datetime"] = pd.to_datetime(closed_brain_candles["datetime"], utc=True)
                closed_brain_candles = closed_brain_candles[closed_brain_candles.datetime + pd.Timedelta(minutes=1) <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True)
                profile = learning_profile("DERIV", GHOST_NAME)
                _forming_bar = None
                if not candles.empty:
                    _last_bar = candles.iloc[-1]
                    _last_bar_time = pd.Timestamp(_last_bar.datetime)
                    if _last_bar_time.floor("min") == pd.Timestamp.now(tz="UTC").floor("min"):
                        _forming_bar = _last_bar
                result = four_brain_decision(closed_brain_candles, result,
                                             learned_weights=profile["multipliers"],
                                             structure_candles=aggregate_timeframe(closed_brain_candles, 5),
                                             forming_candle=_forming_bar)
                result = apply_trade_safety(result, "DERIV", GHOST_NAME, closed_brain_candles)
                result["learning_profile"] = profile
                record_learning_observation("DERIV", GHOST_NAME, result, candles=closed_brain_candles)
                resolve_learning_observations("DERIV", GHOST_NAME, result.get("price"))
                model_key = f"DERIV|{GHOST_NAME}|GHOST_4_6_ZONE_V1"
                model_cache = st.session_state.setdefault("ghost_experience_models", {})
                if model_key not in model_cache or int(time.time()) - model_cache[model_key].get("cached_at", 0) >= 60:
                    trained = train_experience_model("DERIV", GHOST_NAME)
                    model_cache[model_key] = {**trained, "cached_at": int(time.time())}
                result = apply_experience_gate(result, model_cache[model_key], closed_brain_candles)
                result = apply_preparation_gate(result, "GHOST PROTOCOL", GHOST_NAME, 1)
                if result.get("stage") == "ENTRY READY" and result.get("signal") in ("CALL", "PUT"):
                    st.session_state["ghost_last_candidate"] = {"market": "DERIV", "instrument": GHOST_NAME, "result": result, "regime": (result.get("market_regime") or {}).get("tag", "UNKNOWN")}

            st.session_state["deriv_output"] = {
                "instrument": GHOST_NAME, "symbol": GHOST_SYMBOL,
                "ticks": ticks, "candles": candles, "result": result,
                "feed_status": feed_status,
                "mtf_history": st.session_state.get("deriv_mtf_history", {}),
                "mtf_errors": st.session_state.get("deriv_mtf_errors", {}),
                "last_scan": now_cat().isoformat()
            }
            st.session_state["scan_market"] = "deriv"
            if result.get("stage") == "ENTRY READY" and result.get("signal") in ("CALL", "PUT"):
                existing = st.session_state.get("active_signal")
                key = (result.get("signal"), str(result.get("candle1_time")), GHOST_NAME)
                old_key = None if not existing else (existing.get("direction"), existing.get("candle1_time"), existing.get("instrument"))
                if key != old_key:
                    st.session_state["active_signal"] = build_signal_record("GHOST PROTOCOL", GHOST_NAME, result, 1)
            elif result.get("stage") in ("SETUP DEVELOPING", "PREPARE"):
                prep = build_preparation_record("GHOST PROTOCOL", GHOST_NAME, result, 1)
                if prep is not None:
                    st.session_state["active_signal"] = prep
            else:
                active = st.session_state.get("active_signal")
                if active and active.get("instrument") == GHOST_NAME:
                    st.session_state.pop("active_signal", None)
            st.session_state.pop("deriv_scan_error", None)
        except Exception as exc:
            st.session_state["deriv_scan_error"] = str(exc)
            st.error(f"GHOST feed/scan issue: {exc}")


def render_chart_area():
    if market.startswith("Pocket"):
        results = st.session_state.get("scan_output", []) if st.session_state.get("scan_market") == "forex" else []
        valid = [x for x in results if "error" not in x and x.get("df") is not None and not x["df"].empty]
        if valid:
            names = [x["instrument"] for x in valid]
            selected_name = st.session_state.get("ghost_chart_pair", names[0])
            if selected_name not in names:
                selected_name = names[0]
            selected = next(x for x in valid if x["instrument"] == selected_name)
            st.plotly_chart(chart(selected["df"], selected_name + " · 1M", selected["result"].get("support_resistance")), use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown("<div class='signal-card signal-wait'><h3>CHART STANDBY</h3></div>", unsafe_allow_html=True)
    else:
        output = st.session_state.get("deriv_output") if st.session_state.get("scan_market") == "deriv" else None
        if output and output.get("candles") is not None and not output["candles"].empty:
            st.plotly_chart(chart(output["candles"], GHOST_NAME + " · LIVE 1M", output["result"].get("support_resistance")), use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown("<div class='signal-card signal-wait'><h3>CHART STANDBY</h3></div>", unsafe_allow_html=True)


def selected_result():
    if market.startswith("Pocket"):
        results = st.session_state.get("scan_output", []) if st.session_state.get("scan_market") == "forex" else []
        valid = [x for x in results if "error" not in x]
        if not valid:
            return None, None
        names = [x["instrument"] for x in valid]
        chosen_name = st.session_state.get("ghost_chart_pair", names[0])
        if chosen_name not in names:
            chosen_name = names[0]
        chosen = next(x for x in valid if x["instrument"] == chosen_name)
        return chosen["result"], chosen_name
    output = st.session_state.get("deriv_output") if st.session_state.get("scan_market") == "deriv" else None
    return (output["result"], GHOST_NAME) if output else (None, None)


# ============================================================
# GHOST TRADING INTERFACE — SIGNALS, TIMERS, LIVE CHART, BACKUP
# ============================================================
active_signal = st.session_state.get("active_signal")
if active_signal:
    try:
        _now_signal = now_cat()
        _entry_signal = datetime.fromisoformat(active_signal["entry_time"])
        if _entry_signal.tzinfo is None: _entry_signal = _entry_signal.replace(tzinfo=TZ)
        _signal_deadline = (_entry_signal + timedelta(seconds=15)
                            if active_signal.get("stage") == "ENTRY READY"
                            else datetime.fromisoformat(active_signal["expiry_time"]))
        if _signal_deadline.tzinfo is None: _signal_deadline = _signal_deadline.replace(tzinfo=TZ)
        if _now_signal >= _signal_deadline:
            st.session_state.pop("active_signal", None)
            active_signal = None
    except Exception:
        st.session_state.pop("active_signal", None)
        active_signal = None

result, instrument_name = selected_result()

st.markdown("<div class='ghost-kicker'>LIVE SIGNAL PAD</div>", unsafe_allow_html=True)
if market.startswith("Deriv"):
    _feed = st.session_state.get("deriv_live_feed")
    _feed_state = _feed.status() if _feed is not None else None
    if _feed_state:
        _age = _feed_state.get("last_tick_age")
        _age_text = "waiting for first live tick" if _age is None else f"last tick {_age:.1f}s ago"
        st.caption(f"DERIV FEED · {'CONNECTED' if _feed_state.get('connected') else 'RECONNECTING'} · {_age_text} · reconnects {_feed_state.get('reconnects', 0)}")
        if _feed_state.get("last_error"):
            st.warning(f"Feed detail: {_feed_state['last_error']}")
    elif st.session_state.get("deriv_scan_error"):
        st.error(f"Deriv connection/scan: {st.session_state['deriv_scan_error']}")
    else:
        st.info("Deriv feed has not started yet. Select Deriv and press CONNECT & SCAN GHOST once; automatic scanning then maintains it.")
show_signal_pad(active_signal)
if result and result.get("stage") and result.get("stage") not in ("ENTRY READY", "PREPARE"):
    _zone = result.get("zone_analysis", {})
    _zone_state = _zone.get("state", result.get("stage", "SCANNING"))
    _brief = ("Monitoring both zones. Waiting for a qualified market reaction."
              if result.get("stage") == "ZONE MONITORING" else result.get("reason", "Monitoring market structure."))
    st.markdown(f"<div class='ghost-zone-status'><b>MARKET READ · {_zone_state}</b><br>{_brief}</div>", unsafe_allow_html=True)
if result:
    with st.expander("GHOST INTELLIGENCE READOUT & LEARNING", expanded=False):
        _brains = result.get("brains", {})
        if _brains:
            for _name in ("ZONE REACTION", "MARKET STRUCTURE", "CANDLE BEHAVIOUR", "MARKET REGIME"):
                _b = _brains.get(_name, {})
                st.write(f"**{_name}** · {_b.get('vote', 'WAIT')} · score {_b.get('score', 0)} · {_b.get('detail', '')}")
        else:
            st.write("Collecting enough completed candles to evaluate the current support/resistance zones.")
        _lp = result.get("learning_profile", {})
        st.write(f"Resolved learning observations: {_lp.get('resolved_observations', 0)}")
        for _name, _stats in _lp.get("stats", {}).items():
            _acc = _stats.get("accuracy")
            st.write(f"{_name}: {_stats.get('samples', 0)} observations · accuracy {'not established' if _acc is None else f'{_acc:.1%}'} · weight {_stats.get('multiplier', 1.0):.3f}")
        _ai = result.get("experience_ai", {})
        if _ai:
            st.write(f"Experience model: {_ai.get('status', 'collecting')} · resolved examples {_ai.get('samples', 0)}")
        _za = result.get("zone_analysis", {})
        if _za:
            st.write(f"Zone state: {_za.get('state')} · support evidence {_za.get('support_score', 0):.2f} · resistance evidence {_za.get('resistance_score', 0):.2f}")
            st.write(f"Zone distances: support {_za.get('support_zone', {}).get('distance_atr', 'n/a')} ATR · resistance {_za.get('resistance_zone', {}).get('distance_atr', 'n/a')} ATR")

if result and result.get("stage") == "PREPARE" and not active_signal:
    st.markdown("<div class='signal-card signal-prepared'><h3>ENTRY PREPARED</h3><div class='small-muted'>GHOST has selected a future entry time and is rechecking the zone reaction.</div></div>", unsafe_allow_html=True)

st.markdown("<div class='ghost-kicker'>LIVE CANDLE CHART</div>", unsafe_allow_html=True)
render_chart_area()

# Detailed intelligence, reasons and model explanations stay in the learning
# observations; the visible interface only exposes backup and restore controls.
st.divider()
st.markdown("<div class='ghost-kicker'>LEARNING DATA · BACKUP & RESTORE</div>", unsafe_allow_html=True)
cloud_status = st.session_state.get("ghost_cloud_sync_result", {})
if cloud_status.get("ok"):
    st.caption(f"Cloud backup synced · uploaded {cloud_status.get('uploaded', 0)} · retrieved {cloud_status.get('downloaded', 0)}")
elif supabase_cloud_enabled():
    st.caption("Cloud backup connection is awaiting verification.")
else:
    st.caption("Local learning database active · cloud backup not configured.")
backup_col, restore_col = st.columns(2)
with backup_col:
    st.download_button(
        "DOWNLOAD LEARNING BACKUP",
        data=learning_export_bytes(),
        file_name="ghost_learning_history.csv",
        mime="text/csv",
        use_container_width=True
    )
with restore_col:
    learning_backup = st.file_uploader(
        "IMPORT LEARNING BACKUP", type=["csv"], key="ghost_learning_restore"
    )
    if learning_backup is not None:
        try:
            restored = import_learning_csv(learning_backup.getvalue())
            cloud_result = sync_learning_cloud(upload=True, download=True)
            if cloud_result.get("ok"):
                st.success(f"Imported {restored} new observations; cloud backup synchronized.")
            else:
                st.warning(f"Imported {restored} observations locally; cloud sync needs attention: {cloud_result.get('message')}")
        except Exception as exc:
            st.error(f"Import failed: {exc}")


# ============================================================
# GHOST 4.6 — MANUAL TRADE OUTCOME FEEDBACK
# ============================================================
st.divider()
st.markdown("<div class='ghost-kicker'>GHOST 4.6 · TRADE OUTCOME JOURNAL</div>", unsafe_allow_html=True)
st.caption("After a demo trade expires, record its actual WIN / LOSS / VOID result. Only these manually confirmed outcomes train setup-specific risk memory.")
_saved_candidate = st.session_state.get("ghost_last_candidate") or {}
active_result = _saved_candidate.get("result")
active_instrument = _saved_candidate.get("instrument")
if active_result and active_instrument and active_result.get("signal") in ("CALL", "PUT"):
    journal_market = _saved_candidate.get("market", "DERIV" if active_instrument == GHOST_NAME else "FOREX")
    regime_tag = _saved_candidate.get("regime", "UNKNOWN")
    outcome_cols = st.columns([1, 1, 2])
    with outcome_cols[0]:
        outcome_choice = st.selectbox("Expired trade result", ["WIN", "LOSS", "VOID"], key="ghost_trade_outcome")
    with outcome_cols[1]:
        if st.button("SAVE TRADE RESULT", use_container_width=True):
            try:
                journal_trade_outcome(journal_market, active_instrument, active_result, outcome_choice, regime_tag)
                st.success("Outcome saved to GHOST's setup memory.")
            except Exception as exc:
                st.error(f"Could not save outcome: {exc}")
    with outcome_cols[2]:
        st.caption(f"Instrument: {active_instrument} · Regime: {regime_tag}")
else:
    st.caption("A directional setup must be selected before you can attach a manual outcome. Use this after a completed demo trade.")
try:
    init_trade_journal()
    with _learning_connect() as _conn:
        _journal_rows = _conn.execute("SELECT created_at,instrument,direction,regime,outcome FROM ghost_trade_journal ORDER BY id DESC LIMIT 20").fetchall()
    if _journal_rows:
        st.dataframe(pd.DataFrame([dict(r) for r in _journal_rows]), use_container_width=True, hide_index=True)
except Exception as _journal_exc:
    st.caption(f"Trade journal is unavailable: {_journal_exc}")

st.markdown("<div class='small-muted' style='text-align:center;font-size:10px'>GHOST 4.6 · ADAPTIVE ZONE INTELLIGENCE · MANUAL ALERTS ONLY</div>", unsafe_allow_html=True)
