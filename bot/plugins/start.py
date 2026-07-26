from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.database.mongo import db
from bot.config import Config
from bot.plugins.unlock import handle_unlock_logic

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user_id = message.from_user.id
    username = message.from_user.username
    text = message.text.split()
    
    # Check for referral or campaign deep link
    ref_id = None
    campaign_id = None
    if len(text) > 1:
        param = text[1]
        if param.startswith("ref_"):
            parts = param.split("_")
            try:
                ref_id = int(parts[1])
                if ref_id == user_id: ref_id = None # Can't refer self
            except:
                pass
            # If the referral link contains a campaign ID, capture it
            if len(parts) > 2:
                campaign_id = "_".join(parts[2:])
        else:
            campaign_id = param

    # Add user to DB
    user = await db.get_user(user_id)
    if not user:
        await db.add_user(user_id, username)
        user = await db.get_user(user_id)
    
    # Track pending campaign referral for both new and existing users
    if ref_id and campaign_id and user:
        referred_by = user.get("referred_by", {})
        unlocked = user.get("unlocked_campaigns", [])
        if campaign_id not in unlocked and campaign_id not in referred_by:
            # Check if this user was already credited in the referrer's list
            referrer_user = await db.get_user(ref_id)
            already_referred = False
            if referrer_user:
                already_referred = user_id in referrer_user.get("campaign_referrals", {}).get(campaign_id, [])
            
            if not already_referred:
                await db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {f"referred_by.{campaign_id}": ref_id}}
                )
                if not user.get("referrer"):
                    await db.users.update_one(
                        {"user_id": user_id},
                        {"$set": {"referrer": ref_id}}
                    )
                # Refresh user document to get the new state
                user = await db.get_user(user_id)
    
    # Check if user is banned
    if user and user.get("is_banned"):
        await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **You are banned from using this bot.**")
        return

    if campaign_id:
        await handle_unlock_logic(client, message, campaign_id)
        return

    if not campaign_id:
        fsub_channel_id = await db.get_setting("global_fsub_channel_id", Config.CHANNEL_ID)
        fsub_channel_link = await db.get_setting("global_fsub_channel_link", Config.CHANNEL_LINK)
        if fsub_channel_id and fsub_channel_link:
            from bot.utils.force_join import is_user_member
            is_member = await is_user_member(client, fsub_channel_id, user_id)
            if not is_member:
                buttons = [
                    [InlineKeyboardButton("Join Channel", url=fsub_channel_link, icon_custom_emoji_id="6021726637857446455")],
                    [InlineKeyboardButton("Check", callback_data="check_main_fsub", icon_custom_emoji_id="5226702984204797593")]
                ]
                await message.reply_text(
                    "![✈️](tg://emoji?id=5877700484453634587) **Join Our Channel!**\n\n"
                    "You must join our official channel to use this bot and access all features.\n\n"
                    "Click the button below to join, then click **Check** ![🔄](tg://emoji?id=5226702984204797593) to continue.",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                return

    # Main Menu
    welcome_text = (
        f"![👋](tg://emoji?id=5247133031235329609) **Hello, {message.from_user.first_name}!**\n"
        "Welcome to the ultimate content gateway.\n\n"
        "![💎](tg://emoji?id=5800688138833629633) **ACCESS MATERIAL**\n"
        "Paste a campaign link or enter an ID to unlock exclusive files and content.\n\n"
        "![🔢](tg://emoji?id=5226513232549664618) **CREATOR DASHBOARD**\n"
        "Are you a creator? Build your own force-join campaigns and grow your audience for free.\n\n"
        "──────────────────────\n"
        f"![😀](tg://emoji?id=5451709985765468632) **Account ID:** `{user_id}`"
    )

    buttons = []
    if user.get("is_creator"):
        buttons.append([InlineKeyboardButton("Creator Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="6026121742315952530")])
    else:
        buttons.append([InlineKeyboardButton("Start as Creator", callback_data="become_creator", icon_custom_emoji_id="6021435456254646075")])

    # [InlineKeyboardButton("Start Unlocking", callback_data="unlock_info", icon_custom_emoji_id="6019290828759898301")],
    buttons.append([
        InlineKeyboardButton("My History", callback_data="mu_0", icon_custom_emoji_id="6021526054294788288"),
        # InlineKeyboardButton("Invite Friends", callback_data="referral_info", icon_custom_emoji_id="6021642336239360403")
    ])

    buttons.append([InlineKeyboardButton("How it Works", callback_data="help_info", icon_custom_emoji_id="5334544901428229844")])

    await message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex("^main_menu$"))
async def main_menu_callback(client, callback_query):
    user_id = callback_query.from_user.id
    
    # Check global fsub
    fsub_channel_id = await db.get_setting("global_fsub_channel_id", Config.CHANNEL_ID)
    fsub_channel_link = await db.get_setting("global_fsub_channel_link", Config.CHANNEL_LINK)
    if fsub_channel_id and fsub_channel_link:
        from bot.utils.force_join import is_user_member
        is_member = await is_user_member(client, fsub_channel_id, user_id)
        if not is_member:
            buttons = [
                [InlineKeyboardButton("Join Channel", url=fsub_channel_link, icon_custom_emoji_id="6021726637857446455")],
                [InlineKeyboardButton("Check", callback_data="check_main_fsub", icon_custom_emoji_id="5226702984204797593")]
            ]
            await callback_query.message.edit_text(
                "![✈️](tg://emoji?id=5877700484453634587) **Join Our Channel!**\n\n"
                "You must join our official channel to use this bot and access all features.\n\n"
                "Click the button below to join, then click **Check** ![🔄](tg://emoji?id=5226702984204797593) to continue.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
            
    user = await db.get_user(user_id)
    
    welcome_text = (
        f"![👋](tg://emoji?id=5247133031235329609) **Hello, {callback_query.from_user.first_name}!**\n"
        "Welcome to the ultimate content gateway.\n\n"
        "![💎](tg://emoji?id=5800688138833629633) **ACCESS MATERIAL**\n"
        "Paste a campaign link or enter an ID to unlock exclusive files and content.\n\n"
        "![🔢](tg://emoji?id=5226513232549664618) **CREATOR DASHBOARD**\n"
        "Are you a creator? Build your own force-join campaigns and grow your audience for free.\n\n"
        "──────────────────────\n"
        f"![😀](tg://emoji?id=5451709985765468632) **Account ID:** `{user_id}`"
    )

    buttons = []
    if user.get("is_creator"):
        buttons.append([InlineKeyboardButton("Creator Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="6026121742315952530")])
    else:
        buttons.append([InlineKeyboardButton("Start as Creator", callback_data="become_creator", icon_custom_emoji_id="6021435456254646075")])

    # [InlineKeyboardButton("Start Unlocking", callback_data="unlock_info", icon_custom_emoji_id="6019290828759898301")],
    buttons.append([
        InlineKeyboardButton("My History", callback_data="mu_0", icon_custom_emoji_id="6021526054294788288"),
        # InlineKeyboardButton("Invite Friends", callback_data="referral_info", icon_custom_emoji_id="6021642336239360403")
    ])

    buttons.append([InlineKeyboardButton("How it Works", callback_data="help_info", icon_custom_emoji_id="5334544901428229844")])

    try:
        await callback_query.message.edit_text(welcome_text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        pass

@Client.on_callback_query(filters.regex("^check_main_fsub$"))
async def check_main_fsub_cb(client, callback_query):
    user_id = callback_query.from_user.id
    fsub_channel_id = await db.get_setting("global_fsub_channel_id", Config.CHANNEL_ID)
    fsub_channel_link = await db.get_setting("global_fsub_channel_link", Config.CHANNEL_LINK)
    if fsub_channel_id and fsub_channel_link:
        from bot.utils.force_join import is_user_member
        is_member = await is_user_member(client, fsub_channel_id, user_id)
        if not is_member:
            await callback_query.answer("❌ Please join our channel first!", show_alert=True)
            return
            
    await callback_query.answer("✅ Thank you for joining!", show_alert=True)
    
    # Send / Edit to Main Menu
    user = await db.get_user(user_id)
    welcome_text = (
        f"![👋](tg://emoji?id=5247133031235329609) **Hello, {callback_query.from_user.first_name}!**\n"
        "Welcome to the ultimate content gateway.\n\n"
        "![💎](tg://emoji?id=5800688138833629633) **ACCESS MATERIAL**\n"
        "Paste a campaign link or enter an ID to unlock exclusive files and content.\n\n"
        "![🔢](tg://emoji?id=5226513232549664618) **CREATOR DASHBOARD**\n"
        "Are you a creator? Build your own force-join campaigns and grow your audience for free.\n\n"
        "──────────────────────\n"
        f"![😀](tg://emoji?id=5451709985765468632) **Account ID:** `{user_id}`"
    )

    buttons = []
    if user.get("is_creator"):
        buttons.append([InlineKeyboardButton("Creator Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="6026121742315952530")])
    else:
        buttons.append([InlineKeyboardButton("Start as Creator", callback_data="become_creator", icon_custom_emoji_id="6021435456254646075")])

    # [InlineKeyboardButton("Start Unlocking", callback_data="unlock_info", icon_custom_emoji_id="6019290828759898301")],
    buttons.append([
        InlineKeyboardButton("My History", callback_data="mu_0", icon_custom_emoji_id="6021526054294788288"),
        # InlineKeyboardButton("Invite Friends", callback_data="referral_info", icon_custom_emoji_id="6021642336239360403")
    ])

    buttons.append([InlineKeyboardButton("How it Works", callback_data="help_info", icon_custom_emoji_id="5334544901428229844")])

    try:
        await callback_query.message.edit_text(welcome_text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        pass
