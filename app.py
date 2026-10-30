import json
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh


# ============================================================
# PAGE AND SETTINGS
# ============================================================

st.set_page_config(
    page_title="Multi-Timeframe Forex Analyzer",
    page_icon="📈",
    layout="wide",
)

PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY", "USD/ZAR", "EUR/ZAR",
    "AUD/JPY",
]

st.title("📈 Multi-Timeframe Forex Analyzer")
st.caption(
    "15-minute main trend • 5-minute confirmation • "
    "1-minute entry checks • optional Bollinger context"
)

st_autorefresh(interval=60000, key="auto_refresh")


# ============================================================
# TWELVE DATA
# ============================================================

def fetch_candles(symbol, interval, api_key, outputsize):
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "timezone": "UTC",
        "apikey": api_key,
        "format": "JSON",
    })
    url = "https://api.twelvedata.com/time_series?" + params
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ForexAnalyzer/2.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ValueError(
                "API key rejected. Check the TWELVE_DATA_API_KEY Secret or sidebar key."
            ) from exc
        if exc.code == 429:
            raise ValueError(
                "Twelve Data rate or credit limit reached. Wait for the quota to reset."
            ) from exc
        raise ValueError(f"Twelve Data HTTP error: {exc.code}") from exc
    except Exception as exc:
        raise ValueError(f"Unable to retrieve {interval} data: {exc}") from exc

    if "values" not in payload:
        message = payload.get(
            "message",
            payload.get("status", "No candle data returned."),
        )
        raise ValueError(str(message))

    df = pd.DataFrame(payload["values"])
    if df.empty:
        raise ValueError(f"No {interval} candles returned.")

    df["time"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df = (
        df.drop_duplicates(subset=["time"])
        .sort_values("time")
        .reset_index(drop=True)
    )

    if len(df) < 55:
        raise ValueError(
            f"Not enough {interval} candles returned. Need at least 55."
        )
    return df


# Caching reduces API use, but means some data can be delayed.
@st.cache_data(ttl=60, show_spinner=False)
def fetch_1m(symbol, api_key):
    return fetch_candles(symbol, "1min", api_key, 120)


@st.cache_data(ttl=180, show_spinner=False)
def fetch_5m(symbol, api_key):
    return fetch_candles(symbol, "5min", api_key, 100)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_15m(symbol, api_key):
    return fetch_candles(symbol, "15min", api_key, 100)


# ============================================================
# CANDLE FEATURES
# ============================================================

def candle_features(df):
    result = df.copy()

    result["body"] = (result["close"] - result["open"]).abs()
    result["range"] = (result["high"] - result["low"]).clip(lower=1e-12)
    result["body_ratio"] = result["body"] / result["range"]

    result["upper_wick"] = (
        result["high"] - result[["open", "close"]].max(axis=1)
    ).clip(lower=0)
    result["lower_wick"] = (
        result[["open", "close"]].min(axis=1) - result["low"]
    ).clip(lower=0)
    result["upper_wick_ratio"] = result["upper_wick"] / result["range"]
    result["lower_wick_ratio"] = result["lower_wick"] / result["range"]

    result["ema9"] = result["close"].ewm(span=9, adjust=False).mean()
    result["ema21"] = result["close"].ewm(span=21, adjust=False).mean()
    result["ema50"] = result["close"].ewm(span=50, adjust=False).mean()

    # Simple average true range approximation from candle ranges.
    result["atr"] = result["range"].rolling(14, min_periods=5).mean()

    # Standard Bollinger Bands: 20-period SMA +/- 2 standard deviations.
    result["bb_middle"] = result["close"].rolling(20, min_periods=20).mean()
    bb_std = result["close"].rolling(20, min_periods=20).std()
    result["bb_upper"] = result["bb_middle"] + (2.0 * bb_std)
    result["bb_lower"] = result["bb_middle"] - (2.0 * bb_std)
    result["bb_width"] = (
        (result["bb_upper"] - result["bb_lower"])
        / result["bb_middle"].abs().clip(lower=1e-12)
    )

    return result


# ============================================================
# TREND: COMPLETED CANDLES ONLY
# ============================================================

def get_trend(df):
    # Exclude the latest candle because it may still be forming.
    completed = df.iloc[:-1].copy()

    if len(completed) < 50:
        return {
            "direction": "UNCLEAR",
            "strength": "Weak",
            "reason": "Not enough completed candles",
            "data": completed,
        }

    data = candle_features(completed)
    last = data.iloc[-1]
    previous = data.iloc[-4]

    atr = float(last["atr"]) if pd.notna(last["atr"]) else 0.0
    ema_gap = abs(float(last["ema9"] - last["ema21"]))
    slope = float(last["ema9"] - previous["ema9"])

    bullish = (
        last["ema9"] > last["ema21"]
        and last["ema21"] > last["ema50"]
        and last["close"] > last["ema9"]
        and slope > 0
    )
    bearish = (
        last["ema9"] < last["ema21"]
        and last["ema21"] < last["ema50"]
        and last["close"] < last["ema9"]
        and slope < 0
    )

    if bullish:
        direction = "BULLISH"
    elif bearish:
        direction = "BEARISH"
    else:
        direction = "UNCLEAR"

    if direction != "UNCLEAR" and atr > 0 and ema_gap >= atr * 0.12:
        strength = "Strong"
    elif direction != "UNCLEAR" and atr > 0 and ema_gap >= atr * 0.06:
        strength = "Moderate"
    else:
        strength = "Weak"

    reason = (
        f"EMA 9/21/50 alignment; EMA gap {ema_gap:.6f}; "
        f"average candle range {atr:.6f}"
    )
    return {
        "direction": direction,
        "strength": strength,
        "reason": reason,
        "data": data,
    }


# ============================================================
# CONFIRMED SWINGS AND SUPPORT / RESISTANCE
# ============================================================

def find_swings(df, side, left=2, right=2):
    swings = []

    # A swing is only marked after the right-side candles exist.
    for i in range(left, len(df) - right):
        if side == "high":
            value = float(df.iloc[i]["high"])
            left_ok = all(
                value > float(df.iloc[i - j]["high"])
                for j in range(1, left + 1)
            )
            right_ok = all(
                value >= float(df.iloc[i + j]["high"])
                for j in range(1, right + 1)
            )
        else:
            value = float(df.iloc[i]["low"])
            left_ok = all(
                value < float(df.iloc[i - j]["low"])
                for j in range(1, left + 1)
            )
            right_ok = all(
                value <= float(df.iloc[i + j]["low"])
                for j in range(1, right + 1)
            )

        if left_ok and right_ok:
            swings.append({
                "time": df.iloc[i]["time"],
                "price": value,
            })

    return swings


def group_levels(swings, tolerance):
    groups = []

    for swing in sorted(swings, key=lambda item: item["price"]):
        matching_group = None

        for group in groups:
            center = sum(item["price"] for item in group) / len(group)
            if abs(swing["price"] - center) <= tolerance:
                matching_group = group
                break

        if matching_group is None:
            groups.append([swing])
        else:
            matching_group.append(swing)

    levels = []
    for group in groups:
        levels.append({
            "price": sum(item["price"] for item in group) / len(group),
            "touches": len(group),
            "time": max(item["time"] for item in group),
        })

    return levels


def get_levels(df):
    completed = df.iloc[:-1].copy()
    if len(completed) < 20:
        return [], []

    recent = completed.tail(80)
    highs = find_swings(recent, "high")
    lows = find_swings(recent, "low")

    median_range = float(
        (recent["high"] - recent["low"]).tail(30).median()
    )
    price = float(completed.iloc[-1]["close"])
    tolerance = max(median_range * 0.20, abs(price) * 0.00003)

    resistance = group_levels(highs, tolerance)
    support = group_levels(lows, tolerance)

    # Only levels that are on the correct side of the latest completed price.
    support = [
        level for level in support
        if level["price"] < price and level["touches"] >= 2
    ]
    resistance = [
        level for level in resistance
        if level["price"] > price and level["touches"] >= 2
    ]

    support.sort(key=lambda level: abs(price - level["price"]))
    resistance.sort(key=lambda level: abs(price - level["price"]))

    return support, resistance


# ============================================================
# SELECTIVE MULTI-TIMEFRAME SETUP
# ============================================================

def wait_result(base, direction, status, reason):
    return {
        **base,
        "signal": "WAIT",
        "direction": direction,
        "status": status,
        "reason": reason,
    }


def analyze_setup(df1, df5, df15):
    """1m-first binary-style setup. Higher timeframes are context, not gates."""
    trend5, trend15 = get_trend(df5), get_trend(df15)
    base = {"trend15": trend15, "trend5": trend5}
    if len(df1) < 30:
        return wait_result(base, "NONE", "NOT ENOUGH 1M DATA", "Need at least 30 one-minute candles.")

    # Use the latest completed candle; exclude the still-forming candle.
    completed = candle_features(df1.iloc[:-1].tail(80).copy())
    if len(completed) < 25:
        return wait_result(base, "NONE", "NOT ENOUGH COMPLETED DATA", "Waiting for completed 1m candles.")

    last, prev = completed.iloc[-1], completed.iloc[-2]
    recent3 = completed.tail(3)
    age = max(0.0, (datetime.now(timezone.utc) - last["time"]).total_seconds())
    base["data_age"] = age
    if age > 240:
        return wait_result(base, "NONE", "STALE 1M DATA", f"Latest completed 1m candle is about {int(age)} seconds old.")

    o, h, low, close = map(float, [last["open"], last["high"], last["low"], last["close"]])
    candle_range = max(h - low, 1e-12)
    close_pos = (close - low) / candle_range
    body_ratio = float(last["body_ratio"])
    upper_wick = float(last["upper_wick_ratio"])
    lower_wick = float(last["lower_wick_ratio"])
    atr = float(last["atr"]) if pd.notna(last["atr"]) else 0.0
    if atr <= 0:
        return wait_result(base, "NONE", "INDICATORS LOADING", "Waiting for enough 1m data.")

    bull_reject = lower_wick >= 0.45 and close_pos >= 0.60
    bear_reject = upper_wick >= 0.45 and close_pos <= 0.40
    bull_candle = close > o and close_pos >= 0.60
    bear_candle = close < o and close_pos <= 0.40
    momentum = float(recent3.iloc[-1]["close"] - recent3.iloc[0]["open"])
    bb_valid = pd.notna(last["bb_upper"]) and pd.notna(last["bb_lower"])
    bb_bull = bool(bb_valid and close > float(last["bb_middle"]))
    bb_bear = bool(bb_valid and close < float(last["bb_middle"]))

    support, resistance = get_levels(df1)
    near_resistance = bool(resistance and (resistance[0]["price"] - close) / atr < 0.35)
    near_support = bool(support and (close - support[0]["price"]) / atr < 0.35)

    if candle_range > atr * 2.5:
        return wait_result(base, "NONE", "1M CANDLE EXTENDED", "Avoid chasing an unusually large 1m candle.")
    if body_ratio < 0.18 and not bull_reject and not bear_reject:
        return wait_result(base, "NONE", "INDECISIVE 1M CANDLE", "Latest completed 1m candle has no clear direction.")

    call_score, put_score = 0, 0
    call_reasons, put_reasons = [], []
    if bull_candle:
        call_score += 2
        call_reasons.append("bullish 1m candle closed in upper range")
    if bear_candle:
        put_score += 2
        put_reasons.append("bearish 1m candle closed in lower range")
    if bull_reject:
        call_score += 2
        call_reasons.append("lower-wick rejection")
    if bear_reject:
        put_score += 2
        put_reasons.append("upper-wick rejection")
    if momentum > 0:
        call_score += 1
        call_reasons.append("short-term momentum upward")
    elif momentum < 0:
        put_score += 1
        put_reasons.append("short-term momentum downward")
    if bb_bull:
        call_score += 1
        call_reasons.append("close above Bollinger middle band")
    if bb_bear:
        put_score += 1
        put_reasons.append("close below Bollinger middle band")
    if near_resistance:
        call_score -= 2
        call_reasons.append("nearby resistance caution")
    if near_support:
        put_score -= 2
        put_reasons.append("nearby support caution")

    base["bollinger"] = {
        "confirmation": bool(bb_bull or bb_bear),
        "reason": "Supporting context only; no breakout required",
        "upper": float(last["bb_upper"]) if bb_valid else None,
        "middle": float(last["bb_middle"]) if bb_valid else None,
        "lower": float(last["bb_lower"]) if bb_valid else None,
        "width_expanding": bool(pd.notna(last["bb_width"]) and pd.notna(prev["bb_width"]) and last["bb_width"] > prev["bb_width"]),
    }
    base["entry_reference"] = close
    base["call_score"], base["put_score"] = max(0, call_score), max(0, put_score)

    if call_score >= 4 and call_score >= put_score + 2:
        return {**base, "signal": "PREPARE CALL", "direction": "BULLISH", "status": "1M CALL SETUP",
                "reason": "; ".join(call_reasons) + f". Reference close {close:.6f}; forecast for next 1m candle."}
    if put_score >= 4 and put_score >= call_score + 2:
        return {**base, "signal": "PREPARE PUT", "direction": "BEARISH", "status": "1M PUT SETUP",
                "reason": "; ".join(put_reasons) + f". Reference close {close:.6f}; forecast for next 1m candle."}
    return wait_result(base, "NONE", "NO CLEAR 1M ADVANTAGE",
                       f"CALL score {max(0, call_score)}; PUT score {max(0, put_score)}. Wait for a clearer completed 1m candle.")

# ============================================================
# MULTI-PAIR SCANNER UI
# ============================================================

st.title("🔎 Pocket Option Forex Signal Scanner")
st.caption(
    "Scans major forex pairs • 15m trend • 5m confirmation • "
    "1m momentum • Bollinger Bands • ranks the strongest current setup"
)
st_autorefresh(interval=60000, key="scanner_auto_refresh")

# Major non-OTC forex pairs. These may not match Pocket Option OTC prices.
SCAN_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD",
    "USD/CAD", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY",
]

