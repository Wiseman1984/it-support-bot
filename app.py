import os
import io
import time
import traceback

from flask import Flask, request, abort, jsonify
from flask_cors import CORS  # 引入 CORS 支援官網對接

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
CORS(app)  # 允許官網跨網域安全呼叫


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
# 6. Common Prompt (語言自動切換與格式精簡優化版)
# =========================
SYSTEM_PROMPT = f"""
你是 io-bot，一個公司內部與客戶現場使用的 IT / FAE 技術支援 LINE / Web Bot。

【語言辨識與切換規則】
- 預設使用「繁體中文（台灣常用技術用語）」回答。
- 關鍵防禦：若使用者使用英文、日文、簡體中文或其他外文提問，請自動偵測並切換為「該語系」進行回覆。開頭與結尾等結構字眼也要同步切換（例如英文：Hello, I am io-bot. / Any other questions to add?）。

你的主要支援範圍如下：
1. 監控軟體障礙排除 (EZ Pro, NX / Network Optix / Nx Witness, VMS 監控軟體)
2. MegaRAID / RAID 障礙排除 (硬碟異常, Degraded, Rebuild 等)
3. NVR 主機簡易障礙排除 (軟硬體層基本排查, BIOS/UEFI 異常)
4. 網路相關障礙排除 (IP, Subnet Mask, Gateway, DNS, Ping, Port, 防火牆, PoE, VLAN, RTSP, ONVIF)

回答規則：
- 每次回覆開頭都要使用：「您好，我是 io-bot。」（外文提問則切換為該語言的問候語）。
- 每次回覆開頭後方請加上一行提醒：「{MEMORY_NOTICE}」（外文提問亦須翻譯該提醒）。
- 回答必須「極度簡潔、精煉、直奔主題」，絕不囉唆，優先提供現場最直接、可操作的 1~3 個排查步驟。
- 如果使用者提供的是圖片，請先根據圖片判斷可能問題，再提供排查建議。
- 如果使用者先傳圖片、後續又用文字追問，請同時參考上一張圖片與這次文字。
- 如果有提供最近對話紀錄，請根據最近對話延續上下文。
- 如果資訊不足，請先詢問必要資訊，不要過度猜測。
- 如果問題涉及 RAID、硬碟、錄影資料、資料庫或系統碟，請提醒使用者不要任意初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序。

VMS 品牌回答規則：
- 回答 VMS 相關問題時，必須依照使用者詢問的品牌回答（EZ Pro 或 NX），未指定則使用「VMS 監控軟體」作為泛稱。
- 不要在同一個回答中無故同時寫「EZ Pro / NX」，除非使用者明確同時詢問兩者。
- 若同一位使用者前一輪已經指定 VMS 品牌，後續追問若未指定品牌，請延續前一輪品牌脈絡。

聯絡窗口稱呼規則：
- 當回答涉及授權、硬體 ID、License 等需要聯繫原廠時，請統一使用「原廠 VMS」或「原廠 VMS 技術支援窗口」這個稱呼。不要直接寫「EZ Pro 原廠」或「NX 原廠」。

超出範圍回答規則：
- 如果問題超出範圍，請禮貌說明此機器人主要支援範圍，建議改洽相關負責窗口。

回答格式（必須嚴格控制字數，精簡精煉）：

您好，我是 io-bot。
{MEMORY_NOTICE}

問題初步判斷：
...

建議排查步驟：
1. ...
2. ...

有需要補充問題嗎？
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
    brand_time = data.get("timestamp", 0)

    if now - brand_time > IMAGE_CACHE_TTL_SECONDS:
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

    ezpro_keywords = ["ezpro", "ez pro", "ez-pro", "ez_pro", "ezpro server", "ez pro server"]
    nx_keywords = ["nx", "nx witness", "network optix", "networkoptix", "nx server", "nx vms"]

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
回答時請遵守：以 EZ Pro 為主，不要帶入 NX，不要寫「EZ Pro / NX」合併稱呼。建議窗口請使用「原廠 VMS 技術支援窗口」。
"""
    if vms_brand == "NX":
        return """
目前使用者詢問的 VMS 品牌判斷為：NX。
回答時請遵守：以 NX / Nx Witness 為主，不要帶入 EZ Pro，不要寫「EZ Pro / NX」合併稱呼。建議窗口請使用「原廠 VMS 技術支援窗口」。
"""
    return """
目前使用者未明確指定 VMS 品牌。
回答時請遵守：請使用「VMS 監控軟體」作為泛稱。不要無故同時列出 EZ Pro / NX。
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

        if len(user_text) > 500: user_text = user_text[:500] + "...已截斷"
        if len(bot_text) > 800: bot_text = bot_text[:800] + "...已截斷"

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
# 10. Handle text message (LINE)
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

        if last_image:
            prompt = f"""
{SYSTEM_PROMPT}
{brand_instruction}

