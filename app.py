import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)
import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 從 Render 的環境變數中讀取設定
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
# 確保這裡使用的是 os.getenv 來抓取你設定的 GEMINI_API_KEY
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

SYSTEM_PROMPT = "你是一位資深 IT 工程師，專精於伺服器、硬體故障、RAID 配置與 NVR 監控系統。請針對用戶的提問或上傳的圖片，給出精確、專業且易於操作的修復建議。"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([SYSTEM_PROMPT, event.message.text])
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

# 處理圖片訊息 (例如你上傳的 EFI Shell 截圖)
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    # 取得 LINE 伺服器上的圖片內容
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b""
    for chunk in message_content.iter_content():
        image_data += chunk
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    # 將圖片數據傳送給 Gemini 進行視覺分析
    response = model.generate_content([
        SYSTEM_PROMPT,
        {"mime_type": "image/jpeg", "data": image_data}
    ])
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

if __name__ == "__main__":
    # 確保在 Render 上
# 設定 Line 與 Gemini
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

SYSTEM_PROMPT = "你是一位資深 IT 工程師，專精於 NVR 監控、伺服器、RAID 障礙排除。請針對用戶提供的文字或圖片，給出專業、簡潔的診斷建議。"

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
