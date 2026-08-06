import os
import re
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
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
- 控制篇幅精簡：回覆請維持「重點排查與關鍵指令」即可，務必精簡扼要（點到為止），切勿列舉過多冷門情境或冗長說明，避免因字數過長導致使用者閱讀困難。
- 遇到無關/非技術問題（如：股市、天氣、聊天等），請「用簡短一句話拒絕」即可（例：抱歉，我僅能提供 IT 與安防監控系統相關的技術支援。），「絕對不要」在結尾列舉或列出所有產品名稱（如 AIONXIS、EZ Pro 等）。

【產品與專有名詞字典定義】
- AIONXIS：公司自主開發的中控系統（中央管理系統/Web管理介面），絕非 Nx Witness，請勿將兩者混為一談。
  * 運行環境：以 Docker Container 容器方式運行於主機上。
  * 預設服務 Port：7045 (Web 管理介面預設通道)。
  * 標準排查步驟：
    1. 檢查 Docker 服務與容器狀態：請執行 `docker ps` 確認 AIONXIS 容器是否正常運行 (Up 狀態)。若已停止，請執行 `docker restart <container_name>`。
    2. 檢查 Port 7045 通道：確認 Port 7045 未被其他服務占用，且伺服器防火牆 (如 ufw 或 iptables) 與網路防火牆已允許 7045 Port 通訊。
    3. 檢查 IP 與網頁存取：確認瀏覽器輸入格式為 `http://<伺服器IP>:7045`，並可嘗試使用無痕模式排除瀏覽器快取問題。
- Lume Face : 公司自主開發的臉部辨識系統（中央管理系統/Web管理介面），絕非 Nx Witness，請勿將兩者混為一談。
  * 運行環境：以 Docker Container 容器方式運行於主機上。
  * 預設服務 Port：7022 (Web 管理介面預設通道)。
  * 標準排查步驟：
    1. 檢查 Docker 服務與容器狀態：請執行 `docker ps` 確認 lumeface 容器是否正常運行 (Up 狀態)。若已停止，請執行 `docker restart <container_name>`。
    2. 檢查 Port 7022 通道：確認 Port 7022 未被其他服務占用，且伺服器防火牆 (如 ufw 或 iptables) 與網路防火牆已允許 7022 Port 通訊。
    3. 檢查 IP 與網頁存取：確認瀏覽器輸入格式為 `http://<伺服器IP>:7022`，並可嘗試使用無痕模式排除瀏覽器快取問題。
- EZ Pro：專業監控管理軟體 (VMS)。
  *【API 文件取得方式】:
    - 注意：EZ Pro API 文件為互動式網頁介面（無 PDF 檔），且「無法」從 EZ Pro Client 客戶端直接開啟。
    - 正確步驟：
      1. 開啟瀏覽器輸入 `http://<您的伺服器IP>:7001`（若跳出安全性警告請點選「繼續前往」）。
      2. 輸入 EZ Pro 帳號密碼登入 Web Admin 頁面。
      3. 點選頂端選單的「伺服器名稱（房子圖案）」。
      4. 找到「開發人員使用」區塊，點擊「API 文件」即可進入互動式 API 工具。
  *【特殊常見障礙與排除】:
    1. 映像錯誤 / .dll 檔案無法執行 (錯誤狀態 0xc0e90002 / nx_fusion.dll 非設計為在 Windows 上執行 / Client 無法開啟)：
       - 原因：Windows (特別是新筆電/Win11) 開啟了「智慧型應用程式控制 (Smart App Control)」，將系統組件封鎖。
       - 解法：請至 Windows「設定」->「隱私權與安全性」->「Windows 安全性」->「應用程式與瀏覽器控制」->「智慧型應用程式控制」，將其切換為「關閉」。
    2. 點擊 Client 無反應 (但在工作管理員背景有執行進程)：
       - 原因：Client 組件/快取檔損壞。
       - 解法：先卸載 Client，並至安裝路徑 `C:\\Program Files\\ioEZ INC\\EZ Pro\\Client\\` 刪除相應版本資料夾（如 `5.1.5.39242` 等殘留資料夾），最後重新安裝 Client 即可。
