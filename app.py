import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

# 強制在底層將 API 版本設定為 v1 (正式版)
# 這能解決日誌中出現的 404 v1beta 錯誤
os.environ["GOOGLE_API_VERSION"] = "v1"

app = Flask(__name__)

# 1. 讀取環境變數 (請確認 Render 上的 Key 名稱正確)
line_bot_api = LineBotApi(os.getenv('LINE_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 2. 初始化 Gemini
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
            reply_text = "目前無法產生回應，請稍後再試。"
    except Exception as e:
        # 如果依然錯誤，會將具體錯誤碼印在 Render 日誌中
        print(f"Gemini API Error Detail: {str(e)}")
        reply_text = "io bot 權限同步中，請過 10 秒後再嘗試一次。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
