import streamlit as st
import yfinance as yf
import requests
import json
import os
import time
import pandas as pd
import numpy as np
import ssl
import urllib3
import urllib.parse
import gspread
from google.oauth2.service_account import Credentials
import datetime

st.set_page_config(page_title="專屬理財機器人 - 多因子量化終端機", page_icon="📈", layout="wide")

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
yf_session = requests.Session()
yf_session.verify = False
yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
})

# ==========================================
# Google 試算表連線初始化
# ==========================================
def init_gsheet():
    try:
        if "GCP_JSON" in st.secrets:
            creds_dict = json.loads(st.secrets["GCP_JSON"])
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
            return client.open("量化終端機_DB")
    except Exception as e:
        st.warning(f"⚠️ 雲端資料庫連線提示: {e}")
    return None

sheet_db = init_gsheet()

def load_db(table_name, default_val):
    if sheet_db:
        try: return sheet_db.worksheet(table_name).get_all_records() or default_val
        except: return default_val
    else:
        file_name = f"{table_name}.json"
        if os.path.exists(file_name):
            with open(file_name, 'r', encoding='utf-8') as f: return json.load(f)
        return default_val

def save_db(table_name, data):
    if sheet_db:
        try:
            try: worksheet = sheet_db.worksheet(table_name)
            except: worksheet = sheet_db.add_worksheet(title=table_name, rows="150", cols="20")
            worksheet.clear()
            if data:
                df = pd.DataFrame(data)
                worksheet.update([df.columns.values.tolist()] + df.values.tolist())
        except Exception as e: st.error(f"存檔失敗: {e}")
    else:
        with open(f"{table_name}.json", 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)

# ==========================================
# 智慧搜尋與 Yahoo Finance 資料讀取
# ==========================================
def smart_search_taiwan_stock(query):
    query = str(query).strip()
    
    # 1. 如果輸入純數字，自動補上 .TW
    if query.isdigit(): 
        return f"{query}.TW"
        
    # 2. 內建常見台股與 ETF 對照表 (雲端防擋機制，瞬間查詢)
    common_stocks = {
        "台泥": "1101.TW", "亞泥": "1102.TW", "統一": "1216.TW", "台塑": "1301.TW",
        "南亞": "1303.TW", "台化": "1326.TW", "中鋼": "2002.TW", "台積電": "2330.TW",
        "聯電": "2303.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", "長榮": "2603.TW",
        "陽明": "2609.TW", "萬海": "2615.TW", "富邦金": "2881.TW", "國泰金": "2882.TW",
        "兆豐金": "2886.TW", "中信金": "2891.TW", "元大金": "2885.TW", "玉山金": "2884.TW",
        "大立光": "3008.TW", "台達電": "2308.TW", "廣達": "2382.TW", "緯創": "3231.TW",
        "日月光": "3711.TW", "中華電": "2412.TW", "華碩": "2357.TW", "技嘉": "2376.TW",
        "神隆": "1789.TW", "由田": "3455.TWO", "群創": "3481.TW", "捷泰": "8064.TWO",
        "元大高股息": "0056.TW", "元大台灣50": "0050.TW", "國泰永續高股息": "00878.TW", "富邦台50": "006208.TW"
    }
    if query in common_stocks:
        return common_stocks[query]
    
    # 3. 呼叫 Yahoo API 進行中文搜尋 (加入備用網址與偽裝 Headers)
    urls = [
        f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(query)}&quotesCount=5",
        f"https://query1.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(query)}&quotesCount=5"
    ]
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=3, verify=False)
            if res.status_code == 200:
                data = res.json()
                for q in data.get('quotes', []):
                    sym = q.get('symbol', '')
                    if sym.endswith('.TW') or sym.endswith('.TWO'):
                        return sym
        except:
            continue
            
    return query

