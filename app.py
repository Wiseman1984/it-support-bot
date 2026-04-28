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

model = genai.GenerativeModel("gemini-2.5-flash-lite")


# =========================
# 5. Temporary memory
# =========================
LAST_IMAGE_CACHE = {}
LAST_BRAND_CACHE = {}
CHAT_HISTORY_CACHE = {}

# 暫存時間：15 分鐘
IMAGE_CACHE_TTL_SECONDS = 15 * 60
BRAND_CACHE_TTL_SECONDS = 15 * 60
CHAT_HISTORY_TTL_SECONDS = 15 * 60

# 最近 3 輪對話
CHAT_HISTORY_MAX_TURNS = 3

MEMORY_NOTICE = "提醒：系統會暫時保留最近 3 輪對話約 15 分鐘，以協助延續排查脈絡。"


# =========================
# 6. Common Prompt
# =========================
SYSTEM_PROMPT = f"""
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
   - VMS Server 與 Client 連線異常

回答規則：
- 每次回覆開頭都要使用：「您好，我是 io-bot。」
- 每次回覆開頭後方請加上一行提醒：「{MEMORY_NOTICE}」
- 請使用繁體中文與台灣常用技術用語。
- 回答要簡潔、清楚、可執行。
- 優先提供現場可操作的排查步驟。
- 如果使用者提供的是圖片，請先根據圖片判斷可能問題，再提供排查建議。
- 如果使用者先傳圖片、後續又用文字追問，請同時參考上一張圖片與這次文字。
- 如果有提供最近對話紀錄，請根據最近對話延續上下文，但不要被過去錯誤判斷過度影響。
- 如果圖片內容不清楚，請明確請使用者補拍較清楚的畫面，或補充錯誤訊息。
- 如果資訊不足，請先詢問必要資訊，不要過度猜測。
- 如果問題涉及 RAID、硬碟、錄影資料、資料庫或系統碟，請提醒使用者不要任意初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序。
- 如果問題涉及網路連線，請優先引導使用者確認 IP、Subnet Mask、Gateway、DNS、Ping、Port、防火牆、Switch、PoE、VLAN 與網路線狀態。

VMS 品牌回答規則：
- 回答 VMS 相關問題時，必須依照使用者詢問的品牌回答。
- 若使用者明確詢問 EZ Pro 或 EZPRO，回答內容請以 EZ Pro 為主，不要主動帶入 NX、Nx Witness 或 Network Optix。
- 若使用者明確詢問 NX、Nx Witness 或 Network Optix，回答內容請以 NX / Nx Witness 為主，不要主動帶入 EZ Pro。
- 若使用者未指定品牌，請使用「VMS 監控軟體」作為泛稱。
- 若同一位使用者前一輪已經指定 VMS 品牌，後續追問若未指定品牌，請延續前一輪品牌脈絡。
- 技術說明中可以提到使用者指定的產品名稱，例如 EZ Pro 或 NX。
- 不要在同一個回答中無故同時寫「EZ Pro / NX」，除非使用者明確同時詢問兩者。
- 若使用者詢問 EZ Pro，請不要寫「EZ Pro / NX」。
- 若使用者詢問 NX，請不要寫「EZ Pro / NX」。

聯絡窗口稱呼規則：
- 當回答涉及 EZ Pro、EZPRO、NX、Nx Witness、Network Optix、VMS 軟體本身的授權、硬體 ID、License、Server 綁定、版本限制、軟體原廠機制或原廠協助事項時，若需要建議使用者聯絡原廠或系統供應商，請統一使用「原廠 VMS」這個稱呼。
- 不要在「請聯絡...」、「建議洽詢...」、「請洽...」、「建議聯繫...」等建議窗口的句子中直接寫「EZ Pro 原廠」、「EZPRO 原廠」、「NX 原廠」、「Network Optix 原廠」。
- 可以在技術說明中提到 EZ Pro / NX / Network Optix / Nx Witness 作為產品或系統名稱，但在最後建議聯絡窗口時，請改寫為「原廠 VMS」或「原廠 VMS 技術支援窗口」。
- 若使用者詢問授權、硬體 ID、License、啟用、Server ID、Hardware ID、版本限制、轉移授權等問題，最後建議窗口請使用「原廠 VMS 技術支援窗口」。
- 若無法確定是軟體原廠問題、系統整合問題或現場環境問題，請建議先蒐集資訊，再由維護窗口協助判斷是否需要送交「原廠 VMS 技術支援窗口」。

超出範圍回答規則：
- 如果問題超出 VMS 監控軟體、MegaRAID、NVR 主機與網路障礙排除範圍，請禮貌說明此機器人主要支援 VMS 監控軟體、MegaRAID、NVR 主機與網路相關障礙排除，建議改洽相關負責窗口。

回答格式請盡量使用：

您好，我是 io-bot。
{MEMORY_NOTICE}

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
def default_error_reply(message: str) -> str:
    return f"您好，我是 io-bot。\n{MEMORY_NOTICE}\n\n{message}"


def get_user_id(event):
    try:
        return event.source.user_id
    except Exception:
        return "unknown_user"


def limit_reply_text(text: str, max_length: int = 4500) -> str:
    if not text:
        return default_error_reply("目前無法產生回覆，請稍後再試。")

    text = text.strip()

    if len(text) <= max_length:
        return text

    return text[:max_length] + "\n\n...回覆內容較長，已先截斷。請補充問題後我可以繼續協助。"


def resize_image_for_gemini(image: Image.Image, max_size: int = 1280) -> Image.Image:
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


def detect_vms_brand(text: str) -> str:
    if not text:
        return "VMS"

    lower_text = text.lower()

    ezpro_keywords = [
        "ezpro",
        "ez pro",
        "ez-pro",
        "ez_pro",
        "ezpro server",
        "ez pro server",
    ]

    nx_keywords = [
        "nx",
        "nx witness",
        "network optix",
        "networkoptix",
        "nx server",
        "nx vms",
    ]

    if any(keyword in lower_text for keyword in ezpro_keywords):
        return "EZ Pro"

    if any(keyword in lower_text for keyword in nx_keywords):
        return "NX"

    return "VMS"


def save_last_brand(user_id: str, brand: str):
    if brand in ["EZ Pro", "NX"]:
        LAST_BRAND_CACHE[user_id] = {
            "brand": brand,
            "timestamp": time.time()
        }
        print(f"Saved last VMS brand for user {user_id}: {brand}")


def get_last_brand(user_id: str):
    data = LAST_BRAND_CACHE.get(user_id)

    if not data:
        return None

    now = time.time()
    brand_time = data.get("timestamp", 0)

    if now - brand_time > BRAND_CACHE_TTL_SECONDS:
        print(f"Last VMS brand expired for user: {user_id}")
        LAST_BRAND_CACHE.pop(user_id, None)
        return None

    return data.get("brand")


def resolve_vms_brand(user_id: str, user_msg: str) -> str:
    detected_brand = detect_vms_brand(user_msg)

    if detected_brand in ["EZ Pro", "NX"]:
        save_last_brand(user_id, detected_brand)
        return detected_brand

    cached_brand = get_last_brand(user_id)
    if cached_brand in ["EZ Pro", "NX"]:
        print(f"Using cached VMS brand for user {user_id}: {cached_brand}")
        return cached_brand

    return "VMS"


def build_brand_instruction(vms_brand: str) -> str:
    if vms_brand == "EZ Pro":
        return """
