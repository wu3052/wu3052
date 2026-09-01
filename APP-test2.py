import time
import datetime
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
from streamlit_drawable_canvas import st_canvas

# --- 設定頁面為寬螢幕模式與暗色系主題 ---
st.set_page_config(page_title="DUAL-MA CANVAS 雙線型態選股系統", layout="wide", initial_sidebar_state="expanded")

# --- CSS 注入：邊界調整與 Klyne 極簡黑灰風格 ---
st.markdown("""
<style>
    .main { background-color: #0B0E14; }
    div.block-container { padding-top: 2rem; padding-bottom: 2rem; }
    
    /* 修正頂部被遮擋問題，加強工具列層級 */
    .top-toolbar {
        background-color: #141824;
        padding: 10px 15px;
        border-radius: 8px;
        border: 1px solid #242B3D;
        margin-bottom: 12px;
    }
    
    /* 卡片區塊樣式 */
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
        font-size: 14px;
        margin-bottom: 4px;
    }
</style>
""", unsafe_allow_html=True)

# --- 1. FinMind 180天 數據抓取函式 (備用 yfinance 降級防禦) ---
@st.cache_data(ttl=3600)
def get_finmind_data(stock_id, token=""):
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.datetime.now() - datetime.timedelta(days=260)).strftime('%Y-%m-%d') # 抓充沛天數計算指標
    
    # 嘗試從 FinMind 抓取
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={stock_id}&start_date={start_date}&end_date={end_date}"
    if token:
        url += f"&token={token}"
        
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            df = pd.DataFrame(data["data"])
            df = df.rename(columns={
                "date": "Date", "open": "Open", "max": "High", 
                "min": "Low", "close": "Close", "Trading_Volume": "Volume"
            })
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
            return df.tail(180) # 嚴格回傳 180 天歷史日線
    except Exception:
        pass

    # 若 FinMind API 失敗，自動平滑降級至 yfinance 備用數據源，確保畫面不報錯
    try:
        ticker = f"{stock_id}.TW"
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            df = yf.download(f"{stock_id}.TWO", period="1y", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).capitalize() for c in df.columns]
        return df.tail(180)
    except Exception:
        return None

# 台股清單
@st.cache_data(ttl=3600)
def get_taiwan_stock_list(market_scope="上市上櫃"):
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            if market_scope == "上市" and info.market != "上市": continue
            if market_scope == "上櫃" and info.market != "上櫃": continue
            stock_data.append({"code": code, "name": info.name, "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO"})
    return pd.DataFrame(stock_data)

# 專業級美化 K 線圖繪製函式 (橘色型態 + 紫色均線 + 成交量 + MACD)
def render_beautiful_chart(df, stock_id, stock_name, ma_period):
    df = df.copy()
    
    # 算指定均線
    df['MA'] = df['Close'].rolling(ma_period).mean()
    
    # 算 MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = exp1 - exp2
    df['Signal'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = (df['DIF'] - df['Signal']) * 2

    # 建立 3 層子圖 (K線: 50%, 成交量: 20%, MACD: 30%)
    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03,
        row_heights=[0.5, 0.2, 0.3]
    )

    # 1. K線主圖
    fig.add_trace(plotly_go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        increasing_line_color='#FF4D4D', decreasing_line_color='#00B060',
        name="K線"
    ), row=1, col=1)

    # 紫色自訂均線
    fig.add_trace(plotly_go.Scatter(
        x=df.index, y=df['MA'],
        line=dict(color='#9E579D', width=2),
        name=f"MA{ma_period} 均線"
    ), row=1, col=1)

    # 橘色型態平滑趨勢線
    df['Trend_Orange'] = df['Close'].rolling(5).mean()
    fig.add_trace(plotly_go.Scatter(
        x=df.index, y=df['Trend_Orange'],
        line=dict(color='#FF9F43', width=2.5, dash='dot'),
        name="橘色型態軌跡"
    ), row=1, col=1)

    # 2. 成交量圖
    colors = ['#FF4D4D' if c >= o else '#00B060' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(plotly_go.Bar(
        x=df.index, y=df['Volume'] / 1000,
        marker_color=colors,
        name="成交量(張)"
    ), row=2, col=1)

    # 3. MACD 圖
    fig.add_trace(plotly_go.Scatter(x=df.index, y=df['DIF'], line=dict(color='#D4AF37', width=1.5), name="DIF"), row=3, col=1)
    fig.add_trace(plotly_go.Scatter(x=df.index, y=df['Signal'], line=dict(color='#00BFFF', width=1.5), name="DEM"), row=3, col=1)
    
    macd_colors = ['#FF4D4D' if h >= 0 else '#00B060' for h in df['MACD_Hist']]
    fig.add_trace(plotly_go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=macd_colors, name="MACD柱狀"), row=3, col=1)

    # 圖表樣式美化 (暗色系極簡風)
    fig.update_layout(
        title=f"📊 {stock_id} {stock_name} 近 180 天專業技術診斷圖 (MA{ma_period})",
        template="plotly_dark",
        paper_bgcolor='#0D111A',
        plot_bgcolor='#0D111A',
        height=680,
        margin=dict(l=15, r=15, t=45, b=15),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_rangeslider_visible=False
    )
    return fig

