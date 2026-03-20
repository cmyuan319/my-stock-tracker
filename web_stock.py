import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

# 設定網頁標題與寬度
st.set_page_config(page_title="Reid 的資產監控中心", layout="wide")

# 模擬資料庫 (實務上應連接資料庫或 CSV)
# 這裡預設一些資料，確保圖表能跑
if 'db' not in st.session_state:
    st.session_state.db = {
        "stocks": {
            "00631L": {"qty": 10000, "cost": 150.5, "price": 210.2},
            "2330": {"qty": 1000, "cost": 600, "price": 780}
        },
        "pld_amt": 500000,   # 質押借款金額
        "acc_bal": 200000,   # 銀行存款
        "oth_assets": 50000, # 其他資產
        "futures_equity": 300000, # 期貨權益數
        "futures_exposure": 1200000, # 期貨曝險 (例如口數 * 點數 * 乘數)
        "history": {
            "2026-03-18": {"profit": 1500000, "assets": 5000000},
            "2026-03-19": {"profit": 1550000, "assets": 5100000},
            "2026-03-20": {"profit": 1580000, "assets": 5200000}
        }
    }

db = st.session_state.db

# --- 計算邏輯 ---
# 1. 現貨市值與成本
tot_mv = sum(s['qty'] * s['price'] for s in db['stocks'].values())
tot_cost = sum(s['qty'] * s['cost'] for s in db['stocks'].values())
stock_profit = tot_mv - tot_cost

# 2. 總資產計算
# 總資產 = 銀行存款 + 股票市值 + 其他資產 + 期貨權益 - 質押借款
total_assets = db['acc_bal'] + tot_mv + db['oth_assets'] + db['futures_equity'] - db['pld_amt']

# 3. 曝險與維持率
# 總曝險 = 現貨市值 + 期貨曝險
total_exposure = tot_mv + db['futures_exposure']
# 質押維持率 = (質押股票市值 / 借款金額) * 100
m_ratio = (tot_mv / db['pld_amt'] * 100) if db['pld_amt'] > 0 else 0
# 槓桿倍數 = 總曝險 / 總資產
lev_str = f"{total_exposure / total_assets:.2f}x" if total_assets > 0 else "0.00x"

# --- 側邊欄 ---
st.sidebar.title("🛠️ 資產設定")
db['acc_bal'] = st.sidebar.number_input("銀行存款", value=db['acc_bal'])
db['pld_amt'] = st.sidebar.number_input("質押借款", value=db['pld_amt'])
db['futures_equity'] = st.sidebar.number_input("期貨權益數", value=db['futures_equity'])
db['futures_exposure'] = st.sidebar.number_input("期貨總曝險額", value=db['futures_exposure'])

# --- 主介面 ---
st.title("🚀 Reid 投資戰情室")

# 頂部資訊面板
rc1, rc2, rc3 = st.columns(3)
rc1.metric("槓桿倍數", lev_str)
rc2.metric("質押維持率", f"{m_ratio:.1f}%")
rc3.metric("總曝險額", f"${total_exposure:,.0f}")

# 分頁系統
tab1, tab2, tab3, tab4 = st.tabs(["📊 資產分佈", "📜 持股明細", "📈 獲利走勢", "💰 資產走勢"])

with tab1:
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("### 🍕 資產組成比重")
        pie_data = pd.DataFrame({
            "項目": ["現金", "股票市值", "其他資產", "期貨權益"],
            "金額": [db['acc_bal'], tot_mv, db['oth_assets'], db['futures_equity']]
        })
        fig = px.pie(pie_data, values='金額', names='項目', hole=0.4,
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("### 📋 關鍵數據")
        st.write(f"**總資產：** ${total_assets:,.0f}")
        st.write(f"**股票總市值：** ${tot_mv:,.0f}")
        st.write(f"**目前總獲利：** ${stock_profit:,.0f}")
        if m_ratio < 160:
            st.error("⚠️ 警告：質押維持率過低！")
        elif m_ratio < 180:
            st.warning("⚡ 提醒：請留意維持率狀況。")

with tab2:
    st.markdown("### 📋 持股清單")
    df_stocks = pd.DataFrame.from_dict(db['stocks'], orient='index')
    df_stocks['市值'] = df_stocks['qty'] * df_stocks['price']
    df_stocks['損益'] = (df_stocks['price'] - df_stocks['cost']) * df_stocks['qty']
    st.dataframe(df_stocks.style.format("{:,.1f}"))

with tab3:
    st.markdown("### 📈 每日總獲利變動")
    if db.get("history"):
        df_profit = pd.DataFrame([{"日期": k, "總獲利": v["profit"]} for k, v in db["history"].items()])
        st.line_chart(df_profit.set_index("日期"))
    else:
        st.info("尚無歷史獲利數據。")

with tab4:
    st.markdown("### 💰 總資產淨值走勢")
    if db.get("history"):
        df_assets = pd.DataFrame([{"日期": k, "總資產": v["assets"]} for k, v in db["history"].items()])
        st.line_chart(df_assets.set_index("日期"))
    else:
        st.info("尚無歷史資產數據。")

st.divider()
st.caption(f"最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
