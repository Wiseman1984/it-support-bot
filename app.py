import os
import io
import time
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

# 較快、成本較低，適合 LINE Bot 技術支援場景
model = genai.GenerativeModel("gemini-2.5-flash-lite")


# =========================
# 5. Temporary image memory
# =========================
# 暫存使用者最近上傳的圖片
# Render 服務重啟後，這個暫存會消失
LAST_IMAGE_CACHE = {}

# 圖片保留時間，單位秒：30 分鐘
IMAGE_CACHE_TTL_SECONDS = 30 * 60


# =========================
# 6. Common Prompt
# =========================
SYSTEM_PROMPT = """
你是 io-bot，一個公司內部與客戶現場使用的 IT / FAE 技術支援 LINE Bot。

你的主要支援範圍如下：

1. 監控軟體障礙排除
   - EZ Pro
   - NX / Network Optix / Nx Witness
   - VMS 監控軟體
   - 監控系統登入、串流、錄影、回放、攝影機連線、權限、服務狀態、授權、伺服器連線等問題

2. MegaRAID / RAID 障礙排除
   - RAID 狀態檢查
   - 硬碟異常
   - Virtual Drive / Physical Drive 狀態
   - Degraded、Offline、Rebuild、Foreign Config、Failed、Unconfigured Bad 等常見問題
   - MegaRAID Storage Manager、storcli、perccli 相關排查方向

3. NVR 主機簡易障礙排除
   - 軟體層：服務未啟動、錄影異常、登入異常、網路連線異常、資料庫異常
   - 硬體層：硬碟、RAID 卡、網卡、電源、記憶體、CPU、風扇、溫度、BIOS/UEFI 開機異常、Windows 安裝或格式化異常

4. 網路相關障礙排除
   - NVR / Server / Client / Camera 網路連線問題
   - IP 位址、Subnet Mask、Gateway、DNS 設定
   - Ping 不通、同網段找不到設備、跨網段連線異常
   - Port、防火牆、NAT、路由設定
   - ONVIF 搜尋不到攝影機
   - RTSP 串流無法連線
   - Switch、網路線、PoE、VLAN 基本排查
   - NX / EZ Pro Server 與 Client 連線異常

回答規則：
- 每次回覆開頭都要使用：「您好，我是 io-bot。」
- 請使用繁體中文與台灣常用技術用語。
- 回答要簡潔、清楚、可執行。
- 優先提供現場可操作的排查步驟。
- 如果使用者提供的是圖片，請先根據圖片判斷可能問題，再提供排查建議。
- 如果使用者先傳圖片、後續又用文字追問，請同時參考上一張圖片與這次文字。
- 如果圖片內容不清楚，請明確請使用者補拍較清楚的畫面，或補充錯誤訊息。
- 如果資訊不足，請先詢問必要資訊，不要過度猜測。
- 如果問題涉及 RAID、硬碟、錄影資料、資料庫或系統碟，請提醒使用者不要任意初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序。
- 如果問題涉及網路連線，請優先引導使用者確認 IP、Subnet Mask、Gateway、DNS、Ping、Port、防火牆、Switch、PoE、VLAN 與網路線狀態。
- 如果問題超出 VMS 監控軟體、MegaRAID、NVR 主機與網路障礙排除範圍，請禮貌說明此機器人主要支援 VMS 監控軟體、MegaRAID、NVR 主機與網路相關障礙排除，建議改洽相關負責窗口。
- 當回答涉及 EZ Pro、EZPRO、NX、Nx Witness、Network Optix、VMS 軟體本身的授權、硬體 ID、License、Server 綁定、版本限制、軟體原廠機制或原廠協助事項時，若需要建議使用者聯絡原廠或系統供應商，請統一使用「原廠 VMS」這個稱呼。
- 不要在「請聯絡...」、「建議洽詢...」、「請洽...」、「建議聯繫...」等建議窗口的句子中直接寫「EZ Pro 原廠」、「EZPRO 原廠」、「NX 原廠」、「Network Optix 原廠」。
- 可以在技術說明中提到 EZ Pro / NX / Network Optix / Nx Witness 作為產品或系統名稱，但在最後建議聯絡窗口時，請改寫為「原廠 VMS」或「原廠 VMS 技術支援窗口」。
- 若使用者詢問 NX 或 EZ Pro 的授權、硬體 ID、License、啟用、Server ID、Hardware ID、版本限制、轉移授權等問題，最後建議窗口請使用「原廠 VMS 技術支援窗口」。
- 若無法確定是軟體原廠問題、系統整合問題或現場環境問題，請建議先蒐集資訊，再由維護窗口協助判斷是否需要送交「原廠 VMS 技術支援窗口」。

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

注意事項：
- ...
"""


# =========================
# 7. Helper functions
# =========================
def get_user_id(event):
    try:
        return event.source.user_id
    except Exception:
        return "unknown_user"


def limit_reply_text(text: str, max_length: int = 4500) -> str:
    """
    LINE 文字訊息有長度限制，這裡保守限制在 4500 字。
    """
    if not text:
        return "您好，我是 io-bot。\n\n目前無法產生回覆，請稍後再試。"

    text = text.strip()

    if len(text) <= max_length:
        return text

    return text[:max_length] + "\n\n...回覆內容較長，已先截斷。請補充問題後我可以繼續協助。"


