import os, json, time
from datetime import datetime, timedelta, timezone
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

TZ = ZoneInfo('Africa/Lusaka')
DERIV_APP_ID = os.getenv('DERIV_APP_ID', '1089')
FOREX_PAIRS = ['EUR/USD','GBP/USD','USD/JPY','USD/CHF','AUD/USD','USD/CAD','NZD/USD','EUR/GBP','EUR/JPY','GBP/JPY']

st.set_page_config(page_title='Market Signal Desk', page_icon='📡', layout='wide')
st.markdown('''<style>
.block-container{padding-top:1.2rem;padding-bottom:2rem;max-width:1450px}
[data-testid="stMetric"]{background:#111827;padding:14px;border-radius:12px;border:1px solid #263244}
.signal-card{padding:18px 20px;border-radius:14px;background:#111827;border:1px solid #334155;margin:8px 0}
.signal-call{border-left:6px solid #16a34a}.signal-put{border-left:6px solid #dc2626}.signal-wait{border-left:6px solid #64748b}
.small-muted{color:#94a3b8;font-size:0.86rem}
</style>''', unsafe_allow_html=True)

st.title('📡 MARKET SIGNAL DESK')
st.caption('Two independent market engines · Completed candles · CAT (Africa/Lusaka)')

# --- Shared helpers ---
def now_cat(): return datetime.now(TZ)
def as_cat(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None: ts = ts.tz_localize('UTC')
    return ts.tz_convert('Africa/Lusaka')
def fmt_price(value): return f'{value:.5f}' if abs(value) < 100 else f'{value:.3f}'
def blank_result(reason): return {'signal':'WAIT','reason':reason}

def fetch_forex(symbol, key, count):
    r = requests.get('https://api.twelvedata.com/time_series', params={
        'symbol':symbol,'interval':'1min','outputsize':count+3,'apikey':key,'format':'JSON','timezone':'UTC'}, timeout=20)
    r.raise_for_status(); payload = r.json()
    if 'values' not in payload: raise RuntimeError(payload.get('message', 'Twelve Data returned no candles'))
    df = pd.DataFrame(payload['values'])
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True, errors='coerce')
    df = df.dropna(subset=['datetime','open','high','low','close']).sort_values('datetime').reset_index(drop=True)
    # Keep only fully completed one-minute candles.
    cutoff = pd.Timestamp.now(tz='UTC').floor('min')
    return df[df.datetime < cutoff].tail(count).reset_index(drop=True)

def confirmed_pivots(df, strength):
    highs, lows = [], []
    h, l = df.high.to_numpy(), df.low.to_numpy()
    for i in range(strength, len(df)-strength):
        wh, wl = h[i-strength:i+strength+1], l[i-strength:i+strength+1]
        if h[i] == wh.max() and (wh == h[i]).sum() == 1: highs.append((i,float(h[i])))
        if l[i] == wl.min() and (wl == l[i]).sum() == 1: lows.append((i,float(l[i])))
    return highs, lows

def _swing_sequence_direction(points, direction, tolerance):
    """Allow small imperfect swing steps while preserving the overall micro-trend."""
    if len(points) < 3:
        return False
    values = [point[1] for point in points]
    deltas = [b-a for a,b in zip(values, values[1:])]
    if direction == 'up':
        advances = sum(delta > tolerance for delta in deltas)
        pullbacks = sum(delta < -tolerance for delta in deltas)
        return values[-1] > values[0] + tolerance and advances >= 1 and pullbacks <= 1
    advances = sum(delta < -tolerance for delta in deltas)
    pullbacks = sum(delta > tolerance for delta in deltas)
    return values[-1] < values[0] - tolerance and advances >= 1 and pullbacks <= 1

