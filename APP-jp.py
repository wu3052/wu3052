import streamlit as st

st.set_page_config(
    page_title="日語學習互動 App",
    page_icon="🇯🇵",
    layout="wide"
)

# 側邊欄導覽
st.sidebar.title("🇯🇵 日語學習小幫手")
page = st.sidebar.radio("選擇功能", ["影片與學習講義", "單字/筆記本"])

if page == "影片與學習講義":
    st.title("📺 日語教學影片與對應講義")
    st.markdown("邊看影片邊對照講義，輕鬆學習日語發音與基礎對話！")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("🎬 教學影片")
        st.info("由於 Bilibili 官方安全限制，建議點擊下方按鈕前往觀看影片：")
        
        # 提供明顯的按鈕與圖片連結
        st.markdown(
            """
            <a href="https://www.bilibili.com/video/BV1Qx411D7oA/" target="_blank">
                <button style="background-color: #00aeec; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold;">
                    🚀 點擊前往 Bilibili 觀看影片
                </button>
            </a>
            """, 
            unsafe_allow_html=True
        )
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.warning("💡 建議：您可以將瀏覽器視窗左右分割，左邊看影片、右邊對照本 App 的講義學習。")

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
        
        st.text_area("講義內容（可自行修改或複製）：", value=tingroom_text, height=350)
        st.markdown("[🔗 點此查看原始 tingroom 講義網頁](https://jp.tingroom.com/rumen/zary/list_17.html)")

elif page == "單字/筆記本":
    st.title("📝 學習筆記與生字本")
    st.markdown("在這裡記錄您在影片中學到的日語單字或文法：")
    
    user_note = st.text_area("輸入您的筆記：", "例：\nこんにちは - 你好\nありがとう - 謝謝")
    if st.button("保存筆記"):
        st.success("筆記已暫存！")
    
    if user_note:
        st.markdown("### 您的筆記預覽：")
        st.info(user_note)