- Nx Witness：合作/整合之第三方 VMS 軟體。

【回應原則與邊界聲明】
1. 聚焦單一產品：無論使用者詢問哪一個產品（包括 EZ Pro、Lume Face、AIONXIS 等），除非使用者主動提及，否則回覆中「絕對禁止」主動引述或帶出任何其他產品名稱、Port 或指令（例如問 Lume Face 就絕不能出現 AIONXIS 或 Port 7045），避免造成使用者混淆。
2. 嚴禁幻覺與硬套指令：若使用者提及的專有名詞或產品名稱（如：AIONXIS、跌倒偵測等）在知識庫中尚未有詳細技術指令，請給出通用排查步驟（如：服務進程、網頁 Web Port、網路連線、防火牆），「絕對禁止」將其硬套成 Nx Witness 或 EZ Pro 的指令。
3. 當遇到「網頁/中控系統（如 AIONXIS）打不開」時的通用標準步驟：
   - 檢查系統服務 (Service / Daemon) 是否正常運行。
   - 檢查 Web Port (例如 80/443/8080) 是否被占用或遭防火牆擋下。
   - 檢查連線 IP 與瀏覽器快取。
4. 若遇到目前系統尚未正式搭載的模組（如：臉部辨識、跌倒偵測等），可說明該功能屬於進階/擴充模組，排查時請先確認授權與模組載入狀態。
5. 主動引導與明確提問：若使用者僅輸入陳述句或模糊需求（例如僅提及 BIOS、硬碟、網路等），切勿僅覆述問題或空泛詢問。請主動列出該領域最常見的 2~3 個排查重點（如 BIOS 請優先提醒檢查 Boot 啟動順序、Secure Boot 或硬碟識別），並親切詢問是否需要具體操作步驟。
6. 無法解決時的收斂引導（所有語言回覆的最後「務必」包含以下引導）：
   - 當標準排查步驟無法解決問題或屬於硬體故障時，嚴禁要求使用者提供硬體品牌或型號（後台無此資料）。
   - 請嚴格依據使用者發問語言/地區進行分流：
     * 僅限「台灣 / 繁體中文使用者」：
       「若上述步驟仍無法解決，請填寫線上維修表單將產品送回檢測：
       👉 維修申請表單：https://forms.gle/skxA1sSvrSzrZeji8」
     * 所有「非繁體中文 / 海外地區使用者」（包含英文、日文、韓文等所有外語）：
       嚴禁出現任何 Google 表單連結 (`forms.gle`)！請翻譯成該國語言，引導聯繫經銷商或 Email：
       「若上述步驟仍無法解決，請優先聯繫您的原購買經銷商/代理商取得在地支援；或將問題描述與設備狀況 Email 至官方客服信箱（ support@ionetworks.co ），由專人為您服務。」"""

# ==========================================
# 4. 快取記憶體
# ==========================================
CHAT_HISTORY = {}

# ==========================================
# 5. Helper Functions & 多語系招呼語與辨識器
# ==========================================
def fetch_nx_forum_knowledge(query_text: str) -> str:
    """幕後向 Nx 官方論壇 API 搜尋參考技術文章"""
    url = "https://support.networkoptix.com/hc/en-us/api/v2/community/posts/search.json"
    params = {'query': query_text, 'per_page': 2}
    try:
        response = requests.get(url, params=params, timeout=4)
        if response.status_code == 200:
            posts = response.json().get('posts', [])
            extracted_info = ""
            for post in posts:
                title = post.get('title', '')
                details = post.get('details', '')
                extracted_info += f"標題: {title}\n內容摘要: {details[:500]}\n---\n"
            return extracted_info if extracted_info else ""
    except Exception as e:
        print(f"Nx Forum Search Exception: {e}")
    return ""


def get_header_notice(lang_code: str) -> str:
    """根據語言回傳對應的招呼語與保留提示"""
    if lang_code == 'ja':
        return "こんにちは、io-botです。お役に立てて光栄です。\n注意：トラブルシューティングの文脈を考慮するため、直近3回の会話は約15分間一時的に保持されます。"
    elif lang_code == 'ko':
        return "안녕하세요, io-bot입니다. 도움이 되어 기쁩니다.\n참고: 문제 해결 맥락을 유지하기 위해 최근 3회의 대화는 약 15분간 임시 저장됩니다."
    elif lang_code == 'en':
        return "Hello, I am io-bot. Happy to assist you.\nNotice: To help continue the troubleshooting context, the last 3 turns of conversation will be kept for about 15 minutes."
    else:
        # 預設為繁體中文
        return "您好，我是 io-bot，很高興為您提供協助。\n提醒：系統會暫時保留最近 3 輪對話約 15 分鐘，以協助延續排查脈絡。"


def get_language_info(text: str):
    """傳回 (語系指令, 語言代碼)"""
    if not text:
        return "", "zh"

    # 1. 檢測是否包含日文假名
    if re.search(r'[\u3040-\u30ff]', text):
        instruction = "\n【⚠️最高指令：偵測到使用者使用日文，請「完全使用日文(日本語)」回覆！注意：日本屬於海外地區，若需要客服支援，請「絕對禁止」附上 Google 表單連結，務必僅提供聯繫經銷商或 Email (support@ionetworks.co)！】\n"
        return instruction, "ja"

    # 2. 檢測是否包含韓文字母
    if re.search(r'[\uac00-\ud7af\u1100-\u11ff]', text):
        instruction = "\n【⚠️最高指令：偵測到使用者使用韓文，請「完全使用韓文(한국어)」回覆！注意：韓國屬於海外地區，若需要客服支援，請「絕對禁止」附上 Google 表單連結，務必僅提供聯繫經銷商或 Email (support@ionetworks.co)！】\n"
        return instruction, "ko"

    # 3. 只要含有 Unicode 漢字，認定為中文
    if re.search(r'[\u4e00-\u9fff]', text):
        instruction = "\n【⚠️最高指令：使用者輸入中文，請務必完全使用「繁體中文（台灣常用技術用語）」回覆整篇內容，絕不允許出現韓文、日文或英文！】\n"
        return instruction, "zh"

    # 4. 純英文由 langdetect 判斷
    try:
        lang = detect(text)
        if lang == 'en':
            instruction = "\n【⚠️最高指令：偵測到使用者使用英文，請「完全使用英文(English)」回覆！注意：英文使用者屬於海外地區，請「絕對禁止」附上 Google 表單連結，務必僅提供聯繫經銷商或 Email (support@ionetworks.co)！】\n"
            return instruction, "en"
    except:
        pass

    # 5. 保底機制
    instruction = "\n【⚠️最高指令：請完全使用「繁體中文（台灣常用技術用語）」回覆，絕不允許出現韓文、日文或英文！】\n"
    return instruction, "zh"


def default_error_reply(lang_code: str, message: str) -> str:
    header = get_header_notice(lang_code)
    return f"{header}\n\n{message}"


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
# 7. LINE 訊息事件處理邏輯 (文字訊息)
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = get_user_id(event)
    user_msg = event.message.text.strip()

    lang_instruction, lang_code = get_language_info(user_msg)
    header_notice = get_header_notice(lang_code)

    if user_id not in CHAT_HISTORY:
        CHAT_HISTORY[user_id] = []

    history = CHAT_HISTORY[user_id][-6:]

    # 判斷是否需要向 Nx 論壇進行幕後搜尋
    is_ezpro_query = any(keyword in user_msg.lower() for keyword in ['ez pro', 'ezpro', 'vms', '錄影', '監控', 'nx'])
    forum_context = ""
    if is_ezpro_query:
        forum_data = fetch_nx_forum_knowledge(user_msg)
        if forum_data:
            forum_context = f"\n\n【幕後搜尋到的第三方技術討論參考資料（請將其精華融會貫通後回答客戶，絕不要叫客戶自己去看）：】\n{forum_data}"

    try:
        chat = model.start_chat(history=history)
        
        # 【關鍵修復點】：將最高語系指令放置在 Prompt 最頂端與最底部，形成雙重鎖定
        full_prompt = f"""{lang_instruction}

