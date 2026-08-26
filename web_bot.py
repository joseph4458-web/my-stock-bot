import streamlit as st
import yfinance as yf
import math
import requests
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
import time
import pandas as pd
import ssl
import urllib3

# ⚠️ Streamlit 規定頁面設定必須在最前面
st.set_page_config(page_title="多因子量化終端機", page_icon="📈", layout="wide")

# === 穿透企業防火牆的 SSL 解鎖設定 ===
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
yf_session = requests.Session()
yf_session.verify = False
yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
})

# ==========================================
# 1. 核心大腦模組 (共用引擎)
# ==========================================
@st.cache_data(ttl=3600)
def get_market_status():
    try:
        twii = yf.Ticker("^TWII", session=yf_session)
        hist = twii.history(period="100d")
        target_name = "台股大盤"
        if hist.empty:
            twii = yf.Ticker("0050.TW", session=yf_session)
            hist = twii.history(period="100d")
            target_name = "大盤指標(0050)"
        if hist.empty: return "⚠️ 大盤數據無回傳資料"
        
        close = hist['Close'].iloc[-1]
        ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
        last_date = hist.index[-1].strftime('%m/%d')
        if close > ma60: return f"📈 【{target_name}】目前 {close:.2f} 點 (站穩季線 {ma60:.2f}，多頭格局) [{last_date}]"
        else: return f"📉 【{target_name}】目前 {close:.2f} 點 (跌破季線 {ma60:.2f}，嚴控資金！) [{last_date}]"
    except Exception as e:
        return f"⚠️ 大盤數據無法連線"

def get_tw_chinese_name(ticker):
    try:
        pure_id = ticker.split('.')[0]
        url = f"https://tw.stock.yahoo.com/quote/{pure_id}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=3, verify=False)
        if res.status_code == 200 and "<title>" in res.text:
            title = res.text.split("<title>")[1].split("</title>")[0]
            name = title.split("(")[0].strip()
            if name: return name
    except: pass
    return None

def fetch_data(ticker_input):
    ticker = str(ticker_input).strip().upper()
    try:
        if not ticker.endswith('.TW') and not ticker.endswith('.TWO'):
            stock = yf.Ticker(ticker + '.TW', session=yf_session)
            hist = stock.history(period="150d")
            if hist.empty:
                stock = yf.Ticker(ticker + '.TWO', session=yf_session)
                hist = stock.history(period="150d")
                ticker = ticker + '.TWO'
            else:
                ticker = ticker + '.TW'
        else:
            stock = yf.Ticker(ticker, session=yf_session)
            hist = stock.history(period="150d")
            
        if hist.empty: return ticker_input, ticker_input, None, {}
            
        name = get_tw_chinese_name(ticker)
        if not name: name = ticker
        
        info = {}
        try: info = stock.info
        except: pass
        return ticker, name, hist, info
    except:
        return ticker_input, ticker_input, None, {}

def get_news_sentiment_score(ticker, name):
    try:
        query_stock = urllib.parse.quote(f"{name} OR {ticker.split('.')[0]}")
        url_stock = f"https://news.google.com/rss/search?q={query_stock}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        query_macro = urllib.parse.quote("美股 OR 全球經濟 OR 外資買超 OR 融資斷頭")
        url_macro = f"https://news.google.com/rss/search?q={query_macro}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        res_stock = requests.get(url_stock, headers=headers, timeout=3, verify=False)
        root_stock = ET.fromstring(res_stock.text)
        res_macro = requests.get(url_macro, headers=headers, timeout=3, verify=False)
        root_macro = ET.fromstring(res_macro.text)
        
        positive_words = ['漲', '看好', '利多', '外資買超', '反彈', '降息', '復甦']
        negative_words = ['跌', '衰退', '利空', '外資賣超', '萎縮', '通膨', '斷頭']
        fatal_words = ['崩', '風暴', '海嘯', '逃命', '黑天鵝', '股災', '系統性風險']
        
        pos_count = 0; neg_count = 0; fatal_count = 0
        
        for item in root_stock.findall('.//item')[:10]:
            title = item.find('title').text
            for w in positive_words: pos_count += 1 if w in title else 0
            for w in negative_words: neg_count += 1 if w in title else 0
            for w in fatal_words: fatal_count += 1 if w in title else 0
                
        for item in root_macro.findall('.//item')[:10]:
            title = item.find('title').text
            for w in positive_words: pos_count += 0.5 if w in title else 0
            for w in negative_words: neg_count += 1.0 if w in title else 0
            for w in fatal_words: fatal_count += 2.0 if w in title else 0
                
        sentiment_score = max(-30, min(30, (pos_count - neg_count) * 2))
        return sentiment_score, (fatal_count >= 3)
    except: return 0, False