# Prefer the encrypted Streamlit Community Cloud Secret. A sidebar entry is
# retained as a fallback for local testing or deployments without Secrets.
try:
    api_key = st.secrets.get("TWELVE_DATA_API_KEY", "")
except Exception:
    api_key = ""

if not api_key:
    api_key = st.sidebar.text_input("Twelve Data API key", type="password")
else:
    st.sidebar.success("Twelve Data API key loaded securely from app Secrets.")

st.sidebar.subheader("Scanner settings")
refresh_seconds = st.sidebar.selectbox(
    "Refresh interval",
    options=[60, 120, 180, 300],
    index=0,
    format_func=lambda value: f"{value} seconds",
)
st.sidebar.caption(
    "The page refreshes every minute. The selected interval controls how often "
    "you should expect a full rescan; cached data and API limits can delay updates."
)
st.sidebar.warning(
    "Scanning 10 pairs across 3 timeframes can use many API credits. "
    "A free API plan may not support frequent full scans."
)

if not api_key:
    st.info("Add TWELVE_DATA_API_KEY in Streamlit Secrets, or enter your Twelve Data API key in the sidebar.")
    st.stop()

# Streamlit reruns every minute; this gate reduces repeated full scans if a longer
# refresh interval is selected. Session state is only used for this browser session.
import time
now_epoch = time.time()
last_scan_epoch = st.session_state.get("last_scan_epoch", 0)
cached_results = st.session_state.get("scanner_results")

