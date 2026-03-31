import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 取得環境變數
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
genai.configure(api_key=GEMINI_KEY)

# --- 2. io-bot 核心人設 ---
SYSTEM_PROMPT = """你是 io-bot。專業領域：NVR 硬體故障、RAID 陣列、Nx Witness 與 EZ Pro 軟體。
1. 簡潔專業，自動切換中英。2. 詢問身分時以此身分自介。"""

# --- 3. 自動尋找可用模型 ---
def find_best_model():
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for name in available_models:
            if 'gemini-1.5-flash' in name: return name
        return 'models/gemini-1.5-flash'
    except:
        return 'models/gemini-1.5-flash'

CURRENT_MODEL = find_best_model()

# --- 4. 輕量化對話快取 ---
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
        # 如果是新對話，初始化 Session
        if user_id not in chat_sessions:
            model = genai.GenerativeModel(model_name=CURRENT_MODEL, system_instruction=SYSTEM_PROMPT)
            chat_sessions[user_id] = model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        
        # 【核心：記憶管理】只保留最後 10 輪對話 (20 條訊息)
        # 防止 Token 消耗過快與額度爆掉
        if len(chat.history) > 20:
            chat.history = chat.history[-20:]
            
        response = chat.send_message(event.message.text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        
    except Exception as e:
        print(f"Chat Error: {e}")
        # 若 Quota 爆掉或對話過長出錯，重置該用戶對話並救援
        if "429" in str(e) or "400" in str(e):
            if user_id in chat_sessions: del chat_sessions[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前訊息較多，io-bot 已重置記憶以節省額度，請重新提問。"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 暫時無法連線。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        model = genai.GenerativeModel(model_name=CURRENT_MODEL)
        response = model.generate_content([SYSTEM_PROMPT, {"mime_type": "image/jpeg", "data": image_data}])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析失敗。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
