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
    page_title="Market Signal Desk",
    page_icon="馃摗",
    layout="wide"
)

st.markdown("""
<style>
.block-container {
    padding-top: 1.2rem;
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

st.title("馃摗 MARKET SIGNAL DESK")
st.caption(
    "THREE STEPS Forex engine 路 GHOST Three-Step Staircase 路 CAT"
)



def render_ghost_candle_clock(latest_tick=None):
    """
    Render a browser-side UTC minute clock. Its digits update every 100 ms,
    independently of Streamlit reruns. Candle boundaries follow UTC minute
    boundaries, matching the app's 1-minute tick resampling.
    """
    now_epoch = time.time()
    tick_epoch = None
    if latest_tick is not None:
        try:
            tick_epoch = pd.Timestamp(latest_tick).timestamp()
        except Exception:
            tick_epoch = None

    if tick_epoch is not None:
        candle_start = int(tick_epoch // 60) * 60
        feed_age = max(0.0, now_epoch - tick_epoch)
        # Only trust the feed's candle anchor while the latest tick is fresh.
        if feed_age <= 8:
            target_epoch = candle_start + 60
            clock_source = "DERIV TICK TIMESTAMP"
            feed_state = "LIVE FEED"
        else:
            target_epoch = int(now_epoch // 60) * 60 + 60
            clock_source = "LOCAL UTC FALLBACK"
            feed_state = f"FEED DELAYED 路 LAST TICK {feed_age:.1f}s AGO"
    else:
        target_epoch = int(now_epoch // 60) * 60 + 60
        clock_source = "UTC CLOCK 路 WAITING FOR DERIV TICKS"
        feed_state = "WAITING FOR LIVE FEED"

    html = f"""
    <div id="ghost-clock" style="font-family:Arial,sans-serif;background:#101827;
        color:#f8fafc;border:1px solid #334155;border-radius:16px;padding:18px 16px;
        text-align:center;">
      <div style="font-size:12px;letter-spacing:2px;color:#9ca3af;font-weight:700;">
        GHOST 路 LIVE CANDLE CLOCK
      </div>
      <div id="ghost-time" style="font-size:clamp(54px,10vw,82px);line-height:1.12;
          font-weight:800;font-variant-numeric:tabular-nums;color:#34d399;margin:8px 0;">
        00:00
      </div>
      <div id="ghost-label" style="font-size:14px;color:#cbd5e1;">
        seconds until the next 1-minute candle
      </div>
      <div style="display:flex;justify-content:center;gap:10px;align-items:center;
          flex-wrap:wrap;margin-top:14px;">
        <span id="ghost-feed" style="font-size:11px;color:#a7f3d0;
          border:1px solid #365b51;border-radius:20px;padding:5px 9px;">
          {feed_state}
        </span>
        <button id="ghost-sound" type="button" style="border:1px solid #64748b;
          background:#263449;color:#fff;border-radius:20px;padding:7px 12px;
          font-size:12px;font-weight:700;">
          馃敂 ENABLE SOUND
        </button>
      </div>
      <div style="font-size:11px;color:#94a3b8;margin-top:10px;">
        {clock_source} 路 Alerts at 10 seconds and candle change
      </div>
    </div>
    <script>
    (() => {{
      const targetAtLoad = {target_epoch * 1000};
      const serverAtLoad = {now_epoch * 1000};
      const clientAtLoad = Date.now();
      const targetClient = targetAtLoad + (clientAtLoad - serverAtLoad);
      const feedEl = document.getElementById("ghost-feed");
      const timeEl = document.getElementById("ghost-time");
      const labelEl = document.getElementById("ghost-label");
      const soundBtn = document.getElementById("ghost-sound");
      const storageKey = "ghost_candle_sound_enabled";
      let enabled = false;
      try {{ enabled = localStorage.getItem(storageKey) === "yes"; }} catch(e) {{}}
      soundBtn.textContent = enabled ? "馃敂 SOUND ON" : "馃敂 ENABLE SOUND";

      let audioCtx = null;
      function beep(freq, duration) {{
        if (!enabled || !audioCtx) return;
        try {{
          const osc = audioCtx.createOscillator();
          const gain = audioCtx.createGain();
          osc.type = "sine";
          osc.frequency.value = freq;
          gain.gain.setValueAtTime(0.0001, audioCtx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.16, audioCtx.currentTime + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
          osc.connect(gain); gain.connect(audioCtx.destination);
          osc.start(); osc.stop(audioCtx.currentTime + duration + 0.03);
        }} catch(e) {{}}
      }}
      soundBtn.addEventListener("click", () => {{
        enabled = !enabled;
        try {{ localStorage.setItem(storageKey, enabled ? "yes" : "no"); }} catch(e) {{}}
        if (enabled) {{
          const AudioContextClass = window.AudioContext || window.webkitAudioContext;
          if (AudioContextClass) {{
            audioCtx = new AudioContextClass();
            if (audioCtx.state === "suspended") audioCtx.resume();
            beep(880, 0.12);
          }}
          soundBtn.textContent = "馃敂 SOUND ON";
        }} else {{
          soundBtn.textContent = "馃敂 ENABLE SOUND";
        }}
      }});

      const minuteKey = "ghost_last_candle_alert";
      let lastTenKey = "";
      let lastBoundaryKey = "";
      function updateClock() {{
        const now = Date.now();
        const remainingMs = targetClient - now;
        const remaining = Math.max(0, Math.ceil(remainingMs / 1000));
        const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
        const ss = String(remaining % 60).padStart(2, "0");
        timeEl.textContent = mm + ":" + ss;
        labelEl.textContent = remaining > 0
          ? "seconds until the next 1-minute candle"
          : "new candle boundary reached";
        timeEl.style.color = remaining <= 10 ? "#fbbf24" : "#34d399";

        const thisMinute = Math.floor(now / 60000);
        const tenKey = String(thisMinute) + ":10";
        if (remaining === 10 && lastTenKey !== tenKey) {{
          lastTenKey = tenKey;
          beep(660, 0.18);
        }}
        if (remaining === 0) {{
          const boundaryKey = String(Math.floor(targetClient / 60000));
          if (lastBoundaryKey !== boundaryKey) {{
            lastBoundaryKey = boundaryKey;
            beep(990, 0.28);
          }}
        }}
      }}
      updateClock();
      setInterval(updateClock, 100);
    }})();
    </script>
    """
    components.html(html, height=225, scrolling=False)


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
# FOREX ENGINE 鈥� THREE STEPS
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
    data = one_minute.set_index("datetime")
    result = data.resample(
        f"{minutes}min",
        label="left",
        closed="left"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last"
    }).dropna().reset_index()

    now = pd.Timestamp.now(tz="UTC").floor("min")
    result = result[
        result.datetime + pd.Timedelta(minutes=minutes) <= now
    ]
    return result.reset_index(drop=True)



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


def ghost_protocol(ticks):
    """Candle 1 identifies, Candle 2 prepares/confirms, Candle 3 is entry."""
    if ticks is None or ticks.empty:
        return {
            "signal": "WAIT", "stage": "SCANNING",
            "reason": "Waiting for Deriv tick data."
        }

    latest_price = float(ticks.close.iloc[-1])
    now = pd.Timestamp.now(tz="UTC")
    latest_tick = pd.Timestamp(ticks.datetime.iloc[-1])
    tick_age = (now - latest_tick).total_seconds()

    base = {
        "signal": "WAIT",
        "stage": "SCANNING",
        "reason": "Waiting for a new three-candle staircase.",
        "price": latest_price,
        "tick_time": latest_tick,
        "tick_age": tick_age
    }

    if tick_age > 8 or tick_age < -2:
        return {**base, "stage": "FEED CHECK", "reason":
                f"Deriv feed is stale or time-misaligned ({tick_age:.1f}s)."}

    candles = ticks_to_candles(ticks)
    if len(candles) < 4:
        return {**base, "reason": "Collecting enough one-minute candles."}

    current_minute = now.floor("min")
    forming = candles[candles.datetime == current_minute]
    completed = candles[candles.datetime < current_minute].reset_index(drop=True)

    if forming.empty or len(completed) < 3:
        return {**base, "reason": "Waiting for the current one-minute candle and history."}

    candle_age = (now - current_minute).total_seconds()
    base.update({
        "candle_time": current_minute,
        "candle_age": candle_age
    })

    # Candle 2 is forming: the latest completed candle is Candle 1.
    c1 = completed.iloc[-1]
    previous = completed.iloc[-2]
    c1_time = pd.Timestamp(c1.datetime)
    direction, pattern = identify_candle_one(c1, previous)
    c1_close = float(c1.close)

    if direction and current_minute == c1_time + pd.Timedelta(minutes=1):
        beyond_level = (
            latest_price > c1_close if direction == "CALL"
            else latest_price < c1_close
        )
        seconds_to_candle3 = max(
            0, int(60 - candle_age)
        )
        if beyond_level:
            return {
                **base,
                "signal": direction,
                "stage": "PREPARE",
                "reason": (
                    f"{pattern} identified. Candle 2 has moved beyond "
                    f"Candle 1 close ({fmt_price(c1_close)}). Prepare for "
                    "Candle 3; wait for its entry confirmation."
                ),
                "stage_detail": "CANDLE 2 IS CONFIRMING",
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "entry_time": current_minute + pd.Timedelta(minutes=1),
                "countdown": seconds_to_candle3
            }
        return {
            **base,
            "stage": "CANDLE 2 WAITING",
            "reason": (
                f"{pattern} found. Waiting for price to move "
                f"{'above' if direction == 'CALL' else 'below'} "
                f"Candle 1 close at {fmt_price(c1_close)}."
            ),
            "pattern": pattern,
            "entry_point": c1_close,
            "candle1_time": c1_time
        }

    # Candle 3 is forming: completed[-2] is Candle 1 and completed[-1] is Candle 2.
    c1 = completed.iloc[-2]
    c2 = completed.iloc[-1]
    previous = completed.iloc[-3]
    c1_time = pd.Timestamp(c1.datetime)
    direction, pattern = identify_candle_one(c1, previous)
    c1_close = float(c1.close)
    c2_close = float(c2.close)

    if direction and current_minute == c1_time + pd.Timedelta(minutes=2):
        candle2_confirmed = (
            c2_close > c1_close if direction == "CALL"
            else c2_close < c1_close
        )
        candle3_still_valid = (
            latest_price > c1_close if direction == "CALL"
            else latest_price < c1_close
        )

        if not candle2_confirmed:
            return {
                **base,
                "stage": "INVALIDATED",
                "reason": (
                    "Candle 2 did not close beyond Candle 1's closing "
                    "price. The staircase is invalid. Do not enter."
                ),
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "candle2_close": c2_close
            }

        if not candle3_still_valid:
            return {
                **base,
                "stage": "INVALIDATED",
                "reason": (
                    "Candle 3 has moved back across the Candle 1 closing "
                    "level. The setup is invalid. Do not enter."
                ),
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "candle2_close": c2_close
            }

        return {
            **base,
            "signal": direction,
            "stage": "ENTRY READY",
            "reason": (
                f"Candle 2 closed {'above' if direction == 'CALL' else 'below'} "
                f"Candle 1 close. Candle 3 is on the valid side of the entry "
                f"level ({fmt_price(c1_close)}). Manual "
                f"{'RISE' if direction == 'CALL' else 'FALL'} entry window."
            ),
            "stage_detail": "CANDLE 2 CONFIRMED 鈥� CANDLE 3 ENTRY",
            "pattern": pattern,
            "entry_point": c1_close,
            "candle1_time": c1_time,
            "candle2_close": c2_close,
            "entry_time": current_minute,
            "countdown": max(0, int(60 - candle_age))
        }

    return {
        **base,
        "stage": "SCANNING",
        "reason": (
            "Waiting for the next valid Candle 1 鈫� Candle 2 鈫� Candle 3 "
            "sequence. Candle size and higher-timeframe momentum are not filters."
        )
    }


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
        "reference_price": result.get("price"),
        "entry_time": entry.isoformat(),
        "expiry_time": expiration.isoformat(),
        "expiry_minutes": expiry,
        "status": "PREPARE" if result.get("stage") == "PREPARE" else "ENTRY WINDOW"
    }


def show_signal_pad(signal):
    if not signal:
        st.markdown(
            """
            <div class="signal-card signal-wait">
                <h3>WAIT</h3>
                <div class="small-muted">
                    No fresh valid signal. No trade is recommended.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        return

    now = now_cat()
    entry = datetime.fromisoformat(signal["entry_time"])
    expiry = datetime.fromisoformat(signal["expiry_time"])

    if now < entry:
        status = "PREPARE"
        remaining = int((entry - now).total_seconds())
    elif now < expiry:
        status = "ENTRY WINDOW"
        remaining = int((expiry - now).total_seconds())
    else:
        status = "EXPIRED"
        remaining = 0

    color = (
        "signal-call" if signal["direction"] == "CALL"
        else "signal-put"
    )

    st.markdown(
        f"""
        <div class="signal-card {color}">
            <div class="small-muted">
                {signal["market"]} 路 {signal["instrument"]}
            </div>
            <h2>
                {signal["direction"]}
                &nbsp;
                <span style="font-size:0.8em">{status}</span>
            </h2>
            <div><b>{signal.get("stage", status)}</b></div>
            <div>{signal["reason"]}</div>
            <div>Entry level: {fmt_price(signal.get("entry_point"))}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    a, b, c, d = st.columns(4)
    a.metric("Reference price", fmt_price(signal["reference_price"]))
    b.metric(
        "Time remaining",
        f"{remaining // 60:02d}:{remaining % 60:02d}"
    )
    c.metric("Entry time (CAT)", entry.strftime("%H:%M:%S"))
    d.metric("Expiry time (CAT)", expiry.strftime("%H:%M:%S"))

    st.caption(
        "Signal candle: "
        + datetime.fromisoformat(signal["candle_time"]).strftime(
            "%Y-%m-%d %H:%M:%S CAT"
        )
        + " 路 Created: "
        + datetime.fromisoformat(signal["signal_created"]).strftime(
            "%H:%M:%S CAT"
        )
    )

    if status == "EXPIRED":
        st.warning("Signal expired. Do not reuse this signal.")
    elif status == "ENTRY WINDOW":
        st.info(
            "Signal window active. Confirm the live Deriv quote "
            "and contract conditions before any demo entry."
        )


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
            "Pocket Option Forex 路 THREE STEPS",
            "Deriv Synthetics 路 GHOST PROTOCOL"
        ]
    )

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

    st.caption(
        "GHOST checks the Deriv feed every 15 seconds when automatic "
        "scanning is enabled. Forex scans once per minute."
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

if auto_refresh:
    st_autorefresh(interval=15000, key="desk_clock")

now = now_cat()
st.caption(
    f"LOCAL TIME 路 {now.strftime('%A, %d %B %Y 路 %H:%M:%S CAT')}"
)

scan_interval = 15 if market.startswith("Deriv") else 60
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
            with st.spinner(
                "Connecting to Deriv and analysing Volatility 100 (1s)..."
            ):
                with DerivClient(timeout=25) as deriv:
                    symbols = deriv_symbols(deriv)
                    selected = next(
                        (
                            item for item in symbols
                            if item.get("symbol") == GHOST_SYMBOL
                        ),
                        None
                    )

                    if selected is None:
                        raise RuntimeError(
                            f"{GHOST_SYMBOL} was not found in Deriv's "
                            "active-symbol list. Check returned symbols "
                            "and market availability."
                        )

                    ticks = fetch_deriv_ticks(
                        selected["symbol"], 4500, deriv
                    )

                result = ghost_protocol(ticks)

            st.session_state["deriv_output"] = {
                "instrument": GHOST_NAME,
                "symbol": GHOST_SYMBOL,
                "ticks": ticks,
                "candles": ticks_to_candles(ticks),
                "result": result,
                "last_scan": now_cat().isoformat()
            }
            st.session_state["scan_market"] = "deriv"

            if (
                result.get("signal") in ("CALL", "PUT")
                and result.get("stage") in ("PREPARE", "ENTRY READY")
            ):
                existing = st.session_state.get("active_signal")
                same_signal = (
                    existing
                    and existing.get("direction") == result["signal"]
                    and existing.get("candle_time")
                    == as_cat(result["candle_time"]).isoformat()
                    and existing.get("stage") == result.get("stage")
                    and existing.get("instrument") == GHOST_NAME
                )
                if not same_signal:
                    st.session_state["active_signal"] = build_signal_record(
                        "GHOST PROTOCOL", GHOST_NAME, result, 1
                    )
            else:
                active = st.session_state.get("active_signal")
                if active and active.get("instrument") == GHOST_NAME:
                    st.session_state.pop("active_signal", None)

        except Exception as exc:
            st.session_state["deriv_scan_error"] = str(exc)
            st.error(f"GHOST scan failed: {exc}")


# ============================================================
# SIGNAL PAD
# ============================================================

st.subheader("SIGNALS PAD")
active_signal = st.session_state.get("active_signal")
show_signal_pad(active_signal)


# ============================================================
# FOREX DASHBOARD
# ============================================================

if market.startswith("Pocket"):
    st.subheader("THREE STEPS 路 Forex scanner")

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
                        f'Last completed close: {fmt_price(result["price"])} 路 '
                        f'EMA 9: {fmt_price(result["ema9"])} 路 '
                        f'EMA 21: {fmt_price(result["ema21"])}'
                    )


# ============================================================
# GHOST DASHBOARD
# ============================================================

else:
    st.subheader("GHOST 路 THREE-STEP STAIRCASE")

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
        render_ghost_candle_clock(latest_tick_time)
        result = output["result"]
        stage = result.get("stage", "SCANNING")
        direction = result.get("signal", "WAIT")

        st.markdown("### The three-candle sequence")
        a, b, c = st.columns(3)
        a.metric("CANDLE 1", "IDENTIFY")
        b.metric("CANDLE 2", "PREPARE / CONFIRM")
        c.metric("CANDLE 3", "ENTRY")

        st.markdown(f"**Current stage: {stage}**")
        st.write(result.get("reason", "Waiting for a valid setup."))

        if stage == "PREPARE":
            seconds = int(result.get("countdown", 0))
            st.warning(
                f"PREPARE {direction} 鈥� Candle 2 is confirming. "
                f"Candle 3 begins in about {seconds} seconds. "
                "Open Deriv and get ready; wait for the Candle 3 entry check."
            )
        elif stage == "ENTRY READY":
            action = "RISE / CALL" if direction == "CALL" else "FALL / PUT"
            st.success(
                f"CANDLE 2 CONFIRMED 鈥� CANDLE 3 ENTRY: {action}. "
                "This is a manual alert, not an automatic trade."
            )
        elif stage == "INVALIDATED":
            st.error("SETUP INVALIDATED 鈥� DO NOT ENTER.")
        elif stage == "CANDLE 2 WAITING":
            st.info("Candle 1 identified. Waiting for Candle 2 to cross its close.")
        else:
            st.info("SCANNING 鈥� waiting for a valid three-step staircase.")

        tick_age = result.get("tick_age")
        candle_age = result.get("candle_age")
        detail_parts = []
        if tick_age is not None:
            detail_parts.append(f"Tick age: {tick_age:.1f}s")
        if candle_age is not None:
            detail_parts.append(f"Current candle age: {candle_age:.1f}s")
        if detail_parts:
            st.caption(" 路 ".join(detail_parts))

        with st.expander("GHOST live chart and setup details", expanded=True):
            st.plotly_chart(
                chart(output["candles"], GHOST_NAME + " 路 1-minute candles"),
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
        render_ghost_candle_clock()
        st.info(
            "Press CONNECT & SCAN GHOST to connect to Deriv "
            "and retrieve the first set of market data."
        )
        last_error = st.session_state.get("deriv_scan_error")
        if last_error:
            st.warning(f"Most recent Deriv scan error: {last_error}")


# ============================================================
# FOOTER
# ============================================================

st.divider()
st.caption(
    "Research and demo alerting only 鈥� not financial advice. "
    "GHOST does not place trades. Deriv data and execution quotes "
    "can differ. Confirm the live contract quote and timing. "
    "No signal guarantees a profitable outcome."
)
