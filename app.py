import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 設定環境變數 (請確認 Render Dashboard 已填入這三個 KEY)
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
genai.configure(api_key=GEMINI_KEY)

# 2. 設定系統角色
SYSTEM_PROMPT = "你是一位資深 IT 工程師，專精於伺服器、硬體故障與網路架構。請針對用戶提供的文字或圖片，給予專業且精確的診斷建議。"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 3. 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        # 使用 models/ 前綴與最新標籤，解決 404 找不到模型的問題
        model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
        response = model.generate_content([SYSTEM_PROMPT, event.message.text])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        # 將具體錯誤印在 Render Logs 中，方便除錯
        print(f"Gemini Text Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="抱歉，我現在無法處理文字請求，請檢查 API 設定。"))

# 4. 處理圖片訊息 (診斷故障畫面)
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        # 取得圖片內容
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
        
        # 同樣使用最新模型路徑
        model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
        response = model.generate_content([
            SYSTEM_PROMPT,
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Gemini Image Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析失敗，請確認圖片清晰度或 API 額度。"))

# 5. 啟動服務
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