目前使用者詢問的 VMS 品牌判斷為：EZ Pro。

回答時請遵守：
- 回答內容請以 EZ Pro 為主。
- 不要主動帶入 NX、Nx Witness 或 Network Optix。
- 不要寫「EZ Pro / NX」這種合併稱呼。
- 若需要泛稱軟體，可寫「EZ Pro」或「VMS 監控軟體」。
- 若最後需要建議聯絡原廠或支援窗口，請使用「原廠 VMS 技術支援窗口」。
"""

    if vms_brand == "NX":
        return """
目前使用者詢問的 VMS 品牌判斷為：NX。

回答時請遵守：
- 回答內容請以 NX / Nx Witness 為主。
- 不要主動帶入 EZ Pro。
- 不要寫「EZ Pro / NX」這種合併稱呼。
- 若需要泛稱軟體，可寫「NX」或「VMS 監控軟體」。
- 若最後需要建議聯絡原廠或支援窗口，請使用「原廠 VMS 技術支援窗口」。
"""

    return """
目前使用者未明確指定 VMS 品牌。

回答時請遵守：
- 請使用「VMS 監控軟體」作為泛稱。
- 不要無故同時列出 EZ Pro / NX。
- 除非使用者明確提到品牌，否則不要主動指定為 EZ Pro 或 NX。
- 若最後需要建議聯絡原廠或支援窗口，請使用「原廠 VMS 技術支援窗口」。
"""


def clean_expired_chat_history(user_id: str):
    data = CHAT_HISTORY_CACHE.get(user_id)

    if not data:
        return

    now = time.time()
    updated_at = data.get("updated_at", 0)

    if now - updated_at > CHAT_HISTORY_TTL_SECONDS:
        print(f"Chat history expired for user: {user_id}")
        CHAT_HISTORY_CACHE.pop(user_id, None)


def get_chat_history_text(user_id: str) -> str:
    clean_expired_chat_history(user_id)

    data = CHAT_HISTORY_CACHE.get(user_id)

    if not data:
        return "目前沒有可用的最近對話紀錄。"

    turns = data.get("turns", [])

    if not turns:
        return "目前沒有可用的最近對話紀錄。"

    lines = []

    for idx, turn in enumerate(turns, start=1):
        user_text = turn.get("user", "").strip()
        bot_text = turn.get("bot", "").strip()

        if len(user_text) > 500:
            user_text = user_text[:500] + "...已截斷"

        if len(bot_text) > 800:
            bot_text = bot_text[:800] + "...已截斷"

        lines.append(f"第 {idx} 輪：")
        lines.append(f"使用者：{user_text}")
        lines.append(f"io-bot：{bot_text}")

    return "\n".join(lines)


def save_chat_turn(user_id: str, user_text: str, bot_text: str):
    clean_expired_chat_history(user_id)

    data = CHAT_HISTORY_CACHE.get(user_id)

    if not data:
        data = {
            "turns": [],
            "updated_at": time.time()
        }

    turns = data.get("turns", [])

    turns.append({
        "user": user_text,
        "bot": bot_text,
        "timestamp": time.time()
    })

    turns = turns[-CHAT_HISTORY_MAX_TURNS:]

    CHAT_HISTORY_CACHE[user_id] = {
        "turns": turns,
        "updated_at": time.time()
    }

    print(f"Saved chat history for user {user_id}. Turns: {len(turns)}")


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
        "model": "gemini-2.5-flash-lite",
        "chat_history_max_turns": CHAT_HISTORY_MAX_TURNS,
        "memory_minutes": 15
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
        vms_brand = resolve_vms_brand(user_id, user_msg)
        brand_instruction = build_brand_instruction(vms_brand)
        chat_history_text = get_chat_history_text(user_id)

        print(f"Resolved VMS brand: {vms_brand}")

        if last_image:
            print("Cached image found. Answering with text + previous image.")

            prompt = f"""
{SYSTEM_PROMPT}

