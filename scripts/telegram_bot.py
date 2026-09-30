from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
import subprocess
import os

# Stub functions to simulate Gemini CLI calls
def call_gemini_send_invoice(invoice_id):
    print(f"Calling: gemini send-invoice --invoice_id={invoice_id}")
    # subprocess.run(['gemini', 'send-invoice', f'--invoice_id={invoice_id}'])

async def approve_invoice(update: Update, context):
    """Показывает счёт для подтверждения"""
    # Вызывается из Gemini CLI после prepare-invoice
    # context.args would be passed if running as a bot command, 
    # but here we might trigger it differently.
    
    # Mock data
    invoice_data = {
        'id': '2026-02-Romashka',
        'client': 'Ромашка ООО',
        'amount': 67500,
        'pdf_url': 'https://example.com/invoice.pdf' 
    }
    
    if context.args:
        # Parse args logic here if needed
        pass
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, отправить", callback_data=f"send_{invoice_data['id']}")],
        [InlineKeyboardButton("✏️ Изменить сумму", callback_data=f"edit_{invoice_data['id']}")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{invoice_data['id']}")]
    ]
    
    # In a real scenario, we'd need to handle sending the file
    await update.message.reply_text(
        f"Счёт для {invoice_data['client']}\nСумма: {invoice_data['amount']}₽\nPDF: {invoice_data['pdf_url']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_approval(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    action = data[0]
    invoice_id = data[1] if len(data) > 1 else None
    
    if action == "send":
        call_gemini_send_invoice(invoice_id)
        await query.edit_message_text(text=f"📬 Отправляю счёт {invoice_id}...")
    elif action == "cancel":
        await query.edit_message_text(text=f"❌ Отменено: {invoice_id}")
    elif action == "edit":
        await query.edit_message_text(text=f"✏️ Функция редактирования пока не доступна.")

def main():
    """Start the bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set!")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("approve_test", approve_invoice))
    application.add_handler(CallbackQueryHandler(handle_approval))

    application.run_polling()

if __name__ == "__main__":
    print("Telegram Bot Script Loaded.")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        print("Bot Token: Found")
    else:
        print("Bot Token: Not Set (Expected for mock)")
    
    # main() # Commented out to prevent blocking verify loop
