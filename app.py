import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 取得環境變數
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
# 這裡請務必確認 Render 後台的變數名稱是 GEMINI_API_KEY
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 配置 Gemini (徹底移除 v1beta，使用正式版連線)
genai.configure(api_key=GEMINI_KEY)

# 直接指定 'gemini-1.5-flash'，這是付費專案最穩定的路徑
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction="你是 io-bot。專業領域：NVR、RAID、Nx Witness 與 EZ Pro。請簡潔專業回覆。"
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
    user_input = event.message.text.strip()

    if user_input == "重設":
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="[系統] 記憶已重置。"))
        return

    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    try:
        # 發送訊息
        response = chat_sessions[user_id].send_message(user_input)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        # 如果報錯，在 Log 打印出詳細內容，方便我們診斷
        print(f"!!! API 關鍵錯誤提示 !!!: {str(e)}")
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 權限同步中，請過 10 秒再試一次。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
