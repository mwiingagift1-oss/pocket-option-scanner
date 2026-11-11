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
    page_title="GHOST Protocol 4.3.1",
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
.signal-call{border-left:6px solid #ffffff}.signal-put{border-left:6px solid #ff334f}.signal-wait{border-left:6px solid #9a5bc8}
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
<div class="ghost-hero"><div class="ghost-kicker">FOUR INTELLIGENCES · ONE DECISION</div><div class="ghost-title">👻 GHOST PROTOCOL 4.3.1</div><div class="ghost-sub">LIVE SIGNALS · CANDLE CHART · EXPERIENCE LEARNING</div></div>
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
# FOUR-BRAIN SIGNAL FUSION — ALL FOUR SYSTEMS VOTE
# ============================================================
def four_brain_decision(candles, staircase_result, strength=2, min_steps=3, pullback_pct=50, learned_weights=None):
    """Role-aware fusion: distinguish directional evidence from contextual observations."""
    base = dict(staircase_result or {})
    if candles is None or len(candles) < 30:
        base.update({"signal":"WAIT", "stage":"SCANNING", "reason":"Collecting sufficient completed candles for all four intelligence systems.", "brains":{}, "fusion":{}})
        return base

    d = candles.copy().reset_index(drop=True)
    three = three_steps(d, strength, min_steps, pullback_pct)
    bible = candle_bible_analysis(d)
    sakata = homma_sakata_analysis(d)
    sr = support_resistance_analysis(d)
    last = d.iloc[-1]
    price = float(last.close)
    body = abs(float(last.close) - float(last.open))
    span = max(float(last.high) - float(last.low), 1e-12)
    lower = float(min(last.open, last.close) - last.low)
    upper = float(last.high - max(last.open, last.close))
    tol = max(abs(price) * 0.0008, span * 0.35)
    support, resistance = sr.get("support"), sr.get("resistance")
    near_support = support is not None and abs(price - float(support)) <= tol
    near_resistance = resistance is not None and abs(price - float(resistance)) <= tol

    # Each system has a different job and weight. A pattern/location label is not
    # automatically converted into a directional vote.
    base_weights = {"THREE STEPS": 3.0, "CANDLE BIBLE": 2.0,
                    "HOMMA / SAKATA": 1.5, "SUPPORT / RESISTANCE": 2.0}
    learned_weights = learned_weights or {}
    weights = {name: round(weight * float(learned_weights.get(name, 1.0)), 3)
               for name, weight in base_weights.items()}
    votes = {name: "WAIT" for name in weights}
    details = {}

    ts_vote = three.get("signal", "WAIT")
    if ts_vote in ("CALL", "PUT"):
        votes["THREE STEPS"] = ts_vote
    details["THREE STEPS"] = three.get("reason", "No confirmed staircase structure.")

    # Candle Bible requires a recognisable directional pattern, not merely the
    # colour/location of the last candle. Indecision and mixed evidence stay neutral.
    patterns = [str(x).upper() for x in bible.get("patterns", [])]
    bull_candle_terms = ("BULLISH ENGULFING", "HAMMER-LIKE", "THREE WHITE SOLDIERS",
                         "PIERCING LINE", "MORNING STAR", "BULLISH MARUBOZU")
    bear_candle_terms = ("BEARISH ENGULFING", "SHOOTING-STAR", "THREE BLACK CROWS",
                         "DARK CLOUD", "EVENING STAR", "BEARISH MARUBOZU")
    bull_candle = any(any(term in p for term in bull_candle_terms) for p in patterns)
    bear_candle = any(any(term in p for term in bear_candle_terms) for p in patterns)
    if bull_candle and not bear_candle:
        votes["CANDLE BIBLE"] = "CALL"
    elif bear_candle and not bull_candle:
        votes["CANDLE BIBLE"] = "PUT"
    details["CANDLE BIBLE"] = ", ".join(bible.get("patterns", [])) + f" · {bible.get('bias', 'MIXED')}"

    # Sakata formations like Three Mountains / Three Rivers describe repeated
    # resistance/support; they are not directional reversal confirmation alone.
    # Only explicit directional continuation formations can vote.
    sakata_obs = [str(x).upper() for x in sakata.get("observations", [])]
    sakata_bull = any(("THREE METHODS BULLISH" in x) or
                      ("THREE PARALLEL LINES" in x and "BULLISH" in x) for x in sakata_obs)
    sakata_bear = any(("THREE METHODS BEARISH" in x) or
                      ("THREE PARALLEL LINES" in x and "BEARISH" in x) for x in sakata_obs)
    if sakata_bull and not sakata_bear:
        votes["HOMMA / SAKATA"] = "CALL"
    elif sakata_bear and not sakata_bull:
        votes["HOMMA / SAKATA"] = "PUT"
    details["HOMMA / SAKATA"] = ", ".join(sakata.get("observations", []))

    # S/R votes only when price is at a confirmed level and the candle rejects it.
    sr_call = near_support and lower > max(body * 1.15, span * 0.28) and float(last.close) > float(last.open)
    sr_put = near_resistance and upper > max(body * 1.15, span * 0.28) and float(last.close) < float(last.open)
    if sr_call and not sr_put:
        votes["SUPPORT / RESISTANCE"] = "CALL"
    elif sr_put and not sr_call:
        votes["SUPPORT / RESISTANCE"] = "PUT"
    sr_context = []
    if near_support: sr_context.append("testing support")
    if near_resistance: sr_context.append("testing resistance")
    if not sr_context: sr_context.append("not at a confirmed nearby level")
    details["SUPPORT / RESISTANCE"] = (
        f"{'; '.join(sr_context)} · Support {fmt_price(support) if support is not None else '—'}"
        f" · Resistance {fmt_price(resistance) if resistance is not None else '—'}"
    )

    scores = {direction: sum(weights[name] for name, vote in votes.items() if vote == direction)
              for direction in ("CALL", "PUT")}
    supporters = {direction: [name for name, vote in votes.items() if vote == direction]
                  for direction in ("CALL", "PUT")}
    # Context-only Sakata candidates are disclosed, but never counted as a vote.
    candidate = "WAIT"
    lead = abs(scores["CALL"] - scores["PUT"])
    top = "CALL" if scores["CALL"] > scores["PUT"] else "PUT" if scores["PUT"] > scores["CALL"] else "WAIT"
    min_score = 4.0
    min_systems = 2
    direction = (
        top
        if top in supporters
        and scores[top] >= min_score
        and len(supporters[top]) >= min_systems
        and lead >= 2.5
        else "WAIT"
    )

    # Feed/sequence invalidation remains a hard safety stop. A disagreement is
    # not silently resolved: it is shown as CONFLICT / WAIT with its causes.
    hard_block = base.get("stage") in ("FEED CHECK", "INVALIDATED")
    if hard_block:
        direction = "WAIT"
    conflict_names = [name for name, vote in votes.items()
                      if vote in ("CALL", "PUT") and direction != "WAIT" and vote != direction]
    if direction == "WAIT" and scores["CALL"] > 0 and scores["PUT"] > 0:
        conflict_state = "DIRECT CONFLICT"
    elif direction == "WAIT" and (scores["CALL"] > 0 or scores["PUT"] > 0):
        conflict_state = "WEAK / INSUFFICIENT CONFLUENCE"
    elif direction == "WAIT":
        conflict_state = "NO DIRECTIONAL SETUP"
    else:
        conflict_state = "ALIGNED WITH OPPOSING EVIDENCE" if conflict_names else "ALIGNED"

    brains = {
        name: {"vote": votes[name], "weight": weights[name], "detail": details[name],
               "role": {"THREE STEPS":"Structure / trend trigger", "CANDLE BIBLE":"Candle confirmation",
                        "HOMMA / SAKATA":"Classical formation context", "SUPPORT / RESISTANCE":"Location / rejection filter"}[name]}
        for name in weights
    }
    base.update({
        "signal": direction, "brains": brains, "brain_votes": {"CALL":len(supporters["CALL"]), "PUT":len(supporters["PUT"])},
        "brain_scores": scores, "candle_bible": bible, "sakata": sakata,
        "support_resistance": sr, "three_steps_result": three,
        "fusion": {"state":conflict_state, "scores":scores, "supporters":supporters,
                   "conflicts":conflict_names, "minimum_score":min_score,
                   "minimum_systems":min_systems, "weights":weights}
    })

    if direction in ("CALL", "PUT") and not hard_block:
        aligned = supporters[direction]
        opposing = [name for name, vote in votes.items() if vote in ("CALL", "PUT") and vote != direction]
        base["stage"] = "ENTRY READY"
        base["entry_time"] = now_cat().replace(second=0, microsecond=0)
        base["price"] = price
        base["entry_point"] = price
        base["candle_time"] = d.datetime.iloc[-1]
        base["reason"] = (
            f"Weighted confluence {scores[direction]:.1f} vs {scores['PUT' if direction == 'CALL' else 'CALL']:.1f}. "
            f"Supporting systems: {', '.join(aligned)}. "
            + (f"Conflicting evidence: {', '.join(opposing)}." if opposing else "No opposing directional votes.")
        )
        base["supporting_brains"] = aligned
    else:
        base["signal"] = "WAIT"
        if hard_block:
            base["stage"] = "FEED CHECK" if base.get("stage") == "FEED CHECK" else "INVALIDATED"
            base["reason"] = base.get("reason", "Hard safety block: feed or sequence invalidation.")
        else:
            base["stage"] = "CONFLICT / WAIT" if conflict_state == "DIRECT CONFLICT" else "SCANNING"
            base["reason"] = (
                f"{conflict_state}. CALL score {scores['CALL']:.1f}; PUT score {scores['PUT']:.1f}. "
                f"Need at least {min_score:.1f} points from {min_systems} independent systems and a clear margin."
            )
    return base


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
    "candle_pattern_bias", "sakata_pattern_bias", "hour_sin", "hour_cos"
)