# ==========================================
# 專屬台股 API：證交所/櫃買中心 OpenAPI (官方穩定版)
# ==========================================
@st.cache_data(ttl=3600)
def get_tw_stock_valuation():
    valuation_data = {}
    # 1. 抓取上市股票 (TWSE) - 同時抓取名稱與估值
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL", timeout=5).json()
        for item in res_twse:
            valuation_data[item.get("Code")] = {
                "Name": item.get("Name", "").strip(),
                "PE": item.get("PeRatio", "N/A"),
                "PB": item.get("PbRatio", "N/A"),
                "Yield": item.get("DividendYield", "N/A")
            }
    except: pass
        
    # 2. 抓取上櫃股票 (TPEx) - 同時抓取名稱與估值
    try:
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", timeout=5).json()
        for item in res_tpex:
            valuation_data[item.get("SecuritiesCompanyCode")] = {
                "Name": item.get("CompanyName", "").strip(),
                "PE": item.get("PERatio", "N/A"),
                "PB": item.get("PBratio", "N/A"),
                "Yield": item.get("YieldRatio", "N/A")
            }
    except: pass
        
    return valuation_data

# ==========================================
# 資料讀取引擎 (Yahoo + 官方 OpenAPI 智慧雙重引擎)
# ==========================================
def fetch_data(query_input):
    ticker = smart_search_taiwan_stock(query_input)
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="200d")
        
        if hist.empty and ticker.endswith('.TW'):
            ticker = ticker.replace('.TW', '.TWO')
            stock = yf.Ticker(ticker)
            hist = stock.history(period="200d")
            
        if hist.empty: return query_input, query_input, None, {}
        
        pure_id = ticker.split('.')[0]
        val_db = get_tw_stock_valuation()
        val = val_db.get(pure_id, {})
        
        # 1. 名稱修復：優先使用官方快取名稱
        name = val.get("Name")
        if not name:
            name = ticker
            url = f"https://tw.stock.yahoo.com/quote/{pure_id}"
            try:
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3, verify=False)
                if res.status_code == 200 and "<title>" in res.text:
                    name = res.text.split("<title>")[1].split("(")[0].strip()
            except: pass
            
        # 2. 先取得 Yahoo 基本資訊 (保留既有真實數據)
        info = {}
        try: info = stock.info
        except: pass
        
        # 🌟 3. 雙重智慧合併：不強制覆蓋，誰有數字就用誰的！
        # 處理 PE (本益比)
        twse_pe = val.get("PE", "N/A")
        if twse_pe not in ["N/A", "-", "", None]:
            try: info['trailingPE'] = float(str(twse_pe).replace(",", ""))
            except: pass
        
        # 處理 PB (本淨比)
        twse_pb = val.get("PB", "N/A")
        if twse_pb not in ["N/A", "-", "", None]:
            try: info['priceToBook'] = float(str(twse_pb).replace(",", ""))
            except: pass
        
        # 處理 現金殖利率
        twse_dy = val.get("Yield", "N/A")
        if twse_dy not in ["N/A", "-", "", None]:
            try: info['dividendYield'] = float(str(twse_dy).replace(",", "")) / 100
            except: pass
            
        return ticker, name, hist, info
    except:
        return query_input, query_input, None, {}

@st.cache_data(ttl=1800)
def get_market_status():
    try:
        # 🌟 同樣移除 session，避免大盤也被 Yahoo 阻擋
        twii = yf.Ticker("^TWII").history(period="100d")
        if twii.empty: return "⚠️ 大盤連線失敗 (回傳為空)"
        close = twii['Close'].iloc[-1]
        ma60 = twii['Close'].rolling(60).mean().iloc[-1]
        status = "多頭格局" if close > ma60 else "空頭防禦"
        today_str = datetime.datetime.now().strftime("%m/%d")
        return f"☑️ 【台股大盤】目前 {close:.2f} 點 (季線 {ma60:.2f}，{status}) [最終狀態: {today_str}]"
    except Exception as e: 
        return f"⚠️ 大盤連線失敗 ({e})"

