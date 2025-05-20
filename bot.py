import os
import json
import random
import datetime
import aiohttp
import asyncio
import braintree
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = "7928470785:AAHMz54GOWoI-NsbD2zyj0Av_VbnqX7fYzI"  # Replace with your bot token
OWNER_ID = 8179218740  # Replace with your Telegram ID
APPROVED_FILE = "approved.json"

# ========== BRAINTREE CONFIG ==========
braintree.Configuration.configure(
    braintree.Environment.Sandbox,
    merchant_id="q3hwsdcgv5vdxphb",
    public_key="8c64vknj8d38nznb",
    private_key="271bf4fb8d331458a307eb3c276b9a26"
)

# ========== UTILITIES ==========

def load_approved():
    if not os.path.exists(APPROVED_FILE):
        return {}
    with open(APPROVED_FILE, "r") as f:
        return json.load(f)

def save_approved(data):
    with open(APPROVED_FILE, "w") as f:
        json.dump(data, f)

def is_approved(user_id):
    data = load_approved()
    if str(user_id) in data:
        expiry = datetime.datetime.strptime(data[str(user_id)], "%Y-%m-%d")
        if expiry >= datetime.datetime.now():
            return True
        else:
            del data[str(user_id)]
            save_approved(data)
    return False

async def fetch_bin_info(bin_code):
    url = f"https://lookup.binlist.net/{bin_code}"
    headers = {"Accept-Version": "3"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            return None

def generate_card(bin_code):
    cc_number = bin_code + ''.join(str(random.randint(0, 9)) for _ in range(16 - len(bin_code)))
    month = str(random.randint(1, 12)).zfill(2)
    year = str(random.randint(datetime.datetime.now().year + 1, 2035))
    cvv = str(random.randint(100, 999))
    return f"{cc_number}|{month}|{year}|{cvv}"

def check_card_braintree(card_number, exp_month, exp_year, cvv):
    try:
        result = braintree.Transaction.sale({
            "amount": "1.00",
            "credit_card": {
                "number": card_number,
                "expiration_month": exp_month,
                "expiration_year": exp_year,
                "cvv": cvv
            },
            "options": {
                "submit_for_settlement": False
            }
        })
        if result.is_success:
            return "Approved", "Transaction successful"
        else:
            return "Declined", result.message
    except Exception as e:
        return "Declined", str(e)

# ========== COMMAND HANDLERS ==========

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! I am your Credit Card Generator and Checker Bot.\n\n"
        "Available commands:\n"
        "/gen <bin> - Generate cards for a BIN\n"
        "/chk <card> - Check a card (format: number|month|year|cvv)\n"
        "/mass - Check multiple cards at once (up to 10, one per line)\n\n"
        "Note: You must be approved to use commands. Contact the bot owner."
    )

