import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 讀取環境變數 (請確認 Render 後台 GEMINI_API_KEY 已更新)
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 配置 Gemini (穩定版配置，避開 404 測試路徑)
genai.configure(api_key=GEMINI_KEY)

# 直接指定正式版模型名稱，確保付費權限生效
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction=(
        "你是 io-bot。專業領域：NVR 硬體故障排除、RAID 陣列管理、"
        "Nx Witness 與 EZ Pro 監控軟體。請提供簡潔專業的建議。"
    )
)

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
    text = event.message.text.strip()

    # 清除記憶指令
    if text == "重設":
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="記憶已重置。"))
        return

    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    try:
        # 發送訊息並取得回覆
        response = chat_sessions[user_id].send_message(text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"API Error: {e}")
        # 發生錯誤時清除 Session 以便下次重試
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 目前連線中，請稍候幾秒再試一次。"))

if __name__ == "__main__":
    # 確保埠號正確對接 Render 環境
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