# ==========================================
# 量化指標計算與策略引擎
# ==========================================
def compute_technical_indicators(df):
    close = df['Close']
    df['MA5'] = close.rolling(5).mean()
    df['MA20'] = close.rolling(20).mean()
    df['MA60'] = close.rolling(60).mean()
    df['Vol_MA5'] = df['Volume'].rolling(5).mean()
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    low_min9 = df['Low'].rolling(9).min()
    high_max9 = df['High'].rolling(9).max()
    rsv = (close - low_min9) / (high_max9 - low_min9 + 1e-9) * 100
    df['K'] = rsv.ewm(com=2).mean()
    df['D'] = df['K'].ewm(com=2).mean()
    return df

def evaluate_multi_factors(df, info):
    score = 0
    if len(df) < 60: return 50, "🟡 【50分】歷史資料不足，建議觀望。", "🟡"
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close = latest['Close']
    ma5, ma20, ma60 = latest['MA5'], latest['MA20'], latest['MA60']
    
    if close > ma60: score += 20
    if close > ma20: score += 10
    if ma5 > ma20 > ma60: score += 10
    if latest['K'] > latest['D']: score += 15
    if 45 <= latest['RSI'] <= 75: score += 15
    elif latest['RSI'] > 75: score += 5
    if latest['Volume'] > latest['Vol_MA5'] and close > prev['Close']: score += 15
    elif close >= prev['Close']: score += 8
        
    # 安全解析數值，避免 N/A 造成系統當機
    try: pe = float(info.get('trailingPE', 0))
    except: pe = 0
    try: div_yield = float(info.get('dividendYield', 0))
    except: div_yield = 0
    
    if 0 < pe <= 20: score += 8
    elif pe > 35: score += 2
    else: score += 5
    
    if div_yield >= 0.04: score += 7
    else: score += 3

    if score >= 80:
        advice = f"🟢(綠燈) 【{score}分 強勢買進】趨勢偏多！建議可於月線 ({ma20:.2f}) 附近逢低建立部位，以季線 ({ma60:.2f}) 為防守。"
        light = "🟢"
    elif score >= 60:
        advice = f"🟡(黃燈) 【{score}分 區間震盪】目前無明顯突破。建議等待回測季線 ({ma60:.2f}) 量縮止跌再進場。"
        light = "🟡"
    else:
        if close < ma60:
            advice = f"🔴(紅燈) 【{score}分 偏空觀望】已跌破季線趨勢轉弱。風險大請謹慎，建議反彈至月線 ({ma20:.2f}) 減碼！"
        else:
            advice = f"🔴(紅燈) 【{score}分 動能轉弱】目前雖撐在季線上，但指標轉弱。若跌破季線 ({ma60:.2f}) 請停損，逢高減碼。"
        light = "🔴"
        
    return score, advice, light

@st.cache_data(ttl=1800)
def get_market_status():
    try:
        twii = yf.Ticker("^TWII", session=yf_session).history(period="100d")
        if twii.empty: return "⚠️ 大盤連線失敗"
        close = twii['Close'].iloc[-1]
        ma60 = twii['Close'].rolling(60).mean().iloc[-1]
        status = "多頭格局" if close > ma60 else "空頭防禦"
        today_str = datetime.datetime.now().strftime("%m/%d")
        return f"☑️ 【台股大盤】目前 {close:.2f} 點 (站穩季線 {ma60:.2f}，{status}) [最終狀態: {today_str}]"
    except: return "⚠️ 大盤連線失敗"

# ==========================================
# 快取機制防護 (避免 APIError 429)
# ==========================================
@st.cache_data(ttl=600)
def get_cached_auth_db():
    return load_db("users_auth", [])

# ==========================================
# 登入系統
# ==========================================
if 'username' not in st.session_state: st.session_state.username = None
auth_db = get_cached_auth_db()
auth_dict = {item["username"]: item["password"] for item in auth_db}

