import logging
import os
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

cred = credentials.Certificate('firebase-credentials.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

MAP_URL = "https://haochie.github.io/Seer/dashboard.html"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    web_app_button = KeyboardButton(text="🗺️ Open Tactical Map", web_app=WebAppInfo(url=MAP_URL))
    keyboard = ReplyKeyboardMarkup([[web_app_button]], resize_keyboard=True)

    msg = (
        "Welcome to the Outfield BMS System.\n\n"
        "1️⃣ First, register your callsign: `/register <role> <callsign>`\n"
        "*(Roles: troop, safety, conducting)*\n"
        "*(Example: /register troop Platoon 1)*\n\n"
        "2️⃣ Attach your 📍 *Live Location* to broadcast your position.\n\n"
        "🚨 Emergency: Type `/sos` to trigger a CASEVAC ping.\n"
        "🛑 End Exercise: Type `/endex` to wipe the map."
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown', reply_markup=keyboard)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registers a user's role and callsign to Firebase."""
    user_id = str(update.message.from_user.id)
    
    # Check if they provided arguments
    if len(context.args) < 2:
        await update.message.reply_text("Format incorrect. Use: /register <role> <callsign>\nExample: /register safety CPT Lee")
        return
        
    role = context.args[0].lower()
    callsign = " ".join(context.args[1:]) # Joins the rest of the words as the callsign
    
    if role not in ['troop', 'safety', 'conducting']:
        await update.message.reply_text("Invalid role. Choose: troop, safety, or conducting.")
        return

    # Save to a dedicated 'users' collection
    db.collection('users').document(user_id).set({
        'callsign': callsign,
        'role': role
    })
    
    await update.message.reply_text(f"✅ Registered successfully as {callsign} ({role.upper()}). You may now share your Live Location.")

async def trigger_sos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flags the user as an emergency on the map."""
    user_id = str(update.message.from_user.id)
    
    # Check if they are currently active on the map
    doc_ref = db.collection('active_units').document(user_id)
    doc = doc_ref.get()
    
    if doc.exists:
        doc_ref.update({'sos': True})
        await update.message.reply_text("🚨 EMERGENCY PING SENT. Your marker is flashing red on the command map.")
        # Future enhancement: Send a message to a Safety Group Chat here!
    else:
        await update.message.reply_text("❌ We cannot find your location. Please share your Live Location first.")

async def end_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wipes the map by deleting all active locations."""
    # Note: In a real app, you would check if this user is an OIC before letting them wipe the map!
    active_units = db.collection('active_units').stream()
    count = 0
    for unit in active_units:
        db.collection('active_units').document(unit.id).delete()
        count += 1
        
    await update.message.reply_text(f"🛑 ENDEX Called. Map wiped clean. ({count} units removed).")

async def handle_live_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers whenever a user's live location updates."""
    message = update.edited_message or update.message
    
    if message and message.location:
        lat = message.location.latitude
        lng = message.location.longitude
        user_id = str(message.from_user.id)
        
        # 1. Look up their registered callsign from the database
        user_doc = db.collection('users').document(user_id).get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            display_name = user_data.get('callsign')
            role = user_data.get('role')
        else:
            # Fallback if they forgot to register
            display_name = message.from_user.first_name
            role = 'troop'

        # 2. Update their live position. Use set(..., merge=True) so we don't overwrite an active SOS flag!
        db.collection('active_units').document(user_id).set({
            'name': display_name,
            'lat': lat,
            'lng': lng,
            'role': role,
            'timestamp': firestore.SERVER_TIMESTAMP
        }, merge=True) 
        
        logging.info(f"📍 Update: {display_name}: Lat {lat}, Lng {lng}")

if __name__ == '__main__':
    token = os.getenv('BOT_TOKEN')
    application = ApplicationBuilder().token(token).build()
    
    # Register the new commands
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('register', register))
    application.add_handler(CommandHandler('sos', trigger_sos))
    application.add_handler(CommandHandler('endex', end_exercise))
    application.add_handler(MessageHandler(filters.LOCATION, handle_live_location))
    
    print("BMS System online...")
    application.run_polling()
