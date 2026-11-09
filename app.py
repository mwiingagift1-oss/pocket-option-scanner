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
    page_title="GHOST Protocol 3.0 - Market Intelligence",
    page_icon="👻",
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
.signal-caution { border-left: 6px solid #f59e0b; }
.small-muted {
    color: #94a3b8;
    font-size: 0.86rem;
}
.intelligence-panel {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 16px;
    margin: 8px 0;
}
.ghost-identity {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid #334155;
    border-radius: 16px;
    padding: 20px;
    margin-bottom: 16px;
}
</style>
""", unsafe_allow_html=True)

st.title("👻 GHOST PROTOCOL 3.0")
st.caption("MARKET INTELLIGENCE SYSTEM • THREE-STEP STAIRCASE • SAKATA INSIGHTS")

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
# GHOST CANDLE CLOCK
# ============================================================

def render_ghost_candle_clock(latest_tick=None):
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
        if feed_age <= 8:
            target_epoch = candle_start + 60
            clock_source = "DERIV TICK TIMESTAMP"
            feed_state = "LIVE FEED"
        else:
            target_epoch = int(now_epoch // 60) * 60 + 60
            clock_source = "LOCAL UTC FALLBACK"
            feed_state = f"FEED DELAYED • LAST TICK {feed_age:.1f}s AGO"
    else:
        target_epoch = int(now_epoch // 60) * 60 + 60
        clock_source = "UTC CLOCK • WAITING FOR DERIV TICKS"
        feed_state = "WAITING FOR LIVE FEED"

    html = f"""
    <div id="ghost-clock" style="font-family:Arial,sans-serif;background:#101827;
        color:#f8fafc;border:1px solid #334155;border-radius:16px;padding:18px 16px;
        text-align:center;">
      <div style="font-size:12px;letter-spacing:2px;color:#9ca3af;font-weight:700;">
        GHOST • LIVE CANDLE CLOCK
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
          🔔 ENABLE SOUND
        </button>
      </div>
      <div style="font-size:11px;color:#94a3b8;margin-top:10px;">
        {clock_source} • Alerts at 10 seconds and candle change
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
      soundBtn.textContent = enabled ? "🔔 SOUND ON" : "🔔 ENABLE SOUND";

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
          soundBtn.textContent = "🔔 SOUND ON";
        }} else {{
          soundBtn.textContent = "🔔 ENABLE SOUND";
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
# FOREX ENGINE
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
# DERIV WEBSOCKET CLIENT
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
# DERIV DATA FUNCTIONS
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
# CANDLE CONSTRUCTION
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
# LAYER A — BUYER/SELLER STORY ENGINE
# ============================================================

def analyze_buyer_seller_story(completed_candles, lookback=10):
    if completed_candles is None or len(completed_candles) < 5:
        return {
            "state": "INSUFFICIENT_DATA",
            "details": "Not enough completed candles for analysis.",
            "bullish_score": 0,
            "bearish_score": 0,
            "dominance": "NEUTRAL"
        }

    recent = completed_candles.tail(lookback).reset_index(drop=True)
    
    bullish_signals = 0
    bearish_signals = 0
    total_weight = 0
    
    for i in range(len(recent)):
        candle = recent.iloc[i]
        o, h, l, c = float(candle.open), float(candle.high), float(candle.low), float(candle.close)
        
        candle_range = max(h - l, 1e-12)
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        
        weight = min(candle_range / recent['high'].max() - recent['low'].min(), 1.0) if recent['high'].max() != recent['low'].min() else 0.5
        total_weight += weight
        
        if c > o:
            bullish_signals += weight * (body / candle_range)
            bullish_signals += weight * (1 - upper_wick / candle_range)
            
        if c < o:
            bearish_signals += weight * (body / candle_range)
            bearish_signals += weight * (1 - lower_wick / candle_range)
            
        if lower_wick > body * 1.5 and lower_wick > candle_range * 0.3:
            bullish_signals += weight * 0.5
        if upper_wick > body * 1.5 and upper_wick > candle_range * 0.3:
            bearish_signals += weight * 0.5
    
    if total_weight > 0:
        bullish_score = bullish_signals / total_weight
        bearish_score = bearish_signals / total_weight
    else:
        bullish_score = 0
        bearish_score = 0
    
    score_diff = bullish_score - bearish_score
    
    if score_diff > 0.3:
        state = "BUYERS_IN_CONTROL"
        dominance = "BULLISH"
    elif score_diff < -0.3:
        state = "SELLERS_IN_CONTROL" 
        dominance = "BEARISH"
    elif abs(score_diff) < 0.1:
        state = "BALANCED_MARKET"
        dominance = "NEUTRAL"
    elif score_diff > 0:
        state = "BUYERS_LOSING_CONTROL"
        dominance = "WEAK_BULLISH"
    else:
        state = "SELLERS_LOSING_CONTROL"
        dominance = "WEAK_BEARISH"
    
    direction_changes = 0
    prev_direction = None
    for i in range(len(recent)):
        candle = recent.iloc[i]
        current_direction = "BULLISH" if candle.close > candle.open else "BEARISH" if candle.close < candle.open else "NEUTRAL"
        if prev_direction and current_direction != "NEUTRAL" and current_direction != prev_direction:
            direction_changes += 1
        if current_direction != "NEUTRAL":
            prev_direction = current_direction
    
    if direction_changes >= len(recent) * 0.6:
        state = "CHOPPY_MARKET"
        dominance = "CHOPPY"
    
    return {
        "state": state,
        "details": f"Bullish score: {bullish_score:.2f}, Bearish score: {bearish_score:.2f}",
        "bullish_score": round(bullish_score, 3),
        "bearish_score": round(bearish_score, 3),
        "dominance": dominance,
        "direction_changes": direction_changes,
        "total_candles": len(recent)
    }

# ============================================================
# LAYER B — SAKATA-INSPIRED CANDLESTICK INTELLIGENCE
# ============================================================

def detect_sakata_patterns(completed_candles, lookback=15):
    if completed_candles is None or len(completed_candles) < 8:
        return []
    
    patterns = []
    recent = completed_candles.tail(lookback).reset_index(drop=True)
    
    # Three Mountains
    highs = []
    for i in range(2, len(recent) - 2):
        candle = recent.iloc[i]
        if candle.high == recent.iloc[i-2:i+3].high.max():
            highs.append((i, candle.high))
    
    if len(highs) >= 3:
        high_values = [h[1] for h in highs[-3:]]
        if max(high_values) - min(high_values) < (recent['high'].max() - recent['low'].min()) * 0.1:
            patterns.append({
                "pattern": "THREE_MOUNTAINS",
                "description": "Repeated highs detected - potential resistance zone",
                "level": sum(high_values) / len(high_values),
                "type": "RESISTANCE"
            })
    
    # Three Rivers
    lows = []
    for i in range(2, len(recent) - 2):
        candle = recent.iloc[i]
        if candle.low == recent.iloc[i-2:i+3].low.min():
            lows.append((i, candle.low))
    
    if len(lows) >= 3:
        low_values = [l[1] for l in lows[-3:]]
        if max(low_values) - min(low_values) < (recent['high'].max() - recent['low'].min()) * 0.1:
            patterns.append({
                "pattern": "THREE_RIVERS", 
                "description": "Repeated lows detected - potential support zone",
                "level": sum(low_values) / len(low_values),
                "type": "SUPPORT"
            })
    
    # Three Methods
    if len(recent) >= 6:
        first_three = recent.iloc[:3]
        last_three = recent.iloc[3:6]
        
        first_direction = "BULLISH" if first_three.iloc[-1].close > first_three.iloc[0].open else "BEARISH"
        last_direction = "BULLISH" if last_three.iloc[-1].close > last_three.iloc[0].open else "BEARISH"
        
        if first_direction == last_direction:
            middle_range = first_three.iloc[1].high - first_three.iloc[1].low
            overall_range = (recent['high'].max() - recent['low'].min())
            
            if middle_range < overall_range * 0.3:
                patterns.append({
                    "pattern": "THREE_METHODS",
                    "description": f"Impulse-Consolidation-{first_direction} continuation pattern",
                    "level": None,
                    "type": "CONTINUATION"
                })
    
    # Three Parallel Lines
    if len(recent) >= 5:
        closes = [candle.close for candle in recent.iloc[-5:]]
        if all(closes[i] > closes[i-1] for i in range(1, len(closes))):
            patterns.append({
                "pattern": "THREE_PARALLEL_LINES",
                "description": "Sustained bullish momentum with consistent closes",
                "level": closes[-1],
                "type": "BULLISH_MOMENTUM"
            })
        elif all(closes[i] < closes[i-1] for i in range(1, len(closes))):
            patterns.append({
                "pattern": "THREE_PARALLEL_LINES", 
                "description": "Sustained bearish momentum with consistent closes",
                "level": closes[-1],
                "type": "BEARISH_MOMENTUM"
            })
    
    return patterns

# ============================================================
# LAYER C — MARKET STRUCTURE INTELLIGENCE
# ============================================================

def analyze_market_structure(completed_candles, lookback=20):
    if completed_candles is None or len(completed_candles) < 8:
        return {
            "trend": "INSUFFICIENT_DATA",
            "structure": "UNKNOWN",
            "support_levels": [],
            "resistance_levels": [],
            "recent_breakout": None,
            "failed_breakout": None
        }
    
    data = completed_candles.tail(lookback).reset_index(drop=True)
    
    swing_highs = []
    swing_lows = []
    
    for i in range(2, len(data) - 2):
        if data.iloc[i].high == data.iloc[i-2:i+3].high.max():
            swing_highs.append((i, data.iloc[i].high))
        if data.iloc[i].low == data.iloc[i-2:i+3].low.min():
            swing_lows.append((i, data.iloc[i].low))
    
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        recent_highs = [h[1] for h in swing_highs[-3:]]
        recent_lows = [l[1] for l in swing_lows[-3:]]
        
        higher_highs = all(recent_highs[i] > recent_highs[i-1] for i in range(1, len(recent_highs)))
        higher_lows = all(recent_lows[i] > recent_lows[i-1] for i in range(1, len(recent_lows)))
        lower_highs = all(recent_highs[i] < recent_highs[i-1] for i in range(1, len(recent_highs)))
        lower_lows = all(recent_lows[i] < recent_lows[i-1] for i in range(1, len(recent_lows)))
        
        if higher_highs and higher_lows:
            trend = "BULLISH_STRUCTURE"
            structure = "HIGHER_HIGHER_LOWS"
        elif lower_highs and lower_lows:
            trend = "BEARISH_STRUCTURE" 
            structure = "LOWER_LOWER_HIGHS"
        elif not higher_highs and not lower_highs:
            trend = "RANGING"
            structure = "SIDEWAYS"
        else:
            trend = "TRANSITIONING"
            structure = "MIXED"
    else:
        trend = "INSUFFICIENT_SWINGS"
        structure = "UNKNOWN"
    
    support_levels = []
    resistance_levels = []
    
    if swing_lows:
        lows_sorted = sorted(swing_lows, key=lambda x: x[1])
        clusters = []
        current_cluster = [lows_sorted[0]]
        
        for low in lows_sorted[1:]:
            if low[1] - current_cluster[-1][1] < (data['high'].max() - data['low'].min()) * 0.05:
                current_cluster.append(low)
            else:
                if len(current_cluster) >= 2:
                    clusters.append(sum(l[1] for l in current_cluster) / len(current_cluster))
                current_cluster = [low]
        
        if len(current_cluster) >= 2:
            clusters.append(sum(l[1] for l in current_cluster) / len(current_cluster))
        
        support_levels = clusters
    
    if swing_highs:
        highs_sorted = sorted(swing_highs, key=lambda x: x[1])
        clusters = []
        current_cluster = [highs_sorted[0]]
        
        for high in highs_sorted[1:]:
            if high[1] - current_cluster[-1][1] < (data['high'].max() - data['low'].min()) * 0.05:
                current_cluster.append(high)
            else:
                if len(current_cluster) >= 2:
                    clusters.append(sum(h[1] for h in current_cluster) / len(current_cluster))
                current_cluster = [high]
        
        if len(current_cluster) >= 2:
            clusters.append(sum(h[1] for h in current_cluster) / len(current_cluster))
        
        resistance_levels = clusters
    
    recent_breakout = None
    failed_breakout = None
    
    if len(data) >= 10:
        recent_high = data['high'].iloc[-5:].max()
        recent_low = data['low'].iloc[-5:].min()
        prior_high = data['high'].iloc[-10:-5].max()
        prior_low = data['low'].iloc[-10:-5].min()
        
        current_close = data['close'].iloc[-1]
        
        if current_close > prior_high:
            recent_breakout = "BULLISH"
        elif current_close < prior_low:
            recent_breakout = "BEARISH"
            
        if recent_breakout and len(data) >= 3:
            if recent_breakout == "BULLISH" and data['low'].iloc[-1] < prior_high:
                failed_breakout = "BULLISH_FAILED"
            elif recent_breakout == "BEARISH" and data['high'].iloc[-1] > prior_low:
                failed_breakout = "BEARISH_FAILED"
    
    return {
        "trend": trend,
        "structure": structure,
        "support_levels": support_levels,
        "resistance_levels": resistance_levels,
        "recent_breakout": recent_breakout,
        "failed_breakout": failed_breakout,
        "swing_highs": swing_highs[-3:] if swing_highs else [],
        "swing_lows": swing_lows[-3:] if swing_lows else []
    }

# ============================================================
# LAYER D — THREE-STEP STAIRCASE ENGINE
# ============================================================

def identify_candle_one(candle, previous):
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

    bullish_rejection = (
        lower_wick >= max(upper_wick * 1.25, candle_range * 0.25)
        and close_position >= 0.55
    )
    bearish_rejection = (
        upper_wick >= max(lower_wick * 1.25, candle_range * 0.25)
        and close_position <= 0.45
    )

    if bullish_rejection:
        return "CALL", "SUPPORT_REJECTION"
    if bearish_rejection:
        return "PUT", "RESISTANCE_REJECTION"
    if c > previous_high:
        return "CALL", "BULLISH_BREAKOUT"
    if c < previous_low:
        return "PUT", "BEARISH_BREAKOUT"
    if c > previous_close:
        return "CALL", "BULLISH_DIRECTIONAL_STEP"
    if c < previous_close:
        return "PUT", "BEARISH_DIRECTIONAL_STEP"
    return None, "NO_CLEAR_FIRST_STEP"

def assess_candle3_risk(completed, direction, c2, latest_price):
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
        warnings.append("Candle 2 is an indecision candle (small body relative to its range).")

    if direction == "CALL":
        if upper_wick >= max(body * 1.5, candle_range * 0.35):
            warnings.append("Candle 2 has a notable upper rejection wick against the bullish move.")
        prior = completed.iloc[:-2].tail(12)
        if not prior.empty:
            resistance = float(prior.high.max())
            distance = resistance - float(latest_price)
            if 0 <= distance <= candle_range:
                warnings.append(f"Price is within one Candle 2 range of a recent high ({fmt_price(resistance)}), which may act as resistance.")
    else:
        if lower_wick >= max(body * 1.5, candle_range * 0.35):
            warnings.append("Candle 2 has a notable lower rejection wick against the bearish move.")
        prior = completed.iloc[:-2].tail(12)
        if not prior.empty:
            support = float(prior.low.min())
            distance = float(latest_price) - support
            if 0 <= distance <= candle_range:
                warnings.append(f"Price is within one Candle 2 range of a recent low ({fmt_price(support)}), which may act as support.")

    return warnings

def detect_choppy_market(completed_candles, lookback=10):
    if completed_candles is None or len(completed_candles) < lookback:
        return False, "INSUFFICIENT_DATA"
    
    recent = completed_candles.tail(lookback).reset_index(drop=True)
    
    direction_changes = 0
    prev_close = None
    progress = 0
    
    for i in range(len(recent)):
        candle = recent.iloc[i]
        current_close = float(candle.close)
        
        if prev_close is not None:
            if (current_close > prev_close and i > 0 and recent.iloc[i-1].close < prev_close) or \
               (current_close < prev_close and i > 0 and recent.iloc[i-1].close > prev_close):
                direction_changes += 1
            
            if abs(current_close - prev_close) > 0:
                progress += 1
        
        prev_close = current_close
    
    price_range = recent['high'].max() - recent['low'].min()
    total_progress = abs(recent['close'].iloc[-1] - recent['close'].iloc[0])
    
    is_choppy = (
        direction_changes >= lookback * 0.6 or
        (price_range > 0 and total_progress < price_range * 0.1) or
        (direction_changes >= 3 and total_progress < price_range * 0.2)
    )
    
    reason = f"Direction changes: {direction_changes}/{lookback}, Progress: {total_progress:.6f}, Range: {price_range:.6f}"
    
    return is_choppy, reason

def enhanced_ghost_protocol(ticks):
    if ticks is None or ticks.empty:
        return {
            "signal": "WAIT", 
            "stage": "SCANNING",
            "reason": "Waiting for Deriv tick data.",
            "intelligence": {}
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
        "tick_age": tick_age,
        "intelligence": {}
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

    # INTEGRATE INTELLIGENCE LAYERS
    intelligence = {}
    
    buyer_seller = analyze_buyer_seller_story(completed)
    intelligence["buyer_seller"] = buyer_seller
    
    sakata_patterns = detect_sakata_patterns(completed)
    intelligence["sakata_patterns"] = sakata_patterns
    
    market_structure = analyze_market_structure(completed)
    intelligence["market_structure"] = market_structure
    
    is_choppy, choppy_reason = detect_choppy_market(completed)
    intelligence["choppy_market"] = {
        "is_choppy": is_choppy,
        "reason": choppy_reason
    }
    
    base["intelligence"] = intelligence

    candle_age = (now - current_minute).total_seconds()
    base.update({
        "candle_time": current_minute,
        "candle_age": candle_age
    })

    # THREE-STEP STAIRCASE LOGIC
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
        seconds_to_candle3 = max(0, int(60 - candle_age))
        
        if is_choppy:
            return {
                **base,
                "stage": "CHOPPY_MARKET",
                "reason": f"Market appears choppy: {choppy_reason}. Better to wait for clearer conditions.",
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "entry_time": current_minute + pd.Timedelta(minutes=1),
                "countdown": seconds_to_candle3
            }
        
        if beyond_level:
            return {
                **base,
                "signal": direction,
                "stage": "SETUP_DEVELOPING",
                "reason": (
                    f"{pattern} identified. Candle 2 is moving beyond "
                    f"Candle 1 close ({fmt_price(c1_close)}). "
                    "Setup is developing - NOT a signal yet. Wait for Candle 3 confirmation."
                ),
                "stage_detail": "CANDLE_2_DEVELOPING",
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "entry_time": current_minute + pd.Timedelta(minutes=1),
                "countdown": seconds_to_candle3
            }
        return {
            **base,
            "stage": "WAITING_FOR_CONFIRMATION",
            "reason": (
                f"{pattern} found. Waiting for price to move "
                f"{'above' if direction == 'CALL' else 'below'} "
                f"Candle 1 close at {fmt_price(c1_close)}."
            ),
            "pattern": pattern,
            "entry_point": c1_close,
            "candle1_time": c1_time
        }

    # Candle 3 is forming
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
                "reason": "Candle 2 did not close beyond Candle 1's closing price. The staircase is invalid. Do not enter.",
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "candle2_close": c2_close
            }

        if not candle3_still_valid:
            return {
                **base,
                "stage": "INVALIDATED",
                "reason": "Candle 3 has moved back across the Candle 1 closing level. The setup is invalid. Do not enter.",
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "candle2_close": c2_close
            }

        warnings = assess_candle3_risk(completed, direction, c2, latest_price)
        
        intelligence_warnings = []
        
        if buyer_seller["state"] in ["SELLERS_IN_CONTROL", "BUYERS_LOSING_CONTROL"] and direction == "CALL":
            intelligence_warnings.append(f"Buyer/seller story shows: {buyer_seller['details']}")
        elif buyer_seller["state"] in ["BUYERS_IN_CONTROL", "SELLERS_LOSING_CONTROL"] and direction == "PUT":
            intelligence_warnings.append(f"Buyer/seller story shows: {buyer_seller['details']}")
        
        if market_structure["trend"] == "BEARISH_STRUCTURE" and direction == "CALL":
            intelligence_warnings.append("Market structure is bearish but trying for bullish move")
        elif market_structure["trend"] == "BULLISH_STRUCTURE" and direction == "PUT":
            intelligence_warnings.append("Market structure is bullish but trying for bearish move")
        
        for resistance in market_structure["resistance_levels"]:
            if abs(latest_price - resistance) < (latest_price * 0.001):
                intelligence_warnings.append(f"Near resistance level: {fmt_price(resistance)}")
        
        for support in market_structure["support_levels"]:
            if abs(latest_price - support) < (latest_price * 0.001):
                intelligence_warnings.append(f"Near support level: {fmt_price(support)}")
        
        all_warnings = warnings + intelligence_warnings
        
        if all_warnings or is_choppy:
            return {
                **base,
                "signal": direction,
                "stage": "CAUTION",
                "reason": "The Three-Step Staircase is valid, but intelligence layers show potential concerns. This is NOT an ENTRY READY signal.",
                "warnings": all_warnings,
                "stage_detail": "STAIRCASE_VALID_CAUTION",
                "pattern": pattern,
                "entry_point": c1_close,
                "candle1_time": c1_time,
                "candle2_close": c2_close,
                "entry_time": current_minute,
                "countdown": max(0, int(60 - candle_age))
            }
        
        return {
            **base,
            "signal": direction,
            "stage": "ENTRY_READY",
            "reason": (
                f"Candle 2 closed {'above' if direction == 'CALL' else 'below'} "
                f"Candle 1 close. Candle 3 is on the valid side of the entry "
                f"level ({fmt_price(c1_close)}). Intelligence layers confirm setup."
            ),
            "warnings": [],
            "stage_detail": "CANDLE_2_CONFIRMED_CANDLE_3_ENTRY",
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
        "reason": "Waiting for the next valid Candle 1 → Candle 2 → Candle 3 sequence. Market intelligence is being monitored."
    }

# ============================================================
# UNIFIED DECISION ENGINE
# ============================================================

def unified_decision_engine(ghost_result, active_signal=None):
    stage = ghost_result.get("stage", "SCANNING")
    signal = ghost_result.get("signal", "WAIT")
    intelligence = ghost_result.get("intelligence", {})
    
    if stage == "FEED CHECK":
        return "FEED_CHECK", "Market data feed is unreliable. Waiting for stable connection."
    
    if intelligence.get("choppy_market", {}).get("is_choppy", False):
        return "MARKET_UNCLEAR", f"Choppy market conditions: {intelligence['choppy_market']['reason']}"
    
    if stage == "SETUP_DEVELOPING":
        return "OBSERVE", "Setup is developing - Candle 2 is forming. This is NOT a signal."
    
    if stage == "INVALIDATED":
        return "INVALIDATED", "Staircase rules have failed. Setup is invalid."
    
    if stage == "CAUTION":
        return "CAUTION", "Staircase is valid but intelligence shows concerns. NOT entry ready."
    
    if stage == "ENTRY_READY":
        warnings = ghost_result.get("warnings", [])
        if warnings:
            return "CAUTION", f"Entry ready but warnings exist: {warnings[0]}"
        
        return "ENTRY_READY", f"Ready for {signal} entry based on confirmed staircase and intelligence."
    
    if stage in ["WAITING_FOR_CONFIRMATION", "CANDLE_2_WAITING"]:
        return "OBSERVE", "Waiting for Candle 2 confirmation."
    
    return "WAIT", ghost_result.get("reason", "No valid setup conditions met.")

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
        st.markdown("""
        <div class="signal-card signal-wait">
            <h3>WAIT</h3>
            <div class="small-muted">
                No fresh valid signal. No trade is recommended.
            </div>
        </div>
        """, unsafe_allow_html=True)
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

    st.markdown(f"""
    <div class="signal-card {color}">
        <div class="small-muted">
            {signal["market"]} • {signal["instrument"]}
        </div>
        <h2>
            {signal["direction"]}
            <span style="font-size:0.8em">{status}</span>
        </h2>
        <div><b>{signal.get("stage", status)}</b></div>
        <div>{signal["reason"]}</div>
        <div>Entry level: {fmt_price(signal.get("entry_point"))}</div>
    </div>
    """, unsafe_allow_html=True)

    a, b, c, d = st.columns(4)
    a.metric("Reference price", fmt_price(signal["reference_price"]))
    b.metric("Time remaining", f"{remaining // 60:02d}:{remaining % 60:02d}")
    c.metric("Entry time (CAT)", entry.strftime("%H:%M:%S"))
    d.metric("Expiry time (CAT)", expiry.strftime("%H:%M:%S"))

    st