if st.session_state.username is None:
    st.title("🔐 多因子量化終端機")
    col1, col2 = st.columns(2)
    with col1: u_in = st.text_input("👤 帳號：")
    with col2: p_in = st.text_input("🔑 密碼：", type="password")
    if st.button("登入系統", use_container_width=True):
        if u_in and p_in:
            if u_in in auth_dict and auth_dict[u_in] == p_in:
                st.session_state.username = u_in
                st.rerun()
            elif u_in not in auth_dict:
                auth_dict[u_in] = p_in
                save_db("users_auth", [{"username": k, "password": v} for k, v in auth_dict.items()])
                st.cache_data.clear() # 清除快取以抓取新帳號
                st.session_state.username = u_in
                st.rerun()
            else: st.error("❌ 密碼錯誤！")
    st.stop()

username = st.session_state.username
user_watch_key = f"watch_{username}"
user_port_key = f"port_{username}"

# 記憶體快取：只在剛登入時讀取一次，避免瘋狂存取 Google Sheets
if 'data_loaded_for' not in st.session_state or st.session_state.data_loaded_for != username:
    st.session_state.user_watch_list = load_db(user_watch_key, [])
    st.session_state.user_portfolio = load_db(user_port_key, [])
    st.session_state.data_loaded_for = username

user_watch_list = st.session_state.user_watch_list
user_portfolio = st.session_state.user_portfolio

# ==========================================
# 側邊欄 (使用者資訊與系統更新)
# ==========================================
with st.sidebar:
    st.title("👤 使用者資訊")
    st.markdown(f"登入帳號：**{username}**")
    st.markdown("連線狀態：🟢 **Google 試算表已連線**" if sheet_db else "🟡 **本地離線模式**")
    st.divider()
    
    if st.button("🔄 重新讀取與更新報價", use_container_width=True):
        with st.spinner("正在同步雲端資料與最新報價，請稍候..."):
            st.cache_data.clear() 
            
            # 強制從雲端抓取最新清單，防多裝置衝突
            user_watch_list = load_db(user_watch_key, [])
            user_portfolio = load_db(user_port_key, [])
            
            # 更新觀察清單
            for item in user_watch_list:
                tk, nm, hist, inf = fetch_data(item["代號"])
                if hist is not None and not hist.empty:
                    df_tech = compute_technical_indicators(hist)
                    sc, adv, lgt = evaluate_multi_factors(df_tech, inf)
                    item["現價"] = round(float(df_tech['Close'].iloc[-1]), 2)
                    change = df_tech['Close'].iloc[-1] - df_tech['Close'].iloc[-2]
                    item["漲跌行情"] = f"{change:+.2f} ({(change / df_tech['Close'].iloc[-2]) * 100:+.2f}%)"
                    item["季線"] = round(float(df_tech['MA60'].iloc[-1]), 2)
                    item["進場建議 (多因子評分)"] = adv
            save_db(user_watch_key, user_watch_list)
            
            # 更新庫存清單
            for item in user_portfolio:
                tk, nm, hist, inf = fetch_data(item["代號"])
                if hist is not None and not hist.empty:
                    df_tech = compute_technical_indicators(hist)
                    sc, adv, lgt = evaluate_multi_factors(df_tech, inf)
                    
                    curr_price = float(hist['Close'].iloc[-1])
                    cost_total = float(item["買進均價"]) * float(item["股數"])
                    market_val = curr_price * float(item["股數"])
                    
                    item["目前現價"] = round(curr_price, 2)
                    item["總市值"] = int(market_val)
                    item["損益金額"] = int(market_val - cost_total)
                    item["報酬率"] = f"{((curr_price - float(item['買進均價'])) / float(item['買進均價'])) * 100:+.2f}%"
                    item["行動指南"] = adv
            save_db(user_port_key, user_portfolio)
            
            # 同步更新回記憶體
            st.session_state.user_watch_list = user_watch_list
            st.session_state.user_portfolio = user_portfolio
            
        st.success("✅ 資料同步與評分更新完成！")
        time.sleep(1)
        st.rerun()

    if st.button("🚪 登出系統", use_container_width=True):
        st.session_state.username = None
        st.session_state.data_loaded_for = None
        st.rerun()

st.markdown(f"<h3 style='text-align: center; color: #333;'>{get_market_status()}</h3>", unsafe_allow_html=True)
st.divider()