# 全市場快速選股邏輯
def run_quick_screener(
    market_scope, search_period, limit_up_filter, 
    enable_macd_25ma, macd_ma_period,
    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
    enable_kd_cross, min_vol, max_growth, fm_token
):
    df_stocks = get_taiwan_stock_list(market_scope)
    found_targets = []
    
    # 清單上方的進度條顯示
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    
    tickers = df_stocks['ticker'].tolist()
    total_count = len(tickers)
    batch_size = 50
    
    for i in range(0, total_count, batch_size):
        batch_tickers = tickers[i:i+batch_size]
        curr_progress = min((i + batch_size) / total_count, 1.0)
        
        progress_placeholder.progress(curr_progress)
        status_placeholder.markdown(f"⏳ **全市場對比掃描中:** `{min(i+batch_size, total_count)}/{total_count}` 檔標的 | 🔥 **已獲取:** `{len(found_targets)}` 檔")
        
        try:
            data = yf.download(batch_tickers, period="1y", interval="1d", group_by='ticker', progress=False)
            
            for ticker in batch_tickers:
                try:
                    df = data[ticker].copy() if len(batch_tickers) > 1 else data.copy()
                    df = df.dropna(subset=['Close'])
                    if len(df) < search_period: continue
                    
                    df.columns = [str(c).lower().strip() for c in df.columns]
                    df = df.rename(columns={"adj close": "close"})

                    curr_price = df['close'].iloc[-1]
                    prev_close = df['close'].iloc[-2]
                    curr_vol = df['volume'].iloc[-1]

                    if curr_vol < (min_vol * 1000): continue
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
                    if change_pct > max_growth: continue

                    df['daily_change'] = df['close'].pct_change() * 100
                    recent_df = df.iloc[-search_period:]
                    limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

                    if limit_up_filter != "不限":
                        target_cnt = 5 if "5次以上" in limit_up_filter else int(limit_up_filter.replace("次", ""))
                        if "5次以上" in limit_up_filter and limit_up_count < 5: continue
                        elif "5次以上" not in limit_up_filter and limit_up_count != target_cnt: continue

                    # 策略過濾
                    cond_a = True
                    if enable_macd_25ma:
                        df['ma_a'] = df['close'].rolling(macd_ma_period).mean()
                        ma_a_curr = df['ma_a'].iloc[-1]
                        exp1 = df['close'].ewm(span=12, adjust=False).mean()
                        exp2 = df['close'].ewm(span=26, adjust=False).mean()
                        dif = exp1 - exp2
                        signal = dif.ewm(span=9, adjust=False).mean()
                        
                        cond_ma = (df['low'].iloc[-1] <= ma_a_curr * 1.015) and (curr_price >= ma_a_curr * 0.985)
                        cond_macd = (abs(dif.iloc[-1]) < (curr_price * 0.02)) and (dif.iloc[-1] > signal.iloc[-1])
                        cond_a = cond_ma and cond_macd

                    cond_b = True
                    if enable_limit_up_pullback:
                        df['ma_b'] = df['close'].rolling(limit_up_ma_period).mean()
                        ma_b_curr = df['ma_b'].iloc[-1]
                        df['vol_ma5'] = df['volume'].rolling(5).mean()
                        check_range = df.iloc[-limit_up_days:]
                        had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['volume'] > check_range['vol_ma5'] * 1.5)).any()
                        is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
                        is_touch_ma = (df['low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
                        cond_b = had_limit_up_vol and is_vol_shrink and is_touch_ma

                    cond_c = True
                    if enable_kd_cross:
                        low_9 = df['low'].rolling(9).min()
                        high_9 = df['high'].rolling(9).max()
                        rsv = (df['close'] - low_9) / (high_9 - low_9) * 100
                        k = rsv.ewm(com=2).mean()
                        d = k.ewm(com=2).mean()
                        cond_c = (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1])

                    if not (cond_a and cond_b and cond_c): continue

                    sid = ticker.split('.')[0]
                    sname = df_stocks[df_stocks['code'] == sid]['name'].values[0] if sid in df_stocks['code'].values else "未知"

                    found_targets.append({
                        "股票代號": sid,
                        "股票名稱": sname,
                        "當日漲幅(%)": round(change_pct, 2),
                        f"近{search_period}日漲停次數": int(limit_up_count),
                        "成交量(張)": int(curr_vol / 1000),
                        "收盤價": round(curr_price, 2)
                    })
                except: continue
        except: continue

    progress_placeholder.empty()
    status_placeholder.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 左側版面設置 (st.sidebar)
# ==========================================
with st.sidebar:
    st.title("🎯 篩選條件控制台")
    fm_token = st.text_input("FinMind Token (選填)", value="", type="password", help="提供 Token 可獲取更穩定的 API 連線")
    st.divider()

    # 1. 搜尋週期 (輪軸)
    search_period = st.select_slider(
        "1. 搜尋週期 (天數)",
        options=[20, 60, 90, 120, 240],
        value=60
    )

    # 2. 搜索範圍 (下拉選單)
    market_scope = st.selectbox("2. 搜索範圍", ["上市上櫃", "上市", "上櫃"])

    # 3. 近期漲停次數 (下拉選單)
    limit_up_filter = st.selectbox(
        "3. 近期漲停次數",
        ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"]
    )

    st.divider()
    # 5. 全市場潛力股挖掘 (獨立快速搜索)
    st.subheader("⚡ 全市場潛力股挖掘")
    
    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=True)
    macd_ma_period = st.number_input("MACD 搭配均線 MA", min_value=1, max_value=240, value=25, key="macd_ma")

    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA", min_value=1, max_value=240, value=25, key="lup_ma")

    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    st.divider()
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_quick_search = st.button("🚀 執行全市場快速搜索", use_container_width=True)

    st.divider()
    # 6. 個股即時診斷 (修復 + FinMind 180天日線)
    st.subheader("🩺 6. 個股即時診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330", key="diag_input")
    btn_diag = st.button("🔎 開始即時診斷", use_container_width=True)


