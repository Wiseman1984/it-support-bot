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

# 2. 修正點：明確指定 API 版本與初始化
genai.configure(api_key=GEMINI_KEY)

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
        # 改回最基礎的模型名稱，不加 -latest
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(f"你是一位IT工程師：{event.message.text}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Gemini Text Error: {e}")
        # 如果還是失敗，嘗試印出可用模型清單 (除錯用)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"API 報錯：{str(e)[:50]}"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
        
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([
            "你是一位資深 IT 工程師，請診斷圖片問題。",
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Gemini Image Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析失敗。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