tab1, tab2, tab3, tab4 = st.tabs(["🔭 觀察清單", "📦 我的庫存 (損益與避險)", "⭐ 每日 AI 量化精選 (Top 5)", "📊 個股深度量化診斷"])

# ------------------------------------------
# Tab 1: 觀察清單
# ------------------------------------------
with tab1:
    c1, c2 = st.columns([4, 1])
    with c1: w_ticker = st.text_input("輸入代號或名稱 (如：台積電、1789)：", key="w_input")
    with c2: 
        st.write("")
        st.write("")
        if st.button("加入觀察清單", use_container_width=True) and w_ticker:
            with st.spinner("計算中..."):
                ticker, name, hist, info = fetch_data(w_ticker)
                if hist is not None and not hist.empty:
                    df_tech = compute_technical_indicators(hist)
                    score, advice, light = evaluate_multi_factors(df_tech, info)
                    latest_p = df_tech['Close'].iloc[-1]
                    change = latest_p - df_tech['Close'].iloc[-2]
                    
                    st.session_state.user_watch_list = [item for item in st.session_state.user_watch_list if item.get('代號') != ticker]
                    st.session_state.user_watch_list.append({
                        "代號": ticker, "名稱": name, "現價": round(float(latest_p), 2),
                        "漲跌行情": f"{change:+.2f} ({(change / df_tech['Close'].iloc[-2]) * 100:+.2f}%)",
                        "季線": round(float(df_tech['MA60'].iloc[-1]), 2), "進場建議 (多因子評分)": advice
                    })
                    save_db(user_watch_key, st.session_state.user_watch_list)
                    st.rerun()
                else: st.error("查無此股票！")

    if st.session_state.user_watch_list:
        st.dataframe(
            pd.DataFrame(st.session_state.user_watch_list), 
            use_container_width=False, 
            width=1800,
            hide_index=True,
            column_config={
                "進場建議 (多因子評分)": st.column_config.TextColumn("進場建議 (多因子評分)", width=600)
            }
        )
        del_ticker = st.selectbox("選擇要刪除的標的：", [item["代號"] for item in st.session_state.user_watch_list], key="del_w")
        if st.button("🗑️ 刪除選取標的"):
            st.session_state.user_watch_list = [item for item in st.session_state.user_watch_list if item["代號"] != del_ticker]
            save_db(user_watch_key, st.session_state.user_watch_list)
            st.rerun()

# ------------------------------------------
# Tab 2: 我的庫存
# ------------------------------------------
with tab2:
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    with c1: p_tick = st.text_input("股票名稱/代號：", key="p_t")
    with c2: p_shares = st.number_input("持有股數：", value=1000, step=100)
    with c3: p_cost = st.number_input("買進均價：", value=0.0, step=0.5)
    with c4:
        st.write("")
        st.write("")
        if st.button("加入庫存", use_container_width=True) and p_tick and p_cost > 0:
            with st.spinner("獲取報價與 AI 診斷中..."):
                ticker, name, hist, info = fetch_data(p_tick)
                if hist is not None and not hist.empty:
                    df_tech = compute_technical_indicators(hist)
                    score, advice, light = evaluate_multi_factors(df_tech, info)
                    curr_price = float(hist['Close'].iloc[-1])
                    cost_total = int(p_cost * p_shares)
                    market_val = int(curr_price * p_shares)
                    
                    st.session_state.user_portfolio.append({
                        "代號": ticker, "名稱": name, "股數": p_shares, "買進均價": p_cost,
                        "目前現價": round(curr_price, 2), "總成本": cost_total, "總市值": market_val,
                        "損益金額": market_val - cost_total, "報酬率": f"{((curr_price-p_cost)/p_cost)*100:+.2f}%",
                        "行動指南": advice
                    })
                    save_db(user_port_key, st.session_state.user_portfolio)
                    st.rerun()
                else: st.error("查無此股票！")
    
    if st.session_state.user_portfolio:
        df_p = pd.DataFrame(st.session_state.user_portfolio).fillna("")
        if '報酬率 (%)' in df_p.columns and '報酬率' in df_p.columns: df_p = df_p.drop(columns=['報酬率 (%)'])
            
        total_pnl = df_p['損益金額'].replace("", 0).sum() if '損益金額' in df_p.columns else 0
        st.metric("總體未實現損益", f"${int(total_pnl):+,}", delta=f"{int(total_pnl):+,}")
        
        st.dataframe(
            df_p, 
            use_container_width=False, 
            width=1800,
            hide_index=True,
            column_config={
                "行動指南": st.column_config.TextColumn("行動指南", width=600)
            }
        )
        
        del_p_idx = st.selectbox("選擇要結清/移除的持股：", range(len(st.session_state.user_portfolio)), 
                                 format_func=lambda x: f"{st.session_state.user_portfolio[x].get('名稱', '')} ({st.session_state.user_portfolio[x].get('代號', '')})")
        if st.button("🗑️ 移除此筆庫存"):
            st.session_state.user_portfolio.pop(del_p_idx)
            save_db(user_port_key, st.session_state.user_portfolio)
            st.rerun()

