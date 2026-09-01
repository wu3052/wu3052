import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
from streamlit_drawable_canvas import st_canvas

# --- 設定頁面為寬螢幕模式與樣式調整 ---
st.set_page_config(page_title="Klyne 雙線形態選股系統", layout="wide", initial_sidebar_state="expanded")

# CSS 注入：優化元件間距與解決上方選單遮擋問題
st.markdown("""
<style>
    .main { background-color: #0B0E14; }
    div.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    .step-card {
        background-color: #151924;
        border: 1px solid #242B3D;
        border-radius: 8px;
        padding: 12px;
        color: #A0AEC0;
        font-size: 13px;
    }
    .step-title {
        color: #FFFFFF;
        font-weight: bold;
        font-size: 15px;
        margin-bottom: 6px;
    }
</style>
""", unsafe_allow_html=True)

# 取得 FinMind 180天歷史日線數據
def get_finmind_stock_data(stock_id, token=""):
    try:
        end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
        start_date = (pd.Timestamp.today() - pd.Timedelta(days=220)).strftime('%Y-%m-%d') # 取220天確保有180個交易日
        url = "https://api.finmindtrade.com/api/v4/data"
        parameters = {
            "dataset": "TaiwanStockPrice",
            "data_id": str(stock_id),
            "start_date": start_date,
            "end_date": end_date,
        }
        headers = {}
        if token:
            headers["token"] = token
        
        response = requests.get(url, params=parameters, headers=headers)
        data = response.json()
        
        if data.get("status") == 200 and data.get("data"):
            df = pd.DataFrame(data["data"])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.rename(columns={
                "open": "Open", "max": "High", "min": "Low", 
                "close": "Close", "Trading_Volume": "Volume"
            })
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['Close'])
            return df.tail(180) # 確保精準取最後 180 天
    except Exception as e:
        st.error(f"資料擷取失敗: {e}")
    return None

# 取得台股清單輔助函式
@st.cache_data(ttl=3600)
def get_taiwan_stock_list(market_scope="上市上櫃"):
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            if market_scope == "上市" and info.market != "上市": continue
            if market_scope == "上櫃" and info.market != "上櫃": continue
            stock_data.append({"code": code, "name": info.name})
    return pd.DataFrame(stock_data)