def three_steps(df, strength=2, min_steps=3, pullback_pct=50):
    """Micro-trend layer: PREPARE on structure, ENTRY only after candle confirmation."""
    if len(df) < 50:
        return {**blank_result('Waiting for enough completed candles.'), 'stage':'WAIT', 'bias':'NONE'}
    highs, lows = confirmed_pivots(df, strength)
    hs, ls = highs[-max(min_steps, 4):], lows[-max(min_steps, 4):]
    if len(hs) < min_steps or len(ls) < min_steps:
        return {**blank_result('Waiting for at least three confirmed swing highs and lows.'), 'stage':'WAIT', 'bias':'NONE'}

    c = df.close
    e9 = c.ewm(span=9, adjust=False).mean()
    e21 = c.ewm(span=21, adjust=False).mean()
    mid = c.rolling(20).mean()
    std = c.rolling(20).std()
    last, prev = df.iloc[-1], df.iloc[-2]
    bar_med = float((df.high-df.low).tail(20).median())
    tolerance = max(abs(float(last.close))*0.000015, bar_med*0.10)
    recent_h, recent_l = hs[-min_steps:], ls[-min_steps:]
    bull_structure = (_swing_sequence_direction(recent_h, 'up', tolerance) and
                      _swing_sequence_direction(recent_l, 'up', tolerance))
    bear_structure = (_swing_sequence_direction(recent_h, 'down', tolerance) and
                      _swing_sequence_direction(recent_l, 'down', tolerance))

    # Permit small countertrend candles and pullbacks inside the staircase.
    tail = df.tail(12)
    total_range = float(tail.high.max()-tail.low.min())
    bull_pullback = float(tail.high.max()-last.close)
    bear_pullback = float(last.close-tail.low.min())
    limit = max(0.20, min(0.70, pullback_pct/100))
    bull_pullback_ok = total_range <= 0 or bull_pullback <= total_range*limit
    bear_pullback_ok = total_range <= 0 or bear_pullback <= total_range*limit

    bull_context = bull_structure and e9.iloc[-1] >= e21.iloc[-1] and last.close >= mid.iloc[-1] and bull_pullback_ok
    bear_context = bear_structure and e9.iloc[-1] <= e21.iloc[-1] and last.close <= mid.iloc[-1] and bear_pullback_ok
    bull_confirm = last.close > last.open and (last.close > prev.high or last.close > prev.close)
    bear_confirm = last.close < last.open and (last.close < prev.low or last.close < prev.close)
    extension = abs(float(last.close-e9.iloc[-1]))
    late = bar_med > 0 and extension > 3.5*bar_med

    if bull_context and bull_confirm and not late:
        sig, stage, bias = 'CALL', 'ENTRY', 'BULLISH'
        why = 'Bullish micro-staircase confirmed: higher highs and higher lows with continuation.'
    elif bear_context and bear_confirm and not late:
        sig, stage, bias = 'PUT', 'ENTRY', 'BEARISH'
        why = 'Bearish micro-staircase confirmed: lower highs and lower lows with continuation.'
    elif bull_context:
        sig, stage, bias = 'WAIT', 'PREPARE', 'BULLISH'
        why = 'Bullish micro-staircase developing. Wait for a bullish continuation candle.'
    elif bear_context:
        sig, stage, bias = 'WAIT', 'PREPARE', 'BEARISH'
        why = 'Bearish micro-staircase developing. Wait for a bearish continuation candle.'
    else:
        sig, stage, bias = 'WAIT', 'WAIT', 'NONE'
        why = 'No qualifying micro-staircase yet. Small countertrend candles are allowed.'

    return {'signal':sig, 'stage':stage, 'bias':bias, 'reason':why,
            'price':float(last.close), 'candle_time':last.datetime,
            'ema9':float(e9.iloc[-1]), 'ema21':float(e21.iloc[-1]),
            'upper':float((mid+2*std).iloc[-1]), 'lower':float((mid-2*std).iloc[-1]),
            'highs':hs, 'lows':ls, 'tolerance':tolerance}

# --- Deriv public market data ---
def deriv_request(payload, timeout=15):
    if websocket is None: raise RuntimeError('Install websocket-client to connect to Deriv.')
    ws=websocket.create_connection(f'wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}', timeout=timeout)
    try:
        ws.send(json.dumps(payload)); deadline=time.time()+timeout
        while time.time()<deadline:
            msg=json.loads(ws.recv())
            if msg.get('error'): raise RuntimeError(msg['error'].get('message','Deriv API error'))
            if 'candles' in msg or 'active_symbols' in msg: return msg
        raise TimeoutError('Deriv did not respond in time.')
    finally: ws.close()

def deriv_symbols():
    data=deriv_request({'active_symbols':'brief',' product_type':'basic'}) if False else deriv_request({'active_symbols':'brief','product_type':'basic'})
    return data.get('active_symbols',[])

def fetch_deriv_candles(symbol,count):
    data=deriv_request({'ticks_history':symbol,'adjust_start_time':1,'count':count+2,'end':'latest','granularity':60,'style':'candles'})
    df=pd.DataFrame(data.get('candles',[]))
    if df.empty: raise RuntimeError('No candle history returned for this Deriv symbol.')
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['datetime']=pd.to_datetime(df.epoch,unit='s',utc=True)
    df=df.dropna(subset=['open','high','low','close']).sort_values('datetime').reset_index(drop=True)
    # Deriv's latest candle can still be forming; exclude it.
    if len(df)>1: df=df.iloc[:-1].copy()
    return df.tail(count).reset_index(drop=True)

