import os
import base64
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 設定 Line 與 Gemini
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

SYSTEM_PROMPT = "你是一位資深 IT 工程師，專精於 NVR 監控、伺服器、RAID 障礙排除。請針對用戶提供的文字或圖片，給出專業、簡潔的診斷建議。"

@app.route("/callback", method=['POST'])
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
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([SYSTEM_PROMPT, event.message.text])
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b""
    for chunk in message_content.iter_content():
        image_data += chunk
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([
        SYSTEM_PROMPT,
        {"mime_type": "image/jpeg", "data": image_data}
    ])
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

if __name__ == "__main__":
    app.run()
