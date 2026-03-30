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

# --- 2. 動態尋找可用模型函數 ---
def get_available_model():
    try:
        # 列出所有模型並尋找 flash
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'gemini-1.5-flash' in m.name:
                    return m.name
        # 如果沒找到 flash，就回傳第一個可用的模型
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        return available_models[0] if available_models else 'models/gemini-pro'
    except Exception as e:
        print(f"List models error: {e}")
        return 'models/gemini-1.5-flash'

# 預先抓取一次模型名稱
SELECTED_MODEL = get_available_model()
print(f"Successfully selected model: {SELECTED_MODEL}")

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
        response = model.generate_content(f"你是一位IT工程師：{event.message.text}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Gemini Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"錯誤：{str(e)[:100]}"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        
        model = genai.GenerativeModel(SELECTED_MODEL)
        response = model.generate_content([
            "你是一位資深 IT 工程師，請診斷圖片問題並給予修復建議。",
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Gemini Image Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析失敗。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