# ------------------------------------------
# Tab 3: 每日 AI 量化精選 (Top 5)
# ------------------------------------------
with tab3:
    st.subheader("⭐ 盤後 AI 運算強勢股 (即時掃描大型權值/熱門股)")
    if st.button("🚀 啟提今日 AI 掃描"):
        with st.spinner("AI 量化引擎掃描中...這可能需要幾十秒鐘..."):
            hot_stocks = ['2330', '2317', '2454', '2308', '2881', '2603', '3231', '2382', '2891', '2345', '1519', '3034']
            results = []
            for s in hot_stocks:
                tk, nm, hist, inf = fetch_data(s)
                if hist is not None and not hist.empty:
                    df_t = compute_technical_indicators(hist)
                    sc, adv, lgt = evaluate_multi_factors(df_t, inf)
                    results.append({"代號": tk, "名稱": nm, "評分": sc, "現價": round(float(df_t['Close'].iloc[-1]), 2), "AI 建議": adv})
            
            st.dataframe(
                pd.DataFrame(sorted(results, key=lambda x: x["評分"], reverse=True)[:5]),
                use_container_width=False, 
                width=1800,
                hide_index=True,
                column_config={"AI 建議": st.column_config.TextColumn("AI 建議", width=600)}
            )

# ------------------------------------------
# Tab 4: 個股深度量化診斷
# ------------------------------------------
with tab4:
    diag_q = st.text_input("請輸入要深度診斷的個股名稱或代號：", placeholder="例如：台積電")
    if st.button("📊 產生完整體檢報告", use_container_width=True) and diag_q:
        with st.spinner("調閱歷史籌碼與技術資料..."):
            t_id, t_name, hist_data, t_info = fetch_data(diag_q)
            if hist_data is not None and not hist_data.empty:
                df_calc = compute_technical_indicators(hist_data)
                sc, adv, lgt = evaluate_multi_factors(df_calc, t_info)
                latest = df_calc.iloc[-1]
                
                st.markdown(f"## {t_name} ({t_id}) 量化深度報告")
                st.info(f"**綜合行動建議：** {adv}")
                
                col_a, col_b, col_c = st.columns(3)
                
                with col_a:
                    st.markdown("### 🏢 基本面 (公司價值)")
                    eps = t_info.get('trailingEps', 'N/A')
                    roe = t_info.get('returnOnEquity', 'N/A')
                    gm = t_info.get('grossMargins', 'N/A')
                    
                    st.write(f"**EPS (每股盈餘):** {f'{eps:.2f}' if isinstance(eps, (int, float)) else '-'}")
                    st.write(f"**ROE (股東權益報酬):** {f'{roe*100:.2f}%' if isinstance(roe, (int, float)) else '-'}")
                    st.write(f"**毛利率:** {f'{gm*100:.2f}%' if isinstance(gm, (int, float)) else '-'}")
                    st.write("*用途：看獲利品質與趨勢，ROE過高需檢視資本結構是否有風險。*")
                    
                with col_b:
                    st.markdown("### ⚖️ 估值與風險")
                    pe = t_info.get('trailingPE', 'N/A')
                    pb = t_info.get('priceToBook', 'N/A')
                    dy = t_info.get('dividendYield', 'N/A')
                    
                    st.write(f"**本益比 (PE):** {f'{pe:.2f}' if isinstance(pe, (int, float)) else '-'}")
                    st.write(f"**本淨比 (PB):** {f'{pb:.2f}' if isinstance(pb, (int, float)) else '-'}")
                    st.write(f"**現金殖利率:** {f'{dy*100:.2f}%' if isinstance(dy, (int, float)) else '-'}")
                    st.write("*陷阱：單看PE容易忽略成長性與資本結構；估值需結合產業生命周期。*")
                    
                with col_c:
                    st.markdown("### 📉 技術面 (進出場)")
                    st.write(f"**月線 (MA20):** {latest['MA20']:.2f}")
                    st.write(f"**季線 (MA60):** {latest['MA60']:.2f}")
                    st.write(f"**RSI (14):** {latest['RSI']:.2f}")
                    st.write(f"**MACD:** {latest['MACD']:.2f} (信號: {latest['Signal']:.2f})")
                    st.write("*實務建議：應與成交量配合；設定明確停損與倉位管理。*")
                    
                st.markdown("### 📋 實務快速檢查表 (Checklist)")
                c1, c2, c3, c4 = st.columns(4)
                c1.checkbox("站穩季線 (MA60)", value=latest['Close'] > latest['MA60'], disabled=True)
                c2.checkbox("本益比低於 25", value=type(pe)!=str and pe < 25, disabled=True)
                c3.checkbox("RSI 動能健康 (45~75)", value=45 <= latest['RSI'] <= 75, disabled=True)
                c4.checkbox("成交量大於五日均量", value=latest['Volume'] > latest['Vol_MA5'], disabled=True)

            else: st.error("查無此股票資料！")