if cached_results is not None and (now_epoch - last_scan_epoch) < refresh_seconds:
    results = cached_results
    st.caption("Showing the most recent scan; next full scan is not due yet.")
else:
    results = []
    progress = st.progress(0, text="Preparing scan...")
    status = st.empty()

    for index, pair in enumerate(SCAN_PAIRS):
        status.write(f"Scanning {pair} ({index + 1} of {len(SCAN_PAIRS)})...")
        try:
            # Existing per-timeframe caches help reduce calls between scans.
            df1 = fetch_1m(pair, api_key)
            df5 = fetch_5m(pair, api_key)
            df15 = fetch_15m(pair, api_key)
            result = analyze_setup(df1, df5, df15)

            t15 = result.get("trend15", {})
            t5 = result.get("trend5", {})
            bb = result.get("bollinger", {})
            score = 0
            reasons = []

            score = max(int(result.get("call_score", 0)), int(result.get("put_score", 0))) * 20
            if bb.get("confirmation"):
                reasons.append("Bollinger context agrees")
            if result.get("signal") in ("PREPARE CALL", "PREPARE PUT"):
                reasons.append("1m candle setup passed")
            if t5.get("direction") == result.get("direction"):
                reasons.append("5m context agrees (supporting only)")

            direction = t15.get("direction", "UNCLEAR")
            if direction == "BULLISH":
                suggested = "CALL"
            elif direction == "BEARISH":
                suggested = "PUT"
            else:
                suggested = "NONE"

            # Only present a trade candidate when the full analyzer confirms it.
            if result.get("signal") in ("PREPARE CALL", "PREPARE PUT"):
                label = result["signal"].replace("PREPARE ", "")
                status_text = "SETUP CONFIRMED BY FILTERS"
            else:
                label = "WAIT"
                status_text = result.get("status", "No setup")
            results.append({
                "Pair": pair,
                "Signal": label,
                "Setup score": score,
                "15m trend": f'{t15.get("direction", "N/A")} ({t15.get("strength", "N/A")})',
                "5m trend": f'{t5.get("direction", "N/A")} ({t5.get("strength", "N/A")})',
                "Bollinger": "Supporting context" if bb.get("confirmation") else "Neutral",
                "Entry reference": result.get("entry_reference", "—"),
                "Status / reason": status_text + " — " + result.get("reason", ""),
                "_reasons": ", ".join(reasons) if reasons else "No directional confirmation",
                "_raw_signal": result.get("signal", "WAIT"),
            })
        except Exception as exc:
            results.append({
                "Pair": pair,
                "Signal": "ERROR",
                "Setup score": 0,
                "15m trend": "Unavailable",
                "5m trend": "Unavailable",
                "Bollinger": "Unavailable",
                "Status / reason": str(exc),
                "_reasons": "Data unavailable",
                "_raw_signal": "ERROR",
            })
        progress.progress((index + 1) / len(SCAN_PAIRS), text=f"Scanned {index + 1}/{len(SCAN_PAIRS)} pairs")

    status.empty()
    progress.empty()
    st.session_state["scanner_results"] = results
    st.session_state["last_scan_epoch"] = now_epoch