def _vote_number(value):
    return 1.0 if value == "CALL" else -1.0 if value == "PUT" else 0.0


def build_learning_features(result, candles=None):
    """Build a fixed, causal feature vector from the snapshot and completed candles only."""
    result = result or {}
    brains = result.get("brains") or {}
    votes = [_vote_number((brains.get(name) or {}).get("vote", "WAIT")) for name in
             ("THREE STEPS", "CANDLE BIBLE", "HOMMA / SAKATA", "SUPPORT / RESISTANCE")]
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
    vector = np.asarray(votes + [call_score, put_score, call_score-put_score] + vals, dtype=float)
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
    result["experience_ai"] = model_view
    candidate = result.get("signal")
    if probability is not None and candidate in ("CALL","PUT"):
        agrees = probability >= 0.58 if candidate == "CALL" else probability <= 0.42
        if not agrees:
            result["signal"] = "WAIT"
            result["stage"] = "AI DISAGREEMENT / WAIT"
            result["reason"] = (f"Four-brain candidate {candidate} did not pass GHOST's validated experience model "
                                f"(estimated UP probability {probability:.0%}). Candidate cancelled.")
    return result


LEARNING_DB = os.getenv("GHOST_DB_PATH", "ghost_learning.sqlite3")
BRAIN_NAMES = ("THREE STEPS", "CANDLE BIBLE", "HOMMA / SAKATA", "SUPPORT / RESISTANCE")


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
# 60-SECOND CONSENSUS PREPARATION GATE
# ============================================================

