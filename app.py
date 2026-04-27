import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 1. 根據你的 Render 設定，使用原本的變數名稱
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 2. 初始化 Gemini 設定
# transport='rest' 能強迫新版 SDK 走正確的付費通道路徑
genai.configure(api_key=GEMINI_KEY, transport='rest')
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
            reply_text = "機器人目前無法產生回應，請稍後再試。"
            
    except Exception as e:
        # 將錯誤印在 Render 的 Logs 裡方便排查
        error_msg = str(e)
        print(f"Gemini Error: {error_msg}")
        
        # 這是你在 LINE 上會看到的錯誤提示
        reply_text = "io bot 權限同步中，請過 10 秒後再嘗試一次。"

    # 回傳訊息給 LINE
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    # Render 環境預設使用 10000 埠口
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