if not results:
    st.warning("No scan results available yet.")
    st.stop()

# Sort by score, but confirmed signals are shown before WAIT candidates.
results = sorted(
    results,
    key=lambda item: (
        item.get("_raw_signal") in ("PREPARE CALL", "PREPARE PUT"),
        item.get("Setup score", 0),
    ),
    reverse=True,
)

confirmed = [
    item for item in results
    if item.get("_raw_signal") in ("PREPARE CALL", "PREPARE PUT")
]
top = confirmed[0] if confirmed else results[0]

st.subheader("🏆 Strongest current setup")
if confirmed:
    a, b, c = st.columns(3)
    a.metric("Pair", top["Pair"])
    b.metric("Signal", top["Signal"])
    c.metric("Setup score", f'{top["Setup score"]}/100')
    st.success(
        f'{top["Pair"]}: {top["Signal"]} — {top["Setup score"]}/100 setup score. '
        "This is a rule-based ranking, not a measured probability of winning."
    )
    st.write(top["Status / reason"])
else:
    st.warning(
        "No pair currently passes all entry filters. The highest-ranked pair is "
        f'{top["Pair"]} with a setup score of {top["Setup score"]}/100, but its signal remains WAIT. '
        "Do not treat the top-ranked WAIT row as a confirmed trade."
    )
    st.write(top["Status / reason"])

