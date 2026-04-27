import os
import io
import traceback

from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent,
    TextMessage,
    ImageMessage,
    TextSendMessage,
)

from PIL import Image
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

model = genai.GenerativeModel("gemini-2.5-flash")


# =========================
# 5. Common Prompt
# =========================
SYSTEM_PROMPT = """
你是 io-bot，一個公司內部與客戶現場使用的 IT / FAE 技術支援 LINE Bot。

你的主要支援範圍如下：

1. 監控軟體障礙排除
   - EZ Pro
   - NX / Network Optix / Nx Witness
   - 監控系統登入、串流、錄影、回放、攝影機連線、權限、服務狀態、授權、伺服器連線等問題

2. MegaRAID / RAID 障礙排除
   - RAID 狀態檢查
   - 硬碟異常
   - Virtual Drive / Physical Drive 狀態
   - Degraded、Offline、Rebuild、Foreign Config、Failed、Unconfigured Bad 等常見問題
   - MegaRAID Storage Manager、storcli、perccli 相關排查方向

3. NVR 主機簡易障礙排除
   - 軟體層：服務未啟動、錄影異常、登入異常、網路連線異常、資料庫異常
   - 硬體層：硬碟、RAID 卡、網卡、電源、記憶體、CPU、風扇、溫度、BIOS/UEFI 開機異常

回答規則：
- 每次回覆開頭都要使用：「您好，我是 io-bot。」
- 請使用繁體中文與台灣常用技術用語。
- 回答要簡潔、清楚、可執行。
- 優先提供現場可操作的排查步驟。
- 如果使用者提供的是圖片，請先根據圖片判斷可能問題，再提供排查建議。
- 如果圖片內容不清楚，請明確請使用者補拍較清楚的畫面，或補充錯誤訊息。
- 如果資訊不足，請先詢問必要資訊，不要過度猜測。
- 如果問題涉及 RAID、硬碟、錄影資料、資料庫或系統碟，請提醒使用者不要任意初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序。
- 如果問題超出 EZ Pro、NX、MegaRAID、NVR 主機障礙排除範圍，請禮貌說明此機器人主要支援 EZ Pro / NX、MegaRAID 與 NVR 主機障礙排除，建議改洽相關負責窗口。

回答格式請盡量使用：

您好，我是 io-bot。

問題初步判斷：
...

建議排查步驟：
1. ...
2. ...
3. ...

請補充資訊：
- ...
- ...

注意事項：
- ...
"""


# =========================
# 6. Helper: limit LINE reply length
# =========================
def limit_reply_text(text: str, max_length: int = 4500) -> str:
    if not text:
        return "您好，我是 io-bot。\n\n目前無法產生回覆，請稍後再試。"

    text = text.strip()

    if len(text) <= max_length:
        return text

    return text[:max_length] + "\n\n...回覆內容較長，已先截斷。請補充問題後我可以繼續協助。"


# =========================
# 7. Health check route
# =========================
@app.route("/", methods=["GET"])
def home():
    return "LINE io-bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "service": "line-io-bot"
    }, 200


# =========================
# 8. LINE webhook callback
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
# 9. Handle text message
# =========================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_msg = event.message.text

    print("========== User text message ==========")
    print(user_msg)

    try:
        prompt = f"""
{SYSTEM_PROMPT}

使用者提供的文字問題如下：
{user_msg}

請根據上述問題提供協助。
"""

        response = model.generate_content(prompt)

        if response and hasattr(response, "text") and response.text:
            reply_text = response.text.strip()
        else:
            reply_text = "您好，我是 io-bot。\n\n目前 Gemini 回應為空，請再試一次。"

    except Exception as e:
        print("========== Gemini Text API Error ==========")
        print(str(e))
        traceback.print_exc()

        reply_text = "您好，我是 io-bot。\n\n目前系統暫時無法回應，請稍後再試。"

    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=limit_reply_text(reply_text))
        )
        print("Text reply sent successfully.")

    except Exception as e:
        print("========== LINE Text Reply Error ==========")
        print(str(e))
        traceback.print_exc()


# =========================
# 10. Handle image message
# =========================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    print("========== User image message received ==========")

    try:
        # 1. Download image from LINE
        message_content = line_bot_api.get_message_content(event.message.id)

        image_bytes = b""
        for chunk in message_content.iter_content():
            image_bytes += chunk

        image = Image.open(io.BytesIO(image_bytes))

        # 2. Ask Gemini to analyze image
        prompt = f"""
{SYSTEM_PROMPT}

使用者上傳了一張圖片，可能是 NVR 主機、BIOS/UEFI、RAID、MegaRAID、EZ Pro、NX / Network Optix、錯誤訊息或監控系統畫面。

請根據圖片內容進行判斷，並提供：
1. 圖片中可能顯示的問題
2. 現場建議排查步驟
3. 需要使用者補充的資訊
4. 若涉及 RAID / 硬碟 / 系統碟 / 錄影資料，請提醒不要任意初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序

請用繁體中文回答。
"""

        response = model.generate_content([prompt, image])

        if response and hasattr(response, "text") and response.text:
            reply_text = response.text.strip()
        else:
            reply_text = "您好，我是 io-bot。\n\n我已收到圖片，但目前無法判讀內容。請補拍較清楚的畫面，或補充錯誤訊息。"

    except Exception as e:
        print("========== Gemini Image API Error ==========")
        print(str(e))
        traceback.print_exc()

        reply_text = "您好，我是 io-bot。\n\n我已收到圖片，但目前系統暫時無法分析圖片，請稍後再試，或改用文字描述問題。"

    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=limit_reply_text(reply_text))
        )
        print("Image reply sent successfully.")

    except Exception as e:
        print("========== LINE Image Reply Error ==========")
        print(str(e))
        traceback.print_exc()


# =========================
# 11. Run app locally / Render
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
    )
