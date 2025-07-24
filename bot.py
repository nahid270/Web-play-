import os
import asyncio
import threading
import re
from flask import Flask, render_template_string, redirect, request, abort, Response
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, FileIdInvalid
from pymongo import MongoClient

# --- কনফিগারেশন (Configuration) ---
# আপনার সব তথ্য এখানে সরাসরি বসান
# =======================================================================
API_ID = 1234567  # আপনার API ID এখানে বসান
API_HASH = "YOUR_API_HASH"  # আপনার API Hash এখানে বসান
BOT_TOKEN = "YOUR_BOT_TOKEN"  # আপনার বট টোকেন এখানে বসান
MONGO_URI = "YOUR_MONGODB_CONNECTION_STRING"  # আপনার MongoDB কানেকশন স্ট্রিং এখানে বসান

# আপনার ফাইল চ্যানেল এবং ওয়েবসাইটের তথ্য
FILE_CHANNEL = -1001234567890  # আপনার চ্যানেল আইডি এখানে বসান (অবশ্যই integer হতে হবে)
BASE_URL = "https://your-app-name.herokuapp.com"  # আপনার ওয়েবসাইটের URL এখানে বসান
ADMIN_IDS = [123456789, 987654321] # আপনার অ্যাডমিন ইউজার আইডিগুলো এখানে লিস্ট আকারে বসান
# =======================================================================


# --- ইনিশিয়ালাইজেশন (Initializations) ---

# MongoDB ক্লায়েন্ট
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['movie_bot']
movies_collection = db['movies']
ads_collection = db['ads']

