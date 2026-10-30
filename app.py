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
    "1-minute entry checks • Bollinger breakout confirmation"
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
                "API key rejected. Check the key entered in the sidebar."
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
    trend15 = get_trend(df15)
    trend5 = get_trend(df5)

    base = {
        "trend15": trend15,
        "trend5": trend5,
    }

    latest_time = df1.iloc[-1]["time"]
    now = datetime.now(timezone.utc)
    candle_age = max(0.0, (now - latest_time).total_seconds())
    base["data_age"] = candle_age

    # The timestamp is the candle's opening time, not its last update time.
    # This deliberately errs on the cautious side.
    if candle_age > 150:
        return wait_result(
            base, "NONE", "STALE 1-MINUTE DATA",
            "The latest 1-minute candle is too old for a cautious setup check.",
        )

    direction15 = trend15["direction"]
    direction5 = trend5["direction"]

    if (
        direction15 not in ("BULLISH", "BEARISH")
        or direction15 != direction5
    ):
        return wait_result(
            base, "NONE", "TIMEFRAMES NOT ALIGNED",
            "The completed 15-minute and 5-minute trends must agree.",
        )

    if (
        trend15["strength"] != "Strong"
        or trend5["strength"] == "Weak"
    ):
        return wait_result(
            base, direction15, "TREND STRENGTH TOO LOW",
            "Require a Strong 15-minute trend and at least a Moderate 5-minute trend.",
        )

    # Include enough candles to calculate indicators consistently.
    recent = candle_features(df1.tail(30))
    current = recent.iloc[-1]
    atr_value = current["atr"]

    if pd.isna(atr_value) or float(atr_value) <= 0:
        return wait_result(
            base, direction15, "INSUFFICIENT VOLATILITY DATA",
            "Not enough recent candle-range data to evaluate the entry.",
        )

    atr = float(atr_value)
    candle_range = float(current["range"])
    body = float(current["body"])
    body_ratio = float(current["body_ratio"])

    if body_ratio < 0.50:
        return wait_result(
            base, direction15, "WEAK OR INDECISIVE CANDLE",
            "The candle body is too small compared with its full range.",
        )

    if candle_range > atr * 2.2:
        return wait_result(
            base, direction15, "MOVE ALREADY EXTENDED",
            "The current candle is unusually large. Avoid chasing a sudden move.",
        )

    bullish = current["close"] > current["open"]
    bearish = current["close"] < current["open"]

    last_three = recent.tail(3)
    bullish_count = int((last_three["close"] > last_three["open"]).sum())
    bearish_count = int((last_three["close"] < last_three["open"]).sum())

    if direction15 == "BULLISH":
        if not bullish or bullish_count < 2:
            return wait_result(
                base, direction15, "WAITING FOR CALL CONFIRMATION",
                "The current candle and recent 1-minute momentum do not confirm bullish continuation.",
            )
    else:
        if not bearish or bearish_count < 2:
            return wait_result(
                base, direction15, "WAITING FOR PUT CONFIRMATION",
                "The current candle and recent 1-minute momentum do not confirm bearish continuation.",
            )

    # Require the candle to finish in the directional part of its range.
    close_position = (
        float(current["close"]) - float(current["low"])
    ) / max(candle_range, 1e-12)

    if direction15 == "BULLISH" and close_position < 0.65:
        return wait_result(
            base, direction15, "BULLISH CLOSE NOT STRONG ENOUGH",
            "A bullish setup should close in the upper part of its candle range.",
        )

    if direction15 == "BEARISH" and close_position > 0.35:
        return wait_result(
            base, direction15, "BEARISH CLOSE NOT STRONG ENOUGH",
            "A bearish setup should close in the lower part of its candle range.",
        )

    # Bollinger confirmation: look for a recent close beyond the outer band,
    # or a middle-band cross in the trend direction while band width expands.
    # Requiring confirmation within the last 3 candles avoids relying on old breaks.
    bb_rows = recent.tail(4).copy()
    bb_rows = bb_rows.dropna(subset=["bb_upper", "bb_middle", "bb_lower", "bb_width"])
    if len(bb_rows) < 3:
        return wait_result(
            base, direction15, "WAITING FOR BOLLINGER DATA",
            "Need at least 20 candles to calculate Bollinger Bands reliably.",
        )

    bb_last = bb_rows.iloc[-1]
    bb_prev = bb_rows.iloc[-2]
    bb_breakout = False
    bb_reason = ""

    if direction15 == "BULLISH":
        upper_break = bool((bb_rows["close"] > bb_rows["bb_upper"]).any())
        middle_cross = bool(
            bb_prev["close"] <= bb_prev["bb_middle"]
            and bb_last["close"] > bb_last["bb_middle"]
            and bb_last["close"] > bb_last["open"]
        )
        expanding = bool(bb_last["bb_width"] > bb_prev["bb_width"])
        bb_breakout = upper_break or (middle_cross and expanding)
        bb_reason = (
            "upper-band breakout" if upper_break else
            "bullish middle-band cross with expanding bands" if bb_breakout else
            "no recent bullish Bollinger confirmation"
        )
    else:
        lower_break = bool((bb_rows["close"] < bb_rows["bb_lower"]).any())
        middle_cross = bool(
            bb_prev["close"] >= bb_prev["bb_middle"]
            and bb_last["close"] < bb_last["bb_middle"]
            and bb_last["close"] < bb_last["open"]
        )
        expanding = bool(bb_last["bb_width"] > bb_prev["bb_width"])
        bb_breakout = lower_break or (middle_cross and expanding)
        bb_reason = (
            "lower-band breakout" if lower_break else
            "bearish middle-band cross with expanding bands" if bb_breakout else
            "no recent bearish Bollinger confirmation"
        )

    base["bollinger"] = {
        "confirmation": bb_breakout,
        "reason": bb_reason,
        "upper": float(bb_last["bb_upper"]),
        "middle": float(bb_last["bb_middle"]),
        "lower": float(bb_last["bb_lower"]),
        "width_expanding": bool(bb_last["bb_width"] > bb_prev["bb_width"]),
    }

    if not bb_breakout:
        return wait_result(
            base, direction15, "WAITING FOR BOLLINGER CONFIRMATION",
            "Trend and candle checks passed, but " + bb_reason + ". Wait for a band breakout or a middle-band cross with band expansion.",
        )

    # Avoid entries directly into a nearby opposing support/resistance zone.
    support, resistance = get_levels(df1)
    price = float(current["close"])
    distance_limit = atr * 0.35

    if direction15 == "BULLISH" and resistance:
        nearest_resistance = min(
            resistance, key=lambda level: abs(price - level["price"])
        )
        if abs(price - nearest_resistance["price"]) <= distance_limit:
            return wait_result(
                base, direction15, "RESISTANCE TOO CLOSE",
                "A confirmed resistance zone is nearby. Avoid buying directly into it.",
            )

    if direction15 == "BEARISH" and support:
        nearest_support = min(
            support, key=lambda level: abs(price - level["price"])
        )
        if abs(price - nearest_support["price"]) <= distance_limit:
            return wait_result(
                base, direction15, "SUPPORT TOO CLOSE",
                "A confirmed support zone is nearby. Avoid selling directly into it.",
            )

    signal = "PREPARE CALL" if direction15 == "BULLISH" else "PREPARE PUT"

    return {
        **base,
        "signal": signal,
        "direction": direction15,
        "status": "PROVISIONAL SETUP — RECHECK BEFORE ENTRY",
        "reason": (
            "The completed 15m and 5m trends agree, recent 1m momentum "
            "matches, Bollinger Bands confirm the move (" + bb_reason + "), "
            "the candle has a directional close, and nearby opposing levels "
            "were checked. This setup can still fail."
        ),
    }



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

api_key = st.sidebar.text_input("Twelve Data API key", type="password")
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
    st.info("Enter your Twelve Data API key in the sidebar to start scanning.")
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

            if t15.get("direction") in ("BULLISH", "BEARISH"):
                score += 20
                reasons.append("15m trend directional")
            if t15.get("direction") == t5.get("direction") and t15.get("direction") in ("BULLISH", "BEARISH"):
                score += 20
                reasons.append("15m/5m aligned")
            if t15.get("strength") == "Strong":
                score += 15
                reasons.append("strong 15m trend")
            elif t15.get("strength") == "Moderate":
                score += 10
                reasons.append("moderate 15m trend")
            if t5.get("strength") == "Strong":
                score += 10
                reasons.append("strong 5m trend")
            elif t5.get("strength") == "Moderate":
                score += 7
                reasons.append("moderate 5m trend")
            if bb.get("confirmation"):
                score += 20
                reasons.append("Bollinger confirmation")
            if result.get("signal") in ("PREPARE CALL", "PREPARE PUT"):
                score += 15
                reasons.append("all entry filters passed")

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
                "Bollinger": "Confirmed" if bb.get("confirmation") else "Not confirmed",
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
