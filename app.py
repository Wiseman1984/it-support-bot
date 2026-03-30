import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 設定環境變數
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
genai.configure(api_key=GEMINI_KEY)

# --- 2. 系統人設與自動語言邏輯 ---
SYSTEM_PROMPT = """你是一位資深 IT 工程師，專精於伺服器、硬體故障與網路架構。
請根據用戶輸入問題的語言進行回覆（例如：用戶用繁體中文提問，你就用繁體中文回覆；用戶用英文提問，你就用英文回覆）。
語氣要專業且簡潔，針對文字或圖片給予精確的診斷建議。"""

# --- 3. 動態尋找可用模型 ---
def get_available_model():
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'gemini-1.5-flash' in m.name:
                    return m.name
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        return available_models[0] if available_models else 'models/gemini-1.5-flash'
    except:
        return 'models/gemini-1.5-flash'

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
    try:
        model = genai.GenerativeModel(SELECTED_MODEL)
        # 同時傳送系統指令與用戶文字
        response = model.generate_content([SYSTEM_PROMPT, event.message.text])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"錯誤：{str(e)[:100]}"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        
        model = genai.GenerativeModel(SELECTED_MODEL)
        response = model.generate_content([
            SYSTEM_PROMPT,
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api
