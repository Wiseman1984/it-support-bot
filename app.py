import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 1. 讀取環境變數 (請確保 Render 設定為 LINE_ACCESS_TOKEN 與 LINE_SECRET)
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 2. 初始化 Gemini 設定 (關鍵修正)
# 強制指定 api_version 為 'v1'，避開日誌中的 404 v1beta 錯誤
genai.configure(
    api_key=GEMINI_KEY, 
    transport='rest', 
    client_options={'api_version': 'v1'}
)

# 使用 gemini-1.5-flash 付費版模型
model = genai.GenerativeModel('gemini-1.5-flash')

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
    user_msg = event.message.text
    
    try:
        # 呼叫 Gemini 生成內容
        response = model.generate_content(user_msg)
        
        if response.text:
            reply_text = response.text
        else:
            reply_text = "機器人目前回應為空，請試著換個問題。"
            
    except Exception as e:
        # 將錯誤印在 Render Logs
        error_msg = str(e)
        print(f"--- Gemini API Error ---")
        print(error_msg)
        
        # 友善的錯誤提示
        reply_text = "io bot 權限同步中，請過 10 秒後再嘗試一次。"

    # 回傳給 LINE 使用者
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    # Render 會自動分配 PORT，否則預設使用 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
