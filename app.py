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
# 1. 環境變數設定與驗證 (帶排查 Log)
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

# 印出當前抓到的狀態 (出錯時可以一眼看出哪一個是 None)
print("=== 變數載入檢查 ===")
print(f"LINE_ACCESS_TOKEN: {'已設定' if LINE_CHANNEL_ACCESS_TOKEN else '❌ 未設定(None)'}")
print(f"LINE_SECRET:       {'已設定' if LINE_CHANNEL_SECRET else '❌ 未設定(None)'}")
print(f"GEMINI_API_KEY:    {'已設定' if GEMINI_API_KEY else '❌ 未設定(None)'}")

missing_vars = []
if not LINE_CHANNEL_ACCESS_TOKEN: missing_vars.append("LINE_CHANNEL_ACCESS_TOKEN")
if not LINE_CHANNEL_SECRET: missing_vars.append("LINE_CHANNEL_SECRET")
if not GEMINI_API_KEY: missing_vars.append("GEMINI_API_KEY/GOOGLE_API_KEY")

if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==========================================
# 2. 初始化 Gemini 模型 (使用 gemini-2.5-flash-lite)
# ==========================================
genai.configure(api_key=GEMINI_API_KEY, transport="rest")
model = genai.GenerativeModel("gemini-2.5-flash-lite")

# ==========================================
# 3. 系統提示詞 (SYSTEM_PROMPT) - 知識庫與邊界
# ==========================================
SYSTEM_PROMPT = """
你是 io-bot，負責提供專業、親切且條理分明的 IT 與安防監控系統技術支援。

【產品與專有名詞字典定義】
- AIONXIS：公司自主開發的中控系統（中央管理系統/Web管理介面），絕非 Nx Witness，請勿將兩者混為一談。
- EZ Pro：專業監控管理軟體（VMS）。
- Nx Witness：合作/整合之第三方 VMS 軟體。

【邊界與回應原則】
1. 嚴禁幻覺與硬套指令：若使用者提及的產品或模組（如：AIONXIS、臉部辨識、跌倒偵測、中控系統等）在知識庫中尚未有特定的專屬命令，請給出「通用排查步驟」（如：服務進程、網頁 Port 埠號、網路連線、防火牆），絕對禁止將其硬套為 Nx Witness 或 EZ Pro 的專有指令。
2. 網頁/中控系統（如 AIONXIS）打不開時的標準通用排查：
   - 檢查伺服器主機服務 (Service / Daemon) 是否正在運行。
   - 檢查 Web Port (如 80, 443, 8080 等) 是否被占用或遭防火牆擋下。
   - 檢查用戶端與伺服器之間的網路連線 (Ping) 與瀏覽器快取。
3. 若遇到未推出的擴充功能（如臉辨、跌倒偵測），可說明該功能屬於進階/未來規劃模組，排查時請先確認授權與模組狀態。
4. 請始終保持條理清晰，使用條列式步驟引導使用者排查。
"""

MEMORY_NOTICE = "提醒：系統會暫時保留最近 3 輪對話約 15 分鐘，以協助延續排查脈絡。"

# ==========================================
# 4. 快取記憶體 (CHAT_HISTORY)
# ==========================================
CHAT_HISTORY = {}

# ==========================================
# 5. Helper Functions & 語系防禦辨識器
# ==========================================
def get_language_instruction(text: str) -> str:
    """採用多層正則過濾 + langdetect 雙重防禦機制"""
    if not text:
        return ""

    # 1. 檢測是否包含日文假名
    if re.search(r'[\u3040-\u30ff]', text):
        return "\n【⚠️最高指令：偵測到使用者使用日文，請「完全使用日文(日本語)」回覆整篇內容，包含開頭問候語與所有標題結構，絕不允許出現中文或英文！】\n"

    # 2. 檢測是否包含韓文字母
    if re.search(r'[\uac00-\ud7af\u1100-\u11ff]', text):
        return "\n【⚠️最高指令：偵測到使用者使用韓文，請「完全使用韓文(한국어)」回覆整篇內容，包含開頭問候語與所有標題結構，絕不允許出現中文或英文！】\n"

    # 3. 只要含有 Unicode 漢字，100% 認定為中文（防錯字中文被誤判成韓文）
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
    return f"您好，我是 io-bot。\n{MEMORY_NOTICE}\n\n{message}"


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

    # 取得近 3 輪對話文字
    past_messages = CHAT_HISTORY[user_id][-6:]
    history_context = ""
    if past_messages:
        history_context = "\n【過往對話紀錄】\n" + "\n".join(past_messages) + "\n"

    try:
        # 將 Context 統一打包進 Prompt 呼叫 generate_content
        full_prompt = f"{SYSTEM_PROMPT}\n{history_context}\n{lang_instruction}\n使用者最新問題：{user_msg}"
        
        response = model.generate_content(full_prompt)
        bot_reply = response.text.strip()

        # 更新對話歷史紀錄
        CHAT_HISTORY[user_id].append(f"使用者: {user_msg}")
        CHAT_HISTORY[user_id].append(f"io-bot: {bot_reply}")
        CHAT_HISTORY[user_id] = CHAT_HISTORY[user_id][-6:]

        final_reply = f"您好，我是 io-bot。\n{MEMORY_NOTICE}\n\n{bot_reply}"

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
