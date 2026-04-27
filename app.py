import os
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import google.generativeai as genai

app = Flask(__name__)

LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if not LINE_ACCESS_TOKEN:
    print("ERROR: LINE_ACCESS_TOKEN is missing")

if not LINE_SECRET:
    print("ERROR: LINE_SECRET is missing")

if not GEMINI_KEY:
    print("ERROR: GEMINI_API_KEY is missing")

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

genai.configure(api_key=GEMINI_KEY, transport="rest")
model = genai.GenerativeModel("gemini-1.5-flash")


@app.route("/", methods=["GET"])
def home():
    return "LINE Gemini Bot is running."


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    print("LINE callback received")
    print(body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid LINE signature")
        abort(400)
    except Exception as e:
        print(f"LINE callback error: {str(e)}")
        abort(500)

    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text
    print(f"User message: {user_msg}")

    try:
        response = model.generate_content(user_msg)
        reply_text = response.text if response.text else "目前回應為空，請再試一次。"
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        reply_text = "io bot 目前暫時無法回應，請稍後再試。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
