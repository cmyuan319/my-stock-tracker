import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
import time

# --- 頁面基本設定 ---
st.set_page_config(page_title="個人資產紀錄網", layout="wide", page_icon="📈")

# ==========================================
# 🚀 雲端資料庫 Supabase 初始化
# ==========================================
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# ==========================================
# 🔐 Google 登入防護網
# ==========================================
def login_ui():
    if "user_email" in st.session_state:
        return True

    if "code" in st.query_params:
        try:
            code = st.query_params["code"]
            res = supabase.auth.exchange_code_for_session({"auth_code": code})
            st.session_state["user_email"] = res.user.email
            st.query_params.clear()
            st.rerun()
            return True
        except Exception as e:
            st.error("登入失敗或授權碼已過期，請重新嘗試。")
            st.query_params.clear()

    st.markdown("<h1 style='text-align: center; color: #003366; margin-top: 50px;'>🛋️ 個人資產紀錄網</h1>", unsafe_allow_html=True)
    st.write("")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.info("💡 這是一個專屬的私人資產管理系統，請使用 Google 帳號登入，系統會自動載入您個人的專屬資料庫。")
        try:
            res = supabase.auth.sign_in_with_oauth({
                "provider": "google",
                "options": {
                    "redirect_to": "https://reid-stock.streamlit.app/"
                }
            })
            st.link_button("🚀 用 Google 帳號安全登入", res.url, type="primary", use_container_width=True)
        except Exception as e:
            st.error(f"無法產生登入連結: {e}")
    return False

if not login_ui():
    st.stop()

# ==========================================
# 🗄️ 專屬資料庫讀寫邏輯
# ==========================================
user_email = st.session_state["user_email"]

def load_data():
    try:
        response = supabase.table("user_data").select("*").eq("email", user_email).execute()
        if len(response.data) == 0:
            default_db = {
                "fee_discount": 6.0, "pledge_amount": 0.0, "account_balance": 0.0, 
                "credit_loan": 0.0, "buy_records": [], "realized_records": [], "history": {}
            }
            supabase.table("user_data").insert({"email": user_email, "data": default_db}).execute()
            return default_db
        else:
            return response.data[0]["data"]
    except Exception as e:
        st.error(f"資料庫連線異常: {e}")
        return {}

def save_data(data):
    try:
        supabase.table("user_data").update({"data": data}).eq("email", user_email).execute()
    except Exception as e:
        st.error(f"存檔失敗: {e}")

if "db" not in st.session_state:
    st.session_state.db = load_data()

db = st.session_state.db

