import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 環境變數
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 配置 Gemini
genai.configure(api_key=GEMINI_KEY)

# --- 3. io-bot 核心人設 ---
SYSTEM_PROMPT = """你是 io-bot。
你的專業領域包含：
- NVR 伺服器硬體故障診斷與 RAID 磁碟陣列問題。
- 監控管理軟體：精通 Nx Witness 與 EZ Pro 的設定與排錯。
- 網路監控架構、IP 攝影機連接與錄影儲存優化。

指令要求：
1. 根據用戶語言（中/英）自動切換回覆。
2. 當用戶詢問身分時，請以 io-bot 自稱並簡述上述專長。"""

# --- 4. 對話 Session 管理 ---
chat_sessions = {}

# 核心修正：確保模型名稱絕對符合 API 規範
MODEL_ID = 'models/gemini-1.5-flash'

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
    text = event.message.text
    try:
        # 初始化 Session
        if user_id not in chat_sessions:
            model = genai.GenerativeModel(
                model_name=MODEL_ID,
                system_instruction=SYSTEM_PROMPT
            )
            chat_sessions[user_id] = model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        response = chat.send_message(text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
        
    except Exception as e:
        print(f"Chat Error: {e}")
        # 救援機制：如果對話模式失敗，改用最原始的單次生成模式
        try:
            model = genai.GenerativeModel(MODEL_ID)
            # 在單次模式下手動加入人設
            res = model.generate_content(f"System: {SYSTEM_PROMPT}\n\nUser: {text}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res.text))
        except Exception as e2:
            print(f"Final Fallback Error: {e2}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 系統維護中，請檢查 API Key 權限。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        
        model = genai.GenerativeModel(model_name=MODEL_ID)
        response = model.generate_content([
            SYSTEM_PROMPT,
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        
        # 嘗試將結果同步到記憶中
        if user_id in chat_sessions:
            chat_sessions[user_id].history.append({"role": "user", "parts": ["(傳送了診斷圖片)"]})
            chat_sessions[user_id].history.append({"role": "model", "parts": [response.text]})

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Image Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片診斷功能暫時無法使用。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