st.caption(
    "Setup score measures how many of this app's technical conditions agree. "
    "It is NOT a statistically validated win probability."
)

st.subheader("All scanned pairs")
display_rows = []
for item in results:
    display_rows.append({
        "Pair": item["Pair"],
        "Signal": item["Signal"],
        "Setup score": f'{item["Setup score"]}/100',
        "15m trend": item["15m trend"],
        "5m trend": item["5m trend"],
        "Bollinger": item["Bollinger"],
        "Entry reference": item.get("Entry reference", "—"),
        "Status / reason": item["Status / reason"],
    })
st.dataframe(
    pd.DataFrame(display_rows),
    use_container_width=True,
    hide_index=True,
)

with st.expander("How the setup score works"):
    st.write(
        "The score adds points for a directional 15-minute trend, 15m/5m agreement, "
        "trend strength, Bollinger confirmation, and passing all entry filters. "
        "Only a pair that passes the full analyzer is labelled CALL or PUT. "
        "The score is not based on historical win-rate testing and must not be read as a probability."
    )
    st.write(
        "The scanner uses standard forex symbols from Twelve Data, not Pocket Option OTC candles. "
        "Prices and timing can differ between providers."
    )

st.warning(
    "Important: ten pairs × three timeframes can exceed free API limits, especially with frequent scans. "
    "If Twelve Data returns a quota error, reduce scan frequency or scan fewer pairs. "
    "Test on demo first; no signal is guaranteed."
)
