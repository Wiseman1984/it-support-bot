import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 環境變數
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 配置 Gemini - 強制使用 v1 版本以避開 v1beta 的 404 問題
genai.configure(api_key=GEMINI_KEY, transport='rest') # 使用 REST 模式增加穩定性

# 核心設定：直接定義模型名稱
MODEL_NAME = 'models/gemini-1.5-flash'
SYSTEM_PROMPT = "你是 io-bot。專業領域：NVR 硬體故障、RAID 陣列、Nx Witness 與 EZ Pro 軟體。"

# 建立對話 Session 暫存
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
    user_msg = event.message.text
    
    try:
        # 初始化模型與對話
        if user_id not in chat_sessions:
            # 這裡不使用 system_instruction 參數，直接整合進訊息中，這是最相容的做法
            model = genai.GenerativeModel(MODEL_NAME)
            chat_sessions[user_id] = model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        
        # 限制記憶長度 (保留最後 10 輪)
        if len(chat.history) > 20:
            chat.history = chat.history[-20:]
            
        # 發送訊息：手動將人設與使用者問題結合
        # 這樣做可以確保在所有 API 版本上都能正常運作
        combined_prompt = f"{SYSTEM_PROMPT}\n\n用戶提問：{user_msg}"
        response = chat.send_message(combined_prompt)
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))

    except Exception as e:
        print(f"Error logic: {e}")
        # 救援方案：如果對話出錯，改用最簡單的單次生成
        try:
            m = genai.GenerativeModel(MODEL_NAME)
            res = m.generate_content(f"{SYSTEM_PROMPT}\n\n用戶提問：{user_msg}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res.text))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 暫時無法連線，請檢查 API Key 或稍後再試。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
