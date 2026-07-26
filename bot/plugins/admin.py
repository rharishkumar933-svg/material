from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from pyrogram.errors import FloodWait
from bot.database.mongo import db
from bot.config import Config
import asyncio

@Client.on_message(filters.command("admin") & filters.user(Config.OWNER_ID) & filters.private)
async def admin_panel(client, message, edit=False):
    stats = await db.get_global_stats()
    text = (
        "![👑](tg://emoji?id=6021428854889913572) **Admin Panel**\n"
        "──────────────────────\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Total Users:** `{stats['total_users']}`\n"
        f"![🎨](tg://emoji?id=6021435456254646075) **Total Creators:** `{stats['total_creators']}`\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Total Campaigns:** `{stats['total_campaigns']}`\n\n"
        "**Manage Users:**\n"
        "• `/ban [user_id]` - Ban a user from the bot\n"
        "• `/unban [user_id]` - Unban a user\n\n"
        "**Manage Ads:**\n"
        "• `/ads` - Manage ads system & status\n"
        "• `/adslist` - List, view and delete ads\n"
        "• `/settings` - Quick toggle ad auto-delete (3m)"
    )
    buttons = [
        [InlineKeyboardButton("Detailed Stats", callback_data="admin_stats", icon_custom_emoji_id="6026121742315952530")]
    ]
    if edit:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex("^admin_panel_back$"))
async def admin_panel_back(client, callback_query):
    await admin_panel(client, callback_query.message, edit=True)