{SYSTEM_PROMPT}
{forum_context}

使用者問題：{user_msg}

【⚠️最後提醒】：請再次確認，你的整篇答覆（包含標題、步驟、專有名詞說明）必須「完全使用與使用者相同的語言（{lang_code}）」進行撰寫！若為非繁中語系，嚴禁出現任何繁體中文或 Google 表單連結！"""

        response = chat.send_message(full_prompt)
        bot_reply = response.text.strip()

        CHAT_HISTORY[user_id].append({"role": "user", "parts": [user_msg]})
        CHAT_HISTORY[user_id].append({"role": "model", "parts": [bot_reply]})
        CHAT_HISTORY[user_id] = CHAT_HISTORY[user_id][-6:]

        final_reply = f"{header_notice}\n\n{bot_reply}"

    except Exception as e:
        print(f"Gemini API Error: {e}")
        final_reply = default_error_reply(lang_code, "抱歉，系統暫時無法處理您的請求，請稍後再試。")

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=final_reply)
    )

# ==========================================
# 8. LINE 訊息事件處理邏輯 (圖片訊息辨識與多語系支援)
# ==========================================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = get_user_id(event)
    
    try:
        # 1. 向 LINE 伺服器取得圖片內容
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = message_content.content

        # 2. 封裝圖片封包供 Gemini 分析
        image_part = {
            "mime_type": "image/jpeg",
            "data": image_bytes
        }

        # 3. 提示 Gemini 自動辨識圖片內的文字語言，並嚴格遵循該語言規範與收斂條款
        image_prompt = f"""{SYSTEM_PROMPT}