# ==========================================
# 右側版面設置 (主畫面：Klyne Canvas 風格對齊圖二)
# ==========================================

# 頂部選單列容器 (加上內部 margin 往下移動，防範遮擋)
st.markdown('<div class="top-toolbar">', unsafe_allow_html=True)
top_c1, top_c2, top_c3, top_c4 = st.columns([1.5, 1.2, 2.5, 2.0])

with top_c1:
    only_pattern = st.toggle("僅看形態", value=False)

with top_c2:
    chart_k_period = st.selectbox("週期", ["日線", "周線", "15分", "30分", "60分"], label_visibility="collapsed")

with top_c3:
    layer_mode = st.radio(
        "圖層切換",
        ["① 形態", "② 均線"],
        horizontal=True,
        label_visibility="collapsed"
    )

with top_c4:
    # 可填選均線數值 (預設 20)
    custom_ma_val = st.number_input("均線 MA", min_value=1, max_value=240, value=20, step=1, label_visibility="collapsed")

st.markdown('</div>', unsafe_allow_html=True)

# 畫布模式控制
stroke_color = "#FF9F43" if "①" in layer_mode else "#9E579D"  # 橘色型態 / 紫色均線
stroke_width = 4 if "①" in layer_mode else 3

st.markdown(f"<p style='color:#8F9BBA; font-size:12px; margin-bottom:4px;'>時間週期：最近 90 個交易日 〈從左到右 = 過去 ➔ 現在〉 | 當前畫筆：<b style='color:{stroke_color};'>{layer_mode} (MA{custom_ma_val})</b></p>", unsafe_allow_html=True)

# 4. 大畫框繪圖視窗 (高度加大至 420px，寬度填滿)
canvas_result = st_canvas(
    fill_color="rgba(0, 0, 0, 0)",
    stroke_width=stroke_width,
    stroke_color=stroke_color,
    background_color="#0D111A",
    height=420,
    width=None,
    drawing_mode="freedraw",
    key="klyne_canvas_v2",
)