def analyze_stock_expert(hist, ticker, name, info):
    latest_price = hist['Close'].iloc[-1]
    latest_vol = hist['Volume'].iloc[-1]
    ma5 = hist['Close'].rolling(window=5).mean()
    ma20 = hist['Close'].rolling(window=20).mean()
    ma60 = hist['Close'].rolling(window=60).mean()
    ma120 = hist['Close'].rolling(window=120).mean()
    v5 = hist['Volume'].rolling(window=5).mean()
    
    std20 = hist['Close'].rolling(window=20).std()
    lower_band = ma20 - (std20 * 2)
    upper_band = ma20 + (std20 * 2)
    
    macd_hist = (hist['Close'].ewm(span=12, adjust=False).mean() - hist['Close'].ewm(span=26, adjust=False).mean()) - (hist['Close'].ewm(span=12, adjust=False).mean() - hist['Close'].ewm(span=26, adjust=False).mean()).ewm(span=9, adjust=False).mean()

    delta = hist['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - (100 / (1 + gain / loss))

    tech_score = 0
    if len(ma120) > 0 and not math.isnan(ma120.iloc[-1]) and latest_price > ma120.iloc[-1]: tech_score += 5
    if latest_price > ma60.iloc[-1]: tech_score += 5
    if latest_price > ma20.iloc[-1] and ma5.iloc[-1] > ma20.iloc[-1]: tech_score += 5
    if macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2]: tech_score += 5
    if 40 <= rsi.iloc[-1] <= 70: tech_score += 5
    if latest_vol > v5.iloc[-1] * 1.5: tech_score += 5 
    if latest_price >= lower_band.iloc[-1] and latest_price <= upper_band.iloc[-1]: tech_score += 5

    fund_score = 0
    if info:
        peg = info.get('pegRatio')
        pe = info.get('trailingPE')
        roe = info.get('returnOnEquity')
        val_points = 8 if (peg and 0 < peg < 1.2) or (not peg and pe and pe < 15) else 5
        fin_points = 5 if roe and roe > 0.10 else 3
        fund_score = min(30, val_points + fin_points + 5)
    else: fund_score = 15 

    news_score, black_swan = get_news_sentiment_score(ticker, name)
    total_score = int(max(0, min(100, tech_score + fund_score + (15 + (news_score / 2)))))

    if black_swan:
        total_score = min(total_score, 40)
        signal = f"🚨 【{total_score}分】大環境資金恐慌，縮小倉位防守！"
    elif total_score >= 80: signal = f"🟢 【{total_score}分】具備財務支撐且技術量能突破，可偏多操作！"
    elif total_score >= 60: signal = f"🟢 【{total_score}分】量縮回測季線有撐，適合波段低接。"
    else: signal = f"🔴 【{total_score}分】動能背離或估值偏高，風險較大！"

    change = latest_price - hist['Close'].iloc[-2] if len(hist) >= 2 else 0
    change_pct = (change / hist['Close'].iloc[-2]) * 100 if len(hist) >= 2 else 0
    change_str = f"{change:.2f} ({change_pct:.2f}%)"
    
    return round(float(latest_price), 2), change_str, round(float(ma60.iloc[-1]), 2), signal, total_score


