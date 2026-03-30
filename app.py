import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

app = Flask(__name__)

# 1. 取得環境變數
LINE_ACCESS_TOKEN = os.environ.get('LINE_ACCESS_TOKEN')
LINE_SECRET = os.environ.get('LINE_SECRET')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 2. 設定 Gemini
genai.configure(api_key=GEMINI_KEY)

# --- 3. io-bot 核心人設 ---
SYSTEM_PROMPT = """你是 io-bot。
你的專業領域包含：
- NVR 伺服器硬體故障診斷與 RAID 磁碟陣列問題。
- 監控管理軟體：精通 Nx Witness 與 EZ Pro 的設定與排錯。
- 網路監控架構、IP 攝影機連接與錄影儲存優化。

指令要求：
1. 根據用戶語言（中/英）自動切換回覆，保持專業且簡潔。
2. 當用戶詢問身分時，請以 io-bot 自稱並簡述上述專長。"""

# --- 4. 自動偵測模型名稱 (核心修復邏輯) ---
def get_real_model_name():
    try:
        # 列出所有可用的模型，找到包含 gemini-1.5-flash 的正確路徑
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'gemini-1.5-flash' in m.name:
                    print(f"DEBUG: Found model path -> {m.name}")
                    return m.name
        # 如果沒找到，回傳一個最可能的預設路徑
        return 'models/gemini-1.5-flash'
    except Exception as e:
        print(f"DEBUG: List models failed: {e}")
        return 'models/gemini-1.5-flash'

# 儲存正確的模型路徑
ACTUAL_MODEL_PATH = get_real_model_name()

# --- 5. 對話紀錄暫存 ---
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
    try:
        if user_id not in chat_sessions:
            # 使用自動偵測到的路徑初始化
            model = genai.GenerativeModel(
                model_name=ACTUAL_MODEL_PATH,
                system_instruction=SYSTEM_PROMPT
            )
            chat_sessions[user_id] = model.start_chat(history=[])
        
        chat = chat_sessions[user_id]
        response = chat.send_message(event.message.text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Chat Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"io-bot 連線異常，請確認 API Key 狀態。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        
        model = genai.GenerativeModel(model_name=ACTUAL_MODEL_PATH)
        response = model.generate_content([
            SYSTEM_PROMPT,
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        
        if user_id in chat_sessions:
            chat_sessions[user_id].history.append({"role": "user", "parts": ["（用戶傳送了診斷圖片）"]})
            chat_sessions[user_id].history.append({"role": "model", "parts": [response.text]})

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Image Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析暫時無法使用。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
