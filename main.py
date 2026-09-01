import json
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Setup Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 1. Konfigurasi Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON") # String JSON isi kredensial

# Init Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. Inisialisasi Google Sheets Connection
def get_sheets_client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).sheet1

# System Instruction untuk ekstraksi JSON dari AI
SYSTEM_PROMPT = """
Anda adalah asisten pencatat keuangan. Tugas Anda adalah menguji input berupa teks atau foto struk/nota, lalu mengekstrak informasi keuangan menjadi format JSON terstruktur murni (TANPA MARKDOWN ```json ```).

Format JSON WAJIB seperti berikut:
{
  "tanggal": "YYYY-MM-DD",
  "jenis": "Pengeluaran" atau "Pemasukan",
  "kategori": "Makanan/Transportasi/Belanja/Gaji/dll",
  "nominal": 50000,
  "keterangan": "Deskripsi singkat item/layanan",
  "metode": "Cash/QRIS/Transfer/Kartu"
}

Aturan:
- Nilai nominal HARUS berupa angka saja (tanpa Rp, titik, atau koma).
- Jika tanggal tidak tertera di foto/teks, gunakan tanggal hari ini.
- Kembalikan HANYA string JSON murni.
"""

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Selamat datang di Bot Catat Keuangan!**\n\n"
        "Kirimkan foto struk belanjaan Anda atau ketik transaksi langsung.\n"
        "Contoh: *Beli bensin 30rb cash*"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Memproses data dengan AI...")
    
    try:
        content_to_send = [SYSTEM_PROMPT]

        # Cek jika input berupa Foto
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = await photo_file.download_as_bytearray()
            
            image_part = {
                "mime_type": "image/jpeg",
                "data": bytes(photo_bytes)
            }
            content_to_send.append(image_part)
            
            # Tambahkan caption jika ada
            if update.message.caption:
                content_to_send.append(update.message.caption)
        
        # Cek jika input berupa Teks
        elif update.message.text:
            content_to_send.append(f"Input Transaksi: {update.message.text}")

        # Panggil Gemini API
        response = model.generate_content(content_to_send)
        clean_json_str = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(clean_json_str)

        # Catat ke Google Sheets
        sheet = get_sheets_client()
        row_data = [
            data.get("tanggal", ""),
            data.get("jenis", "Pengeluaran"),
            data.get("kategori", "Lain-lain"),
            data.get("nominal", 0),
            data.get("keterangan", "-"),
            data.get("metode", "-")
        ]
        sheet.append_row(row_data)

        # Balas ke user
        reply_msg = (
            f"✅ **Transaksi Berhasil Dicatat!**\n\n"
            f"📅 Tanggal: {data.get('tanggal')}\n"
            f"📌 Jenis: {data.get('jenis')}\n"
            f"🏷️ Kategori: {data.get('kategori')}\n"
            f"💰 Nominal: Rp {data.get('nominal'):,}\n"
            f"📝 Keterangan: {data.get('keterangan')}\n"
            f"💳 Metode: {data.get('metode')}"
        )
        await msg.edit_text(reply_msg, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text("❌ Gagal memproses transaksi. Pastikan format foto atau teks jelas.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    
    print("Bot sedang berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()