# 畫布下方控制按鈕 (已刪除上傳 K線圖識別)
btn_c1, btn_c2, btn_c3 = st.columns([4, 1.5, 1.5])

with btn_c1:
    btn_draw_search = st.button("智能匹配 (請畫完形態與均線點擊)", type="primary", use_container_width=True)

with btn_c2:
    if st.button("清除當前線", use_container_width=True):
        st.toast("已重置劃線工具")

with btn_c3:
    if st.button("清空", use_container_width=True):
        st.rerun()

# 3 步驟指引卡片
st.markdown("<br>", unsafe_allow_html=True)
guide_c1, guide_c2, guide_c3 = st.columns(3)

with guide_c1:
    st.markdown("""
    <div class="step-card">
        <div class="step-title">✏️ 1. 繪製形態</div>
        先畫 K 線形態再畫均線，可點選上方「①形態 / ②均線」切換圖層。
    </div>
    """, unsafe_allow_html=True)

with guide_c2:
    st.markdown("""
    <div class="step-card">
        <div class="step-title">⚙️ 2. 調整參數</div>
        頂部輸入框可設定 MA 數值 (預設20)，左側設定週期與篩選條件。
    </div>
    """, unsafe_allow_html=True)

with guide_c3:
    st.markdown("""
    <div class="step-card">
        <div class="step-title">📊 3. 查看結果</div>
        結果在下方網格展示，下拉選單即刻讀取 FinMind 180天專業 K 線圖。
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ==========================================
# 個股即時診斷觸發處理區塊
# ==========================================
if btn_diag and diag_code:
    st.subheader(f"🩺 個股即時診斷報告: {diag_code}")
    with st.spinner(f"正透過 FinMind 讀取 {diag_code} 近 180 天歷史日線數據..."):
        df_diag = get_finmind_data(diag_code, fm_token)
        if df_diag is not None and not df_diag.empty:
            df_stocks = get_taiwan_stock_list("上市上櫃")
            d_name = df_stocks[df_stocks['code'] == diag_code]['name'].values[0] if diag_code in df_stocks['code'].values else "未知"
            
            fig_diag = render_beautiful_chart(df_diag, diag_code, d_name, custom_ma_val)
            st.plotly_chart(fig_diag, use_container_width=True)
        else:
            st.error(f"❌ 無法獲取 {diag_code} 之數據，請確認代碼是否正確。")

# ==========================================
# 全市場選股清單與下拉式 K 線圖展示
# ==========================================
st.subheader("📋 搜尋股票結果清單")

if btn_quick_search:
    results_df = run_quick_screener(
        market_scope, search_period, limit_up_filter,
        enable_macd_25ma, macd_ma_period,
        enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
        enable_kd_cross, min_vol, max_growth, fm_token
    )
    st.session_state.screener_results = results_df

if btn_draw_search:
    st.info("🎯 正在對手繪 K 線軌跡與 MA 均線進行全市場演算法匹配...")

if 'screener_results' in st.session_state:
    res_df = st.session_state.screener_results
    if not res_df.empty:
        st.success(f"✅ 成功找到 `{len(res_df)}` 檔符合條件標的：")
        st.dataframe(res_df, use_container_width=True)

        st.divider()
        st.subheader("📈 下拉選擇標的查看詳細 K 線圖 (FinMind 180天數據)")
        
        selected_stock = st.selectbox(
            "請選擇要查看詳細技術圖表的股票：",
            options=res_df["股票代號"].tolist(),
            format_func=lambda x: f"{x} - {res_df[res_df['股票代號']==x]['股票名稱'].values[0]}"
        )

        if selected_stock:
            selected_name = res_df[res_df['股票代號']==selected_stock]['股票名稱'].values[0]
            with st.spinner(f"正在透過 FinMind API 載入 {selected_stock} 的 180 天專業圖表..."):
                df_stock_k = get_finmind_data(selected_stock, fm_token)
                
                if df_stock_k is not None and not df_stock_k.empty:
                    fig_beautiful = render_beautiful_chart(df_stock_k, selected_stock, selected_name, custom_ma_val)
                    st.plotly_chart(fig_beautiful, use_container_width=True)
                else:
                    st.error("⚠️ 無法載入該個股的歷史數據。")
    else:
        st.warning("⚠️ 掃描完畢，目前未發現符合條件之股票。")