def resize_image_for_gemini(image: Image.Image, max_size: int = 1280) -> Image.Image:
    """
    將圖片縮小後再送給 Gemini，降低分析時間與傳輸量。
    max_size 代表圖片最長邊不超過 1280px。
    """
    image = image.convert("RGB")
    image.thumbnail((max_size, max_size))
    return image


def save_last_image(user_id: str, image_bytes: bytes):
    LAST_IMAGE_CACHE[user_id] = {
        "image_bytes": image_bytes,
        "timestamp": time.time()
    }
    print(f"Saved last image for user: {user_id}")


def get_last_image(user_id: str):
    data = LAST_IMAGE_CACHE.get(user_id)

    if not data:
        return None

    now = time.time()
    image_time = data.get("timestamp", 0)

    if now - image_time > IMAGE_CACHE_TTL_SECONDS:
        print(f"Last image expired for user: {user_id}")
        LAST_IMAGE_CACHE.pop(user_id, None)
        return None

    try:
        image_bytes = data.get("image_bytes")
        image = Image.open(io.BytesIO(image_bytes))
        image = resize_image_for_gemini(image)
        return image

    except Exception as e:
        print("ERROR: Failed to load cached image")
        print(str(e))
        LAST_IMAGE_CACHE.pop(user_id, None)
        return None


def download_line_image(message_id: str) -> bytes:
    message_content = line_bot_api.get_message_content(message_id)

    image_bytes = b""
    for chunk in message_content.iter_content():
        image_bytes += chunk

    return image_bytes


def is_short_followup_question(text: str) -> bool:
    """
    判斷是否為常見追問。
    目前主要保留給後續擴充使用。
    """
    if not text:
        return False

    followup_keywords = [
        "這是什麼",
        "這個是什麼",
        "怎麼辦",
        "如何處理",
        "原因",
        "為什麼",
        "哪裡錯",
        "錯在哪",
        "怎麼解",
        "怎麼排除",
        "格式化失敗",
        "開不了機",
        "不能開機",
        "無法開機",
        "無法登入",
        "無法錄影",
        "看不到影像",
        "沒有畫面",
        "異常",
        "錯誤",
        "error",
        "failed",
        "fail",
        "ping 不到",
        "連不上",
        "找不到",
        "不能連",
        "無法連線",
        "rtsp",
        "onvif",
    ]

    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in followup_keywords)


# =========================
# 8. Health check route
# =========================
@app.route("/", methods=["GET"])
def home():
    return "LINE io-bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "service": "line-io-bot",
        "model": "gemini-2.5-flash-lite"
    }, 200


# =========================
# 9. LINE webhook callback
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
# 10. Handle text message
# =========================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = get_user_id(event)
    user_msg = event.message.text

    print("========== User text message ==========")
    print(f"user_id: {user_id}")
    print(user_msg)

    try:
        last_image = get_last_image(user_id)

        if last_image:
            print("Cached image found. Answering with text + previous image.")

            prompt = f"""
{SYSTEM_PROMPT}

使用者先前有上傳一張圖片，現在又補充以下文字問題：

使用者文字問題：
{user_msg}

請同時根據「上一張圖片」與「這次文字問題」進行判斷與回答。
若最後需要建議聯絡 EZ Pro、NX、Network Optix 或 VMS 相關原廠/供應商，請統一使用「原廠 VMS」或「原廠 VMS 技術支援窗口」。
"""

            response = model.generate_content([prompt, last_image])

        else:
            print("No cached image found. Answering text only.")

            prompt = f"""
{SYSTEM_PROMPT}

使用者提供的文字問題如下：
{user_msg}

請根據上述文字問題提供協助。
若最後需要建議聯絡 EZ Pro、NX、Network Optix 或 VMS 相關原廠/供應商，請統一使用「原廠 VMS」或「原廠 VMS 技術支援窗口」。
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
# 11. Handle image message
# =========================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = get_user_id(event)

    print("========== User image message received ==========")
    print(f"user_id: {user_id}")

    try:
        # 1. Download image from LINE
        image_bytes = download_line_image(event.message.id)

        # 2. Save original image bytes for follow-up questions
        save_last_image(user_id, image_bytes)

        # 3. Resize image before sending to Gemini
        image = Image.open(io.BytesIO(image_bytes))
        image = resize_image_for_gemini(image)

        # 4. Analyze image
        prompt = f"""
{SYSTEM_PROMPT}

使用者上傳了一張圖片，可能與以下情境相關：
- NVR 主機異常
- BIOS / UEFI 開機畫面
- Windows 安裝或格式化錯誤
- RAID / MegaRAID 狀態
- EZ Pro 或 NX / Network Optix 錯誤畫面
- VMS 監控軟體錯誤畫面
- 監控系統畫面、錄影、串流或服務異常
- 網路連線、IP 設定、防火牆、Port、Switch、PoE、VLAN、RTSP 或 ONVIF 異常

請根據圖片回答：
1. 問題初步判斷
2. 建議排查步驟
3. 需要使用者補充的資訊
4. 若涉及 RAID / 硬碟 / 系統碟 / 錄影資料，請提醒不要初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序
5. 若涉及網路問題，請提醒使用者確認 IP、Subnet Mask、Gateway、DNS、Ping、Port、防火牆、Switch、PoE、VLAN 與網路線狀態
6. 若最後需要建議聯絡 EZ Pro、NX、Network Optix 或 VMS 相關原廠/供應商，請統一使用「原廠 VMS」或「原廠 VMS 技術支援窗口」

請用繁體中文回答，並且開頭必須是「您好，我是 io-bot。」
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
# 12. Run app locally / Render
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
    )
