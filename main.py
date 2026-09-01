import json
import logging
import os
from fastapi import FastAPI, Request
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, Bot

# Setup Logging
logging.basicConfig(level=logging.INFO)

# 1. Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") # Contoh: https://nama-app.onrender.com/webhook

# Init Telegram Bot & Gemini
bot = Bot(token=TELEGRAM_BOT_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()

def get_sheets_client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).sheet1

SYSTEM_PROMPT = """
Anda adalah asisten pencatat keuangan. Tugas Anda adalah menguji input berupa teks atau foto struk/nota, lalu mengekstrak informasi keuangan menjadi format JSON terstruktur murni (TANPA MARKDOWN ```json ```).

Format JSON WAJIB:
{
  "tanggal": "YYYY-MM-DD",
  "jenis": "Pengeluaran" atau "Pemasukan",
  "kategori": "Makanan/Transportasi/Belanja/Gaji/dll",
  "nominal": 50000,
  "keterangan": "Deskripsi singkat item/layanan",
  "metode": "Cash/QRIS/Transfer/Kartu"
}
Aturan: Nilai nominal HARUS angka saja. Kembalikan HANYA string JSON murni.
"""

@app.on_event("startup")
async def startup_event():
    # Otomatis mendaftarkan Webhook ke Telegram saat server Render aktif
    if WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Webhook registered to: {WEBHOOK_URL}")

@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot)
    
    if not update or not update.message:
        return {"status": "ok"}
        
    chat_id = update.message.chat_id
    user_name = update.message.from_user.first_name
    
    # Kirim status awal
    sent_msg = await bot.send_message(chat_id=chat_id, text="⏳ Memproses data dengan AI...")

    try:
        content_to_send = [SYSTEM_PROMPT]

        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = await photo_file.download_as_bytearray()
            content_to_send.append({"mime_type": "image/jpeg", "data": bytes(photo_bytes)})
            if update.message.caption:
                content_to_send.append(update.message.caption)
        elif update.message.text:
            content_to_send.append(f"Input Transaksi: {update.message.text}")

        response = model.generate_content(content_to_send)
        clean_json = response.text.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(clean_json)

        # Simpan ke Sheets (Menambahkan kolom Penginput)
        sheet = get_sheets_client()
        sheet.append_row([
            parsed.get("tanggal", ""),
            user_name,
            parsed.get("jenis", "Pengeluaran"),
            parsed.get("kategori", "Lain-lain"),
            parsed.get("nominal", 0),
            parsed.get("keterangan", "-"),
            parsed.get("metode", "-")
        ])

        reply_text = (
            f"✅ **Transaksi Berhasil Dicatat!**\n\n"
            f"👤 Penginput: {user_name}\n"
            f"📅 Tanggal: {parsed.get('tanggal')}\n"
            f"📌 Jenis: {parsed.get('jenis')}\n"
            f"🏷️ Kategori: {parsed.get('kategori')}\n"
            f"💰 Nominal: Rp {parsed.get('nominal'):,}\n"
            f"📝 Keterangan: {parsed.get('keterangan')}\n"
            f"💳 Metode: {parsed.get('metode')}"
        )
        await bot.edit_message_text(chat_id=chat_id, message_id=sent_msg.message_id, text=reply_text, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Error: {e}")
        await bot.edit_message_text(chat_id=chat_id, message_id=sent_msg.message_id, text="❌ Gagal memproses transaksi. Pastikan foto atau teks jelas.")

    return {"status": "ok"}

@app.get("/")
def home():
    return {"status": "Bot server is running!"}
