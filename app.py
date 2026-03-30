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
1. 根據用戶語言（中/英）自動切換回覆，專業且簡潔。
2. 用戶詢問身分時，以此身分自介。"""

# --- 4. 自動尋找可用模型 (核心修復) ---
def find_best_model():
    try:
        # 直接列出所有模型名單
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        print(f"DEBUG: Available models: {available_models}")
        
        # 優先尋找 1.5 flash 的完整路徑
        for name in available_models:
            if 'gemini-1.5-flash' in name:
                return name
        # 備案：如果沒有 flash，隨便找一個能用的
        return available_models[0] if available_models else 'models/gemini-1.5-flash'
    except Exception as e:
        print(f"DEBUG: Failed to list models: {e}")
        return 'models/gemini-1.5-flash'

# 啟動時先抓一次
CURRENT_MODEL = find_best_model()
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
    global CURRENT_MODEL
    user_id = event.source.user_id
    try:
        if user_id not in chat_sessions:
            model = genai.GenerativeModel(
                model_name=CURRENT_MODEL,
                system_instruction=SYSTEM_PROMPT
            )
            chat_sessions[user_id] = model.start_chat(history=[])
        
        response = chat_sessions[user_id].send_message(event.message.text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except Exception as e:
        print(f"Chat Error: {e}")
        # 如果對話模式掛了，最後一招：單次生成救援
        try:
            m = genai.GenerativeModel(CURRENT_MODEL)
            res = m.generate_content(f"{SYSTEM_PROMPT}\n\nUser: {event.message.text}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res.text))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="io-bot 連線異常，請稍後再試。"))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    global CURRENT_MODEL
    user_id = event.source.user_id
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b"".join([chunk for chunk in message_content.iter_content()])
        
        model = genai.GenerativeModel(model_name=CURRENT_MODEL)
        response = model.generate_content([
            SYSTEM_PROMPT,
            {"mime_type": "image/jpeg", "data": image_data}
        ])
        
        if user_id in chat_sessions:
            chat_sessions[user_id].history.append({"role": "user", "parts": ["(傳送圖片)"]})
            chat_sessions[user_id].history.append({"role": "model", "parts": [response.text]})

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.text))
    except:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="圖片分析失敗。"))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
