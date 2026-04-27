import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 初始化 LINE Bot 金鑰
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 初始化 Gemini (付費版權限)
# 既然已付費，直接鎖定穩定版模型，不需再做自動偵測
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# 設定專業人設：針對你的 NVR 與 IT 專業背景
SYSTEM_INSTRUCTION = (
    "你是 io-bot。專業領域：NVR 硬體故障排除 (主機板、SATA、電源)、"
    "RAID 陣列管理、Nx Witness 與 EZ Pro 監控軟體、網路設定。 "
    "回答請保持專業、精確且簡潔。若遇到硬體問題，請優先建議檢查連接線與電源穩定性。"
)

model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction=SYSTEM_INSTRUCTION
)

# 儲存用戶對話 Session
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
    user_input = event.message.text

    # 針對「重設」指令清除記憶
    if user_input.strip() == "重設":
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="對話記憶已清除。"))
        return

    # 取得或建立對話 Session
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        # 發送訊息至 Gemini
        response = chat.send_message(user_input)
        
        # 限制記憶長度 (保留最後 10 輪對話，避免 Token 浪費並維持回應品質)
        if len(chat.history) > 20:
            chat.history = chat.history[-20:]
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

    except Exception as e:
        print(f"API Error: {e}")
        # 救援機制：若 Session 出錯則清除重開
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 暫時連線異常，請再試一次。"))

if __name__ == "__main__":
    # Render 會自動提供 PORT 環境變數
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
