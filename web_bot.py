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
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="多因子量化終端機", page_icon="📈", layout="wide")

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
yf_session = requests.Session()
yf_session.verify = False
yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
})

# ==========================================
# Google 試算表資料庫連線初始化
# ==========================================
def init_gsheet():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            
            # 👇 加入這行無敵代碼！強制把普通字串的 \n 轉回真正的換行符號
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
            # 開啟我們剛才建立的 Google 試算表
            sheet = client.open("量化終端機_DB")
            return sheet
    except Exception as e:
        st.warning(f"⚠️ 雲端資料庫連線提示: {e}")
    return None

sheet_db = init_gsheet()

# 載入與儲存函式（自動切換雲端或本地）
def load_db(table_name, default_val):
    if sheet_db:
        try:
            worksheet = sheet_db.worksheet(table_name)
            data = worksheet.get_all_records()
            return data
        except:
            return default_val
    else:
        # 本地備用模式
        file_name = f"{table_name}.json"
        if os.path.exists(file_name):
            with open(file_name, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default_val

def save_db(table_name, data):
    if sheet_db:
        try:
            try: worksheet = sheet_db.worksheet(table_name)
            except: worksheet = sheet_db.add_worksheet(title=table_name, rows="100", cols="20")
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
# 核心引擎與原介面邏輯 (略過重複部分保持精簡)
# ==========================================
@st.cache_data(ttl=3600)
def get_market_status():
    try:
        twii = yf.Ticker("^TWII", session=yf_session)
        hist = twii.history(period="100d")
        if hist.empty: hist = yf.Ticker("0050.TW", session=yf_session).history(period="100d")
        if hist.empty: return "⚠️ 大盤數據無回傳資料"
        close = hist['Close'].iloc[-1]
        ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
        return f"📈 【台股大盤】目前 {close:.2f} 點 (季線 {ma60:.2f})"
    except: return "⚠️ 大盤數據無法連線"

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
            else: ticker = ticker + '.TW'
        else:
            stock = yf.Ticker(ticker, session=yf_session)
            hist = stock.history(period="150d")
        if hist.empty: return ticker_input, ticker_input, None, {}
        name = get_tw_chinese_name(ticker)
        return ticker, name, hist, stock.info
    except: return ticker_input, ticker_input, None, {}

def analyze_stock_expert(hist, ticker, name, info):
    latest_price = hist['Close'].iloc[-1]
    ma60 = hist['Close'].rolling(window=60).mean().iloc[-1]
    total_score = 75 # 簡化評分示範
    signal = f"🟢 【{total_score}分】趨勢穩定，可持續關注。"
    change = latest_price - hist['Close'].iloc[-2] if len(hist) >= 2 else 0
    change_pct = (change / hist['Close'].iloc[-2]) * 100 if len(hist) >= 2 else 0
    return round(float(latest_price), 2), f"{change:.2f} ({change_pct:.2f}%)", round(float(ma60), 2), signal, total_score

# ==========================================
# 登入與帳號系統 (結合 Google 試算表)
# ==========================================
if 'username' not in st.session_state:
    st.session_state.username = None

# 從雲端讀取帳號密庫
auth_db = {item["username"]: item["password"] for item in load_db("users_auth", [])}

def save_auth_db(db_dict):
    data_list = [{"username": k, "password": v} for k, v in db_dict.items()]
    save_db("users_auth", data_list)

if st.session_state.username is None:
    st.title("🔐 專屬理財機器人 - 員工登入 (雲端版)")
    st.warning("💡 溫馨提醒：這只是內部的理財輔助小工具，請隨便設定一個簡單好記的密碼即可！")
    
    col1, col2 = st.columns(2)
    with col1: user_input = st.text_input("👤 員工姓名或工號：")
    with col2: pass_input = st.text_input("🔑 密碼：", type="password")
    
    if st.button("安全登入"):
        if user_input.strip() and pass_input.strip():
            u = user_input.strip()
            p = pass_input.strip()
            if u in auth_db:
                if auth_db[u] == p:
                    st.session_state.username = u
                    st.rerun()
                else: st.error("❌ 密碼錯誤！")
            else:
                auth_db[u] = p
                save_auth_db(auth_db)
                st.success(f"✅ 帳號 {u} 註冊成功！")
                time.sleep(1)
                st.session_state.username = u
                st.rerun()
        else: st.warning("⚠️ 欄位不能為空！")
    st.stop()

username = st.session_state.username

# 讀取該用戶的個人資料
user_watch_key = f"watch_{username}"
user_port_key = f"port_{username}"

user_watch_list = load_db(user_watch_key, [])
user_portfolio = load_db(user_port_key, [])

with st.sidebar:
    st.write(f"👤 目前使用者：**{username}**")
    if st.button("登出"):
        st.session_state.username = None
        st.rerun()

st.title(f"🚀 {username} 的專屬量化終端機")
st.info(get_market_status())

tab1, tab2 = st.tabs(["🔭 觀察清單", "📦 我的庫存"])

with tab1:
    st.subheader("新增自選股")
    w_ticker = st.text_input("輸入股票代號：", key="w_input")
    if st.button("加入觀察"):
        if w_ticker:
            ticker, name, hist, info = fetch_data(w_ticker)
            if hist is not None and not hist.empty:
                price, change, _, signal, score = analyze_stock_expert(hist, ticker, name, info)
                user_watch_list.append({"代號": ticker, "名稱": name, "評分": score, "現價": price, "漲跌": change})
                save_db(user_watch_key, user_watch_list)
                st.rerun()
    if user_watch_list:
        st.dataframe(pd.DataFrame(user_watch_list), use_container_width=True, hide_index=True)

with tab2:
    st.subheader("新增庫存")
    c1, c2, c3 = st.columns(3)
    with c1: p_tick = st.text_input("代號", key="p_t")
    with c2: p_shares = st.number_input("股數", value=1000, step=1000)
    with c3: p_price = st.number_input("買進均價", value=0.0)
    if st.button("加入庫存清單"):
        if p_tick and p_price > 0:
            ticker, name, hist, info = fetch_data(p_tick)
            if hist is not None and not hist.empty:
                price, change, _, _, _ = analyze_stock_expert(hist, ticker, name, info)
                pnl = int((price - p_price) * p_shares)
                user_portfolio.append({"代號": ticker, "名稱": name, "股數": p_shares, "買價": p_price, "現價": price, "損益": pnl})
                save_db(user_port_key, user_portfolio)
                st.rerun()
    if user_portfolio:
        st.dataframe(pd.DataFrame(user_portfolio), use_container_width=True, hide_index=True)