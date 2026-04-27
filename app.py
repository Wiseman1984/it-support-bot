import os
import traceback

from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import google.generativeai as genai


app = Flask(__name__)


# =========================
# 1. Read environment variables
# =========================
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# =========================
# 2. Check required variables
# =========================
missing_vars = []

if not LINE_ACCESS_TOKEN:
    missing_vars.append("LINE_ACCESS_TOKEN")

if not LINE_SECRET:
    missing_vars.append("LINE_SECRET")

if not GEMINI_API_KEY:
    missing_vars.append("GEMINI_API_KEY")

if missing_vars:
    print("ERROR: Missing environment variables:", ", ".join(missing_vars))


# =========================
# 3. Initialize LINE Bot
# =========================
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)


# =========================
# 4. Initialize Gemini
# =========================
genai.configure(
    api_key=GEMINI_API_KEY,
    transport="rest"
)

# 原本 gemini-1.5-flash 已不可用或不支援目前 API 版本
# 先改用目前穩定的 Gemini 2.5 Flash
model = genai.GenerativeModel("gemini-2.5-flash")


# =========================
# 5. Health check route
# =========================
@app.route("/", methods=["GET"])
def home():
    return "LINE Gemini Bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "service": "line-gemini-bot"
    }, 200


# =========================
# 6. LINE webhook callback
# =========================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    print("========== LINE callback received ==========")
    print(body)

    try:
        handler.handle(body, signature)

    except InvalidSignatureError:
        print("ERROR: Invalid LINE signature")
        abort(400)

    except Exception as e:
        print("ERROR: LINE callback failed")
        print(str(e))
        traceback.print_exc()
        abort(500)

    return "OK", 200


# =========================
# 7. Handle text message
# =========================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text

    print("========== User message ==========")
    print(user_msg)

    try:
        prompt = f"""
你是一個公司內部 IT Support LINE Bot。
請使用繁體中文回覆，語氣簡潔、清楚、友善。
如果使用者問題不完整，請先詢問必要資訊。

使用者問題：
{user_msg}
"""

        response = model.generate_content(prompt)

        if response and hasattr(response, "text") and response.text:
            reply_text = response.text.strip()
        else:
            reply_text = "目前 Gemini 回應為空，請再試一次。"

    except Exception as e:
        print("========== Gemini API Error ==========")
        print(str(e))
        traceback.print_exc()

        reply_text = "io bot 目前暫時無法回應，請稍後再試。"

    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        print("Reply sent successfully.")

    except Exception as e:
        print("========== LINE Reply Error ==========")
        print(str(e))
        traceback.print_exc()


# =========================
# 8. Run app locally / Render
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
    )
