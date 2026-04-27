import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from google.generativeai import client  # 導入底層客戶端進行強制設定

app = Flask(__name__)

# 1. 讀取環境變數
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 2. 強制 Gemini 走 v1 正式版路徑 (避開 v1beta 404 報錯)
# 這裡使用底層設置，不會引發之前的 ValueError
genai.configure(api_key=GEMINI_KEY, transport='rest')
gemini_client = client.get_default_generative_client()
gemini_client.api_version = 'v1' 

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
        reply_text = response.text if response.text else "目前無法回應。"
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        # 這是您在 LINE 上會看到的提示
        reply_text = "io bot 權限同步中，請過 10 秒後再嘗試一次。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