def ghost_protocol(df, lookback=24, retest_bars=5):
    if len(df)<lookback+8: return blank_result('Waiting for enough completed Deriv candles.')
    # Prior range excludes the most recent 2 candles; breakout must then retest and resume.
    prior=df.iloc[-(lookback+7):-7]
    recent=df.tail(7); trigger=recent.iloc[-1]; prior_range_high=float(prior.high.max()); prior_range_low=float(prior.low.min())
    width=max(prior_range_high-prior_range_low,1e-12)
    atr=float((df.high-df.low).tail(14).mean())
    if width < atr*2.0: return blank_result('Range is too compressed; waiting for a cleaner structure.')
    # Find breakout among the last retest window, then require price to revisit boundary and close away.
    breakout_up=any(float(x.close)>prior_range_high for _,x in recent.iloc[:-1].iterrows())
    breakout_down=any(float(x.close)<prior_range_low for _,x in recent.iloc[:-1].iterrows())
    call=breakout_up and trigger.low<=prior_range_high+atr*0.25 and trigger.close>prior_range_high and trigger.close>trigger.open
    put=breakout_down and trigger.high>=prior_range_low-atr*0.25 and trigger.close<prior_range_low and trigger.close<trigger.open
    sig='CALL' if call else 'PUT' if put else 'WAIT'
    why=('Range breakout retested and closed back above resistance.' if call else
         'Range breakdown retested and closed back below support.' if put else
         'No confirmed breakout-and-retest. Wait for the range to resolve.')
    return {'signal':sig,'reason':why,'price':float(trigger.close),'candle_time':trigger.datetime,
            'range_high':prior_range_high,'range_low':prior_range_low,'atr':atr}

def build_signal_record(market,instrument,result,expiry):
    now=now_cat(); entry=now.replace(second=0,microsecond=0)+timedelta(minutes=1)
    return {'market':market,'instrument':instrument,'direction':result['signal'],'reason':result['reason'],
            'signal_created':now.isoformat(),'candle_time':as_cat(result['candle_time']).isoformat(),
            'reference_price':result['price'],'entry_time':entry.isoformat(),
            'expiry_time':(entry+timedelta(minutes=expiry)).isoformat(),'expiry_minutes':expiry,
            'status':'PREPARE'}

def show_signal_pad(signal):
    if not signal:
        st.markdown('<div class="signal-card signal-wait"><h3>WAIT</h3><div class="small-muted">No fresh valid signal. Timers are inactive.</div></div>',unsafe_allow_html=True)
        return
    now=now_cat(); entry=datetime.fromisoformat(signal['entry_time']); expiry=datetime.fromisoformat(signal['expiry_time'])
    if now < entry: status='PREPARE'; remaining=int((entry-now).total_seconds())
    elif now < expiry: status='ENTRY WINDOW'; remaining=int((expiry-now).total_seconds())
    else: status='EXPIRED'; remaining=0
    color='signal-call' if signal['direction']=='CALL' else 'signal-put'
    st.markdown(f'<div class="signal-card {color}"><div class="small-muted">{signal["market"]} · {signal["instrument"]}</div><h2>{signal["direction"]} &nbsp; <span style="font-size:0.8em">{status}</span></h2><div>{signal["reason"]}</div></div>',unsafe_allow_html=True)
    a,b,c,d=st.columns(4)
    a.metric('Reference price',fmt_price(signal['reference_price']))
    b.metric('Preparation / expiry timer',f'{remaining//60:02d}:{remaining%60:02d}')
    c.metric('Entry time (CAT)',entry.strftime('%H:%M:%S'))
    d.metric('Expiry time (CAT)',expiry.strftime('%H:%M:%S'))
    st.caption(f'Completed signal candle: {datetime.fromisoformat(signal["candle_time"]).strftime("%Y-%m-%d %H:%M:%S CAT")} · Signal created: {datetime.fromisoformat(signal["signal_created"]).strftime("%H:%M:%S CAT")}')
    if status=='EXPIRED': st.warning('Signal expired. Run a fresh scan; do not reuse this signal.')
    elif status=='ENTRY WINDOW': st.info('Entry window is active. Confirm the live platform quote before acting.')
    else: st.info('Preparation only. The timer is linked to this valid signal, not a standing countdown.')

def chart(df,title):
    v=df.tail(100); fig=go.Figure(go.Candlestick(x=v.datetime,open=v.open,high=v.high,low=v.low,close=v.close,name='1m'))
    fig.update_layout(title=title,height=380,xaxis_rangeslider_visible=False,margin=dict(l=10,r=10,t=40,b=10))
    return fig