{brand_instruction}

以下是最近 3 輪對話紀錄，請用來延續上下文：
{chat_history_text}

使用者先前有上傳一張圖片，現在又補充以下文字問題：

使用者文字問題：
{user_msg}

請同時根據「最近對話紀錄」、「上一張圖片」與「這次文字問題」進行判斷與回答。

再次提醒：
- 回覆開頭必須包含：「您好，我是 io-bot。」
- 回覆第二行必須包含：「{MEMORY_NOTICE}」
- 若目前品牌判斷為 EZ Pro，請不要主動提到 NX。
- 若目前品牌判斷為 NX，請不要主動提到 EZ Pro。
- 若最後需要建議聯絡原廠或供應商，請統一使用「原廠 VMS 技術支援窗口」。
"""

            response = model.generate_content([prompt, last_image])

        else:
            print("No cached image found. Answering text only.")

            prompt = f"""
{SYSTEM_PROMPT}

{brand_instruction}

以下是最近 3 輪對話紀錄，請用來延續上下文：
{chat_history_text}

使用者提供的最新文字問題如下：
{user_msg}

請根據「最近對話紀錄」與「最新文字問題」提供協助。

再次提醒：
- 回覆開頭必須包含：「您好，我是 io-bot。」
- 回覆第二行必須包含：「{MEMORY_NOTICE}」
- 若目前品牌判斷為 EZ Pro，請不要主動提到 NX。
- 若目前品牌判斷為 NX，請不要主動提到 EZ Pro。
- 若最後需要建議聯絡原廠或供應商，請統一使用「原廠 VMS 技術支援窗口」。
"""

            response = model.generate_content(prompt)

        if response and hasattr(response, "text") and response.text:
            reply_text = response.text.strip()
        else:
            reply_text = default_error_reply("目前 Gemini 回應為空，請再試一次。")

    except Exception as e:
        print("========== Gemini Text API Error ==========")
        print(str(e))
        traceback.print_exc()

        reply_text = default_error_reply("目前系統暫時無法回應，請稍後再試。")

    try:
        final_reply_text = limit_reply_text(reply_text)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=final_reply_text)
        )

        save_chat_turn(user_id, user_msg, final_reply_text)

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
        image_bytes = download_line_image(event.message.id)
        save_last_image(user_id, image_bytes)

        cached_brand = get_last_brand(user_id)
        vms_brand = cached_brand if cached_brand in ["EZ Pro", "NX"] else "VMS"
        brand_instruction = build_brand_instruction(vms_brand)
        chat_history_text = get_chat_history_text(user_id)

        print(f"Resolved VMS brand for image: {vms_brand}")

        image = Image.open(io.BytesIO(image_bytes))
        image = resize_image_for_gemini(image)

        prompt = f"""
{SYSTEM_PROMPT}

