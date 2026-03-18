import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 頁面基本設定 ---
st.set_page_config(page_title="長期投資看板", layout="wide", page_icon="📈")

# --- 頁面基本設定 ---
st.set_page_config(page_title="長期投資看板", layout="wide", page_icon="📈")

# ==========================================
# 🛑 密碼保護防護網 🛑
# ==========================================
def check_password():
    # 如果已經登入成功過，就直接放行
    if st.session_state.get("password_correct", False):
        return True

    # 畫一個置中的登入畫面
    st.markdown("<h3 style='text-align: center; color: #003366;'>🔒 請輸入專屬密碼</h3>", unsafe_allow_html=True)
    
    # 密碼輸入框 (輸入時會變成黑點)
    pwd_input = st.text_input("Password", type="password", key="pwd_input")
    
    if pwd_input:
        # 核對保險箱裡的密碼
        if pwd_input == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.rerun() # 密碼正確，重新整理畫面放行
        else:
            st.error("❌ 密碼錯誤！這不是你的看盤軟體！")
    return False

# 如果密碼不對，程式就強制停止在這裡，下面的畫面通通不准跑！
if not check_password():
    st.stop()
# ==========================================

# --- 雲端與本機路徑設定 ---
DATA_FILE = "stock_data.json" 
# ... (下面維持你原本的所有程式碼) ...

# --- 雲端與本機路徑設定 ---
DATA_FILE = "stock_data.json" # 舊的本機存檔
GCP_KEY_FILE = "gcp_key.json" # Google 金鑰檔
SHEET_ID = "1iaKyWl8WwQv9Anpgb28drGEX0CrxmwIDF6BsOqI9UxM" # ⚠️ 請在這裡貼上你的 Google 試算表 ID ⚠️

