import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 取得環境變數 (請確保 Render 後台已更新為新 API Key)
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 配置 Gemini (強制使用穩定版配置)
genai.configure(api_key=GEMINI_API_KEY)

# 定義專業人設與模型
# 這裡直接指定 'gemini-1.5-flash'，避開會噴 404 的路徑
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction=(
        "你是 io-bot。你的專業領域是：\n"
        "1. NVR 硬體故障排除（如：主機板、SATA 連接線、電源供應器）。\n"
        "2. RAID 陣列管理與資料復原建議。\n"
        "3. Nx Witness 與 EZ Pro 監控軟體設定與 LDAP 登入問題。\n"
        "請用專業、精確且簡潔的方式回答用戶問題。"
    )
)

# 儲存對話紀錄 (Session)
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

    # 提供手動重設對話功能
    if user_input == "重設":
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="[系統通知] 對話記憶已清除。"))
        return

    # 取得或初始化對話
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        # 發送訊息至 Gemini
        response = chat.send_message(user_input)
        
        # 限制記憶長度，避免過長導致 Token 浪費 (保留最近 10 輪)
        if len(chat.history) > 20:
            chat.history = chat.history[-20:]
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

    except Exception as e:
        print(f"API 錯誤詳情: {e}")
        # 若發生錯誤 (例如 Key 權限尚未同步)，嘗試清除該 Session
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="io-bot 正在對接付費權限中，請稍候 1 分鐘後再傳一次訊息試試！")
        )

if __name__ == "__main__":
    # Render 會自動配置 PORT 環境變數
    port = int(os.environ.get('PORT', 5000))
    app.run(host='