# ==========================================
# 底部：多因子評分指南
# ==========================================
st.write("")
st.write("")
st.markdown("""
<style>
.footer-container {
    display: flex; justify-content: space-between; border: 1px solid #ddd; 
    background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin-top: 50px;
}
.footer-box { flex: 1; text-align: center; border-right: 1px solid #ddd; padding: 0 10px; }
.footer-box:last-child { border-right: none; }
.title-green { color: #2e7d32; font-weight: bold; font-size: 16px; }
.title-yellow { color: #fbc02d; font-weight: bold; font-size: 16px; }
.title-red { color: #c62828; font-weight: bold; font-size: 16px; }
.title-black { color: #212121; font-weight: bold; font-size: 16px; }
.desc { font-size: 13px; color: #555; margin-top: 5px; }
</style>

<div style="font-size: 14px; font-weight: bold; margin-bottom: 5px;">📊 多因子評分指南 (綜合: 營收/ROE/FCF/估值 + KD/MACD/量能 + 外資/總經)</div>
<div class="footer-container">
    <div class="footer-box">
        <div class="title-green">🟢 (綠燈) 80~100分 (或60分以上完美打底)</div>
        <div class="desc">基本/技術雙優，可積極偏多操作<br>逢低於月線承接，季線防守</div>
    </div>
    <div class="footer-box">
        <div class="title-yellow">🟡 (黃燈) 60~79分 (區間震盪)</div>
        <div class="desc">估值合理但量能未出，等回測季線<br>區間低買高賣，等待方向突破</div>
    </div>
    <div class="footer-box">
        <div class="title-red">🔴 (紅燈) 0~59分 (偏空/高估)</div>
        <div class="desc">基本面衰退或破線，風險大勿接刀<br>反彈減碼防禦，嚴格執行停損</div>
    </div>
    <div class="footer-box" style="background-color: #ffebee;">
        <div class="title-black">🦇 (黑天鵝) 總經/大盤警報</div>
        <div class="desc">外資大賣或國際恐慌，無條件觀望<br>系統性風險發酵，現金為王</div>
    </div>
</div>
""", unsafe_allow_html=True)