# ==========================================
# 2. 帳號登入與密碼系統 (隱私保護版)
# ==========================================
if 'username' not in st.session_state:
    st.session_state.username = None

# 用一個獨立的檔案來記錄大家的帳號密碼
auth_file = "user_auth.json"
def load_auth():
    if os.path.exists(auth_file):
        with open(auth_file, 'r', encoding='utf-8') as f: return json.load(f)
    return {}
def save_auth(data):
    with open(auth_file, 'w', encoding='utf-8') as f: json.dump(data, f)

if st.session_state.username is None:
    st.title("🔐 專屬理財機器人 - 員工登入")
    st.info("請輸入您的專屬帳號與密碼。若是首次使用，系統將自動以您輸入的密碼建立新帳號。")
    
    # ⚠️ 加入溫馨提醒的黃色警告框
    st.warning("💡 溫馨提醒：這只是內部的理財輔助小工具，請大家隨便設定一個簡單好記的密碼就好，千萬不要使用自己重要的網路銀行或私人信箱的密碼喔！")
    
    col1, col2 = st.columns(2)
    with col1: user_input = st.text_input("👤 員工姓名或工號：")
    with col2: pass_input = st.text_input("🔑 密碼：", type="password")
    
    if st.button("安全登入"):
        if user_input.strip() and pass_input.strip():
            username = user_input.strip()
            password = pass_input.strip()
            auth_db = load_auth()
            
            # 判斷登入邏輯
            if username in auth_db:
                if auth_db[username] == password:
                    st.session_state.username = username
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤！請重新輸入。")
            else:
                # 第一次使用，自動註冊
                auth_db[username] = password
                save_auth(auth_db)
                st.success(f"✅ 帳號 {username} 註冊成功！正在為您登入...")
                time.sleep(1)
                st.session_state.username = username
                st.rerun()
        else:
            st.warning("⚠️ 帳號與密碼欄位皆不能為空！")
    st.stop() # 阻擋未登入者看到下方畫面

username = st.session_state.username
data_file = f"user_data_{username}.json"

def load_user_data():
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"watch_list": [], "portfolio": []}

def save_user_data(data):
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

user_data = load_user_data()

# ==========================================
# 3. Streamlit 雲端網頁介面 (主畫面)
# ==========================================
with st.sidebar:
    st.write(f"👤 目前使用者：**{username}**")
    if st.button("登出 (切換帳號)"):
        st.session_state.username = None
        st.rerun()

st.title(f"🚀 {username} 的專屬量化終端機")
st.info(get_market_status())

tab1, tab2, tab3 = st.tabs(["🔭 觀察清單", "📦 我的庫存 (損益)", "⭐ 每日 AI 掃描"])

# --- 分頁 1：觀察清單 ---
with tab1:
    st.subheader("新增自選股")
    col1, col2 = st.columns([2, 1])
    with col1:
        watch_ticker = st.text_input("輸入股票代號 (觀察用)：", placeholder="例如：2330", key="watch_input")
    with col2:
        st.write("") 
        if st.button("加入並分析清單"):
            if watch_ticker:
                with st.spinner(f"正在分析 {watch_ticker} ..."):
                    ticker, name, hist, info = fetch_data(watch_ticker)
                    if hist is not None and not hist.empty:
                        price, change, _, signal, score = analyze_stock_expert(hist, ticker, name, info)
                        user_data['watch_list'].append({
                            "代號": ticker, "名稱": name, "綜合評分": score, 
                            "現價": price, "漲跌": change, "AI 建議": signal
                        })
                        save_user_data(user_data)
                        st.rerun()
                    else: st.error("找不到該股票資料！")

    if user_data['watch_list']:
        st.dataframe(pd.DataFrame(user_data['watch_list']), use_container_width=True, hide_index=True)
        if st.button("清空觀察清單"): 
            user_data['watch_list'] = []
            save_user_data(user_data)
            st.rerun()