{brand_instruction}

以下是最近 3 輪對話紀錄，請用來延續上下文：
{chat_history_text}

使用者上傳了一張圖片，可能與以下情境相關：
- NVR 主機異常
- BIOS / UEFI 開機畫面
- Windows 安裝或格式化錯誤
- RAID / MegaRAID 狀態
- VMS 監控軟體錯誤畫面
- 監控系統畫面、錄影、串流或服務異常
- 網路連線、IP 設定、防火牆、Port、Switch、PoE、VLAN、RTSP 或 ONVIF 異常

請根據「最近對話紀錄」與「圖片內容」回答：
1. 問題初步判斷
2. 建議排查步驟
3. 需要使用者補充的資訊
4. 若涉及 RAID / 硬碟 / 系統碟 / 錄影資料，請提醒不要初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序
5. 若涉及網路問題，請提醒使用者確認 IP、Subnet Mask、Gateway、DNS、Ping、Port、防火牆、Switch、PoE、VLAN 與網路線狀態
6. 若最後需要建議聯絡原廠或供應商，請統一使用「原廠 VMS 技術支援窗口」

請用繁體中文回答。

再次提醒：
- 回覆開頭必須包含：「您好，我是 io-bot。」
- 回覆第二行必須包含：「{MEMORY_NOTICE}」
- 若目前品牌判斷為 EZ Pro，請不要主動提到 NX。
- 若目前品牌判斷為 NX，請不要主動提到 EZ Pro。
- 若目前品牌判斷為 VMS，請使用「VMS 監控軟體」作為泛稱。
"""

        response = model.generate_content([prompt, image])

        if response and hasattr(response, "text") and response.text:
            reply_text = response.text.strip()
        else:
            reply_text = default_error_reply("我已收到圖片，但目前無法判讀內容。請補拍較清楚的畫面，或補充錯誤訊息。")

    except Exception as e:
        print("========== Gemini Image API Error ==========")
        print(str(e))
        traceback.print_exc()

        reply_text = default_error_reply("我已收到圖片，但目前系統暫時無法分析圖片，請稍後再試，或改用文字描述問題。")

    try:
        final_reply_text = limit_reply_text(reply_text)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=final_reply_text)
        )

        save_chat_turn(user_id, "使用者上傳了一張圖片。", final_reply_text)

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
