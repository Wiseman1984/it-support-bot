import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 1. 從環境變數讀取金鑰與設定
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# 2. 設定系統角色（IT 工程師）
SYSTEM_PROMPT = "你是一位資深 IT 工程師，專精於伺服器、硬體故障、RAID 配置與 NVR 監控系統。請針對用戶提供的文字或圖片內容，給出專業、簡潔且具備操作性的診斷建議。"

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
    # 使用完整的模型路徑以避免 404 錯誤
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content([SYSTEM_PROMPT, event.message.text])
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

# 4. 處理圖片訊息 (診斷故障畫面)
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    # 取得圖片數據
    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b""
    for chunk in message_content.iter_content():
        image_data += chunk
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    # 送出圖片與系統指令給 Gemini
    response = model.generate_content([
        SYSTEM_PROMPT,
        {"mime_type": "image/jpeg", "data": image_data}
    ])
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

# 5. 啟動服務 (確保縮排正確)
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
