import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 讀取環境變數
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 初始化 Gemini：直接使用最保險的配置
# 當 SDK >= 0.8.3 時，它會優先讀取您的付費 Tier 1 身分
genai.configure(api_key=GEMINI_KEY, transport='rest')

# 建立模型實例
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
        reply_text = response.text if response.text else "機器人暫時無法思考，請再試一次。"
    except Exception as e:
        print(f"Error: {str(e)}")
        reply_text = "系統權限同步中，請過 30 秒再試一次。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