# --- Controls ---
with st.sidebar:
    st.header('Market & controls')
    market=st.radio('Market engine',['Pocket Option Forex · THREE STEPS','Deriv Synthetics · GHOST PROTOCOL'])
    expiry=st.selectbox('Signal expiry',[1,2,3,5],index=0,format_func=lambda n:f'{n} minute(s)')
    candles_count=st.slider('Candles to analyze',80,300,160,20)
    auto_refresh=st.checkbox('Refresh dashboard clock every second',value=True)
    auto_scan=st.checkbox('Automatically scan every minute',value=True)
    sound_alerts=st.checkbox('Enable sound alerts',value=st.session_state.get('sound_alerts_enabled',False),key='sound_alerts_enabled')
    st.caption('Automatic scans use the selected market engine and its current settings.')
    st.divider()
    if market.startswith('Pocket'):
        api_key=st.text_input('Twelve Data API key',value=st.secrets.get('TWELVE_DATA_API_KEY',os.getenv('TWELVE_DATA_API_KEY','')),type='password')
        pairs=st.multiselect('Forex pairs',FOREX_PAIRS,default=FOREX_PAIRS)
        pivot_strength=st.slider('Swing confirmation',2,4,2)
        min_steps=st.slider('Minimum staircase steps',3,5,3)
        pullback_pct=st.slider('Maximum pullback (%)',20,70,50,5)
        scan=st.button('SCAN FOREX',type='primary',use_container_width=True)
    else:
        scan=st.button('CONNECT & SCAN DERIV',type='primary',use_container_width=True)
        st.caption('Deriv public market data only. No account login or trade execution.')
        st.caption('Range Break symbols are discovered from Deriv’s active-symbol list; choose the exact symbols shown by your platform.')
        lookback=st.slider('Range lookback',12,40,24)

if auto_refresh: st_autorefresh(interval=1000,key='desk_clock')
now=now_cat()
st.caption(f'LOCAL TIME · {now.strftime("%A, %d %B %Y · %H:%M:%S CAT")}')

# Scan once per new CAT minute. The one-second refresh only updates the clock/UI.
minute_key=now.strftime('%Y-%m-%d %H:%M')
last_auto_scan=st.session_state.get('last_auto_scan_minute')
auto_scan_due=bool(auto_scan and minute_key != last_auto_scan)
if auto_scan_due:
    st.session_state['last_auto_scan_minute']=minute_key
run_scan=bool(scan or auto_scan_due)
if run_scan:
    st.session_state.pop('active_signal',None)
    if auto_scan_due:
        st.caption(f'Automatic scan started · {now.strftime("%H:%M CAT")}')
    if market.startswith('Pocket'):
        if not api_key: st.error('Add your Twelve Data key in the sidebar or Streamlit Secrets.')
        elif not pairs: st.warning('Select at least one forex pair.')
        else:
            output=[]; bar=st.progress(0); note=st.empty()
            for i,pair in enumerate(pairs):
                note.write(f'Scanning {pair}…')
                try:
                    df=fetch_forex(pair,api_key,candles_count)
                    result=three_steps(df,pivot_strength,min_steps,pullback_pct)
                    output.append({'instrument':pair,'df':df,'result':result})
                except Exception as e: output.append({'instrument':pair,'error':str(e)})
                bar.progress((i+1)/len(pairs))
            note.empty(); st.session_state['scan_output']=output; st.session_state['scan_market']='forex'
            candidates=[x for x in output if x.get('result',{}).get('signal') in ('CALL','PUT')]
            if candidates:
                # Prioritize newest completed signal candle.
                chosen=max(candidates,key=lambda x:x['result']['candle_time'])
                st.session_state['active_signal']=build_signal_record('THREE STEPS',chosen['instrument'],chosen['result'],expiry)
    else:
        with st.spinner('Discovering Deriv symbols…'):
            try:
                symbols=deriv_symbols()
                matches=[s for s in symbols if any(k in (s.get('display_name','')+' '+s.get('symbol','')).lower() for k in ['range break','range_break','rangebreak'])]
                st.session_state['deriv_matches']=matches
                if not matches: raise RuntimeError('No Range Break instruments were found in Deriv active symbols. Check the exact instrument names available in your Deriv account/platform.')
                chosen_symbol=st.session_state.get('chosen_deriv_symbol',matches[0]['symbol'])
                selected=next((s for s in matches if s['symbol']==chosen_symbol),matches[0])
                df=fetch_deriv_candles(selected['symbol'],candles_count)
                result=ghost_protocol(df,lookback)
                st.session_state['deriv_output']={'instrument':selected['display_name'],'symbol':selected['symbol'],'df':df,'result':result}
                st.session_state['scan_market']='deriv'
                if result.get('signal') in ('CALL','PUT'):
                    st.session_state['active_signal']=build_signal_record('GHOST PROTOCOL',selected['display_name'],result,expiry)
            except Exception as e: st.error(f'Deriv scan failed: {e}')

