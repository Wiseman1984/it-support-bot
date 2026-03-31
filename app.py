import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 環境變數
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
genai.configure(api_key=GEMINI_KEY)

# --- 2. io-bot 核心人設 ---
SYSTEM_PROMPT = """你是 io-bot。專業領域：NVR 硬體故障、RAID 陣列、Nx Witness 與 EZ Pro 軟體。
指令：1. 專業簡潔。2. 回答身分時以此身分自介。"""

# --- 3. 嘗試使用不帶 models/ 前綴的最簡稱 ---
# 根據經驗，有時候 404 是因為 SDK 重複加上了路徑
MODEL_NAME = 'gemini-1.5-flash-latest' 

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
        # 如果對話模式持續 404，這裡改用基礎配置
        if user_id not in chat_sessions:
            model = genai.GenerativeModel(MODEL_NAME)
            chat_sessions[user_id] = model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        
        # 限制記憶長度
        if len(chat.history) > 20:
            chat.history = chat.history[-20:]
            
        # 傳送時手動附上人設，避開 system_instruction 參數（有些版本會報 404）
        full_prompt = f"{SYSTEM_PROMPT}\n\nUser: {event.message.text}"
        response = chat.send_message(full_prompt)
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        
    except Exception as e:
        print(f"Chat Error: {e}")
        # 最後一招：單次生成救援，連 models/ 都不加
        try:
            m = genai.GenerativeModel('gemini-1.5-flash')
            res = m.generate_content(f"{SYSTEM_PROMPT}\n\nUser: {event.message.text}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res.text))
        except Exception as e2:
            print(f"Deep Error: {e2}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 連線異常，請稍後。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([SYSTEM_PROMPT, {"mime_type": "image/jpeg", "data": image_data}])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析目前不可用。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
