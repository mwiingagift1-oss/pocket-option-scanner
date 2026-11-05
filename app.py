
import os
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

try:
    import websocket
except ImportError:
    websocket = None


# ============================================================
# CONFIGURATION
# ============================================================

TZ = ZoneInfo("Africa/Lusaka")

DERIV_PUBLIC_WS = (
    "wss://api.derivws.com/trading/v1/options/ws/public"
)

GHOST_SYMBOL = "1HZ100V"
GHOST_NAME = "Volatility 100 (1s) Index"

FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY"
]

st.set_page_config(
    page_title="Market Signal Desk",
    page_icon="📡",
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

st.title("📡 MARKET SIGNAL DESK")
st.caption(
    "THREE STEPS Forex engine · GHOST multi-timeframe Deriv engine · CAT"
)


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
    return f"{value:.5f}" if abs(value) < 100 else f"{value:.3f}"


def blank_result(reason):
    return {
        "signal": "WAIT",
        "reason": reason
    }


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
        df[column] = pd.to_numeric(
            df[column], errors="coerce"
        )

    df["datetime"] = pd.to_datetime(
        df["datetime"], utc=True, errors="coerce"
    )

    df = (
        df.dropna(
            subset=["datetime", "open", "high", "low", "close"]
        )
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
        high_window = high_values[
            i-strength:i+strength+1
        ]
        low_window = low_values[
            i-strength:i+strength+1
        ]

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


def three_steps(
    df,
    strength=2,
    min_steps=3,
    pullback_pct=50
):
    if len(df) < 50:
        return blank_result(
            "Waiting for enough completed candles."
        )

    highs, lows = confirmed_pivots(df, strength)

    hs = highs[-min_steps:]
    ls = lows[-min_steps:]

    if len(hs) < min_steps or len(ls) < min_steps:
        return blank_result(
            "Waiting for confirmed swing structure."
        )

    bullish = (
        all(
            hs[i][1] > hs[i-1][1]
            for i in range(1, len(hs))
        )
        and
        all(
            ls[i][1] > ls[i-1][1]
            for i in range(1, len(ls))
        )
    )

    bearish = (
        all(
            hs[i][1] < hs[i-1][1]
            for i in range(1, len(hs))
        )
        and
        all(
            ls[i][1] < ls[i-1][1]
            for i in range(1, len(ls))
        )
    )

    close = df.close

    ema9 = close.ewm(
        span=9, adjust=False
    ).mean()

    ema21 = close.ewm(
        span=21, adjust=False
    ).mean()

    middle = close.rolling(20).mean()
    deviation = close.rolling(20).std()

    last = df.iloc[-1]
    previous = df.iloc[-2]

    median_range = float(
        (df.high - df.low).tail(20).median()
    )

    extension = abs(
        float(last.close - ema9.iloc[-1])
    )

    tail = df.tail(12)

    move = float(
        tail.high.max() - tail.low.min()
    )

    recent_pullback = (
        float(tail.high.max() - tail.close.iloc[-1])
        if bullish
        else float(tail.close.iloc[-1] - tail.low.min())
    )

    pullback_ok = (
        move <= 0
        or recent_pullback <= move * (pullback_pct / 100)
    )

    late = (
        median_range > 0
        and extension > 2.5 * median_range
    )

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

    signal = (
        "CALL" if call
        else "PUT" if put
        else "WAIT"
    )

    reason = (
        "Confirmed higher highs and higher lows with upward resumption."
        if call
        else
        "Confirmed lower highs and lower lows with downward resumption."
        if put
        else
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
            raise RuntimeError(
                f"Could not connect to Deriv: {exc}"
            )

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
    data = client.request({
        "active_symbols": "brief"
    })

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


def fetch_deriv_ticks(
    symbol,
    count=4500,
    client=None
):
    if client is None:
        with DerivClient(timeout=25) as temporary:
            return fetch_deriv_ticks(
                symbol, count, temporary
            )

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

    if (
        not prices
        or not times
        or len(prices) != len(times)
    ):
        raise RuntimeError(
            "Deriv returned insufficient tick history."
        )

    df = pd.DataFrame({
        "datetime": pd.to_datetime(
            times, unit="s", utc=True
        ),
        "close": pd.to_numeric(
            prices, errors="coerce"
        )
    })

    df = (
        df.dropna()
        .sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
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
        .sort_index()
    )

    candles = series.resample("1min").ohlc()

    return (
        candles.dropna()
        .reset_index()
    )


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

    # Only use fully completed higher-timeframe candles.
    result = result[
        result.datetime
        + pd.Timedelta(minutes=minutes)
        <= now
    ]

    return result.reset_index(drop=True)


# ============================================================
# GHOST MULTI-TIMEFRAME STRATEGY
# ============================================================

def ghost_protocol(ticks):

    wait = {
        "signal": "WAIT",
        "reason": "Waiting for aligned market conditions.",
        "stage": "ANALYSING",
        "stage_detail": ""
    }

    one_minute = ticks_to_candles(ticks)

    if len(one_minute) < 20:
        return {
            **wait,
            "reason": "Collecting more one-minute candles."
        }

    now = pd.Timestamp.now(tz="UTC")
    current_minute = now.floor("min")

    # Developing one-minute candle.
    current = one_minute[
        one_minute.datetime == current_minute
    ]

    # Completed one-minute candles only for higher timeframes.
    completed_1m = one_minute[
        one_minute.datetime < current_minute
    ].copy()

    five = aggregate_timeframe(completed_1m, 5)
    fifteen = aggregate_timeframe(completed_1m, 15)

    if len(five) < 6 or len(fifteen) < 5:
        return {
            **wait,
            "reason": "Collecting enough completed 5m and 15m candles."
        }

    if current.empty:
        return {
            **wait,
            "reason": "Waiting for the developing 1m candle."
        }

    live = current.iloc[-1]

    price = float(ticks.close.iloc[-1])
    latest_tick = ticks.datetime.iloc[-1]

    tick_age = (
        now - latest_tick
    ).total_seconds()

    # Reject stale prices.
    if tick_age > 5 or tick_age < -2:
        return {
            **wait,
            "reason": (
                f"Deriv feed is stale or time-misaligned "
                f"({tick_age:.1f}s)."
            ),
            "tick_age": tick_age
        }

    # Do not signal immediately at the start of a new candle.
    candle_age = (
        now - current_minute
    ).total_seconds()

    if candle_age < 10:
        return {
            **wait,
            "reason": "Waiting for the first 10 seconds of the 1m candle.",
            "tick_age": tick_age
        }

    if candle_age > 55:
        return {
            **wait,
            "reason": "Too late in the current 1m candle for a fresh signal.",
            "tick_age": tick_age
        }

    # --------------------------------------------------------
    # 15-MINUTE MAJOR DIRECTION
    # --------------------------------------------------------

    fifteen["ema3"] = fifteen.close.ewm(
        span=3, adjust=False
    ).mean()

    fifteen["ema5"] = fifteen.close.ewm(
        span=5, adjust=False
    ).mean()

    f15 = fifteen.iloc[-1]

    bullish_15 = (
        f15.ema3 > f15.ema5
        and f15.close > f15.open
    )

    bearish_15 = (
        f15.ema3 < f15.ema5
        and f15.close < f15.open
    )

    # --------------------------------------------------------
    # 5-MINUTE MOMENTUM CONFIRMATION
    # --------------------------------------------------------

    five["ema3"] = five.close.ewm(
        span=3, adjust=False
    ).mean()

    five["ema5"] = five.close.ewm(
        span=5, adjust=False
    ).mean()

    f5 = five.iloc[-1]
    previous_5 = five.iloc[-2]

    bullish_5 = (
        f5.ema3 > f5.ema5
        and f5.close > f5.open
        and f5.close > previous_5.close
    )

    bearish_5 = (
        f5.ema3 < f5.ema5
        and f5.close < f5.open
        and f5.close < previous_5.close
    )

    # --------------------------------------------------------
    # DEVELOPING 1-MINUTE ENTRY
    # --------------------------------------------------------

    candle_open = float(live.open)
    candle_high = float(live.high)
    candle_low = float(live.low)

    candle_range = max(
        candle_high - candle_low,
        1e-12
    )

    body = abs(price - candle_open)
    body_strength = body / candle_range

    bullish_1 = (
        price > candle_open
        and body_strength >= 0.35
    )

    bearish_1 = (
        price < candle_open
        and body_strength >= 0.35
    )

    # --------------------------------------------------------
    # FINAL ALIGNMENT
    # --------------------------------------------------------

    call = (
        bullish_15
        and bullish_5
        and bullish_1
    )

    put = (
        bearish_15
        and bearish_5
        and bearish_1
    )

    if call:
        signal = "CALL"
        reason = (
            "15m bullish direction, 5m bullish momentum "
            "and developing 1m bullish entry."
        )

    elif put:
        signal = "PUT"
        reason = (
            "15m bearish direction, 5m bearish momentum "
            "and developing 1m bearish entry."
        )

    else:
        signal = "WAIT"
        reason = (
            "The 15m trend, 5m momentum and 1m entry "
            "are not fully aligned."
        )

    return {
        "signal": signal,
        "reason": reason,
        "stage": (
            "SIGNAL READY"
            if signal != "WAIT"
            else "WAITING FOR ALIGNMENT"
        ),
        "stage_detail": reason,
        "price": price,
        "candle_time": current_minute,
        "tick_time": latest_tick,
        "tick_age": tick_age,
        "candle_age": candle_age,
        "trend_15m": (
            "BULLISH" if bullish_15
            else "BEARISH" if bearish_15
            else "NEUTRAL"
        ),
        "momentum_5m": (
            "BULLISH" if bullish_5
            else "BEARISH" if bearish_5
            else "NEUTRAL"
        ),
        "entry_1m": (
            "BULLISH" if bullish_1
            else "BEARISH" if bearish_1
            else "NEUTRAL"
        ),
        "body_strength": body_strength
    }


# ============================================================
# SIGNAL TIMER AND RECORD
# ============================================================

def build_signal_record(
    market,
    instrument,
    result,
    expiry=1
):
    created = now_cat()

    entry = created
    expiration = entry + timedelta(minutes=expiry)

    return {
        "market": market,
        "instrument": instrument,
        "direction": result["signal"],
        "reason": result["reason"],
        "signal_created": created.isoformat(),
        "candle_time": as_cat(
            result["candle_time"]
        ).isoformat(),
        "reference_price": result["price"],
        "entry_time": entry.isoformat(),
        "expiry_time": expiration.isoformat(),
        "expiry_minutes": expiry,
        "status": "ENTRY WINDOW"
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

    entry = datetime.fromisoformat(
        signal["entry_time"]
    )

    expiry = datetime.fromisoformat(
        signal["expiry_time"]
    )

    if now < entry:
        status = "PREPARE"
        remaining = int(
            (entry - now).total_seconds()
        )

    elif now < expiry:
        status = "ENTRY WINDOW"
        remaining = int(
            (expiry - now).total_seconds()
        )

    else:
        status = "EXPIRED"
        remaining = 0

    color = (
        "signal-call"
        if signal["direction"] == "CALL"
        else "signal-put"
    )

    st.markdown(
        f"""
        <div class="signal-card {color}">
            <div class="small-muted">
                {signal["market"]} · {signal["instrument"]}
            </div>
            <h2>
                {signal["direction"]}
                &nbsp;
                <span style="font-size:0.8em">{status}</span>
            </h2>
            <div>{signal["reason"]}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Reference price",
        fmt_price(signal["reference_price"])
    )

    b.metric(
        "Time remaining",
        f"{remaining // 60:02d}:{remaining % 60:02d}"
    )

    c.metric(
        "Entry time (CAT)",
        entry.strftime("%H:%M:%S")
    )

    d.metric(
        "Expiry time (CAT)",
        expiry.strftime("%H:%M:%S")
    )

    st.caption(
        "Signal candle: "
        + datetime.fromisoformat(
            signal["candle_time"]
        ).strftime("%Y-%m-%d %H:%M:%S CAT")
        + " · Created: "
        + datetime.fromisoformat(
            signal["signal_created"]
        ).strftime("%H:%M:%S CAT")
    )

    if status == "EXPIRED":
        st.warning(
            "Signal expired. Do not reuse this signal."
        )

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
            "Pocket Option Forex · THREE STEPS",
            "Deriv Synthetics · GHOST PROTOCOL"
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
            value=st.secrets.get(
                "TWELVE_DATA_API_KEY",
                os.getenv("TWELVE_DATA_API_KEY", "")
            ),
            type="password"
        )

        pairs = st.multiselect(
            "Forex pairs",
            FOREX_PAIRS,
            default=FOREX_PAIRS
        )

        pivot_strength = st.slider(
            "Swing confirmation",
            2, 4, 2
        )

        min_steps = st.slider(
            "Minimum staircase steps",
            3, 5, 3
        )

        pullback_pct = st.slider(
            "Maximum pullback (%)",
            20, 70, 50, 5
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
    st_autorefresh(
        interval=5000,
        key="desk_clock"
    )

now = now_cat()

st.caption(
    f"LOCAL TIME · {now.strftime('%A, %d %B %Y · %H:%M:%S CAT')}"
)

if market.startswith("Deriv"):
    scan_interval = 15
else:
    scan_interval = 60

scan_slot = int(time.time() // scan_interval)

last_slot = st.session_state.get(
    "last_auto_scan_slot"
)

auto_scan_due = (
    auto_scan
    and scan_slot != last_slot
)

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
            st.warning(
                "Select at least one Forex pair."
            )

        else:
            output = []
            progress = st.progress(0)
            note = st.empty()

            for i, pair in enumerate(pairs):

                note.write(f"Scanning {pair}...")

                try:
                    df = fetch_forex(
                        pair,
                        api_key,
                        candles_count
                    )

                    result = three_steps(
                        df,
                        pivot_strength,
                        min_steps,
                        pullback_pct
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

                progress.progress(
                    (i + 1) / len(pairs)
                )

            note.empty()

            st.session_state["scan_output"] = output
            st.session_state["scan_market"] = "forex"

            candidates = [
                item for item in output
                if item.get("result", {}).get("signal")
                in ("CALL", "PUT")
            ]

            if candidates:
                chosen = max(
                    candidates,
                    key=lambda item: item["result"]["candle_time"]
                )

                st.session_state["active_signal"] = (
                    build_signal_record(
                        "THREE STEPS",
                        chosen["instrument"],
                        chosen["result"],
                        expiry
                    )
                )
            else:
                st.session_state.pop(
                    "active_signal", None
                )

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
                            "active-symbol list. Check the returned "
                            "symbols and market availability."
                        )

                    ticks = fetch_deriv_ticks(
                        selected["symbol"],
                        4500,
                        deriv
                    )

                result = ghost_protocol(ticks)

            st.session_state["deriv_output"] = {
                "instrument": GHOST_NAME,
                "symbol": GHOST_SYMBOL,
                "ticks": ticks,
                "candles": ticks_to_candles(ticks),
                "result": result
            }

            st.session_state["scan_market"] = "deriv"

            if result.get("signal") in ("CALL", "PUT"):

                existing = st.session_state.get(
                    "active_signal"
                )

                same_signal = (
                    existing
                    and existing.get("direction") == result["signal"]
                    and existing.get("candle_time")
                    == as_cat(result["candle_time"]).isoformat()
                    and existing.get("instrument") == GHOST_NAME
                )

                # Do not restart the timer for the same candle signal.
                if not same_signal:
                    st.session_state["active_signal"] = (
                        build_signal_record(
                            "GHOST PROTOCOL",
                            GHOST_NAME,
                            result,
                            1
                        )
                    )

            else:
                # No current alignment means no current GHOST signal.
                active = st.session_state.get("active_signal")

                if (
                    active
                    and active.get("instrument") == GHOST_NAME
                ):
                    st.session_state.pop(
                        "active_signal", None
                    )

        except Exception as exc:
            st.error(f"GHOST scan failed: {exc}")


# ============================================================
# SIGNAL PAD
# ============================================================

st.subheader("SIGNALS PAD")

active_signal = st.session_state.get(
    "active_signal"
)

show_signal_pad(active_signal)


# ============================================================
# FOREX DASHBOARD
# ============================================================

if market.startswith("Pocket"):

    st.subheader("THREE STEPS · Forex scanner")

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
                st.error(
                    f'{item["instrument"]}: {item["error"]}'
                )
                continue

            result = item["result"]

            col1, col2, col3 = st.columns([2, 1, 3])

            col1.markdown(
                f'**{item["instrument"]}**'
            )

            col2.metric(
                "Signal",
                result["signal"]
            )

            col3.write(
                result["reason"]
            )

            with st.expander("Chart & details"):

                st.plotly_chart(
                    chart(item["df"], item["instrument"]),
                    use_container_width=True
                )

                if "price" in result:
                    st.write(
                        f'Last completed close: '
                        f'{fmt_price(result["price"])} · '
                        f'EMA 9: {fmt_price(result["ema9"])} · '
                        f'EMA 21: {fmt_price(result["ema21"])}'
                    )


# ============================================================
# GHOST DASHBOARD
# ============================================================

else:

    st.subheader(
        "GHOST PROTOCOL · Deriv Rise/Fall"
    )

    output = (
        st.session_state.get("deriv_output")
        if st.session_state.get("scan_market") == "deriv"
        else None
    )

    if output:

        result = output["result"]

        col1, col2, col3 = st.columns([2, 1, 3])

        col1.markdown(
            f'**{output["instrument"]}**'
        )

        col2.metric(
            "Signal",
            result["signal"]
        )

        col3.write(
            result["reason"]
        )

        st.markdown("### Multi-timeframe analysis")

        a, b, c = st.columns(3)

        a.metric(
            "15-minute direction",
            result.get("trend_15m", "—")
        )

        b.metric(
            "5-minute momentum",
            result.get("momentum_5m", "—")
        )

        c.metric(
            "1-minute entry",
            result.get("entry_1m", "—")
        )

        st.caption(
            f'Tick age: {result.get("tick_age", 0):.2f}s · '
            f'1m candle age: {result.get("candle_age", 0):.1f}s · '
            f'1m body strength: '
            f'{result.get("body_strength", 0):.0%}'
        )

        if result["signal"] == "CALL":
            st.success(
                "RISE conditions aligned. This is a demo research signal, "
                "not a guaranteed winning trade."
            )

        elif result["signal"] == "PUT":
            st.error(
                "FALL conditions aligned. This is a demo research signal, "
                "not a guaranteed winning trade."
            )

        else:
            st.info(
                "NO SIGNAL. Wait for all three timeframes to align."
            )

        with st.expander("GHOST live chart and details", expanded=True):

            st.plotly_chart(
                chart(
                    output["candles"],
                    GHOST_NAME + " · 1-minute candles"
                ),
                use_container_width=True
            )

            st.write(
                f'Latest price: {fmt_price(result["price"])}'
            )

            st.write(
                f'15m direction: {result.get("trend_15m", "—")}'
            )

            st.write(
                f'5m momentum: {result.get("momentum_5m", "—")}'
            )

            st.write(
                f'1m entry: {result.get("entry_1m", "—")}'
            )

    else:

        st.info(
            "Press CONNECT & SCAN GHOST to connect to Deriv "
            "and retrieve the first set of market data."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Research and demo alerting only — not financial advice. "
    "GHOST does not place trades. Deriv data and execution quotes "
    "can differ. Confirm the live contract quote and timing. "
    "No signal guarantees a profitable outcome."
)