# Signal pad at top, regardless of market.
st.subheader('SIGNALS PAD')
active_signal = st.session_state.get('active_signal')
show_signal_pad(active_signal)

# Play one short browser beep for each newly detected signal.
# Browsers may require the user to enable sound once before autoplay is allowed.
if sound_alerts and active_signal and active_signal.get('direction') in ('CALL', 'PUT'):
    sound_key = '|'.join(str(active_signal.get(k, '')) for k in ('market', 'instrument', 'direction', 'candle_time'))
    if st.session_state.get('last_sound_signal_key') != sound_key:
        st.session_state['last_sound_signal_key'] = sound_key
        audio_html = """
        <html><body style="margin:0;background:transparent">
        <script>
        (() => {
          try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return;
            const ctx = new Ctx();
            const playTone = (freq, start, duration) => {
              const osc = ctx.createOscillator();
              const gain = ctx.createGain();
              osc.type = 'sine';
              osc.frequency.value = freq;
              gain.gain.setValueAtTime(0.0001, ctx.currentTime + start);
              gain.gain.exponentialRampToValueAtTime(0.22, ctx.currentTime + start + 0.025);
              gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + duration);
              osc.connect(gain); gain.connect(ctx.destination);
              osc.start(ctx.currentTime + start);
              osc.stop(ctx.currentTime + start + duration + 0.02);
            };
            const run = () => { playTone(880, 0, 0.16); playTone(1175, 0.20, 0.22); };
            if (ctx.state === 'suspended') ctx.resume().then(run); else run();
          } catch (e) { /* Audio is optional; signal remains visible. */ }
        })();
        </script></body></html>
        """
        st.components.v1.html(audio_html, height=1, scrolling=False)

if market.startswith('Pocket'):
    st.subheader('THREE STEPS · Forex scanner')
    results=st.session_state.get('scan_output',[]) if st.session_state.get('scan_market')=='forex' else []
    if not results: st.caption('Select pairs and press SCAN FOREX. Only completed one-minute candles are analyzed.')
    for item in results:
        with st.container(border=True):
            if 'error' in item: st.error(f'{item["instrument"]}: {item["error"]}'); continue
            res=item['result']; col1,col2,col3,col4=st.columns([2,1,1,4])
            col1.markdown(f'**{item["instrument"]}**')
            col2.metric('Signal',res['signal'])
            col3.metric('Stage',res.get('stage','WAIT'))
            col4.write(f"{res.get('bias','NONE')} · {res['reason']}")
            with st.expander('Chart & details'):
                st.plotly_chart(chart(item['df'],item['instrument']),use_container_width=True)
                if 'price' in res: st.write(f'Last completed close: {fmt_price(res["price"])} · EMA 9: {fmt_price(res["ema9"])} · EMA 21: {fmt_price(res["ema21"])}')
else:
    st.subheader('GHOST PROTOCOL · Deriv synthetics')
    matches=st.session_state.get('deriv_matches',[])
    if matches:
        options={f'{s.get("display_name",s["symbol"])} ({s["symbol"]})':s['symbol'] for s in matches}
        labels=list(options)
        current=st.session_state.get('chosen_deriv_symbol',options[labels[0]])
        chosen_label=next((k for k,v in options.items() if v==current),labels[0])
        selected_label=st.selectbox('Available Range Break instrument',labels,index=labels.index(chosen_label))
        st.session_state['chosen_deriv_symbol']=options[selected_label]
        out=st.session_state.get('deriv_output')
        if out:
            x,y,z=st.columns([2,1,3]); x.markdown(f'**{out["instrument"]}**'); y.metric('Signal',out['result']['signal']); z.write(out['result']['reason'])
            with st.expander('Chart & range levels'):
                st.plotly_chart(chart(out['df'],out['instrument']),use_container_width=True)
                r=out['result']
                if 'range_high' in r: st.write(f'Resistance: {fmt_price(r["range_high"])} · Support: {fmt_price(r["range_low"])} · ATR: {fmt_price(r["atr"])}')
    else: st.caption('Press CONNECT & SCAN DERIV to discover available Range Break instruments.')

st.divider()
st.caption('Research and alerting only — not financial advice. Data feeds can differ from Pocket Option/Deriv display quotes. Confirm the live price and candle timing on the trading platform. No signal guarantees a profitable outcome.')