以下是最近 3 輪對話紀錄，請用來延續上下文：
{chat_history_text}

使用者先前有上傳一張圖片，現在又補充以下文字問題：
{user_msg}

請同時根據「最近對話紀錄」、「上一張圖片」與「這次文字問題」進行判斷與回答。
"""
            response = model.generate_content([prompt, last_image])
        else:
            prompt = f"""
{SYSTEM_PROMPT}
{brand_instruction}

以下是最近 3 輪對話紀錄，請用來延續上下文：
{chat_history_text}

使用者提供的最新文字問題如下：
{user_msg}

請根據「最近對話紀錄」與「最新文字問題」提供協助。
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
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=final_reply_text))
        save_chat_turn(user_id, user_msg, final_reply_text)
        print("Text reply sent successfully.")
    except Exception as e:
        print("========== LINE Text Reply Error ==========")
        print(str(e))
        traceback.print_exc()


# =========================
# 11. Handle image message (LINE)
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

        image = Image.open(io.BytesIO(image_bytes))
        image = resize_image_for_gemini(image)

        prompt = f"""
{SYSTEM_PROMPT}
{brand_instruction}

以下是最近 3 輪對話紀錄，請用來延續上下文：
{chat_history_text}

使用者上傳了一張圖片，請根據「最近對話紀錄」與「圖片內容」回答問題，格式請嚴格遵守精簡要求。
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
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=final_reply_text))
        save_chat_turn(user_id, "使用者上傳了一張圖片。", final_reply_text)
        print("Image reply sent successfully.")
    except Exception as e:
        print("========== LINE Image Reply Error ==========")
        print(str(e))
        traceback.print_exc()


# =========================
# 12. 新增：專門給官網外包廠商對接的 Web API 路由
# =========================
@app.route("/api/web-chat", methods=["POST"])
def web_chat():
    try:
        data = request.json or {}
        user_id = data.get("user_id", "web_anonymous")
        user_msg = data.get("message", "")

        if not user_msg:
            return jsonify({"status": "error", "message": "Message is empty"}), 400

        vms_brand = resolve_vms_brand(user_id, user_msg)
        brand_instruction = build_brand_instruction(vms_brand)
        chat_history_text = get_chat_history_text(user_id)

        prompt = f"""
{SYSTEM_PROMPT}
{brand_instruction}

以下是最近 3 輪對話紀錄，請用來延續上下文：
{chat_history_text}

使用者提供的最新文字問題如下：
{user_msg}

請根據「最近對話紀錄」與「最新文字問題」提供精簡協助。
"""
        response = model.generate_content(prompt)
        
        if response and hasattr(response, "text") and response.text:
            reply_text = response.text.strip()
            # 官網回覆同樣計入多輪對話快取
            save_chat_turn(user_id, user_msg, reply_text)
            return jsonify({"status": "success", "reply": reply_text}), 200
        else:
            return jsonify({"status": "error", "reply": "目前 AI 回應為空，請再試一次。"}), 200

    except Exception as e:
        print(f"Web Chat Error: {str(e)}")
        return jsonify({"status": "error", "reply": "系統忙碌中，請稍後再試。"}), 500


# =========================
# 13. Run app locally / Render
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
    )
