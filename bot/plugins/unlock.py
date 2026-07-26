import pyrogram.enums.parse_mode
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from pyrogram.enums import ButtonStyle
from bot.database.mongo import db
from bot.utils.force_join import is_user_member, get_invite_link
from bot.config import Config
import asyncio
from pyrogram.errors import MessageNotModified

async def handle_unlock_logic(client, message, campaign_id, callback_query=None):
    user_id = callback_query.from_user.id if callback_query else message.from_user.id
    campaign = await db.get_campaign(campaign_id)
    
    if not campaign:
        await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Campaign not found.")
        return

    # Ensure user exists in DB
    user = await db.get_user(user_id)
    if not user:
        await db.add_user(user_id, message.from_user.username)
        user = await db.get_user(user_id)

    # Check if user is banned
    if user and user.get("is_banned"):
        if callback_query:
            try:
                await callback_query.answer("🚫 You are banned from using this bot.", show_alert=True)
            except Exception:
                pass
        else:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **You are banned from using this bot.**")
        return

    # Increment views
    await db.increment_campaign_stats(campaign_id, "views")

    # Check Requirements in parallel for speed
    missing_channels = []
    fj_channels = campaign['requirements'].get('force_join', [])
    request_channels = campaign['requirements'].get('request_join', [])
    
    if fj_channels:
        # Create tasks for all channels
        tasks = [is_user_member(client, ch_id, user_id, use_request_link=(ch_id in request_channels)) for ch_id in fj_channels]
        results = await asyncio.gather(*tasks)
        
        for i, is_member in enumerate(results):
            if not is_member:
                ch_id = fj_channels[i]
                invite_link = await get_invite_link(client, ch_id, use_request_link=(ch_id in request_channels))
                channel_info = await db.get_channel(ch_id)
                missing_channels.append({"title": channel_info['title'] if channel_info else f"ID:{ch_id}", "link": invite_link})

    # Check Referrals
    user = await db.get_user(user_id)
    required_refs = campaign['requirements'].get('referrals', 0)
    campaign_refs_list = user.get("campaign_referrals", {}).get(campaign_id, []) if user else []
    current_refs = len(campaign_refs_list)
    
    if missing_channels:
        if callback_query:
            try:
                await callback_query.answer("❌ You haven't completed all steps yet! Please join the channels and try again.", show_alert=True)
            except Exception:
                pass

        # Show requirements message
        text = f"Join channel to unlock Material ![💎](tg://emoji?id=5800688138833629633): {campaign['title']}\n"
        
        buttons = []
        for ch in missing_channels:
            buttons.append([InlineKeyboardButton(f"Join {ch['title']}", url=ch['link'], icon_custom_emoji_id="6021726637857446455")])

        buttons.append([InlineKeyboardButton("Unlock", callback_data=f"cu_{campaign_id}", icon_custom_emoji_id="6019290828759898301", style=ButtonStyle.SUCCESS)])
        
        try:
            # If it's a callback, we MUST edit the message to avoid spam
            if callback_query:
                await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        except MessageNotModified:
            # If message is same, just ignore
            pass
        except Exception:
            # Fallback to reply if other edit fails
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # At this point, we know they joined all channels. Credit the campaign referrer if pending.
    if user:
        referred_by = user.get("referred_by", {})
        referrer_id = referred_by.get(campaign_id)
        if referrer_id:
            # 1. Credit the referrer
            await db.users.update_one(
                {"user_id": referrer_id},
                {
                    "$addToSet": {f"campaign_referrals.{campaign_id}": user_id},
                    "$inc": {"referral_count": 1}
                }
            )
            # 2. Unset the pending referrer to prevent double-crediting
            await db.users.update_one(
                {"user_id": user_id},
                {"$unset": {f"referred_by.{campaign_id}": ""}}
            )
            # 3. Reload user document to get updated state
            user = await db.get_user(user_id)
            
            # 4. Notify the referrer in real-time
            try:
                referrer_user = await db.get_user(referrer_id)
                if referrer_user:
                    referrer_campaign_refs = referrer_user.get("campaign_referrals", {}).get(campaign_id, [])
                    current_referrer_refs = len(referrer_campaign_refs)
                    
                    # Notify referrer of the successful join and progress
                    await client.send_message(
                        chat_id=referrer_id,
                        text=(
                            f"![🎉](tg://emoji?id=6023579259115674297) **New Referral!**\n"
                            f"Someone successfully joined the channels using your referral link for campaign: **{campaign['title']}**!\n\n"
                            f"![📈](tg://emoji?id=6026121742315952530) **Progress:** `{current_referrer_refs}/{required_refs}` referrals completed."
                        )
                    )
            except Exception as e:
                print(f"Error notifying referrer: {e}")

    # Recalculate referrals for the current user B
    campaign_refs_list = user.get("campaign_referrals", {}).get(campaign_id, []) if user else []
    current_refs = len(campaign_refs_list)

    if current_refs < required_refs:
        # User has joined channels, but needs refers!
        if callback_query:
            try:
                await callback_query.answer("⚠️ You still need referrals to unlock! Here is your referral link.", show_alert=True)
            except Exception:
                pass

        bot_username = (await client.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}_{campaign_id}"
        
        text = (
            f"Join channel to unlock Material ![💎](tg://emoji?id=5800688138833629633): {campaign['title']}\n\n"
            f"![👥](tg://emoji?id=6021642336239360403) **Need {required_refs} referrals to unlock.**\n\n"
            "![🔗](tg://emoji?id=5807453545548487345) **Your unique referral link:**\n"
            f"`{ref_link}`"
        )
        
        buttons = [
            [InlineKeyboardButton("Share Link", url=f"https://t.me/share/url?url={ref_link}", icon_custom_emoji_id="5807453545548487345")],
            [InlineKeyboardButton("Unlock", callback_data=f"cu_{campaign_id}", icon_custom_emoji_id="6019290828759898301", style=ButtonStyle.SUCCESS)]
        ]
        
        try:
            if callback_query:
                await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        except MessageNotModified:
            pass
        except Exception:
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # All requirements met -> Send Material
    if callback_query:
        try:
            await callback_query.answer("Content unlocked! ✅", show_alert=False)
            await callback_query.message.delete()
        except Exception:
            pass

    await db.increment_campaign_stats(campaign_id, "unlocks", user_id=user_id)
    await db.track_unlock(user_id, campaign_id) # Track for user
    
    # Support both single material (legacy) and multiple materials
    materials = campaign.get('materials')
    if not materials:
        if 'material' in campaign:
            materials = [campaign['material']]
        else:
            materials = []
            
    sent_msgs = []
    
    for mat in materials:
        msg = None
        if mat['type'] == "text":
            msg = await message.reply_text(mat['content'])
        elif mat['type'] == "photo":
            msg = await message.reply_photo(mat['file_id'], caption=mat.get('caption'))
        elif mat['type'] == "video":
            msg = await message.reply_video(mat['file_id'], caption=mat.get('caption'))
        elif mat['type'] == "document":
            msg = await message.reply_document(mat['file_id'], caption=mat.get('caption'))
        elif mat['type'] == "animation":
            msg = await message.reply_animation(mat['file_id'], caption=mat.get('caption'))
        elif mat['type'] == "link":
            text = (
                "![🎉](tg://emoji?id=6023579259115674297) **Content Unlocked!**\n"
                "──────────────────────\n"
                f"![🎯](tg://emoji?id=6025879072368761539) **Campaign:** {campaign['title']}\n\n"
                f"![🔗](tg://emoji?id=5807453545548487345) **Link:** {mat['content']}\n\n"
                "Your premium content is ready! Click the button below to view it."
            )
            buttons = [[InlineKeyboardButton("Open Content", url=mat['content'], icon_custom_emoji_id="6019290828759898301")]]
            msg = await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), link_preview_options=LinkPreviewOptions(is_disabled=False))
            
        if msg:
            sent_msgs.append(msg)
            
    # Trigger Ad after content unlock
    asyncio.create_task(show_ad_after_unlock(client, user_id))

    if sent_msgs:
        delete_enabled = await db.get_setting("delete_content_enabled", True)
        if delete_enabled:
            delay = await db.get_setting("delete_content_time", 60)
            
            # Format time beautifully
            time_str = f"{delay} seconds" if delay < 60 else f"{delay // 60} minute{'s' if delay >= 120 else ''}"
            if delay % 60 != 0 and delay >= 60:
                time_str = f"{delay // 60}m {delay % 60}s"
                
            notify_msg = await message.reply_text(
                f"![⏰](tg://emoji?id=6034898821517940846) **Notice:** This content will be automatically deleted in **{time_str}**.\n"
                "Please forward it to any chat or Saved Messages to keep it permanently."
            )
            # Schedule deletion
            asyncio.create_task(auto_delete_message(sent_msgs, notify_msg, delay))

