import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 從環境變數取得金鑰
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
genai.configure(api_key=GEMINI_KEY)

# --- 2. 核心人設：io-bot (NVR / RAID / Nx / EZ Pro) ---
SYSTEM_PROMPT = """你是 io-bot。
你的專業領域包含：
- NVR 伺服器硬體故障診斷與 RAID 磁碟陣列問題。
- 監控管理軟體：精通 Nx Witness (Network Optix) 與 EZ Pro 的設定與排錯。
- 網路監控架構、IP 攝影機連接與錄影儲存優化。

指令要求：
1. 根據用戶語言（中/英）自動切換回覆，保持專業且簡潔。
2. 當用戶詢問身分時，請以 io-bot 自稱並簡述上述專長。"""

# --- 3. 對話紀錄暫存 (Session Management) ---
chat_sessions = {}

def get_available_model():
    try:
        for m in genai.list_models():
            if 'gemini-1.5-flash' in m.name: return m.name
        return 'models/gemini-1.5-flash'
    except: return 'models/gemini-1.5-flash'

SELECTED_MODEL = get_available_model()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    try:
        # 檢查該用戶是否有現有的對話 Session
        if user_id not in chat_sessions:
            model = genai.GenerativeModel(
                model_name=SELECTED_MODEL,
                system_instruction=SYSTEM_PROMPT
            )
            chat_sessions[user_id] = model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        response = chat.send_message(event.message.text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Chat Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 暫時無法連線，請稍後再試。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    try:
        # 獲取圖片內容
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        
        # 圖片分析使用單次生成模式
        model = genai.GenerativeModel(SELECTED_MODEL)
        response = model.generate_content([
            SYSTEM_PROMPT,
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        
        # 將圖片分析結果存入對話紀錄，確保連續性
        if user_id in chat_sessions:
            chat_sessions[user_id].history.append({"role": "user", "parts": ["（傳送圖片進行診斷）"]})
            chat_sessions[user_id].history.append({"role": "model", "parts": [response.text]})

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Image Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析失敗，請重試。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
