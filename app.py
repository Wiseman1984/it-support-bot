import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 1. 設定您的環境變數 (請確保 Render 的 Environment Variables 已設定這些 Key)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 2. 初始化 Gemini 設定
# 強制指定使用 REST 傳輸模式，這能有效解決某些環境下 SDK 誤判 API 版本的問題
genai.configure(api_key=GEMINI_KEY, transport='rest')

# 初始化模型 (不要在名稱前加上 models/，新版 SDK 會自動處理)
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

@app.event_log = [] # 簡單的日誌記錄

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    
    try:
        # 呼叫 Gemini API 生成內容
        response = model.generate_content(user_msg)
        
        if response.text:
            reply_text = response.text
        else:
            reply_text = "機器人現在無法生成文字，請稍後再試。"
            
    except Exception as e:
        # 將錯誤詳細資訊印在 Render 日誌中方便排查
        error_msg = str(e)
        print(f"--- Gemini API Error Details ---")
        print(error_msg)
        
        # 針對常見的 404/v1beta 錯誤提供友善提示
        if "404" in error_msg or "v1beta" in error_msg:
            reply_text = "系統偵測到環境版本衝突，請確保 requirements.txt 已更新並選擇 'Clear Build Cache' 重新部署。"
        else:
            reply_text = f"連線暫時異常，請稍後再試一次。\n(錯誤代碼: {error_msg[:20]}...)"

    # 回傳訊息給 LINE 使用者
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    # Render 會自動分配 port，本地測試預設使用 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
