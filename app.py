import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 環境變數設定
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
genai.configure(api_key=GEMINI_KEY)

# --- 2. 預先初始化模型 (解決 404 關鍵) ---
# 使用最保險的模型名稱，並在啟動時就建立實例
MODEL_NAME = 'gemini-1.5-flash'
try:
    # 建立一個全域使用的模型實例
    base_model = genai.GenerativeModel(model_name=MODEL_NAME)
    print(f"Successfully initialized {MODEL_NAME}")
except Exception as e:
    print(f"Init Error: {e}")

SYSTEM_PROMPT = "你是 io-bot。專業領域：NVR 硬體、RAID、Nx Witness 與 EZ Pro。"
chat_sessions = {}

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
        # 如果用戶沒有對話紀錄，建立新的 Chat Session
        if user_id not in chat_sessions:
            # 直接使用已經初始化好的 base_model
            chat_sessions[user_id] = base_model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        
        # 記憶管理：保留最後 10 輪 (20 條訊息)
        if len(chat.history) > 20:
            chat.history = chat.history[-20:]
            
        # 發送訊息 (手動注入人設)
        response = chat.send_message(f"{SYSTEM_PROMPT}\n\n用戶問：{event.message.text}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        
    except Exception as e:
        print(f"Chat Error: {e}")
        # 若發生錯誤 (如 Quota Exceeded)，清除該用戶記憶並通知
        if "429" in str(e):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="抱歉，目前提問人數較多，請稍等一分鐘後再試。"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="系統連線異常，請稍後。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