@Client.on_callback_query(filters.regex("^admin_stats$") & filters.user(Config.OWNER_ID))
async def admin_stats_callback(client, callback_query):
    # Fetch detailed statistics
    total_users = await db.users.count_documents({})
    total_creators = await db.users.count_documents({"is_creator": True})
    total_campaigns = await db.campaigns.count_documents({})
    total_channels = await db.channels.count_documents({})
    
    # Calculate views & unlocks
    total_views = 0
    total_unlocks = 0
    async for camp in db.campaigns.find():
        total_views += camp.get('views', 0)
        total_unlocks += camp.get('unlocks', 0)
        
    avg_conversion = (total_unlocks / total_views * 100) if total_views > 0 else 0.0
    
    text = (
        "![📈](tg://emoji?id=6026121742315952530) **Global Detailed Statistics**\n"
        "──────────────────────\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Total Registered Users:** `{total_users}`\n"
        f"![🎨](tg://emoji?id=6021435456254646075) **Total Creators:** `{total_creators}`\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Total Active Campaigns:** `{total_campaigns}`\n"
        f"![📢](tg://emoji?id=6021726637857446455) **Total Connected Channels:** `{total_channels}`\n\n"
        f"![👁](tg://emoji?id=6024008227564296298) **Total Campaign Views:** `{total_views}`\n"
        f"![🔑](tg://emoji?id=6019290828759898301) **Total Campaign Unlocks:** `{total_unlocks}`\n"
        f"![📈](tg://emoji?id=6026121742315952530) **Global Conversion Rate:** `{avg_conversion:.2f}%`"
    )
    
    buttons = [
        [InlineKeyboardButton("Back", callback_data="admin_panel_back", icon_custom_emoji_id="5985574171550160682")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_message(filters.command(["broadcast", "bcast"]) & filters.user(Config.OWNER_ID) & filters.private)
async def broadcast_command_handler(client, message):
    # Check if this is a reply or contains text
    broadcast_msg = message.reply_to_message
    broadcast_text = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    
    if not broadcast_msg and not broadcast_text:
        await message.reply_text(
            "![🛑](tg://emoji?id=6028583295447472629) **Broadcast Error**\n"
            "──────────────────────\n"
            "Please use one of the following methods:\n\n"
            "![1️⃣](tg://emoji?id=6035214020577859654) **Reply to any message** (text, image, video, sticker) with `/broadcast` or `/bcast`.\n"
            "![2️⃣](tg://emoji?id=6035384337505982633) **Send text directly** after the command: `/broadcast Hello Users!`"
        )
        return
        
    status_msg = await message.reply_text("![📢](tg://emoji?id=6021726637857446455) **Preparing Broadcast...**\nFetching users list from database...")
    
    # Fetch all users
    users = await db.users.find({}, {"user_id": 1}).to_list(length=None)
    total_users = len(users)
    
    if total_users == 0:
        await status_msg.edit_text("![🛑](tg://emoji?id=6028583295447472629) No users found in database to broadcast to.")
        return
        
    await status_msg.edit_text(f"![📢](tg://emoji?id=6021726637857446455) **Broadcasting...**\nSending to `{total_users}` users...")
    
    success = 0
    failed = 0
    
    for i, user in enumerate(users):
        user_id = user['user_id']
        try:
            if broadcast_msg:
                # Copy the replied message (preserves caption, media, and inline keyboard!)
                await broadcast_msg.copy(user_id)
            else:
                # Send text directly
                await client.send_message(user_id, broadcast_text)
            success += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
            # Retry
            try:
                if broadcast_msg:
                    await broadcast_msg.copy(user_id)
                else:
                    await client.send_message(user_id, broadcast_text)
                success += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
            
        # Update progress every 10 users to be interactive and informative
        if (i + 1) % 10 == 0 or (i + 1) == total_users:
            try:
                await status_msg.edit_text(
                    "![📢](tg://emoji?id=6021726637857446455) **Broadcast in Progress...**\n"
                    "──────────────────────\n"
                    f"![👥](tg://emoji?id=6021642336239360403) **Progress:** `{i + 1}` / `{total_users}` users\n"
                    f"![✅](tg://emoji?id=5219899949281453881) **Success:** `{success}`\n"
                    f"![🛑](tg://emoji?id=6028583295447472629) **Failed:** `{failed}`"
                )
            except Exception:
                pass
                
        # Sleep slightly to comply with Telegram standards and prevent flood waits
        await asyncio.sleep(0.05)
        
    await status_msg.edit_text(
        "![📢](tg://emoji?id=6021726637857446455) **Broadcast Completed!**\n"
        "──────────────────────\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Total Targeted:** `{total_users}` users\n"
        f"![✅](tg://emoji?id=5219899949281453881) **Successful Sends:** `{success}`\n"
        f"![🛑](tg://emoji?id=6028583295447472629) **Failed/Blocked:** `{failed}`"
    )

# --- User Ban / Unban Management ---

@Client.on_message(filters.command("ban") & filters.user(Config.OWNER_ID) & filters.private)
async def ban_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:** `/ban [user_id]`")
    
    try:
        user_id = int(args[1])
        await db.users.update_one({"user_id": user_id}, {"$set": {"is_banned": True}}, upsert=True)
        await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) **User `{user_id}` has been banned from using the bot.**")
    except ValueError:
        await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Invalid User ID. Must be an integer.**")

@Client.on_message(filters.command("unban") & filters.user(Config.OWNER_ID) & filters.private)
async def unban_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:** `/unban [user_id]`")
    
    try:
        user_id = int(args[1])
        await db.users.update_one({"user_id": user_id}, {"$set": {"is_banned": False}}, upsert=True)
        await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) **User `{user_id}` has been unbanned.**")
    except ValueError:
        await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Invalid User ID. Must be an integer.**")

# --- Ads Management System ---

