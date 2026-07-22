import os
import io
import time
import traceback

from flask import Flask, request, abort, jsonify
from flask_cors import CORS

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
from langdetect import detect  # 新增：語系偵測套件


app = Flask(__name__)
CORS(app)


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
if not LINE_ACCESS_TOKEN: missing_vars.append("LINE_ACCESS_TOKEN")
if not LINE_SECRET: missing_vars.append("LINE_SECRET")
if not GEMINI_API_KEY: missing_vars.append("GEMINI_API_KEY")
if missing_vars: print("ERROR: Missing environment variables:", ", ".join(missing_vars))


# =========================
# 3. Initialize LINE Bot
# =========================
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)


# =========================
# 4. Initialize Gemini
# =========================
genai.configure(api_key=GEMINI_API_KEY, transport="rest")
model = genai.GenerativeModel("gemini-2.5-flash-lite")


# =========================
# 5. Temporary memory
# =========================
LAST_IMAGE_CACHE = {}
LAST_BRAND_CACHE = {}
CHAT_HISTORY_CACHE = {}

IMAGE_CACHE_TTL_SECONDS = 15 * 60
BRAND_CACHE_TTL_SECONDS = 15 * 60
CHAT_HISTORY_TTL_SECONDS = 15 * 60
CHAT_HISTORY_MAX_TURNS = 3

MEMORY_NOTICE = "提醒：系統會暫時保留最近 3 輪對話約 15 分鐘，以協助延續排查脈絡。"