def apply_preparation_gate(result, market, instrument, expiry=1, prep_seconds=60):
    """A candidate must survive a full 60-second observation before entry is printed."""
    result = dict(result or {})
    pending_all = st.session_state.setdefault("ghost_pending_candidates", {})
    key = f"{market}|{instrument}"
    now = now_cat()
    candidate = result.get("signal") if result.get("signal") in ("CALL", "PUT") else None
    hard_state = result.get("stage") in ("FEED CHECK", "INVALIDATED")
    if hard_state or candidate is None:
        pending_all.pop(key, None)
        if not hard_state:
            result["signal"] = "WAIT"
        return result

    candle_key = str(result.get("candle_time", ""))
    last_issued = st.session_state.get("ghost_last_issued", {})
    if last_issued.get(key) == (candidate, candle_key):
        active = st.session_state.get("active_signal")
        if active and active.get("instrument") == instrument and active.get("direction") == candidate:
            result.update({"signal": candidate, "stage": "ENTRY READY",
                           "entry_time": as_cat(active["entry_time"]).to_pydatetime(),
                           "reason": active.get("reason", result.get("reason", "Signal remains active."))})
        else:
            result.update({"signal": "WAIT", "stage": "SCANNING",
                           "reason": "This candle's candidate has already been evaluated; waiting for a fresh completed candle."})
        return result

    pending = pending_all.get(key)
    if pending is None or pending.get("direction") != candidate:
        entry_at = now + timedelta(seconds=prep_seconds)
        pending = {"direction": candidate, "created_at": now.isoformat(),
                   "entry_at": entry_at.isoformat(), "candle_key": str(result.get("candle_time", "")),
                   "reason": result.get("reason", "Four-brain candidate detected."),
                   "supporting_brains": result.get("supporting_brains", [])}
        pending_all[key] = pending
        result.update({"signal": "WAIT", "stage": "PREPARE", "candidate_direction": candidate,
                       "entry_time": entry_at, "reason": "60-second preparation: GHOST has detected a possible " + candidate +
                       " setup. No entry yet. It is observing whether the four-brain evidence survives. " + pending["reason"]})
        return result

    entry_at = datetime.fromisoformat(pending["entry_at"])
    remaining = (entry_at - now).total_seconds()
    if remaining > 0:
        result.update({"signal": "WAIT", "stage": "PREPARE", "candidate_direction": candidate,
                       "entry_time": entry_at, "reason": f"Preparation continues · {max(0,int(remaining))} seconds remaining. " +
                       "Candidate evidence is being monitored; no trade entry is authorised."})
        return result

    # At the end of preparation the current scan must still independently support the same direction.
    pending_all.pop(key, None)
    last_issued = st.session_state.setdefault("ghost_last_issued", {})
    candle_key = str(result.get("candle_time", ""))
    if last_issued.get(key) == (candidate, candle_key):
        result.update({"signal": "WAIT", "stage": "SCANNING", "reason": "This candle's candidate was already evaluated; waiting for a fresh completed candle."})
        return result
    last_issued[key] = (candidate, candle_key)
    result.update({"signal": candidate, "stage": "ENTRY READY", "entry_time": now,
                   "entry_point": result.get("price"),
                   "reason": "60-second preparation completed and current four-brain consensus still supports " + candidate + ". " + result.get("reason", "")})
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
        "reason": result.get("reason", "Candidate is under 60-second review; no entry yet."),
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
    """Minimal user-facing signal pad; detailed reasoning remains in learning data."""
    if not signal:
        st.markdown("<div class='signal-card signal-wait'><h2>WAIT</h2><div class='small-muted'>No active signal</div></div>", unsafe_allow_html=True)
        return
    now = now_cat()
    entry = datetime.fromisoformat(signal["entry_time"])
    expiry = datetime.fromisoformat(signal["expiry_time"])
    if signal.get("stage") == "PREPARE" and now >= entry:
        st.markdown("<div class='signal-card signal-wait'><h2>WAIT</h2><div class='small-muted'>Preparation window closed</div></div>", unsafe_allow_html=True)
        return
    if now < entry:
        status = "PREPARE"
        remaining = max(0, int((entry-now).total_seconds()))
    elif now < expiry:
        status = "ENTRY WINDOW"
        remaining = max(0, int((expiry-now).total_seconds()))
    else:
        status = "EXPIRED"
        remaining = 0
    if status == "EXPIRED":
        st.markdown("<div class='signal-card signal-wait'><h2>WAIT</h2><div class='small-muted'>Signal expired</div></div>", unsafe_allow_html=True)
        return
    direction = signal.get("direction", "WAIT")
    css = "signal-call" if direction == "CALL" else "signal-put" if direction == "PUT" else "signal-wait"
    label = "UP / CALL" if direction == "CALL" else "DOWN / PUT" if direction == "PUT" else "WAIT"
    st.markdown(
        f"<div class='signal-card {css}'><div class='small-muted'>GHOST SIGNAL · {signal.get('instrument','')}</div>"
        f"<h1 style='font-size:30px;margin:2px 0'>{label}</h1><div><b>{status}</b></div></div>",
        unsafe_allow_html=True
    )
    a, b, c = st.columns(3)
    a.metric("TIMER", f"{remaining//60:02d}:{remaining%60:02d}")
    b.metric("PRINTED (CAT)", entry.strftime("%H:%M:%S"))
    c.metric("EXPIRY (CAT)", expiry.strftime("%H:%M:%S"))