@Client.on_message(filters.command("ads") & filters.user(Config.OWNER_ID) & filters.private)
async def ads_manage_cmd(client: Client, message: Message):
    args = message.text.split(maxsplit=2)
    enabled = await db.get_setting("ads_enabled", False)
    status = "ON" if enabled else "OFF"
    delete_ads = await db.get_setting("delete_ads_3mins", True)
    delete_status = "Enabled" if delete_ads else "Disabled"
    ads_delete_time = await db.get_setting("delete_ads_time", 180)
    
    if len(args) < 2:
        return await message.reply_text(
            f"![🎯](tg://emoji?id=6025879072368761539) **Ads System Settings**\n"
            f"──────────────────────\n"
            f"![⚡️](tg://emoji?id=6023761060786346622) **Ads System Status:** `{status}`\n"
            f"![⌛️](tg://emoji?id=5807485774983077261) **Auto-Delete Status:** `{delete_status}`\n"
            f"![⏱](tg://emoji?id=6034973034257848185) **Auto-Delete Timer:** `{ads_delete_time}s`\n\n"
            f"**Commands:**\n"
            f"• `/ads on` - Enable ads system\n"
            f"• `/ads off` - Disable ads system\n"
            f"• `/ads toggle_del` - Toggle ad auto-delete ON/OFF\n"
            f"• `/ads timer [seconds]` - Set ad auto-delete timer\n"
            f"• `/ads set [title]` - Reply to any message (text, media) to set as Ad\n"
            f"• `/adslist` - List, view and remove ads\n\n"
            f"**Example to Set Ad:**\n"
            f"1. Send your advertisement (image, video, text).\n"
            f"2. Reply to that message with `/ads set Ad Title`"
        )

    cmd = args[1].lower()
    
    if cmd == "on":
        await db.set_setting("ads_enabled", True)
        await message.reply_text("![✅](tg://emoji?id=5219899949281453881) Ads system enabled successfully.")
    elif cmd == "off":
        await db.set_setting("ads_enabled", False)
        await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Ads system disabled successfully.")
    elif cmd == "toggle_del":
        new_val = not delete_ads
        await db.set_setting("delete_ads_3mins", new_val)
        await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) Ad auto-delete is now `{'Enabled' if new_val else 'Disabled'}`.")
    elif cmd == "timer":
        args_timer = message.text.split()
        if len(args_timer) < 3:
            return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:** `/ads timer [seconds]`")
        try:
            val = int(args_timer[2])
            if val < 5:
                return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Ad auto-delete timer must be at least 5 seconds.")
            await db.set_setting("delete_ads_time", val)
            await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) Ad auto-delete timer set to `{val}` seconds.")
        except ValueError:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Invalid value. Please provide seconds as an integer.")
    elif cmd == "set":
        if not message.reply_to_message:
            return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Please reply to a message to set it as an ad.")
        if len(args) < 3:
            return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:** `/ads set [ad_title]` (reply to an ad message)")
        
        title = args[2]
        chat_id = message.chat.id
        message_id = message.reply_to_message.id
        
        await db.add_ad(title, chat_id, message_id)
        await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) Ad **'{title}'** added successfully!")