async def gen_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_approved(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /gen <bin>\nExample: /gen 516989")
        return

    bin_code = args[0]
    if len(bin_code) < 6:
        await update.message.reply_text("BIN must be at least 6 digits.")
        return

    bin_info = await fetch_bin_info(bin_code)
    if not bin_info:
        await update.message.reply_text("Invalid or unsupported BIN.")
        return

    cards = [generate_card(bin_code) for _ in range(10)]
    msg = f"Bin → {bin_code}\nAmount → 10\n\n" + "\n".join(cards)
    msg += f"\n\nBin Info: {bin_info.get('scheme','').upper()} - {bin_info.get('type','').upper()} - {'PREPAID' if bin_info.get('prepaid') else 'NOT PREPAID'}"
    msg += f"\nBank: {bin_info.get('bank', {}).get('name','N/A')}"
    msg += f"\nCountry: {bin_info.get('country', {}).get('name','N/A')} {bin_info.get('country', {}).get('emoji','')}"
    await update.message.reply_text(msg)

async def chk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_approved(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /chk <cc>\nExample: /chk 4111111111111111|12|2026|123")
        return

    card = args[0]
    await update.message.reply_text("🔍 Checking...")
    try:
        number, month, year, cvv = card.split("|")
        if len(number) < 12 or len(month) not in (1,2) or len(year) not in (2,4) or len(cvv) not in (3,4):
            raise ValueError("Invalid card parts length")

        # Fix year format (support YY or YYYY)
        if len(year) == 2:
            year = "20" + year

        status, result = check_card_braintree(number, month, year, cvv)
        bin_info = await fetch_bin_info(number[:6])
        bank = bin_info.get('bank', {}).get('name','N/A')
        country = bin_info.get('country', {}).get('name','N/A')
        emoji = bin_info.get('country', {}).get('emoji','')
        brand = bin_info.get('scheme','').upper()
        card_type = bin_info.get('type','').upper()
        prepaid = 'PREPAID' if bin_info.get('prepaid') else 'NOT PREPAID'

        msg = f"""
Card ↯ {card}
Status - {"✅ Approved" if status=="Approved" else "❌ Declined"}
Result -⤿ {result} ⤾

💳 Brand: {brand}
🏦 Bank: {bank}
🌎 Country: {country} {emoji}
💼 Type: {card_type} - {prepaid}
Gateway: Stripe Auth
Checked by: @{update.effective_user.username or 'User'}
"""
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid card format or error: {e}")

async def mass_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_approved(user_id):
        await update.message.reply_text("❌ You are not approved to use this command.")
        return

    text = update.message.text.replace("/mass", "").strip()
    cards = [c.strip() for c in text.split("\n") if c.strip()]
    if not cards or len(cards) > 10:
        await update.message.reply_text("Send up to 10 cards after /mass, one per line.")
        return

    await update.message.reply_text("Checking cards...")
    replies = []

    for card in cards:
        try:
            number, month, year, cvv = card.split("|")
            if len(year) == 2:
                year = "20" + year

            status, result = check_card_braintree(number, month, year, cvv)
            bin_info = await fetch_bin_info(number[:6])
            brand = bin_info.get('scheme','').upper()
            bank = bin_info.get('bank', {}).get('name','N/A')
            country = bin_info.get('country', {}).get('name','N/A')
            emoji = bin_info.get('country', {}).get('emoji','')
            card_type = bin_info.get('type','').upper()
            prepaid = 'PREPAID' if bin_info.get('prepaid') else 'NOT PREPAID'
            msg = f"Card ↯ {card} → {'✅ Approved' if status == 'Approved' else '❌ Declined'} → {result}"
            replies.append(msg)
        except Exception:
            replies.append(f"{card} → Invalid Format ❌")

    replies.append(f"\nChecked by: @{update.effective_user.username or 'User'}")
    await update.message.reply_text("\n".join(replies))

async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage: /add <id> <days>\nExample: /add 123456789 5")
        return

    user_id, days = args[0], int(args[1])
    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    data = load_approved()
    data[user_id] = expiry_date
    save_approved(data)
    await update.message.reply_text(f"✅ User {user_id} approved until {expiry_date}")

async def remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remove <id>\nExample: /remove 123456789")
        return

    user_id = args[0]
    data = load_approved()
    if user_id in data:
        del data[user_id]
        save_approved(data)
        await update.message.reply_text(f"✅ User {user_id} removed.")
    else:
        await update.message.reply_text("❌ User not found.")

async def lists_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    data = load_approved()
    if not data:
        await update.message.reply_text("No approved users.")
        return

    msg = "✅ Approved Users:\n"
    for user_id, expiry in data.items():
        msg += f"- {user_id} → till {expiry}\n"
    await update.message.reply_text(msg)

# ========== MAIN ==========

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("gen", gen_handler))
    app.add_handler(CommandHandler("chk", chk_handler))
    app.add_handler(CommandHandler("mass", mass_handler))
    app.add_handler(CommandHandler("add", add_handler))
    app.add_handler(CommandHandler("remove", remove_handler))
    app.add_handler(CommandHandler("lists", lists_handler))
    print("🤖 Bot is running... Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