# 掃描邏輯（快速搜索 + 進度條）
def run_quick_screener(
    market_scope, search_period, limit_up_filter, 
    enable_macd_25ma, macd_ma_period,
    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
    enable_kd_cross, min_vol, max_growth, finmind_token
):
    df_stocks = get_taiwan_stock_list(market_scope)
    found_targets = []
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    total_count = len(df_stocks)
    
    for idx, row in df_stocks.iterrows():
        sid = row['code']
        sname = row['name']
        
        current_progress = min((idx + 1) / total_count, 1.0)
        progress_bar.progress(current_progress)
        status_text.markdown(f"🔍 **掃描進度:** `{idx+1}/{total_count}` ({sid}) | 🔥 **符合標的:** `{len(found_targets)}` 檔")
        
        try:
            df = get_finmind_stock_data(sid, finmind_token)
            if df is None or len(df) < search_period: 
                continue
            
            curr_price = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            curr_vol = df['Volume'].iloc[-1]

            # 1. 基本量價過濾 (FinMind Volume 單位通常為股，轉成張需除以1000)
            vol_zhang = curr_vol / 1000
            if vol_zhang < min_vol: continue
            
            change_pct = ((curr_price - prev_close) / prev_close) * 100
            if change_pct > max_growth: continue

            # 2. 計算近 N 日漲停次數 (台股漲幅 >= 9.5%)
            df['daily_change'] = df['Close'].pct_change() * 100
            recent_df = df.iloc[-search_period:]
            limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

            if limit_up_filter != "不限":
                target_cnt = 5 if "5次以上" in limit_up_filter else int(limit_up_filter.replace("次", ""))
                if "5次以上" in limit_up_filter and limit_up_count < 5: continue
                elif "5次以上" not in limit_up_filter and limit_up_count != target_cnt: continue

            # 3. 策略判定
            cond_a = True
            if enable_macd_25ma:
                df['ma_a'] = df['Close'].rolling(macd_ma_period).mean()
                ma_a_curr = df['ma_a'].iloc[-1]
                exp1 = df['Close'].ewm(span=12, adjust=False).mean()
                exp2 = df['Close'].ewm(span=26, adjust=False).mean()
                dif = exp1 - exp2
                signal = dif.ewm(span=9, adjust=False).mean()
                
                cond_ma = (df['Low'].iloc[-1] <= ma_a_curr * 1.015) and (curr_price >= ma_a_curr * 0.985)
                cond_macd = (abs(dif.iloc[-1]) < (curr_price * 0.02)) and (dif.iloc[-1] > signal.iloc[-1])
                cond_a = cond_ma and cond_macd

            cond_b = True
            if enable_limit_up_pullback:
                df['ma_b'] = df['Close'].rolling(limit_up_ma_period).mean()
                ma_b_curr = df['ma_b'].iloc[-1]
                df['vol_ma5'] = df['Volume'].rolling(5).mean()
                
                check_range = df.iloc[-limit_up_days:]
                had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['Volume'] > check_range['vol_ma5'] * 1.5)).any()
                is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
                is_touch_ma = (df['Low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
                
                cond_b = had_limit_up_vol and is_vol_shrink and is_touch_ma

            cond_c = True
            if enable_kd_cross:
                low_9 = df['Low'].rolling(9).min()
                high_9 = df['High'].rolling(9).max()
                rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
                k = rsv.ewm(com=2).mean()
                d = k.ewm(com=2).mean()
                cond_c = (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1])

            if not (cond_a and cond_b and cond_c): continue

            found_targets.append({
                "股票代號": sid,
                "股票名稱": sname,
                "當日漲幅(%)": round(change_pct, 2),
                f"近{search_period}日漲停次數": int(limit_up_count),
                "成交量(張)": int(vol_zhang),
                "收盤價": round(curr_price, 2)
            })
        except: 
            continue

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 左側版面設置 (st.sidebar)
# ==========================================
with st.sidebar:
    st.title("🎯 篩選條件控制台")
    fm_token = st.text_input("FinMind Token (選填)", value="", type="password", help="若頻繁請求可填入 FinMind API Token")
    st.divider()

    search_period = st.select_slider("1. 搜尋週期 (天數)", options=[20, 60, 90, 120, 240], value=60)
    market_scope = st.selectbox("2. 搜索範圍", ["上市上櫃", "上市", "上櫃"])
    limit_up_filter = st.selectbox("3. 近期漲停次數", ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"])

    st.divider()
    st.subheader("⚡ 全市場潛力股挖掘")
    
    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=True)
    macd_ma_period = st.number_input("MACD 搭配均線 MA", min_value=1, max_value=240, value=20)

    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA", min_value=1, max_value=240, value=20, key="lup_ma")

    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    st.divider()
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_quick_search = st.button("🚀 執行全市場快速搜索", use_container_width=True)

    st.divider()
    st.subheader("🩺 個股即時診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    if st.button("🔎 開始診斷", use_container_width=True) and diag_code:
        with st.spinner(f"正在透過 FinMind 診斷 {diag_code}..."):
            df_diag = get_finmind_stock_data(diag_code, fm_token)
            if df_diag is not None and not df_diag.empty:
                last_p = df_diag['Close'].iloc[-1]
                prev_p = df_diag['Close'].iloc[-2]
                chg = ((last_p - prev_p)/prev_p)*100
                st.success(f"📊 {diag_code} 即時診斷完成")
                st.metric("最新收盤價", f"{last_p:.2f}", f"{chg:.2f}%")
            else:
                st.error("無法取得該代號數據，請確認代號正確。")


# ==========================================
# 右側版面設置：美化版大畫布與控制列
# ==========================================

# 調整後的頂部控制列（避免被上方欄位遮擋）
st.markdown("### 🎨 雙線形態繪畫與搜索面板")
top_c1, top_c2, top_c3, top_c4 = st.columns([1.2, 1.2, 1.2, 1.2])

with top_c1:
    only_pattern = st.toggle("僅看形態", value=False)
with top_c2:
    chart_k_period = st.selectbox("週期選單", ["日線", "周線", "15分", "30分", "60分"], label_visibility="collapsed")
with top_c3:
    layer_mode = st.radio("圖層切換", ["① 形態", "② 均線"], horizontal=True, label_visibility="collapsed")
with top_c4:
    user_ma_input = st.number_input("當前均線數值", min_value=1, max_value=240, value=20, step=1, label_visibility="collapsed")

stroke_color = "#FF9F43" if "①" in layer_mode else "#9E579D"
stroke_width = 3 if "①" in layer_mode else 2

st.markdown(f"<p style='color:#A0AEC0; font-size:12px; margin-bottom:4px;'>目前繪製模式：<b style='color:{stroke_color};'>{layer_mode}</b> (均線參數設定: {user_ma_input})</p>", unsafe_allow_html=True)

# 畫框加大 (height = 450)
canvas_result = st_canvas(
    fill_color="rgba(0, 0, 0, 0)",
    stroke_width=stroke_width,
    stroke_color=stroke_color,
    background_color="#0D111A",
    height=450,
    width=None,
    drawing_mode="freedraw",
    key="klyne_large_canvas",
)

# 畫布下方按鈕列 (已移除上傳K線圖識別，按鈕適當配置)
btn_c1, btn_c2, btn_c3 = st.columns([3, 1.5, 1.5])

with btn_c1:
    btn_draw_search = st.button("🎨 請畫完形態與均線 (搜索股票)", type="primary", use_container_width=True)
with btn_c2:
    if st.button("清除當前線", use_container_width=True):
        st.toast("已清除最近一筆繪製")
with btn_c3:
    if st.button("清空", use_container_width=True):
        st.rerun()

st.divider()

# ==========================================
# 搜尋結果清單與簡潔乾淨的 K 線圖
# ==========================================
st.subheader("📋 搜尋股票結果清單")

if btn_quick_search:
    with st.spinner("正在執行全市場快速搜索與進度統計..."):
        results_df = run_quick_screener(
            market_scope, search_period, limit_up_filter,
            enable_macd_25ma, macd_ma_period,
            enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
            enable_kd_cross, min_vol, max_growth, fm_token
        )
        st.session_state.screener_results = results_df

if btn_draw_search:
    st.info("🎯 正在對手繪軌跡進行形狀擬合，比對全市場形態中...")

if 'screener_results' in st.session_state:
    res_df = st.session_state.screener_results
    if not res_df.empty:
        st.success(f"✅ 成功找到 {len(res_df)} 檔符合條件標的：")
        st.dataframe(res_df, use_container_width=True)

        st.subheader("📈 下拉選擇標的查看詳細 K 線圖 (FinMind 180天歷史數據)")
        selected_stock = st.selectbox(
            "選擇股票代號",
            options=res_df["股票代號"].tolist(),
            format_func=lambda x: f"{x} - {res_df[res_df['股票代號']==x]['股票名稱'].values[0]}"
        )

        if selected_stock:
            df_k = get_finmind_stock_data(selected_stock, fm_token)
            if df_k is not None and not df_k.empty:
                # 計算搭配的均線 (使用 user_ma_input 數值)
                ma_col_name = f"MA{user_ma_input}"
                df_k[ma_col_name] = df_k['Close'].rolling(user_ma_input).mean()

                # 計算 MACD (12, 26, 9)
                exp1 = df_k['Close'].ewm(span=12, adjust=False).mean()
                exp2 = df_k['Close'].ewm(span=26, adjust=False).mean()
                df_k['DIF'] = exp1 - exp2
                df_k['MACD_Signal'] = df_k['DIF'].ewm(span=9, adjust=False).mean()
                df_k['MACD_Hist'] = df_k['DIF'] - df_k['MACD_Signal']

                # 建立美化版簡潔 K 線圖 (白色背景、無多餘文字、附成交量與 MACD)
                fig = make_subplots(
                    rows=3, cols=1, shared_xaxes=True, 
                    vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2]
                )

                # 1. K線與紫色均線
                fig.add_trace(plotly_go.Candlestick(
                    x=df_k.index, open=df_k['Open'], high=df_k['High'],
                    low=df_k['Low'], close=df_k['Close'], name="K線",
                    increasing_line_color='#EF5350', decreasing_line_color='#26A69A'
                ), row=1, col=1)

                fig.add_trace(plotly_go.Scatter(
                    x=df_k.index, y=df_k[ma_col_name], 
                    line=dict(color='#9E579D', width=2), 
                    name=f"均線 {ma_col_name}"
                ), row=1, col=1)

                # 2. 成交量圖
                colors = ['#EF5350' if row['Close'] >= row['Open'] else '#26A69A' for index, row in df_k.iterrows()]
                fig.add_trace(plotly_go.Bar(
                    x=df_k.index, y=df_k['Volume'], marker_color=colors, name="成交量"
                ), row=2, col=1)

                # 3. MACD 圖
                fig.add_trace(plotly_go.Scatter(x=df_k.index, y=df_k['DIF'], line=dict(color='#29B6F6', width=1.5), name="DIF"), row=3, col=1)
                fig.add_trace(plotly_go.Scatter(x=df_k.index, y=df_k['MACD_Signal'], line=dict(color='#FFA726', width=1.5), name="MACD"), row=3, col=1)
                
                macd_colors = ['#EF5350' if val >= 0 else '#26A69A' for val in df_k['MACD_Hist']]
                fig.add_trace(plotly_go.Bar(x=df_k.index, y=df_k['MACD_Hist'], marker_color=macd_colors, name="MACD Histogram"), row=3, col=1)

                # 版面極簡與白色背景美化
                fig.update_layout(
                    plot_bgcolor='#FFFFFF',
                    paper_bgcolor='#FFFFFF',
                    font=dict(color='#333333', size=11),
                    height=600,
                    margin=dict(l=30, r=30, t=20, b=20),
                    xaxis_rangeslider_visible=False,
                    showlegend=False
                )
                
                # 座標軸格線與邊框優化
                fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#E0E0E0')
                fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#E0E0E0')

                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("無法從 FinMind 取得該標的歷史數據。")
    else:
        st.warning("⚠️ 掃描完畢，未搜尋到符合所有條件的股票。")
