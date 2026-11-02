import os
from flask import Flask, abort, request
from groq import Groq
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 初始化 Groq 客戶端（會自動讀取環境變數中的 GROQ_API_KEY）
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# LINE Bot 設定
line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))

# 您的 System Prompt 保持不變（包含所有產品邊界、排查步驟與 2FA 規則）
SYSTEM_PROMPT = """
[請保持您原本在 app.py 裡寫好的完整 SYSTEM_PROMPT 內容]
"""


def call_groq_ai(user_message):
  try:
    chat_completion = groq_client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_message,
            },
        ],
        model="llama-3.3-70b-versatile",  # 速度快且反應極佳的 Groq 模型
        temperature=0.3,
    )
    return chat_completion.choices[0].message.content
  except Exception as e:
    print(f"Groq API Error: {e}")
    return "抱歉，系統暫時無法處理您的請求，請稍後再試。"


@app.route("/callback", methods=["POST"])
def callback():
  signature = request.headers["X-Line-Signature"]
  body = request.get_data(as_text=True)
  app.logger.info("Request body: " + body)
  try:
    handler.handle(body, signature)
  except InvalidSignatureError:
    abort(400)
  return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
  user_msg = event.message.text
  # 呼叫 Groq AI 取得回覆
  ai_reply = call_groq_ai(user_msg)

  line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ai_reply))


if __name__ == "__main__":
  app.run(port=5000)