# =========================
# 6. Common Prompt
# =========================
SYSTEM_PROMPT = f"""
你是 io-bot，一個公司內部與客戶現場使用的 IT / FAE 技術支援 LINE / Web Bot。

【重要語言對齊規則】
- 預設使用「繁體中文（台灣常用技術用語）」回答。
- 如果在 Prompt 最上方有看到強制切換語系的【⚠️最高指令】，請務必嚴格遵守該指令的語系回覆，包含所有的問候語、標題與內文，絕不可混入其他語言。

你的主要支援範圍如下：
1. 監控軟體障礙排除 (EZ Pro, NX / Network Optix / Nx Witness, VMS 監控軟體)
2. MegaRAID / RAID 障礙排除 (硬碟異常, Degraded, Rebuild 等)
3. NVR 主機簡易障礙排除 (軟硬體層基本排查, BIOS/UEFI 異常)
4. 網路相關障礙排除 (IP, Subnet Mask, Gateway, DNS, Ping, Port, 防火牆, PoE, VLAN, RTSP, ONVIF)

回答規則：
- 每次回覆開頭都要使用：「您好，我是 io-bot。」（外文提問則務必切換為該語言的問候語）。
- 每次回覆開頭後方請加上一行提醒：「{MEMORY_NOTICE}」（外文提問亦須翻譯該提醒）。
- 回答必須「極度簡潔、精煉、直奔主題」，絕不囉唆，優先提供現場最直接、可操作的 1~3 個排查步驟。
- 如果使用者提供的是圖片，請先根據圖片判斷可能問題，再提供排查建議。
- 如果使用者先傳圖片、後續又用文字追問，請同時參考上一張圖片與這次文字。
- 如果有提供最近對話紀錄，請根據最近對話延續上下文。
- 如果問題涉及 RAID、硬碟、錄影資料、資料庫或系統碟，請提醒使用者不要任意初始化、格式化、重建 RAID、拔插硬碟或更換硬碟順序。

VMS 品牌回答規則：
- 回答 VMS 相關問題時，必須依照使用者詢問的品牌回答（EZ Pro 或 NX），未指定則使用「VMS 監控軟體」作為泛稱。
- 不要在同一個回答中無故同時寫「EZ Pro / NX」，除非使用者明確同時詢問兩者。

聯絡窗口稱呼規則：
- 當需要建議聯繫原廠時，請統一使用「原廠 VMS」或「原廠 VMS 技術支援窗口」這個稱呼。不要直接寫「EZ Pro 原廠」或「NX 原廠」。

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
# 7. Helper functions & Language Detector
# =========================
def get_language_instruction(text: str) -> str:
    """自動偵測使用者輸入的語系，強行施加最高指令給 Gemini"""
    if not text:
        return ""
    try:
        lang = detect(text)
        if lang == 'ja':
            return "\n【⚠️最高指令：偵測到使用者使用日文，請「完全使用日文(日本語)」回覆，絕不許出現中文或英文！】\n"
        elif lang == 'ko':
            return "\n【⚠️最高指令：偵測到使用者使用韓文，請「完全使用韓文(한국어)」回覆，絕不許出現中文或英文！】\n"
        elif lang == 'en':
            return "\n【⚠️最高指令：偵測到使用者使用英文，請「完全使用英文(English)」回覆，絕不許出現中文！】\n"
        else:
            # 包含 zh, zh-tw, zh-cn 或其他無法精準辨識的語言，一律鎖定繁體中文
            return "\n【⚠️最高指令：請完全使用「繁體中文（台灣常用技術用語）」回覆，絕不允許出現韓文、日文或英文！】\n"
    except:
        # 萬一連 langdetect 都因為錯字辨識失敗，保底強制使用繁體中文
        return "\n【⚠️最高指令：請完全使用「繁體中文（台灣常用技術用語）」回覆，絕不允許出現韓文、日文或英文！】\n"



def default_error_reply(message: str) -> str:
    return f"您好，我是 io-bot。\n{MEMORY_NOTICE}\n\n{message}"


def get_user_id(event):
    try: return event.source.user_id
    except: return "unknown_user"


def limit_reply_text(text: str, max_length: int = 4500) -> str:
    if not text: return default_error_reply("目前無法產生回覆，請稍後再試。")
    text = text.strip()
    if len(text) <= max_length: return text
    return text[:max_length] + "\n\n...回覆內容較長，已先截斷。請補充問題後我可以繼續協助。"


def resize_image_for_gemini(image: Image.Image, max_size: int = 1280) -> Image.Image:
    image = image.convert("RGB")
    image.thumbnail((max_size, max_size))
    return image


def save_last_image(user_id: str, image_bytes: bytes):
    LAST_IMAGE_CACHE[user_id] = {"image_bytes": image_bytes, "timestamp": time.time()}


def get_last_image(user_id: str):
    data = LAST_IMAGE_CACHE.get(user_id)
    if not data: return None
    if time.time() - data.get("timestamp", 0) > IMAGE_CACHE_TTL_SECONDS:
        LAST_IMAGE_CACHE.pop(user_id, None)
        return None
    try:
        image = Image.open(io.BytesIO(data.get("image_bytes")))
        return resize_image_for_gemini(image)
    except:
        LAST_IMAGE_CACHE.pop(user_id, None)
        return None


def download_line_image(message_id: str) -> bytes:
    message_content = line_bot_api.get_message_content(message_id)
    return b"".join(chunk for chunk in message_content.iter_content())


def detect_vms_brand(text: str) -> str:
    if not text: return "VMS"
    lower_text = text.lower()
    if any(k in lower_text for k in ["ezpro", "ez pro", "ez-pro", "ez_pro"]): return "EZ Pro"
    if any(k in lower_text for k in ["nx", "nx witness", "network optix", "networkoptix"]): return "NX"
    return "VMS"


def save_last_brand(user_id: str, brand: str):
    if brand in ["EZ Pro", "NX"]:
        LAST_BRAND_CACHE[user_id] = {"brand": brand, "timestamp": time.time()}


def get_last_brand(user_id: str):
    data = LAST_BRAND_CACHE.get(user_id)
    if not data: return None
    if time.time() - data.get("timestamp", 0) > BRAND_CACHE_TTL_SECONDS:
        LAST_BRAND_CACHE.pop(user_id, None)
        return None
    return data.get("brand")


def resolve_vms_brand(user_id: str, user_msg: str) -> str:
    detected_brand = detect_vms_brand(user_msg)
    if detected_brand in ["EZ Pro", "NX"]:
        save_last_brand(user_id, detected_brand)
        return detected_brand
    cached_brand = get_last_brand(user_id)
    return cached_brand if cached_brand in ["EZ Pro", "NX"] else "VMS"


def build_brand_instruction(vms_brand: str) -> str:
    if vms_brand == "EZ Pro":
        return "\n目前品牌脈絡：EZ Pro。請以 EZ Pro 角度回答，勿提 NX，勿使用合併稱呼。\n"
    if vms_brand == "NX":
        return "\n目前品牌脈絡：NX。請以 NX/Nx Witness 角度回答，勿提 EZ Pro，勿使用合併稱呼。\n"
    return "\n目前品牌脈絡：未指定。請使用「VMS 監控軟體」作為泛稱。\n"


def clean_expired_chat_history(user_id: str):
    data = CHAT_HISTORY_CACHE.get(user_id)
    if data and (time.time() - data.get("updated_at", 0) > CHAT_HISTORY_TTL_SECONDS):
        CHAT_HISTORY_CACHE.pop(user_id, None)


def get_chat_history_text(user_id: str) -> str:
    clean_expired_chat_history(user_id)
    data = CHAT_HISTORY_CACHE.get(user_id)
    if not data or not data.get("turns", []): return "目前沒有可用的最近對話紀錄。"
    lines = []
    for idx, turn in enumerate(data.get("turns", []), start=1):
        lines.append(f"第 {idx} 輪 - 使用者: {turn.get('user', '')[:200]} | io-bot: {turn.get('bot', '')[:200]}")
    return "\n".join(lines)


def save_chat_turn(user_id: str, user_text: str, bot_text: str):
    clean_expired_chat_history(user_id)
    data = CHAT_HISTORY_CACHE.get(user_id) or {"turns": [], "updated_at": time.time()}
    turns = data.get("turns", [])
    turns.append({"user": user_text, "bot": bot_text, "timestamp": time.time()})
    CHAT_HISTORY_CACHE[user_id] = {"turns": turns[-CHAT_HISTORY_MAX_TURNS:], "updated_at": time.time()}


# =========================
# 8. Routes
# =========================
@app.route("/", methods=["GET"])
def home(): return "LINE io-bot is running.", 200

@app.route("/health", methods=["GET"])
def health(): return {"status": "ok", "service": "line-io-bot", "model": "gemini-2.5-flash-lite"}, 200

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    except: abort(500)
    return "OK", 200


# =========================
# 9. Handle text message (LINE)
# =========================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = get_user_id(event)
    user_msg = event.message.text

    try:
        last_image = get_last_image(user_id)
        vms_brand = resolve_vms_brand(user_id, user_msg)
        brand_instruction = build_brand_instruction(vms_brand)
        chat_history_text = get_chat_history_text(user_id)
        lang_instruction = get_language_instruction(user_msg)  # 取得語系強制令

        if last_image:
            prompt = f"{lang_instruction}\n{SYSTEM_PROMPT}\n{brand_instruction}\n對話紀錄:\n{chat_history_text}\n使用者先前有上傳一張圖片，現在又補充文字問題：{user_msg}"
            response = model.generate_content([prompt, last_image])
        else:
            prompt = f"{lang_instruction}\n{SYSTEM_PROMPT}\n{brand_instruction}\n對話紀錄:\n{chat_history_text}\n最新文字問題：{user_msg}"
            response = model.generate_content(prompt)

        reply_text = response.text.strip() if response and hasattr(response, "text") and response.text else default_error_reply("Gemini 回應為空")
    except Exception as e:
        print(traceback.format_exc())
        reply_text = default_error_reply("系統暫時無法回應")

    try:
        final_reply_text = limit_reply_text(reply_text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=final_reply_text))
        save_chat_turn(user_id, user_msg, final_reply_text)
    except:
        print(traceback.format_exc())


# =========================
# 10. Handle image message (LINE)
# =========================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = get_user_id(event)
    try:
        image_bytes = download_line_image(event.message.id)
        save_last_image(user_id, image_bytes)

        cached_brand = get_last_brand(user_id)
        vms_brand = cached_brand if cached_brand in ["EZ Pro", "NX"] else "VMS"
        brand_instruction = build_brand_instruction(vms_brand)
        chat_history_text = get_chat_history_text(user_id)

        image = Image.open(io.BytesIO(image_bytes))
        image = resize_image_for_gemini(image)

        prompt = f"{SYSTEM_PROMPT}\n{brand_instruction}\n對話紀錄:\n{chat_history_text}\n使用者上傳了一張圖片，請根據圖片分析可能問題並提供精簡排查步驟。"
        response = model.generate_content([prompt, image])
        reply_text = response.text.strip() if response and hasattr(response, "text") and response.text else default_error_reply("無法判讀圖片內容")
    except Exception as e:
        print(traceback.format_exc())
        reply_text = default_error_reply("系統暫時無法分析圖片")

    try:
        final_reply_text = limit_reply_text(reply_text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=final_reply_text))
        save_chat_turn(user_id, "使用者上傳了一張圖片。", final_reply_text)
    except:
        print(traceback.format_exc())


# =========================
# 11. Web API 路由 (供官網外包廠商對接)
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
        lang_instruction = get_language_instruction(user_msg)  # 取得語系強制令

        prompt = f"{lang_instruction}\n{SYSTEM_PROMPT}\n{brand_instruction}\n對話紀錄:\n{chat_history_text}\n最新文字問題：{user_msg}"
        response = model.generate_content(prompt)
        
        if response and hasattr(response, "text") and response.text:
            reply_text = response.text.strip()
            save_chat_turn(user_id, user_msg, reply_text)
            return jsonify({"status": "success", "reply": reply_text}), 200
        else:
            return jsonify({"status": "error", "reply": "目前 AI 回應為空，請再試一次。"}), 200
    except Exception as e:
        print(f"Web Chat Error: {str(e)}")
        return jsonify({"status": "error", "reply": "系統忙碌中，請稍後再試。"}), 500


# =========================
# 12. Run app
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