# --- Google Sheets 連線與資料搬家邏輯 ---
@st.cache_resource
def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # 雲端環境：從 Secrets 保險箱讀取我們貼上的 JSON 字串
    if "gcp_json" in st.secrets:
        key_dict = json.loads(st.secrets["gcp_json"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict)
    # 本機環境：讀取資料夾裡的 json 檔案
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name(GCP_KEY_FILE, scope)
        
    client = gspread.authorize(creds)
    return client

def load_data():
    try:
        client = init_gspread()
        sheet = client.open_by_key(SHEET_ID).sheet1
        val = sheet.acell('A1').value
        
        # 如果雲端有資料，直接讀取
        if val:
            return json.loads(val)
            
        # 如果雲端沒有資料，啟動「自動搬家」程序！
        elif os.path.exists(DATA_FILE):
            st.toast("🚀 偵測到本機紀錄，正在為您自動上傳至 Google 雲端...", icon="☁️")
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                local_data = json.load(f)
            # 把本機資料寫上雲端
            sheet.update_acell('A1', json.dumps(local_data, ensure_ascii=False))
            st.toast("✅ 雲端搬家完成！以後皆自動同步至 Google 試算表。", icon="🎉")
            return local_data
            
    except Exception as e:
        st.error(f"連線 Google 試算表失敗，請檢查金鑰與 ID: {e}")
        
    return {"fee_discount": 6.0, "pledge_amount": 500000.0, "buy_records": [], "realized_records": []}

def save_data(data):
    try:
        client = init_gspread()
        sheet = client.open_by_key(SHEET_ID).sheet1
        # 將字典轉成 JSON 字串存入 A1 儲存格
        sheet.update_acell('A1', json.dumps(data, ensure_ascii=False))
    except Exception as e:
        st.error(f"儲存至雲端失敗: {e}")

# 初始化資料
if "db" not in st.session_state:
    st.session_state.db = load_data()

db = st.session_state.db

# --- 核心計算與爬蟲 ---
# --- 核心計算與爬蟲 ---
@st.cache_data(ttl=60)
def fetch_price(ticker):
    price = 0.0
    name = ticker
    
    # 1. 引擎 A：從 Google 財經抓取「即時股價」 (報價穩定且快速)
    try:
        url_g = f"https://www.google.com/finance/quote/{ticker}:TPE?hl=zh-TW"
        resp_g = requests.get(url_g, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup_g = BeautifulSoup(resp_g.text, 'html.parser')
        p_div = soup_g.find('div', class_='YMlKec fxKbKc')
        if p_div: 
            price = float(p_div.text.replace('$', '').replace(',', ''))
    except:
        pass
        
    # 2. 引擎 B：從 Yahoo 奇摩股市抓取「股票名稱」 (中文名稱最精準)
    try:
        url_y = f"https://tw.stock.yahoo.com/quote/{ticker}"
        resp_y = requests.get(url_y, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup_y = BeautifulSoup(resp_y.text, 'html.parser')
        # Yahoo 股市的名稱通常固定放在 <h1> 標籤裡
        h1_tag = soup_y.find('h1')
        if h1_tag:
            name = h1_tag.text
    except:
        pass
        
    return price, name

def calc_cost_profit(ticker, shares, buy_price, sell_price=None):
    disc = db["fee_discount"] / 10.0
    buy_cost = shares * buy_price
    buy_fee = buy_cost * 0.001425 * disc
    total_cost = buy_cost + buy_fee
    
    if sell_price is not None:
        sell_rev = shares * sell_price
        sell_fee = sell_rev * 0.001425 * disc
        tax_rate = 0.001 if ticker.startswith("00") else 0.003
        sell_tax = sell_rev * tax_rate
        return round(sell_rev - sell_fee - sell_tax - total_cost)
    return total_cost

# --- 彈出視窗 (Dialogs) ---
@st.dialog("🔍 逐筆買進明細與管理")
def show_details_dialog(ticker, name):
    st.markdown(f"### {ticker} {name}")
    st.write("點擊垃圾桶刪除紀錄。")
    records = sorted([r for r in db["buy_records"] if r["ticker"] == ticker], key=lambda x: x["date"], reverse=True)
    if not records:
        st.warning("目前無庫存紀錄。")
        return
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    c1.write("**買進日期**")
    c2.write("**股數**")
    c3.write("**單價**")
    c4.write("**刪除**")
    st.divider()
    for r in records:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(r["date"])
        c2.write(f"{r['shares']:,}")
        c3.write(f"${r['price']:.2f}")
        if c4.button("🗑️", key=f"del_{r['id']}"):
            db["buy_records"] = [rec for rec in db["buy_records"] if rec["id"] != r["id"]]
            save_data(db)
            st.rerun()

@st.dialog("🛒 賣出股票")
def show_sell_dialog(ticker, name):
    st.markdown(f"### 賣出 {ticker} {name}")
    tot_s = sum(r["shares"] for r in db["buy_records"] if r["ticker"] == ticker)
    st.info(f"目前總庫存: **{tot_s:,}** 股")
    sell_date = st.date_input("賣出日期")
    sell_shares = st.number_input("賣出股數", min_value=1, max_value=tot_s, step=1000)
    current_p, _ = fetch_price(ticker)
    sell_price = st.number_input("賣出單價", value=current_p, min_value=0.01, step=1.0)
    if st.button("確認賣出", type="primary", use_container_width=True):
        rem = sell_shares
        target_records = sorted([r for r in db["buy_records"] if r["ticker"] == ticker], key=lambda x: x["date"])
        for r in target_records:
            if rem <= 0: break
            take = min(r["shares"], rem)
            db["realized_records"].append({
                "sell_date": str(sell_date), "ticker": ticker, 
                "shares": take, "buy_price": r["price"], "sell_price": sell_price
            })
            r["shares"] -= take
            rem -= take
        db["buy_records"] = [r for r in db["buy_records"] if r["shares"] > 0]
        save_data(db)
        st.success(f"已成功賣出 {sell_shares} 股！")
        time.sleep(1)
        st.rerun()

# --- 側邊欄 ---
with st.sidebar:
    st.header("⚙️ 設定與操作區")
    with st.expander("全域設定", expanded=False):
        new_disc = st.number_input("手續費折數", value=float(db["fee_discount"]), step=0.1)
        new_pledge = st.number_input("質押金額", value=float(db["pledge_amount"]), step=10000.0)
        if st.button("更新設定", use_container_width=True):
            db["fee_discount"] = new_disc
            db["pledge_amount"] = new_pledge
            save_data(db)
            st.success("設定已更新！")
            st.rerun()

    with st.expander("➕ 新增股票", expanded=False):
        in_date = st.date_input("買進日期")
        in_ticker = st.text_input("股票代號").upper()
        in_shares = st.number_input("買進股數", min_value=1, step=1000)
        in_price = st.number_input("買進單價", min_value=0.01, step=1.0)
        if st.button("確認新增", type="primary", use_container_width=True):
            if in_ticker:
                next_id = max([r.get("id", 0) for r in db["buy_records"]] + [0]) + 1
                db["buy_records"].append({
                    "id": next_id, "date": str(in_date), "ticker": in_ticker, 
                    "shares": in_shares, "price": in_price
                })
                save_data(db)
                st.success(f"已新增 {in_ticker}！")
                st.rerun()

# --- 主畫面區塊 ---
st.markdown("### 📊 資產總覽看板")

agg = {}
for r in db["buy_records"]:
    t = r["ticker"]
    if t not in agg: agg[t] = {"shares": 0, "cost_basis": 0}
    agg[t]["shares"] += r["shares"]
    agg[t]["cost_basis"] += r["shares"] * r["price"]

tot_exp, tot_mv, tot_unrealized = 0, 0, 0
v0050, vLev = 0, 0
display_data = []

for t, d in agg.items():
    shares = d["shares"]
    if shares == 0: continue
    avg_cost = d["cost_basis"] / shares
    curr_p, name = fetch_price(t)
    
    mv = shares * curr_p
    tot_mv += mv
    
    if t.endswith("L"):
        tot_exp += (mv * 2)
        vLev += mv
    else:
        tot_exp += mv
        if t == "0050": v0050 += mv
        
    cost = calc_cost_profit(t, shares, avg_cost)
    tax_rate = 0.001 if t.startswith("00") else 0.003
    sell_fee = mv * 0.001425 * (db["fee_discount"] / 10.0)
    net_v = mv - sell_fee - (mv * tax_rate)
    un_profit = round(net_v - cost)
    tot_unrealized += un_profit
    ret_rate = (un_profit / cost) * 100 if cost > 0 else 0
    
    color = "red" if un_profit > 0 else "green" if un_profit < 0 else "black"
    
    display_data.append({
        "ticker": t, "name": name, "shares": shares, "avg_cost": avg_cost, 
        "curr_p": curr_p, "mv": mv, "un_profit": un_profit, "ret_rate": ret_rate, "color": color
    })

tot_realized = sum(calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"]) for r in db["realized_records"])

net_asset = tot_mv - db["pledge_amount"]
if net_asset > 0: lev_str = f"{tot_exp / net_asset:.2f}x"
elif net_asset <= 0 and tot_exp > 0: lev_str = "∞"
else: lev_str = "0.0x"

m_ratio = (tot_mv / db["pledge_amount"] * 100) if db["pledge_amount"] > 0 else 0
tot_profit = tot_unrealized + tot_realized

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("0050 現值", f"${v0050:,.0f}")
col2.metric("正2 現值", f"${vLev:,.0f}")
col3.metric("總曝險", f"${tot_exp:,.0f}")
col4.metric("質押金額", f"${db['pledge_amount']:,.0f}")
col5.metric("淨資產", f"${net_asset:,.0f}")

col6, col7, col8, col9, col10 = st.columns(5)
col6.metric("槓桿倍數", lev_str)
col7.metric("質押維持率", f"{m_ratio:.1f}%")
col8.metric("未實現獲利", f"${tot_unrealized:,.0f}")
col9.metric("已實現獲利", f"${tot_realized:,.0f}")
col10.metric("總獲利", f"${tot_profit:,.0f}")

st.divider()

tab1, tab2 = st.tabs(["📉 未實現損益", "💰 已實現損益"])

with tab1:
    if display_data:
        hc1, hc2, hc3, hc4, hc5, hc6, hc7, hc8, hc9 = st.columns([1, 1.5, 1, 1, 1, 1.2, 1.2, 1, 1.5])
        hc1.markdown("**代號**")
        hc2.markdown("**名稱**")
        hc3.markdown("**總股數**")
        hc4.markdown("**均價**")
        hc5.markdown("**現價**")
        hc6.markdown("**市值**")
        hc7.markdown("**未實現**")
        hc8.markdown("**報酬率**")
        hc9.markdown("**操作 (明細/賣出)**")
        st.markdown("<hr style='margin-top: 5px; margin-bottom: 5px;'>", unsafe_allow_html=True)
        
        for item in display_data:
            c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns([1, 1.5, 1, 1, 1, 1.2, 1.2, 1, 1.5])
            color = item['color']
            c1.write(item["ticker"])
            c2.write(item["name"])
            c3.write(f"{item['shares']:,}")
            c4.write(f"{item['avg_cost']:.2f}")
            c5.write(f"{item['curr_p']:.2f}")
            c6.write(f"{round(item['mv']):,}")
            c7.markdown(f"<span style='color:{color}; font-weight:bold;'>{item['un_profit']:,}</span>", unsafe_allow_html=True)
            c8.markdown(f"<span style='color:{color}; font-weight:bold;'>{item['ret_rate']:.2f}%</span>", unsafe_allow_html=True)
            
            btn_col1, btn_col2 = c9.columns(2)
            if btn_col1.button("🔍", key=f"detail_{item['ticker']}", help="查看買進明細"):
                show_details_dialog(item['ticker'], item['name'])
            if btn_col2.button("🛒", key=f"sell_{item['ticker']}", help="賣出股票"):
                show_sell_dialog(item['ticker'], item['name'])
            st.markdown("<hr style='margin-top: 0px; margin-bottom: 5px; border-top: 1px dashed #bbb;'>", unsafe_allow_html=True)
    else:
        st.info("目前沒有未實現的庫存喔！快去左側新增吧。")

with tab2:
    if db["realized_records"]:
        real_list = []
        for r in sorted(db["realized_records"], key=lambda x: x["sell_date"], reverse=True):
            p = calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"])
            _, name = fetch_price(r["ticker"])
            real_list.append({
                "賣出日期": r["sell_date"], "股票代號": r["ticker"], "股票名稱": name,
                "交易股數": f"{r['shares']:,}", "買進價格": f"{r['buy_price']:.2f}",
                "賣出價格": f"{r['sell_price']:.2f}", "已實現損益": f"{p:,}"
            })
        st.dataframe(pd.DataFrame(real_list), use_container_width=True, hide_index=True)
    else:
        st.info("目前還沒有賣出紀錄。")

# --- 底部標語 (已移至最下方、斜體放大加粗) ---
st.write("") # 空行留白
st.markdown("<h2 style='text-align: center; color: #003366; font-style: italic; font-weight: bold;'>躺在指數的道路上耍廢 🛋️</h2>", unsafe_allow_html=True)