async def show_ad_after_unlock(client, user_id):
    ad = await db.get_random_ad()
    if ad:
        try:
            ad_msg = await client.copy_message(user_id, ad['chat_id'], ad['message_id'])
            if not ad_msg:
                print("Error displaying ad: copy_message returned None")
                return
            
            # Check auto-delete setting
            delete_ads = await db.get_setting("delete_ads_3mins", True)
            if delete_ads:
                delay = await db.get_setting("delete_ads_time", 180) # Dynamic ad delete timer!
                asyncio.create_task(delete_ad_after_delay(client, user_id, ad_msg.id, delay))
        except Exception as e:
            print(f"Error displaying ad: {e}")

async def delete_ad_after_delay(client, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass

async def auto_delete_message(msg_or_msgs, notify_msg, delay):
    await asyncio.sleep(delay)
    try:
        if isinstance(msg_or_msgs, list):
            for m in msg_or_msgs:
                try:
                    await m.delete()
                except Exception:
                    pass
        else:
            await msg_or_msgs.delete()
        await notify_msg.edit_text("![🗑](tg://emoji?id=6021413766669801212) **Content Deleted.**\nMaterial has been removed for security/privacy.")
    except Exception:
        pass

@Client.on_callback_query(filters.regex("^already_unlocked$"))
async def already_unlocked_handler(client, callback_query):
    await callback_query.answer("This content is already unlocked! ✅", show_alert=True)

@Client.on_callback_query(filters.regex("^unlock_info$"))
async def unlock_info_handler(client, callback_query):
    user_id = callback_query.from_user.id
    bot_username = (await client.get_me()).username
    text = (
        "![🔒](tg://emoji?id=5945145850551343409) **Unlock Content**\n"
        "──────────────────────\n"
        "To unlock content, please **send the campaign link** or **campaign ID** below.\n\n"
        "**You can send:**\n"
        f"• `t.me/{bot_username}?start=ID` (Link)\n"
        "• `ID` (Just the ID)\n\n"
        "Please send it now:"
    )
    buttons = [[InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    await db.users.update_one({"user_id": user_id}, {"$set": {"state": "waiting_for_unlock_id"}})

async def handle_manual_unlock(client, message):
    text = message.text.strip()
    campaign_id = text
    
    # Check if it's a link and extract the start param
    if "t.me/" in text or "telegram.me/" in text:
        if "start=" in text:
            campaign_id = text.split("start=")[1].split("&")[0]
        else:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Invalid link. The link must contain a `?start=ID` parameter.")
            return

    # Clear state and process
    await db.users.update_one({"user_id": message.from_user.id}, {"$set": {"state": None}})
    await handle_unlock_logic(client, message, campaign_id)

@Client.on_callback_query(filters.regex(r"^mu_(\d+)$"))
async def my_unlocks_handler(client, callback_query):
    page = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    user = await db.get_user(user_id)
    unlocked_ids = user.get("unlocked_campaigns", [])
    
    if not unlocked_ids:
        text = "![🛑](tg://emoji?id=6028583295447472629) You haven't unlocked any content yet."
        buttons = [[InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]]
        await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Pagination Logic
    PER_PAGE = 5
    total_pages = (len(unlocked_ids) + PER_PAGE - 1) // PER_PAGE
    start = page * PER_PAGE
    current_ids = unlocked_ids[start:start+PER_PAGE]

    text = (
        "![📖](tg://emoji?id=6021526054294788288) **My Unlocks History**\n"
        "──────────────────────\n"
        f"![📄](tg://emoji?id=6019492172531767926) **Page:** `{page + 1}` **of** `{total_pages}`\n\n"
        "Select a material to re-access it."
    )
    
    buttons = []
    for cid in current_ids:
        camp = await db.get_campaign(cid)
        if camp:
            camp_title = camp['title']
            if len(camp_title) > 20:
                camp_title = camp_title[:17] + "..."
            title = camp_title
            callback_data = f"cu_{cid}"
            icon_id = "6019290828759898301"
        else:
            title = "Deleted Content"
            callback_data = f"cu_deleted_{cid}"
            icon_id = "6021413766669801212"
            
        buttons.append([InlineKeyboardButton(title, callback_data=callback_data, icon_custom_emoji_id=icon_id)])
    
    # Navigation Buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Prev", callback_data=f"mu_{page - 1}", icon_custom_emoji_id="5985574171550160682"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next", callback_data=f"mu_{page + 1}", icon_custom_emoji_id="5807453545548487345"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([InlineKeyboardButton("Back to Menu", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")])
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^cu_"))
async def check_unlock_callback(client, callback_query):
    data = callback_query.data
    if data.startswith("cu_deleted_"):
        await callback_query.answer("❌ This campaign has been deleted by the creator.", show_alert=True)
        return
        
    campaign_id = data.removeprefix("cu_")
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ This campaign has been deleted by the creator.", show_alert=True)
        return
        
    await handle_unlock_logic(client, callback_query.message, campaign_id, callback_query=callback_query)

@Client.on_message(filters.command("refer") & filters.private)
async def refer_command_handler(client, message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await db.add_user(user_id, message.from_user.username)
        user = await db.get_user(user_id)
        
    bot_username = (await client.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    text = (
        "![👥](tg://emoji?id=6021642336239360403) **Your Referral Stats**\n"
        "──────────────────────\n"
        f"![📈](tg://emoji?id=6026121742315952530) **Total Referrals:** `{user.get('referral_count', 0)}`\n\n"
        "![🔗](tg://emoji?id=5807453545548487345) **Your referral link:**\n"
        f"`{ref_link}`\n\n"
        "Share this link — when someone joins via it, your referral count increases!"
    )
    buttons = [
        [InlineKeyboardButton("Share Link", url=f"https://t.me/share/url?url={ref_link}", icon_custom_emoji_id="5807453545548487345")],
        [InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^referral_info$"))
async def referral_info_handler(client, callback_query):
    user_id = callback_query.from_user.id
    user = await db.get_user(user_id)
    bot_username = (await client.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    text = (
        "![👥](tg://emoji?id=6021642336239360403) **Your Referral Stats**\n"
        "──────────────────────\n"
        f"![📈](tg://emoji?id=6026121742315952530) **Total Referrals:** `{user.get('referral_count', 0)}`\n\n"
        "![🔗](tg://emoji?id=5807453545548487345) **Your referral link:**\n"
        f"`{ref_link}`\n\n"
        "Share this link — when someone joins via it, your referral count increases!"
    )
    buttons = [
        [InlineKeyboardButton("Share Link", url=f"https://t.me/share/url?url={ref_link}", icon_custom_emoji_id="5807453545548487345")],
        [InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^refinfo_(.+)$"))
async def campaign_referral_info_handler(client, callback_query):
    campaign_id = callback_query.data.removeprefix("refinfo_")
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ Campaign not found.", show_alert=True)
        return
        
    user_id = callback_query.from_user.id
    user = await db.get_user(user_id)
    bot_username = (await client.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}_{campaign_id}"
    
    campaign_refs_list = user.get("campaign_referrals", {}).get(campaign_id, []) if user else []
    current_refs = len(campaign_refs_list)
    required_refs = campaign['requirements'].get('referrals', 0)
    
    text = (
        f"![👥](tg://emoji?id=6021642336239360403) **Referral Stats: {campaign['title']}**\n"
        "──────────────────────\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Target:** `{required_refs}` referrals\n"
        f"![📈](tg://emoji?id=6026121742315952530) **Your Campaign Referrals:** `{current_refs}`\n\n"
        "![🔗](tg://emoji?id=5807453545548487345) **Your unique referral link:**\n"
        f"`{ref_link}`\n\n"
        "Share this link — when someone joins via it, they are redirected to this content, and your referral count increases specifically for this campaign!"
    )
    buttons = [
        [InlineKeyboardButton("Share Link", url=f"https://t.me/share/url?url={ref_link}", icon_custom_emoji_id="5807453545548487345")],
        [InlineKeyboardButton("Back", callback_data=f"cu_{campaign_id}", icon_custom_emoji_id="5985574171550160682")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
