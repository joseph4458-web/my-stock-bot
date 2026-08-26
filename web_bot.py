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
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="多因子量化終端機 Pro", page_icon="📈", layout="wide")

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
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
            return client.open("量化終端機_DB")
    except Exception as e:
        st.warning(f"⚠️ 雲端資料庫連線提示: {e}")
    return None

sheet_db = init_gsheet()

def load_db(table_name, default_val):
    if sheet_db:
        try:
            worksheet = sheet_db.worksheet(table_name)
            data = worksheet.get_all_records()
            return data if data else default_val
        except:
            return default_val
    else:
        file_name = f"{table_name}.json"
        if os.path.exists(file_name):
            with open(file_name, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default_val

def save_db(table_name, data):
    if sheet_db:
        try:
            try:
                worksheet = sheet_db.worksheet(table_name)
            except:
                worksheet = sheet_db.add_worksheet(title=table_name, rows="150", cols="20")
            worksheet.clear()
            if data:
                df = pd.DataFrame(data)
                worksheet.update([df.columns.values.tolist()] + df.values.tolist())
        except Exception as e:
            st.error(f"存檔至 Google 試算表失敗: {e}")
    else:
        file_name = f"{table_name}.json"
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

# ==========================================
# 量化指標計算引擎
# ==========================================
def compute_technical_indicators(df):
    close = df['Close']
    high = df['High']
    low = df['Low']
    vol = df['Volume']
    
    # 均線
    df['MA5'] = close.rolling(5).mean()
    df['MA20'] = close.rolling(20).mean()
    df['MA60'] = close.rolling(60).mean()
    df['Vol_MA5'] = vol.rolling(5).mean()
    
    # RSI (14)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # KD (9, 3, 3)
    low_min9 = low.rolling(9).min()
    high_max9 = high.rolling(9).max()
    rsv = (close - low_min9) / (high_max9 - low_min9 + 1e-9) * 100
    df['K'] = rsv.ewm(com=2).mean()
    df['D'] = df['K'].ewm(com=2).mean()
    
    return df

def evaluate_multi_factors(df, info):
    score = 0
    details = []
    
    if len(df) < 60:
        return 50, "🟡 【50分】數據歷史不足 60 日，以中性看待", "🟡"
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close = latest['Close']
    
    # 1. 均線趨勢因子 (40 分)
    if close > latest['MA60']:
        score += 20
        details.append("站上季線 (+20)")
    else:
        details.append("跌破季線 (+0)")
        
    if close > latest['MA20']:
        score += 10
        details.append("站上月線 (+10)")
        
    if latest['MA5'] > latest['MA20'] > latest['MA60']:
        score += 10
        details.append("均線多頭排列 (+10)")
        
    # 2. 動能指標因子 (30 分)
    if latest['K'] > latest['D']:
        score += 15
        details.append("KD金叉向上 (+15)")
        
    if 45 <= latest['RSI'] <= 75:
        score += 15
        details.append("RSI動能健康 (+15)")
    elif latest['RSI'] > 75:
        score += 5
        details.append("RSI偏高過熱 (+5)")
        
    # 3. 量價配合因子 (15 分)
    if latest['Volume'] > latest['Vol_MA5'] and close > prev['Close']:
        score += 15
        details.append("出量上攻 (+15)")
    elif close >= prev['Close']:
        score += 8
        details.append("價漲量平 (+8)")
        
    # 4. 基本面估值因子 (15 分)
    pe = info.get('trailingPE', None)
    div_yield = info.get('dividendYield', None)
    
    if pe and 0 < pe <= 20:
        score += 8
        details.append("本益比合宜 (+8)")
    elif pe and pe > 35:
        score += 2
        details.append("本益比偏高 (+2)")
    else:
        score += 5
        
    if div_yield and div_yield >= 0.04:
        score += 7
        details.append("高殖利率保護 (+7)")
    else:
        score += 3
        
    # 燈號判定 (嚴格對應分數門檻)
    if score >= 80:
        light = "🟢"
        signal_text = f"🟢 【{score}分】強勢偏多 | 多頭趨勢明確，各項量化指標表現優異。"
    elif score >= 60:
        light = "🟡"
        signal_text = f"🟡 【{score}分】中性整理 | 處於震盪整理格局，建議分批觀察或逢低佈局。"
    else:
        light = "🔴"
        signal_text = f"🔴 【{score}分】弱勢警戒 | 走勢疲弱或跌破關鍵支撐，建議防禦減碼。"
        
    return score, signal_text, light

# ==========================================
# Yahoo Finance 資料讀取
# ==========================================
def get_tw_chinese_name(ticker):
    try:
        pure_id = ticker.split('.')[0]
        url = f"https://tw.stock.yahoo.com/quote/{pure_id}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3, verify=False)
        if res.status_code == 200 and "<title>" in res.text:
            title = res.text.split("<title>")[1].split("</title>")[0]
            name = title.split("(")[0].strip()
            if name: return name
    except: pass
    return ticker

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
        return ticker, name, hist, stock.info
    except:
        return ticker_input, ticker_input, None, {}

@st.cache_data(ttl=3600)
def get_market_status():
    try:
        twii = yf.Ticker("^TWII", session=yf_session)
        hist = twii.history(period="100d")
        if hist.empty: hist = yf.Ticker("0050.TW", session=yf_session).history(period="100d")
        if hist.empty: return "⚠️ 大盤數據回傳逾時"
        close = hist['Close'].iloc[-1]
        ma60 = hist['Close'].rolling(60).mean().iloc[-1]
        bias = ((close - ma60) / ma60) * 100
        status = "🟢 多頭主導" if close > ma60 else "🔴 空頭防禦"
        return f"📊 【台股大盤指數】目前 **{close:.2f}** 點 (季線 **{ma60:.2f}**，乖離率 **{bias:+.2f}%** | {status})"
    except:
        return "⚠️ 大盤數據暫時無法連線"

# ==========================================
# 登入與權限管理
# ==========================================
if 'username' not in st.session_state:
    st.session_state.username = None

auth_db = {item["username"]: item["password"] for item in load_db("users_auth", [])}

def save_auth_db(db_dict):
    data_list = [{"username": k, "password": v} for k, v in db_dict.items()]
    save_db("users_auth", data_list)

if st.session_state.username is None:
    st.title("🔐 多因子量化終端機 - 登入")
    st.caption("內建 Google 雲端同步資料庫，資料永久儲存")
    
    col1, col2 = st.columns(2)
    with col1: user_input = st.text_input("👤 使用者帳號：")
    with col2: pass_input = st.text_input("🔑 密碼：", type="password")
    
    if st.button("登入系統", use_container_width=True):
        if user_input.strip() and pass_input.strip():
            u = user_input.strip()
            p = pass_input.strip()
            if u in auth_db:
                if auth_db[u] == p:
                    st.session_state.username = u
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤！")
            else:
                auth_db[u] = p
                save_auth_db(auth_db)
                st.success(f"✅ 帳號 {u} 建立成功，系統自動登入中...")
                time.sleep(1)
                st.session_state.username = u
                st.rerun()
        else:
            st.warning("⚠️ 請完整輸入帳號與密碼！")
    st.stop()

# ==========================================
# 系統主畫面
# ==========================================
username = st.session_state.username
user_watch_key = f"watch_{username}"
user_port_key = f"port_{username}"

user_watch_list = load_db(user_watch_key, [])
user_portfolio = load_db(user_port_key, [])

with st.sidebar:
    st.title("👤 使用者資訊")
    st.markdown(f"登入帳號：**{username}**")
    st.markdown("連線狀態：🟢 **Google 試算表已連線**" if sheet_db else "🟡 **本地離線模式**")
    st.divider()
    if st.button("🚪 登出系統", use_container_width=True):
        st.session_state.username = None
        st.rerun()

st.title(f"🚀 多因子量化終端機 Pro")
st.info(get_market_status())

tab1, tab2, tab3, tab4 = st.tabs([
    "🔭 自選監控清單", 
    "📦 我的庫存損益", 
    "📊 個股量化診斷", 
    "📖 量化評分說明"
])

# ------------------------------------------
# Tab 1: 自選監控清單
# ------------------------------------------
with tab1:
    st.subheader("➕ 新增自選監控標的")
    c1, c2 = st.columns([3, 1])
    with c1:
        w_ticker = st.text_input("輸入台股代號（例如 2330、0050、2603）：", key="w_input")
    with c2:
        st.write("")
        st.write("")
        add_watch_btn = st.button("加入自選清單", use_container_width=True)
        
    if add_watch_btn and w_ticker:
        with st.spinner("量化引擎計算中..."):
            ticker, name, hist, info = fetch_data(w_ticker)
            if hist is not None and not hist.empty:
                df_tech = compute_technical_indicators(hist)
                score, signal, light = evaluate_multi_factors(df_tech, info)
                latest_p = round(float(df_tech['Close'].iloc[-1]), 2)
                change = latest_p - df_tech['Close'].iloc[-2] if len(df_tech) >= 2 else 0
                change_pct = (change / df_tech['Close'].iloc[-2]) * 100 if len(df_tech) >= 2 else 0
                
                # 避免重複新增
                user_watch_list = [item for item in user_watch_list if item.get('代號') != ticker]
                user_watch_list.append({
                    "燈號": light,
                    "代號": ticker,
                    "名稱": name,
                    "現價": latest_p,
                    "漲跌幅": f"{change:+.2f} ({change_pct:+.2f}%)",
                    "評分": score,
                    "季線 MA60": round(float(df_tech['MA60'].iloc[-1]), 2),
                    "RSI(14)": round(float(df_tech['RSI'].iloc[-1]), 1),
                    "診斷結論": signal
                })
                save_db(user_watch_key, user_watch_list)
                st.success(f"已將 {name} ({ticker}) 加入監控！")
                st.rerun()
            else:
                st.error("查無此股票代號或無法取得數據！")

    st.divider()
    st.subheader("📋 目前自選清單")
    if user_watch_list:
        df_display = pd.DataFrame(user_watch_list)
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        del_ticker = st.selectbox("選擇要刪除的自選標的：", [item["代號"] for item in user_watch_list], key="del_w")
        if st.button("🗑️ 刪除選取標的"):
            user_watch_list = [item for item in user_watch_list if item["代號"] != del_ticker]
            save_db(user_watch_key, user_watch_list)
            st.rerun()
    else:
        st.info("目前自選清單為空，請在上方輸入代號新增股票。")

# ------------------------------------------
# Tab 2: 我的庫存損益
# ------------------------------------------
with tab2:
    st.subheader("➕ 新增持有部位")
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    with c1: p_tick = st.text_input("股票代號：", key="p_t")
    with c2: p_shares = st.number_input("持有股數：", value=1000, step=100)
    with c3: p_cost = st.number_input("買進均價 (元)：", value=0.0, step=0.5)
    with c4:
        st.write("")
        st.write("")
        add_port_btn = st.button("加入庫存管理", use_container_width=True)
        
    if add_port_btn and p_tick and p_cost > 0:
        with st.spinner("更新即時損益中..."):
            ticker, name, hist, info = fetch_data(p_tick)
            if hist is not None and not hist.empty:
                curr_price = round(float(hist['Close'].iloc[-1]), 2)
                cost_total = int(p_cost * p_shares)
                market_val = int(curr_price * p_shares)
                pnl = market_val - cost_total
                pnl_pct = ((curr_price - p_cost) / p_cost) * 100
                
                user_portfolio.append({
                    "代號": ticker,
                    "名稱": name,
                    "股數": p_shares,
                    "買進均價": p_cost,
                    "目前現價": curr_price,
                    "總成本": cost_total,
                    "總市值": market_val,
                    "損益金額": pnl,
                    "報酬率 (%)": f"{pnl_pct:+.2f}%"
                })
                save_db(user_port_key, user_portfolio)
                st.success(f"已成功加入 {name} 庫存！")
                st.rerun()
            else:
                st.error("查無此股票代號！")
                
    st.divider()
    st.subheader("💼 庫存資產總覽")
    if user_portfolio:
        df_p = pd.DataFrame(user_portfolio)
        
        # 統計總覽卡片
        total_cost = df_p['總成本'].sum()
        total_market = df_p['總市值'].sum()
        total_pnl = df_p['損益金額'].sum()
        total_roi = ((total_market - total_cost) / total_cost * 100) if total_cost > 0 else 0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("總投資成本", f"${total_cost:,}")
        m2.metric("總資產市值", f"${total_market:,}")
        m3.metric("未實現損益", f"${total_pnl:+,}", delta=f"{total_pnl:+,}")
        m4.metric("總報酬率", f"{total_roi:+.2f}%", delta=f"{total_roi:+.2f}%")
        
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        
        del_p_idx = st.selectbox("選擇要結清/移除的持股：", range(len(user_portfolio)), 
                                 format_func=lambda x: f"{user_portfolio[x]['名稱']} ({user_portfolio[x]['代號']}) - {user_portfolio[x]['股數']}股")
        if st.button("🗑️ 移除此筆庫存"):
            user_portfolio.pop(del_p_idx)
            save_db(user_port_key, user_portfolio)
            st.rerun()
    else:
        st.info("目前無持股紀錄，請在上方建立第一筆庫存。")

# ------------------------------------------
# Tab 3: 個股深入量化診斷
# ------------------------------------------
with tab3:
    st.subheader("🔍 即時多因子深度診斷")
    search_q = st.text_input("輸入要診斷的個股代號：", value="2330", key="diag_input")
    if st.button("開始診斷", use_container_width=True):
        with st.spinner("進行深度多因子回測與診斷..."):
            t_id, t_name, hist_data, t_info = fetch_data(search_q)
            if hist_data is not None and not hist_data.empty:
                df_calc = compute_technical_indicators(hist_data)
                sc, sig_txt, lgt = evaluate_multi_factors(df_calc, t_info)
                latest_bar = df_calc.iloc[-1]
                
                c_a, c_b, c_c, c_d = st.columns(4)
                c_a.metric("標的名稱", f"{t_name} ({t_id})")
                c_b.metric("目前價格", f"{latest_bar['Close']:.2f}")
                c_c.metric("量化總評分", f"{sc} 分", delta=f"{lgt} {sc}分")
                c_d.metric("季線支撐 (MA60)", f"{latest_bar['MA60']:.2f}")
                
                st.subheader(sig_txt)
                
                # 技術指標面板
                st.markdown("#### 📐 核心技術因子明細")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("月線 (MA20)", f"{latest_bar['MA20']:.2f}")
                k2.metric("RSI (14)", f"{latest_bar['RSI']:.1f}")
                k3.metric("KD 指標", f"K:{latest_bar['K']:.1f} / D:{latest_bar['D']:.1f}")
                vol_ratio = (latest_bar['Volume'] / latest_bar['Vol_MA5']) if latest_bar['Vol_MA5'] > 0 else 1
                k4.metric("量能放大倍數", f"{vol_ratio:.2f} 倍")
                
                # 走勢圖
                st.markdown("#### 📈 近期價格走勢與均線")
                st.line_chart(df_calc[['Close', 'MA20', 'MA60']].dropna())
            else:
                st.error("查無個股資料！")

# ------------------------------------------
# Tab 4: 量化評分說明書
# ------------------------------------------
with tab4:
    st.subheader("📖 多因子評分系統與燈號定義")
    
    st.markdown("""
    本系統採用多因子量化評分模型，總分為 **100 分**，綜合評估市場四大面向：
    
    * **均線趨勢因子 (40 分)**：評估股價與 MA20/MA60 的位階，以及短中長期均線之多頭排列架構。
    * **動能指標因子 (30 分)**：評估 KD 黃金交叉/死亡交叉與 RSI 強弱動能，避免過度追高或承接崩跌股。
    * **量價配合因子 (15 分)**：檢驗帶量上攻或量縮拉回之結構健康度。
    * **基本面因子 (15 分)**：檢視本益比估值區間與現金殖利率安全邊際。
    """)
    
    st.divider()
    st.markdown("""
    #### 🚦 燈號標準與分數嚴格對照表
    * 🟢 **綠燈 [80 ~ 100 分]**：**強勢偏多**
      * 條件：站上季線生命線、均線多頭、動能向上且基本面穩定。
      * 策略：順勢操作、持股續抱、拉回量縮偏多切入。
    * 🟡 **黃燈 [60 ~ 79 分]**：**中性整理**
      * 條件：均線糾結、指標多空互見、區間整理。
      * 策略：區間低買高賣、觀望等待突破方向。
    * 🔴 **紅燈 [0 ~ 59 分]**：**弱勢警戒**
      * 條件：跌破關鍵季線支撐、指標死叉向下或估值過高。
      * 策略：減碼防禦、嚴格執行停損、不盲目猜底。
    """)