# --- 核心計算與雙引擎爬蟲 ---
@st.cache_data(ttl=60)
def fetch_price(ticker):
    price = 0.0
    name = ticker
    try:
        url_g = f"https://www.google.com/finance/quote/{ticker}:TPE?hl=zh-TW"
        resp_g = requests.get(url_g, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup_g = BeautifulSoup(resp_g.text, 'html.parser')
        p_div = soup_g.find('div', class_='YMlKec fxKbKc')
        if p_div: 
            price = float(p_div.text.replace('$', '').replace(',', ''))
    except: pass
        
    try:
        url_y = f"https://tw.stock.yahoo.com/quote/{ticker}"
        resp_y = requests.get(url_y, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup_y = BeautifulSoup(resp_y.text, 'html.parser')
        title_tag = soup_y.find('title')
        if title_tag:
            extracted_name = title_tag.text.split('(')[0].strip()
            if "Yahoo" not in extracted_name:
                name = extracted_name
    except: pass
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
@st.dialog("⚙️ 全域設定")
def show_settings_dialog():
    new_disc = st.number_input("手續費折數", value=float(db.get("fee_discount", 6.0)), step=0.1)
    if st.button("儲存設定", type="primary", use_container_width=True):
        db["fee_discount"] = new_disc
        save_data(db)
        st.success("設定已更新！")
        time.sleep(1)
        st.rerun()

@st.dialog("➕ 新增股票")
def show_add_stock_dialog():
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
            time.sleep(1)
            st.rerun()

@st.dialog("🔍 逐筆買進明細與管理")
def show_details_dialog(ticker, name):
    st.markdown(f"### {ticker} {name}")
    records = sorted([r for r in db["buy_records"] if r["ticker"] == ticker], key=lambda x: x["date"], reverse=True)
    if not records:
        st.warning("目前無庫存紀錄。")
        return
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    c1.write("**日期**")
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

@st.dialog("📥 匯入舊版資料")
def show_import_dialog():
    st.info("請到您原本的 Google 試算表，複製「A1 儲存格」裡密密麻麻的文字，貼在下方並按下匯入即可。")
    old_data_str = st.text_area("貼上舊資料", height=150)
    if st.button("確認匯入", type="primary", use_container_width=True):
        if old_data_str:
            try:
                parsed_data = json.loads(old_data_str)
                # 確保新欄位都在
                for k in ["account_balance", "credit_loan", "pledge_amount"]:
                    if k not in parsed_data: parsed_data[k] = 0.0
                if "history" not in parsed_data: parsed_data["history"] = {}
                
                # 覆寫並存檔至 Supabase
                st.session_state.db = parsed_data
                save_data(parsed_data)
                st.success("🎉 舊資料無痛轉移成功！")
                time.sleep(1)
                st.rerun()
            except json.JSONDecodeError:
                st.error("格式錯誤！請確認您有複製到完整的 A1 儲存格內容（開頭是 { ，結尾是 } ）。")
            except Exception as e:
                st.error(f"發生未知的錯誤: {e}")

# --- 頂部操作列 (移除 Email，加入匯入按鈕) ---
col_space, col_add, col_set, col_in, col_out = st.columns([6, 1, 1, 1, 1])
with col_add:
    if st.button("➕", help="新增股票", use_container_width=True): show_add_stock_dialog()
with col_set:
    if st.button("⚙️", help="設定", use_container_width=True): show_settings_dialog()
with col_in:
    if st.button("📥", help="匯入舊資料", use_container_width=True): show_import_dialog()
with col_out:
    if st.button("🚪", help="登出", use_container_width=True):
        supabase.auth.sign_out()
        st.session_state.clear()
        st.rerun()

# --- 核心數據計算 ---
agg = {}
for r in db["buy_records"]:
    t = r["ticker"]
    if t not in agg: agg[t] = {"shares": 0, "cost_basis": 0}
    agg[t]["shares"] += r["shares"]
    agg[t]["cost_basis"] += r["shares"] * r["price"]

tot_exp, tot_mv, tot_unrealized = 0, 0, 0
display_data = []

for t, d in agg.items():
    shares = d["shares"]
    if shares == 0: continue
    avg_cost = d["cost_basis"] / shares
    curr_p, name = fetch_price(t)
    
    mv = shares * curr_p
    tot_mv += mv
    if t.endswith("L"): tot_exp += (mv * 2)
    else: tot_exp += mv
        
    cost = calc_cost_profit(t, shares, avg_cost)
    tax_rate = 0.001 if t.startswith("00") else 0.003
    sell_fee = mv * 0.001425 * (db["fee_discount"] / 10.0)
    net_v = mv - sell_fee - (mv * tax_rate)
    un_profit = round(net_v - cost)
    tot_unrealized += un_profit
    ret_rate = (un_profit / cost) * 100 if cost > 0 else 0
    
    display_data.append({
        "ticker": t, "name": name, "shares": shares, "avg_cost": avg_cost, 
        "curr_p": curr_p, "mv": mv, "un_profit": un_profit, "ret_rate": ret_rate
    })

tot_realized = sum(calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"]) for r in db["realized_records"])
tot_profit = tot_unrealized + tot_realized

# 資金數據與公式
acc_bal = float(db.get("account_balance", 0.0))
pld_amt = float(db.get("pledge_amount", 0.0))
crd_loan = float(db.get("credit_loan", 0.0))

total_assets = acc_bal + tot_mv - pld_amt - crd_loan
if total_assets > 0: lev_str = f"{tot_exp / total_assets:.2f}x"
elif total_assets <= 0 and tot_exp > 0: lev_str = "∞"
else: lev_str = "0.0x"
m_ratio = (tot_mv / pld_amt * 100) if pld_amt > 0 else 0

# --- 🚀 每日 14:00 後自動記錄邏輯 ---
tz_tw = timezone(timedelta(hours=8))
now_tw = datetime.now(tz_tw)
today_str = now_tw.strftime('%Y-%m-%d')

for k, v in db["history"].items():
    if isinstance(v, (int, float)): db["history"][k] = {"profit": v, "assets": total_assets}

if now_tw.hour >= 14:
    current_history = db["history"].get(today_str, {})
    if current_history.get("profit") != tot_profit or current_history.get("assets") != total_assets:
        db["history"][today_str] = {"profit": tot_profit, "assets": total_assets}
        save_data(db)

# --- 主畫面：極簡大看板 ---
st.markdown(f"#### 📅 {now_tw.strftime('%Y/%m/%d')}")
m1, m2 = st.columns(2)
m1.metric("總資產", f"${total_assets:,.0f}")
m2.metric("總獲利", f"${tot_profit:,.0f}")

st.divider()

# --- 五大分頁 ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📉 未實現", "💰 已實現", "📈 獲利走勢", "📊 資產走勢", "⚖️ 資金控管"])

with tab1:
    if display_data:
        for item in display_data:
            card_title = f"{item['ticker']} {item['name']} ｜ 報酬率: {item['ret_rate']:.2f}%"
            with st.expander(card_title):
                c1, c2, c3 = st.columns(3)
                c1.metric("總股數", f"{item['shares']:,}")
                c2.metric("均價", f"${item['avg_cost']:.2f}")
                c3.metric("現價", f"${item['curr_p']:.2f}")
                
                c4, c5, c6 = st.columns(3)
                c4.metric("目前市值", f"${round(item['mv']):,}")
                c5.metric("未實現損益", f"${item['un_profit']:,}")
                c6.metric("報酬率", f"{item['ret_rate']:.2f}%")
                
                st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
                btn1, btn2 = st.columns(2)
                if btn1.button("🔍 明細", key=f"d_{item['ticker']}", use_container_width=True): show_details_dialog(item['ticker'], item['name'])
                if btn2.button("🛒 賣出", key=f"s_{item['ticker']}", use_container_width=True): show_sell_dialog(item['ticker'], item['name'])
    else:
        st.info("目前沒有未實現的庫存喔！快點擊上方 ➕ 新增吧。")

with tab2:
    if db["realized_records"]:
        for r in sorted(db["realized_records"], key=lambda x: x["sell_date"], reverse=True):
            p = calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"])
            _, name = fetch_price(r["ticker"])
            card_title = f"{r['sell_date']} ｜ {r['ticker']} {name} ｜ 損益: ${p:,}"
            with st.expander(card_title):
                c1, c2, c3 = st.columns(3)
                c1.metric("交易股數", f"{r['shares']:,}")
                c2.metric("買進價格", f"${r['buy_price']:.2f}")
                c3.metric("賣出價格", f"${r['sell_price']:.2f}")
    else:
        st.info("目前還沒有賣出紀錄。")

with tab3:
    st.markdown("### 📈 每日總獲利走勢")
    if db["history"]:
        df_profit = pd.DataFrame([{"日期": k, "總獲利": v["profit"]} for k, v in db["history"].items()])
        st.line_chart(df_profit.set_index("日期"))
    else:
        st.info("系統會從今天 14:00 開始自動幫你記錄！")

with tab4:
    st.markdown("### 📊 每日總資產走勢")
    if db["history"]:
        df_assets = pd.DataFrame([{"日期": k, "總資產": v["assets"]} for k, v in db["history"].items()])
        st.line_chart(df_assets.set_index("日期"))
    else:
        st.info("系統會從今天 14:00 開始自動幫你記錄！")

with tab5:
    st.markdown("#### 🛡️ 風險與獲利指標")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("總曝險", f"${tot_exp:,.0f}")
    rc2.metric("槓桿倍數", lev_str)
    rc3.metric("質押維持率", f"{m_ratio:.1f}%")
    
    st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
    
    st.markdown("#### 💵 資金編輯區")
    ec1, ec2, ec3 = st.columns(3)
    new_bal = ec1.number_input("帳戶餘額", value=int(acc_bal), step=10000)
    new_pld = ec2.number_input("質押金額", value=int(pld_amt), step=10000)
    new_crd = ec3.number_input("信貸金額", value=int(crd_loan), step=10000)
    
    if st.button("💾 更新資金數據", type="primary"):
        db["account_balance"] = float(new_bal)
        db["pledge_amount"] = float(new_pld)
        db["credit_loan"] = float(new_crd)
        save_data(db)
        st.success("資金數據已更新！")
        time.sleep(1)
        st.rerun()

st.write("") 
st.markdown("<h1 style='text-align: center; color: #003366; font-style: italic; font-weight: bold; font-size: 36px;'>躺在指數的道路上耍廢 🛋️</h1>", unsafe_allow_html=True)
