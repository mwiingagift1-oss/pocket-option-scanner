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
