import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 取得環境變數 (請確認 Render 後台環境變數名稱與此一致)
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 配置 Gemini (強制使用正式穩定版連線)
genai.configure(api_key=GEMINI_KEY)

# 初始化模型：型號名稱確定為 'gemini-1.5-flash'
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction=(
        "你是 io-bot。專業領域：\n"
        "1. NVR 硬體故障排除 (SATA 線、電源、硬碟)。\n"
        "2. RAID 陣列狀態管理。\n"
        "3. Nx Witness 與 EZ Pro 監控軟體相關設定。\n"
        "請保持專業、簡潔且有條理的回答。"
    )
)

# 儲存對話 Session (簡單快取)
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

    # 提供手動重置對話指令
    if user_input == "重設":
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="[系統] 對話紀錄已清除。"))
        return

    # 若無 Session 則初始化
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    try:
        # 發送訊息至 Gemini 伺服器
        response = chat_sessions[user_id].send_message(user_input)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Gemini API Error: {e}")
        # 發生錯誤時重置該用戶 session，以便下次重新對接
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="[io-bot] 正在同步付費權限，請稍候 10 秒後再試一次。")
        )

if __name__ == "__main__":
    # Render 會自動提供 PORT 環境變數
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