@Client.on_message(filters.command("adslist") & filters.user(Config.OWNER_ID) & filters.private)
async def ads_list_cmd(client: Client, message: Message):
    ads = await db.get_all_ads()
    if not ads:
        return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) No ads added yet. Use `/ads` to add ads.")
    
    buttons = []
    for ad in ads:
        buttons.append([InlineKeyboardButton(ad['title'], callback_data=f"ad_manage_{ad['_id']}", icon_custom_emoji_id="6025879072368761539")])
    
    await message.reply_text("![🎯](tg://emoji?id=6025879072368761539) **Active Ads List**\nSelect an ad to manage below:", reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^ad_manage_") & filters.user(Config.OWNER_ID))
async def ad_manage_cb(client: Client, cb: CallbackQuery):
    ad_id = cb.data.split("_")[2]
    ad = await db.get_ad(ad_id)
    if not ad:
        return await cb.answer("Ad not found!", show_alert=True)
    
    text = f"![🎯](tg://emoji?id=6025879072368761539) **Manage Ad:** {ad['title']}"
    buttons = [
        [
            InlineKeyboardButton("View Ad", callback_data=f"ad_view_{ad_id}", icon_custom_emoji_id="5424892643760937442"),
            InlineKeyboardButton("Remove Ad", callback_data=f"ad_delete_{ad_id}", icon_custom_emoji_id="5445267414562389170")
        ],
        [InlineKeyboardButton("Back to List", callback_data="ad_list_back", icon_custom_emoji_id="5985574171550160682")]
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^ad_view_") & filters.user(Config.OWNER_ID))
async def ad_view_cb(client: Client, cb: CallbackQuery):
    ad_id = cb.data.split("_")[2]
    ad = await db.get_ad(ad_id)
    if not ad:
        return await cb.answer("Ad not found!", show_alert=True)
    
    try:
        await client.copy_message(cb.from_user.id, ad['chat_id'], ad['message_id'])
        await cb.answer("Ad preview sent!")
    except Exception as e:
        await cb.answer(f"Error: {e}", show_alert=True)

@Client.on_callback_query(filters.regex(r"^ad_delete_") & filters.user(Config.OWNER_ID))
async def ad_delete_cb(client: Client, cb: CallbackQuery):
    ad_id = cb.data.split("_")[2]
    await db.delete_ad_data(ad_id)
    await cb.answer("✅ Ad deleted successfully!", show_alert=True)
    
    ads = await db.get_all_ads()
    if not ads:
        await cb.message.edit_text("![🛑](tg://emoji?id=6028583295447472629) No ads added yet. Use `/ads` to add ads.")
    else:
        buttons = []
        for ad in ads:
            buttons.append([InlineKeyboardButton(ad['title'], callback_data=f"ad_manage_{ad['_id']}", icon_custom_emoji_id="6025879072368761539")])
        await cb.message.edit_text("![🎯](tg://emoji?id=6025879072368761539) **Active Ads List**\nSelect an ad to manage below:", reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^ad_list_back") & filters.user(Config.OWNER_ID))
async def ad_list_back_cb(client: Client, cb: CallbackQuery):
    ads = await db.get_all_ads()
    if not ads:
        return await cb.message.edit_text("![🛑](tg://emoji?id=6028583295447472629) No ads added yet. Use `/ads` to add ads.")
    
    buttons = []
    for ad in ads:
        buttons.append([InlineKeyboardButton(ad['title'], callback_data=f"ad_manage_{ad['_id']}", icon_custom_emoji_id="6025879072368761539")])
    
    await cb.message.edit_text("![🎯](tg://emoji?id=6025879072368761539) **Active Ads List**\nSelect an ad to manage below:", reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_message(filters.command("settings") & filters.user(Config.OWNER_ID) & filters.private)
async def settings_cmd(client: Client, message: Message):
    args = message.text.split()
    
    # Content Auto-Delete Settings
    delete_content_enabled = await db.get_setting("delete_content_enabled", True)
    delete_content_time = await db.get_setting("delete_content_time", 60)
    content_status = "ON" if delete_content_enabled else "OFF"
    
    # Ads Settings
    delete_ads_enabled = await db.get_setting("delete_ads_3mins", True)
    delete_ads_time = await db.get_setting("delete_ads_time", 180)
    ads_del_status = "Enabled" if delete_ads_enabled else "Disabled"
    
    # Force Subscribe Settings
    fsub_channel_id = await db.get_setting("global_fsub_channel_id", Config.CHANNEL_ID)
    fsub_channel_link = await db.get_setting("global_fsub_channel_link", Config.CHANNEL_LINK)
    fsub_status = "Enabled" if (fsub_channel_id and fsub_channel_link) else "Disabled"
    
    if len(args) < 2:
        return await message.reply_text(
            f"![⚙](tg://emoji?id=6021637109264160908) **Admin Control Panel / Settings**\n"
            f"──────────────────────\n"
            f"![🔒](tg://emoji?id=5945145850551343409) **Content Privacy Auto-Delete:** `{content_status}`\n"
            f"![⏱](tg://emoji?id=6034973034257848185) **Content Deletion Timer:** `{delete_content_time}s`\n\n"
            f"![⌛️](tg://emoji?id=5807485774983077261) **Ads Auto-Delete Status:** `{ads_del_status}`\n"
            f"![⏱](tg://emoji?id=6034973034257848185) **Ad Auto-Delete Timer:** `{delete_ads_time}s`\n\n"
            f"![📢](tg://emoji?id=6021726637857446455) **Global Force Subscribe:** `{fsub_status}`\n"
            f"![📄](tg://emoji?id=6019492172531767926) **Channel ID:** `{fsub_channel_id}`\n"
            f"![🔗](tg://emoji?id=5807453545548487345) **Channel Link:** `{fsub_channel_link}`\n\n"
            f"**Content Privacy Commands:**\n"
            f"• `/settings content on` - Turn content auto-delete ON\n"
            f"• `/settings content off` - Turn content auto-delete OFF\n"
            f"• `/settings content timer [seconds]` - Set deletion delay\n\n"
            f"**Ad Deletion Commands:**\n"
            f"• `/ads toggle_del` - Toggle ad auto-delete ON/OFF\n"
            f"• `/ads timer [seconds]` - Set ad deletion timer\n\n"
            f"**Force Subscribe Commands:**\n"
            f"• `/settings fsub on [channel_id] [channel_link]` - Enable & set global fsub\n"
            f"• `/settings fsub off` - Disable global fsub"
        )
        
    subcmd = args[1].lower()
    
    if subcmd == "content":
        if len(args) < 3:
            return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:** `/settings content [on/off/timer]`")
            
        action = args[2].lower()
        if action == "on":
            await db.set_setting("delete_content_enabled", True)
            await message.reply_text("![✅](tg://emoji?id=5219899949281453881) Content auto-delete enabled successfully.")
        elif action == "off":
            await db.set_setting("delete_content_enabled", False)
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Content auto-delete disabled successfully.")
        elif action == "timer":
            if len(args) < 4:
                return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:** `/settings content timer [seconds]`")
            try:
                val = int(args[3])
                if val < 5:
                    return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Timer must be at least 5 seconds.")
                await db.set_setting("delete_content_time", val)
                await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) Content auto-delete timer set to `{val}` seconds.")
            except ValueError:
                await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Invalid value. Please provide seconds as an integer.")
        else:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Invalid content settings action. Use `on`, `off` or `timer`.")
    elif subcmd == "fsub":
        if len(args) < 3:
            return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:**\n• `/settings fsub on [channel_id] [channel_link]`\n• `/settings fsub off`")
            
        action = args[2].lower()
        if action == "on":
            if len(args) < 5:
                return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **Usage:** `/settings fsub on [channel_id] [channel_link]`\nExample: `/settings fsub on -1001234567890 https://t.me/mychannel`")
            try:
                ch_id = int(args[3])
                link = args[4]
                if not link.startswith("https://t.me/"):
                     return await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Channel link must be a valid Telegram link starting with `https://t.me/`.")
                await db.set_setting("global_fsub_channel_id", ch_id)
                await db.set_setting("global_fsub_channel_link", link)
                await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) Global Force Subscribe enabled for:\n![📄](tg://emoji?id=6019492172531767926) Channel ID: `{ch_id}`\n![🔗](tg://emoji?id=5807453545548487345) Link: {link}")
            except ValueError:
                await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Invalid Channel ID. It must be an integer (e.g., `-1001234567890`).")
        elif action == "off":
            await db.set_setting("global_fsub_channel_id", 0)
            await db.set_setting("global_fsub_channel_link", "")
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Global Force Subscribe has been disabled.")
        else:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Invalid action. Use `on` or `off`.")
    else:
        await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Invalid command. Use `/settings` to see options.")
