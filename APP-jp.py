import streamlit as st

st.set_page_config(
    page_title="日語學習互動 App",
    page_icon="🇯🇵",
    layout="wide"
)

# 側邊欄導覽
st.sidebar.title("🇯🇵 日語學習小幫手")
page = st.sidebar.radio("選擇功能", ["影片與學習講義", "單字/筆記本"])

# 教育廣播電臺 Channel+ 目標網址
NER_URL = "https://channelplus.ner.gov.tw/episode/86967b1d-d0d6-425d-8d95-7f7f0412602b?courseId="
TINGROOM_URL = "https://jp.tingroom.com/rumen/zary/list_17.html"

if page == "影片與學習講義":
    st.title("📺 日語教學節目與對應講義")
    st.markdown("邊聽/看節目邊對照講義，輕鬆學習日語發音與基礎對話！")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("🎬 教學節目 (教育電臺 Channel+)")
        
        # 嘗試使用 iframe 嵌入教育電臺頁面
        ner_iframe = f"""
        <iframe src="{NER_URL}" width="100%" height="450px" style="border:none; border-radius:10px;"></iframe>
        """
        st.components.v1.html(ner_iframe, height=450)
        
        st.markdown(f"[🔗 點此在 Channel+ 原網站獨立觀看]({NER_URL})", unsafe_allow_html=True)

    with col2:
        st.subheader("📖 課程重點與逐字稿講義")
        
        # 內建整理好的講義內容，確保 100% 穩定顯示
        tingroom_text = """【第1課：日語發音與基礎會話重點】

1. 五十音基礎 (假名介紹)
- 清音、濁音、半濁音
- 撥音、促音、長音的念法

2. 常見基礎招呼語：
- おはようございます (早安)
- こんにちは (你好)
- こんばんは (晚安)
- さようなら (再見)
- ありがとう (謝謝)
- すみません (不好意思 / 對不起)

3. 句型練習：
- ～は…です (…是…)
- 例：私は学生です (我是學生)
"""
        
        st.text_area("講義內容（可自行修改或複製）：", value=tingroom_text, height=400)
        st.markdown(f"[🔗 點此查看原始 tingroom 講義網頁]({TINGROOM_URL})", unsafe_allow_html=True)

elif page == "單字/筆記本":
    st.title("📝 學習筆記與生字本")
    st.markdown("在這裡記錄您在節目中學到的日語單字或文法：")
    
    user_note = st.text_area("輸入您的筆記：", "例：\nこんにちは - 你好\nありがとう - 謝謝")
    if st.button("保存筆記"):
        st.success("筆記已暫存！")
    
    if user_note:
        st.markdown("### 您的筆記預覽：")
        st.info(user_note)