# ============================================================
# CHARTS
# ============================================================

def chart(df, title, levels=None):
    view = df.tail(110).copy()
    fig = go.Figure(go.Candlestick(
        x=view.datetime, open=view.open, high=view.high, low=view.low, close=view.close,
        name="LIVE 1M", increasing=dict(line=dict(color="#ffffff",width=1),fillcolor="#ffffff"),
        decreasing=dict(line=dict(color="#ff334f",width=1),fillcolor="#ff334f")
    ))
    if levels:
        support=levels.get("support") if isinstance(levels,dict) else None
        resistance=levels.get("resistance") if isinstance(levels,dict) else None
        if support is not None:
            fig.add_hline(y=float(support),line_dash="dot",line_color="#a45bd0",line_width=1.4,annotation_text="SUPPORT",annotation_position="bottom right")
        if resistance is not None:
            fig.add_hline(y=float(resistance),line_dash="dot",line_color="#ffffff",line_width=1.4,annotation_text="RESISTANCE",annotation_position="top right")
    fig.update_layout(
        title=dict(text=title,font=dict(size=15,color="#ffffff")),
        height=300, paper_bgcolor="#170d25", plot_bgcolor="#170d25",
        font=dict(color="#ffffff",family="Arial"),
        xaxis_rangeslider_visible=False,
        margin=dict(l=8,r=8,t=42,b=8),
        xaxis=dict(showgrid=True,gridcolor="#392448",zerolinecolor="#7546a0",rangeslider=dict(visible=False)),
        yaxis=dict(showgrid=True,gridcolor="#392448",side="right",zerolinecolor="#7546a0"),
        showlegend=False
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
        "Deriv keeps a persistent live tick subscription; the dashboard refreshes every 5 seconds. "
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
    st_autorefresh(interval=5000, key="desk_clock")

now = now_cat()
st.caption(
    f"LOCAL TIME · {now.strftime('%A, %d %B %Y · %H:%M:%S CAT')}"
)

scan_interval = 2 if market.startswith("Deriv") else 60
scan_slot = int(time.time() // scan_interval)
last_slot = st.session_state.get("last_auto_scan_slot")

auto_scan_due = auto_scan and scan_slot != last_slot
pending_prefix = "GHOST PROTOCOL|" if market.startswith("Deriv") else "GHOST FOUR-BRAIN FOREX|"
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
                                                 learned_weights=profile["multipliers"])
                    result["learning_profile"] = profile
                    record_learning_observation("FOREX", pair, result, candles=df)
                    resolve_learning_observations("FOREX", pair, result.get("price"))
                    model_key = f"FOREX|{pair}"
                    model_cache = st.session_state.setdefault("ghost_experience_models", {})
                    if model_key not in model_cache or int(time.time()) - model_cache[model_key].get("cached_at", 0) >= 60:
                        trained = train_experience_model("FOREX", pair)
                        model_cache[model_key] = {**trained, "cached_at": int(time.time())}
                    result = apply_experience_gate(result, model_cache[model_key], df)
                    result = apply_preparation_gate(result, "GHOST FOUR-BRAIN FOREX", pair, expiry)
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
                same_active = (existing and existing.get("market") == "GHOST FOUR-BRAIN FOREX"
                               and existing.get("instrument") == chosen["instrument"]
                               and existing.get("direction") == chosen["result"].get("signal")
                               and str(existing.get("candle_time", "")) == str(chosen["result"].get("candle_time", "")))
                if not same_active:
                    st.session_state["active_signal"] = build_signal_record(
                        "GHOST FOUR-BRAIN FOREX", chosen["instrument"], chosen["result"], expiry)
            elif preparing:
                chosen = max(preparing, key=lambda item: item["result"].get("candle_time", ""))
                prep = build_preparation_record(
                    "GHOST FOUR-BRAIN FOREX", chosen["instrument"], chosen["result"], expiry)
                if prep is not None:
                    st.session_state["active_signal"] = prep
            else:
                active = st.session_state.get("active_signal")
                if active and active.get("market") == "GHOST FOUR-BRAIN FOREX":
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
                result = four_brain_decision(closed_brain_candles, result,
                                             learned_weights=profile["multipliers"])
                result["learning_profile"] = profile
                record_learning_observation("DERIV", GHOST_NAME, result, candles=closed_brain_candles)
                resolve_learning_observations("DERIV", GHOST_NAME, result.get("price"))
                model_key = f"DERIV|{GHOST_NAME}"
                model_cache = st.session_state.setdefault("ghost_experience_models", {})
                if model_key not in model_cache or int(time.time()) - model_cache[model_key].get("cached_at", 0) >= 60:
                    trained = train_experience_model("DERIV", GHOST_NAME)
                    model_cache[model_key] = {**trained, "cached_at": int(time.time())}
                result = apply_experience_gate(result, model_cache[model_key], closed_brain_candles)
                result = apply_preparation_gate(result, "GHOST PROTOCOL", GHOST_NAME, 1)

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
        if now_cat() >= datetime.fromisoformat(active_signal["expiry_time"]):
            st.session_state.pop("active_signal", None)
            active_signal = None
    except Exception:
        st.session_state.pop("active_signal", None)
        active_signal = None

result, instrument_name = selected_result()

st.markdown("<div class='ghost-kicker'>LIVE SIGNAL PAD</div>", unsafe_allow_html=True)
show_signal_pad(active_signal)

if result and result.get("stage") in ("PREPARE", "SETUP DEVELOPING") and not active_signal:
    st.markdown("<div class='signal-card signal-wait'><h3>PREPARE</h3><div class='small-muted'>Potential setup being monitored</div></div>", unsafe_allow_html=True)

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

st.markdown("<div class='small-muted' style='text-align:center;font-size:10px'>GHOST PROTOCOL · PURPLE / RED / WHITE</div>", unsafe_allow_html=True)
