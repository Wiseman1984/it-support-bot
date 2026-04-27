import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 1. 讀取變數 (維持您 Render 上的設定名稱)
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 2. 修正後的初始化方式 (移除引發報錯的 api_version 參數)
genai.configure(api_key=GEMINI_KEY, transport='rest')

# 直接指定模型，讓 SDK 根據 API Key 的付費身分自動判斷路徑
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
        # 呼叫 Gemini
        response = model.generate_content(user_msg)
        
        if response.text:
            reply_text = response.text
        else:
            reply_text = "機器人目前回應為空，請試著換個問題。"
            
    except Exception as e:
        error_msg = str(e)
        print(f"Gemini API Error: {error_msg}")
        reply_text = "io bot 權限同步中，請過 10 秒後再嘗試一次。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