# ব্যবহারকারীর সাথে যোগাযোগের জন্য প্রধান বট ক্লায়েন্ট
bot = Client(
    "MovieBot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# ওয়েব সার্ভারের জন্য স্ট্রিমিং লিঙ্ক জেনারেট করার ক্লায়েন্ট
web_client = Client(
    "WebStreamer",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH,
    no_updates=True
)

# Flask ওয়েব অ্যাপ
web_app = Flask(__name__)


# --- Pyrogram বট হ্যান্ডলার (Bot Handlers) ---

@bot.on_message(filters.channel & (filters.video | filters.document) & filters.chat(FILE_CHANNEL))
async def save_movie_handler(client: Client, message: Message):
    if not message.caption:
        print(f"Skipping message {message.id}: No caption found.")
        return

    media = message.video or message.document
    if not media:
        return

    title = message.caption.split("\n")[0].strip()
    
    movies_collection.update_one(
        {"file_unique_id": media.file_unique_id},
        {
            "$set": {
                "title": title,
                "file_id": media.file_id,
                "file_unique_id": media.file_unique_id,
                "message_id": message.id,
                "channel_id": message.chat.id
            }
        },
        upsert=True
    )
    print(f"Saved/Updated movie: {title}")

@bot.on_message(filters.private & filters.command("start"))
async def start_handler(client: Client, message: Message):
    await message.reply("🎬 Welcome to Movie Bot!\nSend a movie name to search.")

@bot.on_message(filters.private & filters.text & ~filters.command("start"))
async def search_movie_handler(client: Client, message: Message):
    query = message.text.strip()
    results = list(movies_collection.find({"title": {'$regex': query, '$options': 'i'}}).limit(10))

    if not results:
        await message.reply("❌ Sorry, movie not found!")
        return

    buttons = [
        [InlineKeyboardButton(f"▶️ {result['title']}", url=f"{BASE_URL}/watch/{result['message_id']}")]
        for result in results
    ]

    await message.reply(
        "🎬 Here are your search results:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# --- Flask ওয়েব সার্ভার রুট (Web Server Routes) ---

@web_app.route("/")
def home_route():
    return "<h3>✅ Movie Bot & Streaming Server is Running!</h3>"

@web_app.route("/watch/<int:msg_id>")
def watch_movie_route(msg_id):
    movie = movies_collection.find_one({"message_id": msg_id})
    if not movie:
        return abort(404, "Movie not found. The link may have expired or been removed.")
        
    title = movie["title"]
    channel_id = str(movie["channel_id"])[4:]
    tg_link = f"https://t.me/c/{channel_id}/{msg_id}"
    
    stream_link = f"{BASE_URL}/stream/{msg_id}"
    
    ad_document = ads_collection.find_one({"name": "main_ad"})
    ad_code = ad_document["code"] if ad_document else ""

    template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Watch {{title}}</title>
        <link href="https://vjs.zencdn.net/8.10.0/video-js.css" rel="stylesheet" />
        <style>
            body { font-family: sans-serif; background-color: #000; color: #fff; margin: 0; }
            .container { max-width: 900px; margin: 20px auto; background-color: #181818; border-radius: 8px; padding: 20px; }
            h2 { text-align: center; }
            .ad-space { margin: 20px 0; text-align: center; }
            .video-js { width: 100% !important; height: auto !important; border-radius: 8px; }
            .button-container { text-align: center; margin-top: 20px; }
            .download-btn { padding: 12px 25px; background-color: #0088cc; color: #fff; text-decoration: none; border-radius: 5px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>{{title}}</h2>
            <div class="ad-space">{{ ad_code|safe }}</div>
            <video id="player" class="video-js vjs-big-play-centered" controls preload="auto" poster="https://i.imgur.com/8X3vQvj.jpg">
                <source src="{{ stream_link }}" type="video/mp4" />
                <p class="vjs-no-js">Please enable JavaScript to watch this video.</p>
            </video>
            <div class="button-container">
                <a href="{{ tg_link }}" target="_blank" class="download-btn">📥 Download Movie</a>
            </div>
        </div>
        <script src="https://vjs.zencdn.net/8.10.0/video.min.js"></script>
    </body>
    </html>
    """
    return render_template_string(template, title=title, stream_link=stream_link, tg_link=tg_link, ad_code=ad_code)


@web_app.route("/stream/<int:msg_id>")
async def stream_generator_route(msg_id):
    movie = movies_collection.find_one({"message_id": msg_id})
    if not movie:
        return abort(404)

    file_id = movie["file_id"]
    
    async def generate_chunks():
        try:
            async for chunk in web_client.stream_media(file_id):
                yield chunk
        except FloodWait as e:
            print(f"FloodWait for {e.value} seconds. Sleeping...")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"Error while streaming: {e}")

    return Response(generate_chunks(), mimetype="video/mp4")

# Admin panel routes
@web_app.route("/admin/<int:admin_id>")
def admin_panel_route(admin_id):
    if admin_id not in ADMIN_IDS: return abort(403)
    ad = ads_collection.find_one({"name": "main_ad"}) or {"code": ""}
    return render_template_string('<h3>Admin Ad Panel</h3><form action="/update_ad/{{id}}" method="post"><textarea name="ad_code" rows="10" cols="80">{{ad}}</textarea><br><br><input type="submit" value="Save"></form>', id=admin_id, ad=ad['code'])

@web_app.route("/update_ad/<int:admin_id>", methods=["POST"])
def update_ad_route(admin_id):
    if admin_id not in ADMIN_IDS: return abort(403)
    code = request.form.get("ad_code")
    ads_collection.update_one({"name": "main_ad"}, {"$set": {"code": code}}, upsert=True)
    return redirect(f"/admin/{admin_id}")


# --- প্রধান এক্সিকিউশন (Main Execution) ---

async def main():
    print("Starting web client...")
    await web_client.start()
    
    flask_thread = threading.Thread(
        target=lambda: web_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False),
        daemon=True
    )
    print("Starting Flask server...")
    flask_thread.start()

    print("Starting main bot client...")
    await bot.start()
    
    print("✅ Bot and Web Server are now running successfully!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        
