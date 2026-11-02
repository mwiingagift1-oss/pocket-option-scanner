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

def parse_forex_frame(values, count):
    df = pd.DataFrame(values)
    if df.empty or 'datetime' not in df.columns:
        raise RuntimeError('Twelve Data returned no candle values for this pair.')
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True, errors='coerce')
    df = df.dropna(subset=['datetime', 'open', 'high', 'low', 'close']).sort_values('datetime').reset_index(drop=True)
    # Never analyze the currently-forming one-minute candle.
    cutoff = pd.Timestamp.now(tz='UTC').floor('min')
    return df[df.datetime < cutoff].tail(count).reset_index(drop=True)


def fetch_forex_batch(symbols, key, count):
    """Fetch several pairs in one HTTP call; Twelve Data still charges per symbol."""
    if not symbols:
        return {}, {}, None
    response = requests.get(
        'https://api.twelvedata.com/time_series',
        params={
            'symbol': ','.join(symbols),
            'interval': '1min',
            'outputsize': count + 3,
            'apikey': key,
            'format': 'JSON',
            'timezone': 'UTC',
        },
        timeout=25,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code == 429 or str(payload.get('code', '')) == '429':
        message = payload.get('message', 'Twelve Data credit limit reached (HTTP 429).')
        raise RuntimeError(f'RATE_LIMIT: {message}')
    if not response.ok:
        message = payload.get('message', f'HTTP {response.status_code}')
        raise RuntimeError(f'Twelve Data request failed: {message}')

    frames, errors = {}, {}
    # Batch responses are keyed by symbol. Also support the single-symbol shape.
    if len(symbols) == 1 and isinstance(payload, dict) and 'values' in payload:
        payload = {symbols[0]: payload}
    for symbol in symbols:
        item = payload.get(symbol) if isinstance(payload, dict) else None
        if not isinstance(item, dict):
            errors[symbol] = 'No response returned for this pair.'
            continue
        if 'values' not in item:
            errors[symbol] = item.get('message', item.get('code', 'No candle data returned.'))
            continue
        try:
            frames[symbol] = parse_forex_frame(item['values'], count)
        except Exception as exc:
            errors[symbol] = str(exc)
    credit_info = {
        'used': response.headers.get('api-credits-used', 'unknown'),
        'left': response.headers.get('api-credits-left', 'unknown'),
    }
    return frames, errors, credit_info

def confirmed_pivots(df, strength):
    highs, lows = [], []
    h, l = df.high.to_numpy(), df.low.to_numpy()
    for i in range(strength, len(df)-strength):
        wh, wl = h[i-strength:i+strength+1], l[i-strength:i+strength+1]
        if h[i] == wh.max() and (wh == h[i]).sum() == 1: highs.append((i,float(h[i])))
        if l[i] == wl.min() and (wl == l[i]).sum() == 1: lows.append((i,float(l[i])))
    return highs, lows

def three_steps(df, strength=2, min_steps=3, pullback_pct=50):
    if len(df) < 50: return blank_result('Waiting for enough completed candles.')
    highs,lows = confirmed_pivots(df,strength)
    # Use a bounded recent sequence; each swing must advance in the same direction.
    hs,ls = highs[-min_steps:],lows[-min_steps:]
    if len(hs)<min_steps or len(ls)<min_steps: return blank_result('Waiting for confirmed swing structure.')
    bullish = all(hs[i][1]>hs[i-1][1] for i in range(1,len(hs))) and all(ls[i][1]>ls[i-1][1] for i in range(1,len(ls)))
    bearish = all(hs[i][1]<hs[i-1][1] for i in range(1,len(hs))) and all(ls[i][1]<ls[i-1][1] for i in range(1,len(ls)))
    c=df.close; e9=c.ewm(span=9,adjust=False).mean(); e21=c.ewm(span=21,adjust=False).mean()
    mid=c.rolling(20).mean(); std=c.rolling(20).std()
    last,prev=df.iloc[-1],df.iloc[-2]
    bar_med=float((df.high-df.low).tail(20).median())
    extension=abs(float(last.close-e9.iloc[-1]))
    # Measure the latest counter-move against the preceding directional leg.
    tail=df.tail(12); move=float(tail.high.max()-tail.low.min())
    recent_pullback=float((tail.high.max()-tail.close.iloc[-1]) if bullish else (tail.close.iloc[-1]-tail.low.min()))
    pullback_ok = move <= 0 or recent_pullback <= move*(pullback_pct/100)
    late = bar_med>0 and extension>2.5*bar_med
    call = bullish and e9.iloc[-1]>e21.iloc[-1] and last.close>mid.iloc[-1] and last.close>prev.high and pullback_ok and not late
    put = bearish and e9.iloc[-1]<e21.iloc[-1] and last.close<mid.iloc[-1] and last.close<prev.low and pullback_ok and not late
    sig='CALL' if call else 'PUT' if put else 'WAIT'
    why = ('Confirmed higher highs/higher lows with upward resumption.' if call else
           'Confirmed lower highs/lower lows with downward resumption.' if put else
           'No fresh, confirmed staircase entry. Wait; do not chase.')
    return {'signal':sig,'reason':why,'price':float(last.close),'candle_time':last.datetime,
            'ema9':float(e9.iloc[-1]),'ema21':float(e21.iloc[-1]),'upper':float((mid+2*std).iloc[-1]),
            'lower':float((mid-2*std).iloc[-1]),'highs':hs,'lows':ls}

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
    st.caption('Automatic scans use the selected market engine and its current settings.')
    st.divider()
    if market.startswith('Pocket'):
        try:
            saved_key = st.secrets.get('TWELVE_DATA_API_KEY', os.getenv('TWELVE_DATA_API_KEY', ''))
        except Exception:
            saved_key = os.getenv('TWELVE_DATA_API_KEY', '')
        api_key=st.text_input('Twelve Data API key',value=saved_key,type='password',help='Keep this key private. Prefer Streamlit Secrets for deployment.')
        pairs=st.multiselect('Forex pairs',FOREX_PAIRS,default=FOREX_PAIRS)
        max_pairs_per_minute=st.slider('Pairs to refresh per minute',1,10,8,help='Twelve Data charges one API credit per symbol, even in a batch. Basic currently allows 8 credits/minute; choose 9–10 only if your plan allows it.')
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
        if not api_key:
            st.error('Add your Twelve Data key in the sidebar or Streamlit Secrets.')
        elif not pairs:
            st.warning('Select at least one forex pair.')
        else:
            # Round-robin the selected pairs so Basic-plan users stay within 8 credits/minute.
            cursor = int(st.session_state.get('forex_pair_cursor', 0)) % len(pairs)
            batch_size = min(max_pairs_per_minute, len(pairs))
            scan_pairs = [pairs[(cursor + i) % len(pairs)] for i in range(batch_size)]
            st.session_state['forex_pair_cursor'] = (cursor + batch_size) % len(pairs)
            note = st.empty()
            note.info('Refreshing: ' + ', '.join(scan_pairs))
            try:
                frames, errors, credit_info = fetch_forex_batch(scan_pairs, api_key, candles_count)
                st.session_state['api_credit_info'] = credit_info
                previous = {x['instrument']: x for x in st.session_state.get('scan_output', []) if x.get('instrument')}
                fresh_candidates = []
                for pair in pairs:
                    if pair in frames:
                        df = frames[pair]
                        result = three_steps(df, pivot_strength, min_steps, pullback_pct)
                        item = {'instrument': pair, 'df': df, 'result': result, 'fresh': True,
                                'updated_at': now_cat().isoformat()}
                        if result.get('signal') in ('CALL', 'PUT'):
                            fresh_candidates.append(item)
                        previous[pair] = item
                    elif pair in errors:
                        old = previous.get(pair)
                        if old:
                            old['fresh'] = False
                            old['error'] = errors[pair]
                        else:
                            previous[pair] = {'instrument': pair, 'error': errors[pair], 'fresh': False}
                    elif pair not in previous:
                        previous[pair] = {'instrument': pair, 'result': blank_result('Queued for the next scan cycle.'),
                                          'df': None, 'fresh': False}
                    else:
                        previous[pair]['fresh'] = False
                output = [previous[p] for p in pairs if p in previous]
                st.session_state['scan_output'] = output
                st.session_state['scan_market'] = 'forex'
                note.empty()
                if credit_info:
                    st.caption(f"Twelve Data credits used: {credit_info['used']} · Credits left this minute: {credit_info['left']}")
                if fresh_candidates:
                    chosen = max(fresh_candidates, key=lambda x: x['result']['candle_time'])
                    st.session_state['active_signal'] = build_signal_record('THREE STEPS', chosen['instrument'], chosen['result'], expiry)
                else:
                    st.session_state.pop('active_signal', None)
            except Exception as exc:
                note.empty()
                message = str(exc)
                if message.startswith('RATE_LIMIT:'):
                    st.error('Twelve Data limit reached. The scanner has stopped this batch instead of repeatedly retrying. It will try again on the next scheduled minute. ' + message.replace('RATE_LIMIT:', '').strip())
                else:
                    st.error(f'Forex batch scan failed: {message}')
                st.session_state['last_forex_scan_error'] = message
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
show_signal_pad(st.session_state.get('active_signal'))

if market.startswith('Pocket'):
    st.subheader('THREE STEPS · Forex scanner')
    results=st.session_state.get('scan_output',[]) if st.session_state.get('scan_market')=='forex' else []
    st.info('Quota-aware mode: pairs are refreshed in rotating batches. On Twelve Data Basic (8 credits/minute, 800/day), 10 pairs cannot all be refreshed every minute; this app refreshes up to 8 per minute and rotates the remaining pairs. Batch calls reduce HTTP requests but do not reduce credits per symbol.')
    if not results: st.caption('Select pairs and press SCAN FOREX. Only completed one-minute candles are analyzed.')
    for item in results:
        with st.container(border=True):
            if 'error' in item and 'result' not in item:
                st.error(f'{item["instrument"]}: {item["error"]}')
                continue
            res=item['result']; col1,col2,col3=st.columns([2,1,3])
            freshness = 'LIVE UPDATE' if item.get('fresh') else 'CACHED / QUEUED'
            col1.markdown(f'**{item["instrument"]}**  ·  {freshness}')
            col2.metric('Signal',res['signal'])
            col3.write(res['reason'])
            if item.get('error'):
                st.caption(f'Latest refresh issue: {item["error"]}')
            if item.get('df') is not None:
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
