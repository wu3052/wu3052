import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots

# --- 1. 頁面配置與美化 CSS ---
st.set_page_config(page_title="台股即時 K 線圖與詳情系統", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main { background-color: #F8F9FA; }
    div.block-container { padding-top: 2rem; padding-bottom: 2rem; }
</style>
""", unsafe_allow_html=True)

# --- 2. 資料獲取函式 (FinMind 180天數據 + yfinance 備份) ---
def get_finmind_data(stock_id, token=""):
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.today() - pd.Timedelta(days=220)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    parameters = {
        "dataset": "TaiwanStockPrice",
        "data_id": str(stock_id),
        "start_date": start_date,
        "end_date": today,
        "token": token
    }
    try:
        response = requests.get(url, params=parameters, timeout=5)
        data = response.json()
        if data.get("status") == 200 and data.get("data"):
            df = pd.DataFrame(data["data"])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.rename(columns={
                'open': 'Open', 'max': 'High', 'min': 'Low', 
                'close': 'Close', 'Trading_Volume': 'Volume'
            })
            return df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    except:
        pass
    
    # 備份：使用 yfinance 抓取 180 天數據
    ticker = f"{stock_id}.TW" if stock_id in twstock.codes and twstock.codes[stock_id].market == "上市" else f"{stock_id}.TWO"
    try:
        df = yf.download(ticker, period="180d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except:
        return None

# 獲取台股清單輔助函式
@st.cache_data(ttl=3600)
def get_taiwan_stock_list():
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            stock_data.append({"code": code, "name": info.name})
    return pd.DataFrame(stock_data)

# --- 3. 繪製美化白色 K 線圖的共用函式 (含 MACD、成交量與實線橘色形態) ---
def plot_beautified_chart(df_k, stock_title, ma_num):
    ma_col_name = f'MA{ma_num}'
    df_k[ma_col_name] = df_k['Close'].rolling(ma_num).mean()
    
    # 計算 MACD
    exp1 = df_k['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df_k['Close'].ewm(span=26, adjust=False).mean()
    df_k['DIF'] = exp1 - exp2
    df_k['MACD_Signal'] = df_k['DIF'].ewm(span=9, adjust=False).mean()
    df_k['MACD_Hist'] = df_k['DIF'] - df_k['MACD_Signal']

    # 建立 3 子圖 (K線 + 成交量 + MACD)
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.6, 0.2, 0.2]
    )

    # 1. 頂部 K 線圖與自訂紫色均線
    fig.add_trace(plotly_go.Candlestick(
        x=df_k.index, open=df_k['Open'], high=df_k['High'],
        low=df_k['Low'], close=df_k['Close'], name="K線",
        increasing_line_color='#EF5350', decreasing_line_color='#26A69A'
    ), row=1, col=1)

    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k[ma_col_name], 
        line=dict(color='#8A2BE2', width=2), 
        name=f"{ma_col_name} (均線)"
    ), row=1, col=1)

    # 形態趨勢線（橘色實線）
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index[-20:], y=df_k['Close'].iloc[-20:] * 0.98,
        line=dict(color='#FF9F43', width=2),  # 實線呈現
        name="形態趨勢線"
    ), row=1, col=1)

    # 2. 中間成交量
    colors = ['#EF5350' if row['Close'] >= row['Open'] else '#26A69A' for _, row in df_k.iterrows()]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['Volume'] / 1000, 
        marker_color=colors, name="成交量(張)"
    ), row=2, col=1)

    # 3. 底部 MACD
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['DIF'], line=dict(color='#2196F3', width=1.5), name="DIF"
    ), row=3, col=1)
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['MACD_Signal'], line=dict(color='#FF9800', width=1.5), name="MACD"
    ), row=3, col=1)
    
    macd_colors = ['#EF5350' if val >= 0 else '#26A69A' for val in df_k['MACD_Hist']]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['MACD_Hist'], marker_color=macd_colors, name="MACD Histogram"
    ), row=3, col=1)

    # 白色簡潔風格背景設定
    fig.update_layout(
        title=dict(text=f"<b>{stock_title}</b> - 180天歷史日線圖", font=dict(size=14, color="#2D3748")),
        template="plotly_white",
        height=600,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


# ==========================================
# 4. 側邊欄設定 (僅保留即時 K 線圖查詢與均線設定)
# ==========================================
with st.sidebar:
    st.title("⚙️ 參數與即時診斷設定")
    st.divider()

    fm_token = st.text_input("FinMind Token (選填)", value="", type="password", help="輸入後數據載入更快速穩定")
    custom_ma_num = st.number_input("均線數值設定", min_value=1, max_value=240, value=20)

    st.divider()
    st.subheader("🩺 個股即時 K 線圖診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    diag_btn = st.button("🔎 產出即時 K 線圖", use_container_width=True, type="primary")


# ==========================================
# 5. 主畫面：個股即時 K 線圖診斷與下拉選擇清單
# ==========================================
st.title("📈 台股即時 K 線圖與技術分析系統")
st.markdown("透過 FinMind API 獲取 180 天歷史日線數據，結合簡潔白色風格、紫色均線、橘色實線形態與 MACD 指標。")
st.divider()

# 若有點擊「個股即時 K 線圖診斷」
if diag_btn and diag_code:
    with st.spinner(f"正在從 FinMind 擷取 {diag_code} 180天歷史數據並繪製即時 K 線圖..."):
        df_diag = get_finmind_data(diag_code, fm_token)
        if df_diag is not None and not df_diag.empty:
            st.success(f"📊 股票代號 {diag_code} 即時 K 線圖診斷報告")
            fig_diag = plot_beautified_chart(df_diag, f"{diag_code} 即時診斷", custom_ma_num)
            st.plotly_chart(fig_diag, use_container_width=True)
        else:
            st.error(f"❌ 查無 {diag_code} 的歷史數據，請確認代號是否正確。")

st.divider()

# 下拉選擇台股清單查看詳細 K 線圖
st.subheader("📋 下拉選擇標的查看詳細美化 K 線圖")
df_all_stocks = get_taiwan_stock_list()

if not df_all_stocks.empty:
    selected_stock = st.selectbox(
        "請選擇欲檢視的股票代號與名稱",
        options=df_all_stocks["code"].tolist(),
        format_func=lambda x: f"{x} - {df_all_stocks[df_all_stocks['code']==x]['name'].values[0]}"
    )

    if selected_stock:
        with st.spinner(f"正在從 FinMind 載入 {selected_stock} 的 180 天歷史日線數據與指標..."):
            df_k = get_finmind_data(selected_stock, fm_token)
            if df_k is not None and not df_k.empty:
                stock_name = df_all_stocks[df_all_stocks['code']==selected_stock]['name'].values[0]
                fig_res = plot_beautified_chart(df_k, f"{selected_stock} {stock_name}", custom_ma_num)
                st.plotly_chart(fig_res, use_container_width=True)
            else:
                st.warning("⚠️ 無法獲取該標的的歷史數據，請檢查網絡或 FinMind 狀態。")
else:
    st.warning("⚠️ 無法載入台股清單代號。")
