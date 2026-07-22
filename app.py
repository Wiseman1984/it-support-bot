import os
import re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from langdetect import detect

app = Flask(__name__)

# ==========================================
# 1. 環境變數設定
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or os.getenv("LINE_ACCESS_TOKEN") or ""
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET") or os.getenv("LINE_SECRET") or ""
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==========================================
# 2. 初始化 Gemini 模型
# ==========================================
genai.configure(api_key=GEMINI_API_KEY, transport="rest")
model = genai.GenerativeModel("gemini-2.5-flash-lite")

# ==========================================
# 3. 系統提示詞 (SYSTEM_PROMPT)
# ==========================================
SYSTEM_PROMPT = """你是 io-bot，負責提供專業、親切且條理分明的 IT 與安防監控系統技術支援。

【回覆格式規範】
- 開頭已經有系統統一問候，請「絕對不要」在回覆開頭重複自我介紹或問候（例如切勿輸入：您好！我是 io-bot...），請直接從解答重點開始說明。

【產品與專有名詞字典定義】
- AIONXIS：公司自主開發的中控系統（中央管理系統/Web管理介面），絕非 Nx Witness，請勿將兩者混為一談。
  * 運行環境：以 Docker Container 容器方式運行於主機上。
  * 預設服務 Port：7045 (Web 管理介面預設通道)。
  * 標準排查步驟：
    1. 檢查 Docker 服務與容器狀態：請執行 `docker ps` 確認 AIONXIS 容器是否正常運行 (Up 狀態)。若已停止，請執行 `docker restart <container_name>`。
    2. 檢查 Port 7045 通道：確認 Port 7045 未被其他服務占用，且伺服器防火牆 (如 ufw 或 iptables) 與網路防火牆已允許 7045 Port 通訊。
    3. 檢查 IP 與網頁存取：確認瀏覽器輸入格式為 `http://<伺服器IP>:7045`，並可嘗試使用無痕模式排除瀏覽器快取問題。
- EZ Pro：專業監控管理軟體 (VMS)。
- Nx Witness：合作/整合之第三方 VMS 軟體。

【回應原則與邊界聲明】
1. 嚴禁幻覺與硬套指令：若使用者提及的專有名詞或產品名稱（如：AIONXIS、跌倒偵測等）在知識庫中尚未有詳細技術指令，請給出通用排查步驟（如：服務進程、網頁 Web Port、網路連線、防火牆），「絕對禁止」將其硬套成 Nx Witness 或 EZ Pro 的指令。
2. 當遇到「網頁/中控系統（如 AIONXIS）打不開」時的通用標準步驟：
   - 檢查系統服務 (Service / Daemon) 是否正常運行。
   - 檢查 Web Port (例如 80/443/8080) 是否被占用或遭防火牆擋下。
   - 檢查連線 IP 與瀏覽器快取。
3. 若遇到目前系統尚未正式搭載的模組（如：臉部辨識、跌倒偵測等），可說明該功能屬於進階/擴充模組，排查時請先確認授權與模組載入狀態。"""

# 定義統一的簡短問候開頭
HEADER_NOTICE = "您好，我是 io-bot，很高興為您提供協助。\n提醒：系統會暫時保留最近 3 輪對話約 15 分鐘，以協助延續排查脈絡。"

# ==========================================
# 4. 快取記憶體
# ==========================================
CHAT_HISTORY = {}

# ==========================================
# 5. Helper Functions & 語系防禦辨識器
# ==========================================
def get_language_instruction(text: str) -> str:
    if not text:
        return ""

    # 1. 檢測是否包含日文假名
    if re.search(r'[\u3040-\u30ff]', text):
        return "\n【⚠️最高指令：偵測到使用者使用日文，請「完全使用日文(日本語)」回覆整篇內容，包含開頭問候語與所有標題結構，絕不允許出現中文或英文！】\n"

    # 2. 檢測是否包含韓文字母
    if re.search(r'[\uac00-\ud7af\u1100-\u11ff]', text):
        return "\n【⚠️最高指令：偵測到使用者使用韓文，請「完全使用韓文(한국어)」回覆整篇內容，包含開頭問候語與所有標題結構，絕不允許出現中文或英文！】\n"

    # 3. 只要含有 Unicode 漢字，100% 認定為中文
    if re.search(r'[\u4e00-\u9fff]', text):
        return "\n【⚠️最高指令：使用者輸入中文，請務必完全使用「繁體中文（台灣常用技術用語）」回覆整篇內容，絕不允許出現韓文、日文或英文！】\n"

    # 4. 純英文由 langdetect 判斷
    try:
        lang = detect(text)
        if lang == 'en':
            return "\n【⚠️最高指令：偵測到使用者使用英文，請「完全使用英文(English)」回覆整篇內容，絕不允許出現中文！】\n"
    except:
        pass

    # 5. 保底機制
    return "\n【⚠️最高指令：請完全使用「繁體中文（台灣常用技術用語）」回覆，絕不允許出現韓文、日文或英文！】\n"


def default_error_reply(message: str) -> str:
    return f"{HEADER_NOTICE}\n\n{message}"


def get_user_id(event):
    try:
        return event.source.user_id
    except:
        return "unknown_user"

# ==========================================
# 6. Webhook 進入點
# ==========================================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# ==========================================
# 7. LINE 訊息事件處理邏輯
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = get_user_id(event)
    user_msg = event.message.text.strip()

    lang_instruction = get_language_instruction(user_msg)

    if user_id not in CHAT_HISTORY:
        CHAT_HISTORY[user_id] = []

    history = CHAT_HISTORY[user_id][-6:]

    try:
        chat = model.start_chat(history=history)
        full_prompt = f"{SYSTEM_PROMPT}\n{lang_instruction}\n使用者問題：{user_msg}"
        response = chat.send_message(full_prompt)
        bot_reply = response.text.strip()

        CHAT_HISTORY[user_id].append({"role": "user", "parts": [user_msg]})
        CHAT_HISTORY[user_id].append({"role": "model", "parts": [bot_reply]})
        CHAT_HISTORY[user_id] = CHAT_HISTORY[user_id][-6:]

        final_reply = f"{HEADER_NOTICE}\n\n{bot_reply}"

    except Exception as e:
        print(f"Gemini API Error: {e}")
        final_reply = default_error_reply("抱歉，系統暫時無法處理您的請求，請稍後再試。")

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=final_reply)
    )

# ==========================================
# 8. Flask App 啟動
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
