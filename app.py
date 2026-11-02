import base64
import os
from flask import Flask, abort, request
from groq import Groq
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    ImageMessage,
    MessageEvent,
    TextMessage,
    TextSendMessage,
)

app = Flask(__name__)

# 初始化 Groq 客戶端（會自動讀取環境變數中的 GROQ_API_KEY）
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# LINE Bot 設定
line_bot_api = LineBotApi(os.environ.get("LINE_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_SECRET"))

# 完整的 System Prompt（包含所有產品邊界、排查步驟與 2FA 規則）
SYSTEM_PROMPT = """
您是 ioNetworks 的專業 AI 技術支援客服機器人（io-bot），專門協助處理 ioNetworks 相關監控與 AI 產品的技術諮詢與故障排查。

【產品範圍與規則】
- EZ Pro: 專業監控管理軟體 (VMS)。
  *【API 文件取得方式】:
    - 注意：EZ Pro API 文件為互動式網頁介面（無 PDF 檔），且「無法」從 EZ Pro Client 客戶端直接開啟。
    - 正確步驟：
      1. 開啟瀏覽器輸入 `http://<您的伺服器IP>:7001`（若跳出安全性警告請點選「繼續前往」）。
      2. 輸入 EZ Pro 帳號密碼登入 Web Admin 頁面。
      3. 點選頂端選單的「伺服器名稱 (房子圖案)」。
      4. 找到「開發人員使用」區塊，點擊「API 文件」即可進入互動式 API 工具。

  *【帳號登入與雙重認證 (2FA/雙因子認證/兩階段驗證)】:
    - 當使用者詢問是否支援 2FA/雙因子認證/雙重認證時，請務必分情境說明：
      1. 本地端帳號 (Local Account)：登入 Client 時「不支援」2FA 雙重認證。
      2. 雲端帳號 (EZ Pro Cloud Account)：透過 EZ Pro Cloud 帳號登入與綁定時「支援」2FA 雙重認證機制。

  *【特殊常見障礙與排除】:
    1. 映像錯誤 / .dll 檔案無法執行 (錯誤狀態 0xc0e90002 / nx_fusion.dll 非設計為在 Windows 上執行 / Client 無法開啟)：
       - 原因：Windows (特別是新筆電/Win11) 開啟了「智慧型應用程式控制 (Smart App Control)」，將系統組件封鎖。
       - 解法：請至 Windows「設定」->「隱私權與安全性」->「Windows 安全性」->「應用程式與瀏覽器控制」->「智慧型應用程式控制」，將其切換為「關閉」。
    2. 點擊 Client 無反應 (但在工作管理員背景有執行進程)：
       - 原因：Client 組件/快取檔損壞。
       - 解法：先卸載 Client，並至安裝路徑 `C:\\Program Files\\ioEZ INC\\EZ Pro\\Client\\` 刪除相應版本資料夾，最後重新安裝 Client 即可。

- Lume Face: 公司自主開發的臉部辨識系統 (中央管理系統/Web管理介面，絕非 Nx Witness，請勿將兩者混為一談)。
  * 運行環境：以 Docker Container 容器方式運行於主機上。
  * 預設服務 Port：7022 (Web 管理介面預設通道)。
  * 標準排查步驟：
    1. 檢查 Docker 服務與容器狀態：請執行 `docker ps` 確認 lumeface 容器是否正在運行 (Up 狀態)。若已停止，請執行 `docker restart lumeface`。
    2. 檢查 Port 7022 通道：確認 Port 7022 未被其他服務占用，且伺服器防火牆與網路防火牆已允許 7022 Port。
    3. 檢查 IP 與網頁存取：確認瀏覽器輸入格式為 `http://<伺服器IP>:7022`，並可嘗試使用無痕模式排除瀏覽器快取問題。

- Nx Witness: 合作/整合之第三方 VMS 軟體。

【回應原則與邊界聲明】
1. 聚焦單一產品：無論使用者詢問哪一個產品，除非使用者主動提及，否則回覆中「絕對禁止」主動引述其他產品干擾。
2. 嚴禁幻覺與硬套指令：若使用者提及的專有名詞或產品名稱在知識庫中尚未有詳細技術指令，請給出通用排查步驟。
3. 嚴格邊界控制：若使用者詢問與 ioNetworks 產品無關的通用知識、生活聊天或無關技術，請禮貌拒絕並引導回產品技術支援。
"""


# 自動動態偵測 Groq 文字可用模型的函式
def get_working_model():
  try:
    models = groq_client.models.list()
    for m in models.data:
      if "gpt" in m.id or "llama" in m.id or "mixtral" in m.id:
        return m.id
    if models.data:
      return models.data[0].id
  except Exception as e:
    print(f"自動偵測模型失敗: {e}")
  return "openai/gpt-oss-20b"


def call_groq_ai(user_message):
  try:
    active_model = get_working_model()
    chat_completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        model=active_model,
        temperature=0.3,
    )
    return chat_completion.choices[0].message.content
  except Exception as e:
    print(f"Groq API Error: {e}")
    return "抱歉，系統暫時無法處理您的請求，請稍後再試。"


@app.route("/callback", methods=["POST"])
def callback():
  signature = request.headers["X-Line-Signature"]
  body = request.get_data(as_text=True)
  app.logger.info("Request body: " + body)
  try:
    handler.handle(body, signature)
  except InvalidSignatureError:
    abort(400)
  return "OK"


# 處理文字訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
  user_msg = event.message.text
  ai_reply = call_groq_ai(user_msg)
  line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ai_reply))


# 動態自動偵測 Groq 可用的 Vision 視覺模型
def get_working_vision_model():
  try:
    models = groq_client.models.list()
    for m in models.data:
      model_id = m.id.lower()
      # 自動尋找包含 vision 或 llava 的模型代號
      if "vision" in model_id or "llava" in model_id:
        return m.id
    # 如果清單中找不到，預設嘗試常見代號
    return "meta-llama/llama-4-vision-11b"
  except Exception as e:
    print(f"動態偵測 Vision 模型失敗: {e}")
    return "meta-llama/llama-4-vision-11b"


# 處理圖片訊息事件（動態尋找 Vision 模型進行精準圖文解析）
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
  message_id = event.message.id
  try:
    # 取得 LINE 傳來的圖片二進位內容
    message_content = line_bot_api.get_message_content(message_id)
    image_bytes = b"".join(message_content.iter_content())

    # 將圖片轉為 Base64 格式
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{base64_image}"

    # 動態取得當前可用的 Vision 模型
    active_vision_model = get_working_vision_model()
    print(f"當前使用的 Vision 模型: {active_vision_model}")

    # 呼叫 Groq 視覺模型進行看圖解析，並結合 SYSTEM_PROMPT 知識庫
    chat_completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "請幫我分析這張錯誤截圖或畫面，對照系統知識庫指出可能發生的狀況與具體的排除解法。"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        model=active_vision_model,  # 使用動態抓到的 Vision 模型
        temperature=0.3,
    )
    reply_text = chat_completion.choices[0].message.content

  except Exception as e:
    print(f"圖片辨識發生錯誤: {e}")
    reply_text = (
        "抱歉，目前視覺辨識模型連線異常或正在更新中，請將畫面上的錯誤代碼或文字直接發送給我，我將立即為您提供排除指引！"
    )

  line_bot_api.reply_message(
      event.reply_token, TextSendMessage(text=reply_text)
  )


if __name__ == "__main__":
  app.run(port=5000)
