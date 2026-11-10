import os
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
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
    page_title="GHOST Protocol 3.2",
    page_icon="📡",
    layout="wide"
)

st.markdown("""
<style>
:root { color-scheme: dark; }
.stApp { background: radial-gradient(ellipse at top, #17243a 0%, #0b1220 55%, #080d17 100%); }
.block-container { max-width: 1180px; padding: 1.0rem 1.15rem 3rem; }
[data-testid="stSidebar"] { background: #0d1727; }
[data-testid="stMetric"] { background: #111d30; border: 1px solid #293b55; padding: 13px; border-radius: 13px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: #293b55 !important; border-radius: 14px; }
.ghost-hero { background: linear-gradient(120deg,#101d31,#172b42 60%,#10251f); border:1px solid #35506a; border-radius:18px; padding:20px; margin: 8px 0 18px; }
.ghost-kicker { color:#8da9c8; letter-spacing:2px; font-size:11px; font-weight:800; }
.ghost-title { color:#f4f8ff; font-size:clamp(25px,4vw,38px); font-weight:900; margin:5px 0; }
.ghost-sub { color:#9fb2ca; font-size:13px; }
.signal-card { padding:18px 20px; border-radius:14px; background:#111d30; border:1px solid #334862; margin:8px 0; }
.signal-call { border-left:6px solid #22c55e; }
.signal-put { border-left:6px solid #ef4444; }
.signal-wait { border-left:6px solid #64748b; }
.small-muted { color:#9aacc2; font-size:.86rem; }
section[data-testid="stMain"] { overflow-x:hidden; }
[data-testid="stPlotlyChart"] { border:1px solid #263b54; border-radius:12px; overflow:hidden; }
h1,h2,h3 { letter-spacing:-.02em; }
@media (max-width: 700px) { .block-container { padding-left:.7rem; padding-right:.7rem; } [data-testid="stMetric"] { padding:9px; } }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="ghost-hero">
  <div class="ghost-kicker">AUTONOMOUS MARKET INTELLIGENCE · MANUAL EXECUTION ONLY</div>
  <div class="ghost-title">👻 GHOST PROTOCOL 3.2</div>
  <div class="ghost-sub">Unified terminal · Deriv synthetic intelligence · Forex THREE STEPS · CAT</div>
</div>
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
# FOREX ENGINE — THREE STEPS
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


def session_intelligence(ticks, one_minute, timeframe_history=None):
    """Measure candle-range and tick-activity context; tick count is NOT volume."""
    result = {}
    if one_minute is None or one_minute.empty:
        return result
    now_utc = pd.Timestamp.now(tz="UTC")
    completed_1m = one_minute.copy()
    completed_1m["datetime"] = pd.to_datetime(completed_1m["datetime"], utc=True)
    completed_1m = completed_1m[completed_1m.datetime + pd.Timedelta(minutes=1) <= now_utc]
    if completed_1m.empty:
        return result
    for label, minutes in (("15m", 15), ("1h", 60), ("4h", 240), ("1d", 1440)):
        native = (timeframe_history or {}).get(label)
        if native is not None and not native.empty:
            bars = native.copy()
            bars["datetime"] = pd.to_datetime(bars["datetime"], utc=True, errors="coerce")
            bars = bars.dropna(subset=["datetime", "open", "high", "low", "close"])
            bars = bars[bars.datetime + pd.Timedelta(minutes=minutes) <= now_utc].reset_index(drop=True)
        else:
            bars = aggregate_timeframe(completed_1m, minutes)
        if bars.empty:
            result[label] = {"bars": 0, "range": None, "average": None, "state": "COLLECTING"}
            continue
        bars = bars.copy()
        bars["range"] = bars.high - bars.low
        close_series = bars.close.astype(float)
        ema_fast = close_series.ewm(span=9, adjust=False).mean()
        ema_slow = close_series.ewm(span=21, adjust=False).mean()
        if len(bars) >= 21 and ema_fast.iloc[-1] > ema_slow.iloc[-1] and close_series.iloc[-1] > ema_fast.iloc[-1]:
            trend = "BULLISH"
        elif len(bars) >= 21 and ema_fast.iloc[-1] < ema_slow.iloc[-1] and close_series.iloc[-1] < ema_fast.iloc[-1]:
            trend = "BEARISH"
        else:
            trend = "MIXED / BUILDING"
        latest = float(bars.range.iloc[-1])
        prior_ranges = bars.range.iloc[:-1].tail(20)
        if len(prior_ranges) < 5:
            result[label] = {"bars": len(bars), "range": latest, "average": None, "ratio": None, "state": "COLLECTING BASELINE", "trend": trend}
            continue
        baseline = float(prior_ranges.mean())
        ratio = latest / baseline if baseline > 0 else None
        state = "EXPANDING" if ratio is not None and ratio >= 1.35 else "CONTRACTING" if ratio is not None and ratio <= 0.70 else "NORMAL" if ratio is not None else "COLLECTING BASELINE"
        result[label] = {"bars": len(bars), "range": latest, "average": baseline, "ratio": ratio, "state": state, "trend": trend}
    # Activity proxy: number of received ticks per completed minute. Not exchange volume.
    if ticks is not None and not ticks.empty:
        tick_data = ticks.copy()
        tick_data["datetime"] = pd.to_datetime(tick_data["datetime"], utc=True)
        counts = tick_data.set_index("datetime").resample("1min").size()
        counts = counts[counts.index + pd.Timedelta(minutes=1) <= now_utc]
        if not counts.empty:
            recent_window = counts.tail(15)
            prior_window = counts.iloc[:-15].tail(120)
            recent = float(recent_window.mean())
            baseline = float(prior_window.mean()) if len(prior_window) >= 15 else None
            activity_state = ("ABOVE BASELINE" if recent > baseline * 1.25 else "BELOW BASELINE" if recent < baseline * 0.75 else "NORMAL") if baseline and baseline > 0 else "COLLECTING BASELINE"
            result["tick_activity"] = {"recent_per_min": recent, "baseline_per_min": baseline, "state": activity_state}
        # Hour-of-day CAT profile from observed ticks; descriptive only.
        local = tick_data.datetime.dt.tz_convert("Africa/Lusaka")
        hourly = pd.DataFrame({"hour": local.dt.hour, "tick": 1}).groupby("hour").tick.sum()
        result["hour_profile"] = {int(k): int(v) for k, v in hourly.items()}
        range_frame = completed_1m.copy()
        range_frame["local_hour"] = range_frame.datetime.dt.tz_convert("Africa/Lusaka").dt.hour
        range_frame["four_hour_block"] = (range_frame.local_hour // 4) * 4
        range_frame["range"] = range_frame.high - range_frame.low
        result["hour_range_profile"] = {
            int(hour): {"average_range": float(group.range.mean()), "bars": int(len(group))}
            for hour, group in range_frame.groupby("local_hour") if len(group) >= 3
        }
        result["four_hour_profile"] = {
            f"{int(block):02d}:00-{(int(block)+4)%24:02d}:00": {"average_range": float(group.range.mean()), "bars": int(len(group))}
            for block, group in range_frame.groupby("four_hour_block") if len(group) >= 10
        }
    return result


# ============================================================
# GHOST THREE-STEP STAIRCASE STRATEGY
# ============================================================

def identify_candle_one(candle, previous):
    """Identify a directional first step from rejection, breakout, or close progression."""
    o = float(candle.open)
    h = float(candle.high)
    l = float(candle.low)
    c = float(candle.close)
    previous_high = float(previous.high)
    previous_low = float(previous.low)
    previous_close = float(previous.close)

    candle_range = max(h - l, 1e-12)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    close_position = (c - l) / candle_range

    # Rejection has priority because it can signal a reversal regardless
    # of the candle body colour.
    bullish_rejection = (
        lower_wick >= max(upper_wick * 1.25, candle_range * 0.25)
        and close_position >= 0.55
    )
    bearish_rejection = (
        upper_wick >= max(lower_wick * 1.25, candle_range * 0.25)
        and close_position <= 0.45
    )

    if bullish_rejection:
        return "CALL", "SUPPORT REJECTION"
    if bearish_rejection:
        return "PUT", "RESISTANCE REJECTION"
    if c > previous_high:
        return "CALL", "BULLISH BREAKOUT"
    if c < previous_low:
        return "PUT", "BEARISH BREAKOUT"
    if c > previous_close:
        return "CALL", "BULLISH DIRECTIONAL STEP"
    if c < previous_close:
        return "PUT", "BEARISH DIRECTIONAL STEP"
    return None, "NO CLEAR FIRST STEP"


def assess_candle3_risk(completed, direction, c2, latest_price):
    """Return soft Candle 3 risk warnings; never overrides hard staircase rules."""
    warnings = []
    o = float(c2.open)
    h = float(c2.high)
    l = float(c2.low)
    c = float(c2.close)
    candle_range = max(h - l, 1e-12)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if body / candle_range <= 0.15:
        warnings.append(
            "Candle 2 is an indecision candle (small body relative to its range)."
        )

    if direction == "CALL":
        if upper_wick >= max(body * 1.5, candle_range * 0.35):
            warnings.append(
                "Candle 2 has a notable upper rejection wick against the bullish move."
            )
        prior = completed.iloc[:-2].tail(12)
        if not prior.empty:
            resistance = float(prior.high.max())
            distance = resistance - float(latest_price)
            if 0 <= distance <= candle_range:
                warnings.append(
                    "Price is within one Candle 2 range of a recent high "
                    f"({fmt_price(resistance)}), which may act as resistance."
                )
    else:
        if lower_wick >= max(body * 1.5, candle_range * 0.35):
            warnings.append(
                "Candle 2 has a notable lower rejection wick against the bearish move."
            )
        prior = completed.iloc[:-2].tail(12)
        if not prior.empty:
            support = float(prior.low.min())
            distance = float(latest_price) - support
            if 0 <= distance <= candle_range:
                warnings.append(
                    "Price is within one Candle 2 range of a recent low "
                    f"({fmt_price(support)}), which may act as support."
                )

    return warnings


def analyze_market_structure(completed):
    """
    Describe recent price structure for context only.
    This analysis never creates or invalidates a staircase entry by itself.
    """
    if completed is None or len(completed) < 8:
        return {
            "label": "BUILDING MARKET HISTORY",
            "detail": "More completed candles are needed to assess recent structure.",
            "opposing_pressure": None,
            "recent_direction": "MIXED",
            "prior_impulse": "MIXED"
        }

    data = completed.tail(8).reset_index(drop=True)
    prior = data.iloc[:5]
    recent = data.iloc[5:]

    prior_move = float(prior.close.iloc[-1]) - float(prior.open.iloc[0])
    recent_move = float(recent.close.iloc[-1]) - float(recent.open.iloc[0])

    prior_direction = (
        "BULLISH" if prior_move > 0
        else "BEARISH" if prior_move < 0
        else "MIXED"
    )

    recent_closes = recent.close.astype(float).tolist()
    rising_steps = sum(
        recent_closes[i] > recent_closes[i - 1]
        for i in range(1, len(recent_closes))
    )
    falling_steps = sum(
        recent_closes[i] < recent_closes[i - 1]
        for i in range(1, len(recent_closes))
    )

    recent_direction = (
        "BULLISH" if rising_steps >= 2
        else "BEARISH" if falling_steps >= 2
        else "MIXED"
    )

    prior_high = float(prior.high.max())
    prior_low = float(prior.low.min())
    recent_high = float(recent.high.max())
    recent_low = float(recent.low.min())

    bearish_structure_break = (
        recent_direction == "BEARISH" and recent_low < prior_low
    )
    bullish_structure_break = (
        recent_direction == "BULLISH" and recent_high > prior_high
    )

    opposing_pressure = None
    if prior_direction == "BULLISH" and recent_direction == "BEARISH":
        opposing_pressure = "BEARISH"
        label = (
            "BULLISH IMPULSE — POSSIBLE BEARISH PULLBACK"
            if not bearish_structure_break
            else "BULLISH IMPULSE — BEARISH STRUCTURE BREAK"
        )
        detail = (
            "The earlier candles advanced upward, but the latest candles "
            "are moving down. A break below the earlier swing-low area "
            "suggests stronger bearish pressure; without that break, this "
            "may still be only a pullback."
        )
    elif prior_direction == "BEARISH" and recent_direction == "BULLISH":
        opposing_pressure = "BULLISH"
        label = (
            "BEARISH IMPULSE — POSSIBLE BULLISH PULLBACK"
            if not bullish_structure_break
            else "BEARISH IMPULSE — BULLISH STRUCTURE BREAK"
        )
        detail = (
            "The earlier candles advanced downward, but the latest candles "
            "are moving up. A break above the earlier swing-high area "
            "suggests stronger bullish pressure; without that break, this "
            "may still be only a pullback."
        )
    elif recent_direction == "BULLISH":
        label = "RECENT BULLISH PRESSURE"
        detail = "Recent completed closes are generally stepping upward."
    elif recent_direction == "BEARISH":
        label = "RECENT BEARISH PRESSURE"
        detail = "Recent completed closes are generally stepping downward."
    else:
        label = "RANGE / MIXED STRUCTURE"
        detail = "Recent completed candles do not show a clear directional sequence."

    swing_highs, swing_lows = confirmed_pivots(completed.tail(60).reset_index(drop=True), 2)
    swing_label = "INSUFFICIENT SWINGS"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1][1] > swing_highs[-2][1]
        hl = swing_lows[-1][1] > swing_lows[-2][1]
        lh = swing_highs[-1][1] < swing_highs[-2][1]
        ll = swing_lows[-1][1] < swing_lows[-2][1]
        swing_label = "HH + HL · UPTREND" if hh and hl else "LH + LL · DOWNTREND" if lh and ll else "MIXED SWING STRUCTURE"

    return {
        "label": label,
        "detail": detail,
        "swing_structure": swing_label,
        "opposing_pressure": opposing_pressure,
        "recent_direction": recent_direction,
        "prior_impulse": prior_direction,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "structure_break": (
            bearish_structure_break or bullish_structure_break
        )
    }


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
            "note": "Candlestick names are approximate OHLC pattern matches. They provide context only; the Three-Step Staircase remains the sole entry authority."}


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
            "note": "Sakata labels are conservative OHLC candidates. Gaps and parallel-line formations are uncommon in continuous synthetic markets; none is an entry trigger. Three-Step Staircase remains the only entry authority."}


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


def ghost_protocol(ticks):
    """Three-Step Staircase: C1 setup, C2 completed close, C3 only entry window."""
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
# SIGNAL TIMER AND RECORD
# ============================================================


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
        "reason": result.get("reason", "Candle 2 is still forming; wait for its close."),
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
    if not signal:
        st.markdown("<div class=\"signal-card signal-wait\"><h3>WAIT · NO ACTIVE SIGNAL</h3><div class=\"small-muted\">GHOST is analysing. No countdown or timer is displayed until a valid signal is issued.</div></div>", unsafe_allow_html=True)
        return
    now=now_cat(); entry=datetime.fromisoformat(signal["entry_time"]); expiry=datetime.fromisoformat(signal["expiry_time"])
    if signal.get("stage") == "PREPARE" and now >= entry:
        st.markdown("<div class='signal-card signal-wait'><h3>PREPARATION WINDOW CLOSED</h3><div class='small-muted'>Waiting for Candle 2 close validation. No directional signal or entry timer is active.</div></div>", unsafe_allow_html=True)
        return
    if now < entry: status="PREPARE"; remaining=max(0,int((entry-now).total_seconds()))
    elif now < expiry: status="ENTRY WINDOW"; remaining=max(0,int((expiry-now).total_seconds()))
    else: status="EXPIRED"; remaining=0
    if status == "EXPIRED":
        st.markdown("<div class='signal-card signal-wait'><h3>SIGNAL EXPIRED</h3><div class='small-muted'>Timer removed. This alert must not be reused.</div></div>",unsafe_allow_html=True)
        return
    if status == "PREPARE":
        color = "signal-wait"
        heading = "PREPARATION WINDOW · NO DIRECTION YET"
    else:
        color = "signal-call" if signal["direction"] == "CALL" else "signal-put"
        heading = f"{signal['direction']} · {status}"
    st.markdown(f'''<div class="signal-card {color}"><div class="small-muted">{signal['market']} · {signal['instrument']}</div><h2>{heading}</h2><div><b>{signal.get('stage','ENTRY READY')}</b></div><div>{signal['reason']}</div><div>Entry reference: {fmt_price(signal.get('entry_point'))}</div></div>''',unsafe_allow_html=True)
    a,b,c=st.columns(3)
    a.metric("SIGNAL TIMER",f"{remaining//60:02d}:{remaining%60:02d}")
    b.metric("ENTRY (CAT)",entry.strftime("%H:%M:%S"))
    c.metric("EXPIRY (CAT)",expiry.strftime("%H:%M:%S"))
    st.caption("Timer exists only during this active signal lifecycle. Expired or invalidated signals are cleared.")


# ============================================================
# CHARTS
# ============================================================

def chart(df, title):
    view = df.tail(100)
    fig = go.Figure(
        go.Candlestick(
            x=view.datetime,
            open=view.open,
            high=view.high,
            low=view.low,
            close=view.close,
            name="1m"
        )
    )
    fig.update_layout(
        title=title,
        height=380,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=40, b=10)
    )
    return fig


# ============================================================
# SIDEBAR CONTROLS
# ============================================================

with st.sidebar:
    st.header("Market & controls")

    market = st.radio(
        "Market engine",
        [
            "Pocket Option Forex · THREE STEPS",
            "Deriv Synthetics · GHOST PROTOCOL"
        ]
    )
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
        "Deriv uses a persistent live tick subscription with analysis refresh every 2 seconds. "
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
run_scan = bool(scan or auto_scan_due)

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
            ]

            if candidates:
                chosen = max(
                    candidates,
                    key=lambda item: item["result"]["candle_time"]
                )
                st.session_state["active_signal"] = build_signal_record(
                    "THREE STEPS",
                    chosen["instrument"],
                    chosen["result"],
                    expiry
                )
            else:
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
            elif result.get("stage") == "SETUP DEVELOPING":
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


# ============================================================
# SIGNAL PAD
# ============================================================

st.subheader("01 · SIGNAL COMMAND CENTRE")
active_signal = st.session_state.get("active_signal")
if active_signal:
    try:
        if now_cat() >= datetime.fromisoformat(active_signal["expiry_time"]):
            st.session_state.pop("active_signal", None)
            active_signal = None
    except Exception:
        st.session_state.pop("active_signal", None)
        active_signal = None
show_signal_pad(active_signal)


# ============================================================
# FOREX DASHBOARD
# ============================================================

if market.startswith("Pocket"):
    st.subheader("02 · FOREX THREE-STEP SCANNER")

    results = (
        st.session_state.get("scan_output", [])
        if st.session_state.get("scan_market") == "forex"
        else []
    )

    if not results:
        st.caption(
            "Select Forex pairs and press SCAN FOREX. "
            "Only completed one-minute candles are analysed."
        )

    for item in results:
        with st.container(border=True):
            if "error" in item:
                st.error(f'{item["instrument"]}: {item["error"]}')
                continue

            result = item["result"]
            col1, col2, col3 = st.columns([2, 1, 3])
            col1.markdown(f'**{item["instrument"]}**')
            col2.metric("Signal", result["signal"])
            col3.write(result["reason"])

            with st.expander("Chart & details"):
                st.plotly_chart(
                    chart(item["df"], item["instrument"]),
                    use_container_width=True
                )
                if "price" in result:
                    st.write(
                        f'Last completed close: {fmt_price(result["price"])} · '
                        f'EMA 9: {fmt_price(result["ema9"])} · '
                        f'EMA 21: {fmt_price(result["ema21"])}'
                    )


# ============================================================
# GHOST DASHBOARD
# ============================================================

else:
    st.subheader("02 · DERIV GHOST INTELLIGENCE")

    output = (
        st.session_state.get("deriv_output")
        if st.session_state.get("scan_market") == "deriv"
        else None
    )

    if output:
        latest_tick_time = (
            output["ticks"].datetime.iloc[-1]
            if output.get("ticks") is not None and not output["ticks"].empty
            else None
        )
        result = output["result"]
        stage = result.get("stage", "SCANNING")
        direction = result.get("signal", "WAIT")
        fs = output.get("feed_status", {})
        feed_age = fs.get("last_tick_age")
        feed_label = "CONNECTED" if fs.get("connected") and feed_age is not None and feed_age <= 8 else "RECONNECTING / DELAYED"
        st.caption(f"DERIV STREAM · {feed_label} · last tick age: {feed_age:.1f}s" if feed_age is not None else f"DERIV STREAM · {feed_label}")
        if fs.get("last_error"):
            st.caption("Stream diagnostic: " + str(fs["last_error"]))

        st.markdown("### The three-candle sequence")
        a, b, c = st.columns(3)
        a.metric("CANDLE 1", "IDENTIFY")
        b.metric("CANDLE 2", "CLOSE CONFIRMATION")
        c.metric("CANDLE 3", "ENTRY")

        st.markdown(f"**Current stage: {stage}**")
        st.write(result.get("reason", "Waiting for a valid setup."))

        # Buyer/seller candle story: OHLC-derived pressure, not real order flow.
        st.markdown("### BUYER / SELLER STORY ENGINE")
        story_candles = output.get("candles")
        if story_candles is not None and len(story_candles) >= 5:
            closed_story = story_candles.copy()
            closed_story["datetime"] = pd.to_datetime(closed_story["datetime"], utc=True)
            closed_story = closed_story[closed_story.datetime + pd.Timedelta(minutes=1) <= pd.Timestamp.now(tz="UTC")].tail(8)
            if not closed_story.empty:
                green = int((closed_story.close > closed_story.open).sum())
                red = int((closed_story.close < closed_story.open).sum())
                overlap = float((closed_story.high - closed_story.low).tail(5).mean())
                net = float(closed_story.close.iloc[-1] - closed_story.open.iloc[0])
                story = "BUYERS DOMINANT" if green >= 6 and net > 0 else "SELLERS DOMINANT" if red >= 6 and net < 0 else "MIXED / CONTESTED"
                st.write(f"**{story}** · {green} bullish closes / {red} bearish closes across the last {len(closed_story)} completed candles.")
                st.caption("This is candle-derived pressure only. It is not exchange order flow or buyer/seller volume.")
            else:
                st.caption("Collecting completed candles for buyer/seller story.")
        structure = result.get("market_structure")
        if structure:
            st.markdown("**GHOST market structure**")
            st.info(
                f'{structure.get("label", "ASSESSING")} — '
                f'{structure.get("detail", "")}\n\n'
                f'Swing sequence: {structure.get("swing_structure", "COLLECTING")}'
            )

        st.markdown("**Multi-Timeframe Session & Volatility Intelligence**")
        mtf = session_intelligence(output.get("ticks"), output.get("candles"), output.get("mtf_history"))
        mtf_cols = st.columns(4)
        for col, tf in zip(mtf_cols, ("15m", "1h", "4h", "1d")):
            item = mtf.get(tf, {})
            col.metric(tf, item.get("state", "COLLECTING"),
                       delta=(f'{item.get("trend", "MIXED")} · {item["ratio"]:.2f}× range' if item.get("ratio") is not None else item.get("trend")))
        mtf_errors = output.get("mtf_errors", {})
        if mtf_errors:
            st.caption("Some higher-timeframe history is still collecting: " + " · ".join(f"{k}: {v}" for k, v in mtf_errors.items()))
        activity = mtf.get("tick_activity")
        if activity:
            st.caption(f'Tick activity proxy: {activity["recent_per_min"]:.1f} ticks/min vs {activity["baseline_per_min"]:.1f} baseline · {activity["state"]}. This is tick frequency, NOT traded volume.')
        st.markdown("### CANDLE BIBLE · CANDLESTICK INTELLIGENCE")
        completed_for_context = output.get("candles").copy()
        if completed_for_context is not None and not completed_for_context.empty:
            completed_for_context["datetime"] = pd.to_datetime(completed_for_context["datetime"], utc=True)
            completed_for_context = completed_for_context[completed_for_context.datetime + pd.Timedelta(minutes=1) <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True)
        bible = candle_bible_analysis(completed_for_context)
        st.write(f"**{bible['bias']}** · " + " · ".join(bible["patterns"]))
        st.caption(bible["note"])

        st.markdown("### HOMMA / SAKATA · CLASSICAL PATTERN CONTEXT")
        sakata = homma_sakata_analysis(completed_for_context)
        for observation in sakata["observations"]:
            st.write("• " + observation)
        st.caption(sakata["note"])

        st.markdown("### SUPPORT / RESISTANCE MAP")
        sr = support_resistance_analysis(completed_for_context)
        sr_a, sr_b = st.columns(2)
        sr_a.metric("NEAREST SUPPORT", fmt_price(sr.get("support")) if sr.get("support") is not None else "COLLECTING")
        sr_b.metric("NEAREST RESISTANCE", fmt_price(sr.get("resistance")) if sr.get("resistance") is not None else "COLLECTING")
        st.caption(sr["note"])

        if stage == "SETUP DEVELOPING":
            st.info("SETUP DEVELOPING — Candle 2 is still open. Its close must confirm; no directional signal is issued yet.")
        elif stage == "ENTRY READY":
            action = "RISE / CALL" if direction == "CALL" else "FALL / PUT"
            st.success(
                f"CANDLE 2 CONFIRMED — CANDLE 3 ENTRY: {action}. "
                "This is a manual alert, not an automatic trade."
            )
        elif stage == "CAUTION":
            st.warning(
                f"CAUTION {direction} — staircase rules are still valid, "
                "but opposing candle behaviour or nearby structure was detected. "
                "This is NOT an ENTRY READY signal. Do not treat it as an automatic entry."
            )
            for warning in result.get("warnings", []):
                st.write(f"• {warning}")
        elif stage == "INVALIDATED":
            st.error("SETUP INVALIDATED — DO NOT ENTER.")
        elif stage == "CANDLE 2 WAITING":
            st.info("Candle 1 identified. Waiting for Candle 2 to cross its close.")
        else:
            st.info("SCANNING — waiting for a valid three-step staircase.")

        tick_age = result.get("tick_age")
        candle_age = result.get("candle_age")
        detail_parts = []
        if tick_age is not None:
            detail_parts.append(f"Tick age: {tick_age:.1f}s")
        if candle_age is not None:
            detail_parts.append(f"Current candle age: {candle_age:.1f}s")
        if detail_parts:
            st.caption(" · ".join(detail_parts))

        with st.expander("GHOST live chart and setup details", expanded=True):
            st.plotly_chart(
                chart(output["candles"], GHOST_NAME + " · 1-minute candles"),
                use_container_width=True
            )
            latest_price = result.get("price")
            st.write(f"Latest price: {fmt_price(latest_price)}")
            st.write(f"Pattern: {result.get('pattern', 'Not identified')}")
            st.write(f"Entry reference (Candle 1 close): {fmt_price(result.get('entry_point'))}")
            if result.get("candle2_close") is not None:
                st.write(f"Candle 2 close: {fmt_price(result.get('candle2_close'))}")

        last_scan = output.get("last_scan")
        if last_scan:
            st.caption(
                "Last successful Deriv scan (CAT): "
                + datetime.fromisoformat(last_scan).strftime("%Y-%m-%d %H:%M:%S")
            )
    else:
        st.info("GHOST is standing by. Connect and scan to load live Deriv market data. No signal timer is shown while waiting.")
        last_error = st.session_state.get("deriv_scan_error")
        if last_error:
            st.warning(f"Most recent Deriv scan error: {last_error}")


# ============================================================
# FOOTER
# ============================================================

st.divider()
st.caption(
    "Research and demo alerting only — not financial advice. "
    "GHOST 3.2 does not place trades. Deriv data and execution quotes "
    "can differ. Confirm the live contract quote and timing. "
    "No signal guarantees a profitable outcome."
)