【⚠️最高指令：視覺語言自動偵測與回覆規範】
1. 請先辨識這張圖片中的錯誤視窗、介面或系統文字屬於何種語言（繁體中文 / 英文 / 日文 / 韓文 等）。
2. 請「完全使用圖片中的語言」回答排查步驟！
3. 若圖片語言為非繁體中文/海外地區（如日文、韓文、英文），「絕對禁止」附上 Google 表單連結 (forms.gle)，請引導聯繫經銷商或 Email ( support@ionetworks.co )。
4. 開頭請勿重複自我介紹或問候。

請詳細分析圖片中的錯誤訊息與代碼，並給出精準的解決步驟。"""

        # 4. 呼叫 Gemini 視覺多模態生成解答
        response = model.generate_content([image_prompt, image_part])
        bot_reply = response.text.strip()

        # 5. 根據 Gemini 回覆的語言自動搭配頂部招呼語 (Header)
        _, detected_lang = get_language_info(bot_reply)
        header_notice = get_header_notice(detected_lang)

        # 6. 寫入歷史記錄
        if user_id not in CHAT_HISTORY:
            CHAT_HISTORY[user_id] = []
        CHAT_HISTORY[user_id].append({"role": "user", "parts": ["[使用者傳送了一張錯誤截圖]"]})
        CHAT_HISTORY[user_id].append({"role": "model", "parts": [bot_reply]})
        CHAT_HISTORY[user_id] = CHAT_HISTORY[user_id][-6:]

        final_reply = f"{header_notice}\n\n{bot_reply}"

    except Exception as e:
        print(f"Image Handle Error: {e}")
        final_reply = default_error_reply("zh", "抱歉，目前無法解析圖片內容。請嘗試以文字描述您遇到的問題與錯誤代碼。")

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=final_reply)
    )

# ==========================================
# 9. Flask App 啟動
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