# --- 分頁 2：我的庫存 ---
with tab2:
    st.subheader("新增買進庫存")
    c1, c2, c3, c4 = st.columns(4)
    with c1: port_ticker = st.text_input("股票代號：", key="port_ticker")
    with c2: port_shares = st.number_input("股數：", min_value=1, step=1000, value=1000)
    with c3: port_price = st.number_input("買進均價：", min_value=0.0, step=0.1, format="%.2f")
    with c4:
        st.write("")
        if st.button("加入庫存"):
            if port_ticker and port_price > 0:
                with st.spinner(f"正在結算 {port_ticker} 績效..."):
                    ticker, name, hist, info = fetch_data(port_ticker)
                    if hist is not None and not hist.empty:
                        price, change, ma60, ai_signal, _ = analyze_stock_expert(hist, ticker, name, info)
                        
                        # 簡單手續費與稅金概算 (無折扣)
                        buy_fee = math.floor(port_price * port_shares * 0.001425)
                        sell_fee = math.floor(price * port_shares * 0.001425)
                        sell_tax = math.floor(price * port_shares * 0.003)
                        pnl = round((price * port_shares) - sell_fee - sell_tax - (port_price * port_shares) - buy_fee)
                        
                        if price >= port_price * 1.10: final_signal = "💰 【10% 達標】已達停利目標！"
                        elif price < ma60 * 0.97: final_signal = "⚠️ 【破線停損】跌破季線趨勢轉弱！"
                        else: final_signal = ai_signal

                        user_data['portfolio'].append({
                            "代號": ticker, "名稱": name, "股數": port_shares, "買價": port_price,
                            "現價": price, "淨損益": pnl, "庫存監控建議": final_signal
                        })
                        save_user_data(user_data)
                        st.rerun()
                    else: st.error("找不到該股票資料！")
                    
    if user_data['portfolio']:
        st.dataframe(pd.DataFrame(user_data['portfolio']), use_container_width=True, hide_index=True)
        # 計算總績效
        total_inv = sum(item["買價"] * item["股數"] for item in user_data['portfolio'])
        total_pnl = sum(item["淨損益"] for item in user_data['portfolio'])
        roi = (total_pnl / total_inv * 100) if total_inv > 0 else 0
        st.success(f"📊 總投入成本: {total_inv:,.0f} 元 | 總淨利: {total_pnl:,.0f} 元 | 總報酬率: {roi:.2f}%")
        
        if st.button("清空庫存清單"):
            user_data['portfolio'] = []
            save_user_data(user_data)
            st.rerun()

# --- 分頁 3：每日掃描 ---
with tab3:
    st.subheader("內建多因子觀測池")
    if st.button("🔍 啟動深度掃描 (Top 5)"):
        pool = ['2330', '2317', '2454', '2308', '2881', '0050', '0056', '00878', '3231', '2603']
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, t in enumerate(pool):
            status_text.text(f"深度運算中 ({i+1}/{len(pool)}): 正在剖析 {t} ...")
            ticker, name, hist, info = fetch_data(t)
            if hist is not None and not hist.empty:
                price, change, _, signal, score = analyze_stock_expert(hist, ticker, name, info)
                results.append({"代號": ticker, "名稱": name, "評分": score, "現價": price, "AI 建議": signal})
            progress_bar.progress((i + 1) / len(pool))
            time.sleep(1) 
            
        status_text.text("✅ 掃描完成！")
        results.sort(key=lambda x: x['評分'], reverse=True)
        st.dataframe(pd.DataFrame(results[:5]), use_container_width=True, hide_index=True)

st.markdown("---")
st.caption("🟢 綠燈(80-100分) | 🟡 黃燈(60-79分) | 🔴 紅燈(0-59分) | 🚨 黑天鵝(系統風險)")