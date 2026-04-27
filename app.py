import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 取得環境變數 (請確認 Render 後台設置正確)
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 配置 Gemini (強制使用正式穩定版 API，避開 v1beta)
genai.configure(api_key=GEMINI_API_KEY)

# 初始化模型：明確指定型號，不使用帶有 beta 或 models/ 的前綴
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction=(
        "你是 io-bot。專業領域：NVR 硬體故障排除、RAID 管理、"
        "Nx Witness 與 EZ Pro 監控軟體設定。請簡潔專業回覆。"
    )
)

# 儲存對話 Session
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

    # 提供重設功能
    if user_input == "重設":
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="[系統] 對話記憶已清除。"))
        return

    # 取得或初始化 Session
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    try:
        # 直接發送訊息至穩定版介面
        response = chat_sessions[user_id].send_message(user_input)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"API Error Detected: {e}")
        # 若發生錯誤，清除該 Session 以利下一次傳訊時重新連線
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="io-bot 權限同步中，請過 10 秒後再傳一次試試！")
        )

if __name__ == "__main__":
    # Render 自動分配 PORT
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
