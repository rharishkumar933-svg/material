from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired
from bot.database.mongo import db
from bot.config import Config
from bot.plugins.campaign import handle_campaign_creation_states, show_requirement_settings, campaign_drafts
from bot.plugins.unlock import handle_manual_unlock
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import CallbackQuery
from bot.utils.force_join import get_invite_link

@Client.on_callback_query(filters.regex("^become_creator$"))
async def become_creator_handler(client, callback_query):
    user_id = callback_query.from_user.id
    await db.set_creator(user_id, True)
    await creator_dashboard_handler(client, callback_query)

@Client.on_callback_query(filters.regex("^connect_channel$"))
async def connect_channel_prompt(client, callback_query):
    user_id = callback_query.from_user.id
    user = await db.get_user(user_id)
    bot_username = (await client.get_me()).username
    
    # Direct link to add bot as admin in channel
    add_link = f"https://t.me/{bot_username}?startchannel=true&admin=post_messages+invite_users"
    
    back_target = "creator_dashboard" if user.get("is_creator") else "become_creator"
    
    text = (
        "![🔗](tg://emoji?id=5807453545548487345) **Connect Your Channel**\n"
        "──────────────────────\n"
        "Please send the **Username** or **ID** of your channel.\n\n"
        "**Supported Formats:**\n"
        "• `@MyChannel` (Username)\n"
        "• `-100123456789` (Channel ID)\n\n"
        "![💡](tg://emoji?id=6019364380074843443) **Quick Tip:** Use the button below to add the bot to your channel instantly! (Recommended for private channels)"
    )
    
    buttons = [
        [InlineKeyboardButton("Add Bot to Channel", url=add_link, icon_custom_emoji_id="6021726637857446455")],
        [InlineKeyboardButton("Back", callback_data=back_target, icon_custom_emoji_id="5985574171550160682")]
    ]
    
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    await db.users.update_one({"user_id": user_id}, {"$set": {"state": "waiting_for_channel"}})

@Client.on_chat_member_updated()
async def auto_detect_admin(client, chat_member_updated):
    
    new_status = chat_member_updated.new_chat_member.status if chat_member_updated.new_chat_member else None
    old_status = chat_member_updated.old_chat_member.status if chat_member_updated.old_chat_member else None
    
    print(f"DEBUG: ChatMemberUpdated in {chat_member_updated.chat.title} | Status: {old_status} -> {new_status}")

    # Detect if bot was added or promoted to admin
    if new_status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        if chat_member_updated.new_chat_member.user.is_self:
            chat = chat_member_updated.chat
            
            # If from_user is missing, we can't link it automatically
            if not chat_member_updated.from_user:
                print("DEBUG: from_user is missing in ChatMemberUpdated")
                return
                
            user_id = chat_member_updated.from_user.id
            print(f"DEBUG: Promoting bot for user {user_id} in {chat.title}")
            
            # Save to DB
            await db.add_channel(user_id, chat.id, chat.title, chat.username)
            await db.set_creator(user_id, True)
            
            # Notify the user in private
            try:
                text = (
                    "![✅](tg://emoji?id=5219899949281453881) **Auto-Detection Success!**\n"
                    "──────────────────────\n"
                    f"![📢](tg://emoji?id=6021726637857446455) **{chat.title}** has been automatically connected to your account.\n\n"
                    "![✨](tg://emoji?id=6019145074749740966) You can now use it in your campaigns!\n"
                    "Tap **Dashboard** below to manage your campaigns."
                )
                buttons = [
                    [InlineKeyboardButton("Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="6026121742315952530")],
                    [InlineKeyboardButton("New Campaign", callback_data="new_campaign", icon_custom_emoji_id="5807718484901108517")]
                ]
                await client.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(buttons))
            except Exception as e:
                print(f"Error sending auto-detect notification: {e}")

@Client.on_message(filters.private & ~filters.command(["start", "creator", "refer", "broadcast", "bcast", "admin", "ban", "unban", "ads", "adslist", "settings"]))
async def handle_text_states(client, message):
    user = await db.get_user(message.from_user.id)
    if not user: return
    
    if user.get("is_banned"):
        await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) **You are banned from using this bot.**")
        return
    
    state = user.get("state")
    if state == "waiting_for_channel":
        await handle_channel_connection(client, message)
    elif state == "waiting_for_unlock_id":
        await handle_manual_unlock(client, message)
    elif state and state.startswith("waiting_for_campaign_"):
        
        if state == "waiting_for_campaign_ref":
            try:
                ref_count = int(message.text.strip())
                if ref_count < 0:
                    await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Please send a number greater than or equal to 0.")
                    return
                draft = campaign_drafts.get(message.from_user.id)
                if draft:
                    draft['requirements']['referrals'] = ref_count
                    await db.users.update_one({"user_id": message.from_user.id}, {"$set": {"state": None}})
                    
                    # Try to delete user's message to keep chat history clean
                    try:
                        await message.delete()
                    except Exception:
                        pass
                        
                    prompt_msg_id = draft.get("prompt_message_id")
                    if prompt_msg_id:
                        try:
                            # Direct edit of the prompt message in place to present Step 3 Requirement settings
                            class FakeMessage:
                                def __init__(self, msg_id, chat_id):
                                    self.id = msg_id
                                    self.message_id = msg_id
                                    self.chat = type('FakeChat', (), {'id': chat_id})()
                                    self.from_user = type('FakeUser', (), {'is_self': True})()
                                    
                                async def edit_text(self, text, reply_markup=None):
                                    return await client.edit_message_text(self.chat.id, self.id, text, reply_markup=reply_markup)
                                    
                            fake_msg = FakeMessage(prompt_msg_id, message.chat.id)
                            await show_requirement_settings(client, fake_msg, message.from_user.id)
                            return
                        except Exception as e:
                            print(f"Error editing creation prompt inline: {e}")
                            
                    # Fallback
                    await message.reply_text(f"![✅](tg://emoji?id=5219899949281453881) Referral requirement set to: **{ref_count}**")
                    await show_requirement_settings(client, message, message.from_user.id)
                else:
                    await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Session expired.")
            except ValueError:
                await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Please send a valid number.")
        else:
            await handle_campaign_creation_states(client, message, state)
    elif state and state.startswith("waiting_for_edit_ref_"):
        parts = state.split("_")
        page = int(parts[-1])
        campaign_id = "_".join(parts[4:-1])
        
        try:
            ref_count = int(message.text.strip())
            if ref_count < 0:
                await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Please send a number greater than or equal to 0.")
                return
                
            campaign = await db.get_campaign(campaign_id)
            if not campaign:
                await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Campaign not found.")
                await db.users.update_one({"user_id": message.from_user.id}, {"$set": {"state": None}})
                return
                
            reqs = campaign.get('requirements', {})
            reqs['referrals'] = ref_count
            await db.update_campaign_requirements(campaign_id, reqs)
            
            # Fetch and clear prompt_message_id
            prompt_msg_id = user.get("prompt_message_id")
            
            await db.users.update_one(
                {"user_id": message.from_user.id}, 
                {"$set": {"state": None}, "$unset": {"prompt_message_id": ""}}
            )
            
            # Try to delete user's message to keep chat history clean
            try:
                await message.delete()
            except Exception:
                pass
                
            if prompt_msg_id:
                try:
                    # In-place edit of the edit requirements menu directly
                    class FakeCallbackQuery:
                        def __init__(self, client, from_user, chat_id, msg_id, data):
                            self.client = client
                            self.from_user = from_user
                            self.data = data
                            self.message = type('FakeMessage', (), {
                                'chat': type('FakeChat', (), {'id': chat_id})(),
                                'id': msg_id,
                                'message_id': msg_id,
                                'edit_text': lambda text, reply_markup=None: client.edit_message_text(chat_id, msg_id, text, reply_markup=reply_markup)
                            })()
                        async def answer(self, text="", show_alert=False):
                            pass
                            
                    fake_cb = FakeCallbackQuery(
                        client=client,
                        from_user=message.from_user,
                        chat_id=message.chat.id,
                        msg_id=prompt_msg_id,
                        data=f"ec_{campaign_id}_{page}"
                    )
                    await edit_campaign_menu_handler(client, fake_cb)
                    return
                except Exception as e:
                    print(f"Error editing campaign edit requirements prompt inline: {e}")
            
            # Fallback
            text = (
                f"![✅](tg://emoji?id=5219899949281453881) Referral requirement updated to: **{ref_count}**\n\n"
                f"![🎯](tg://emoji?id=6025879072368761539) **Campaign:** {campaign['title']}"
            )
            buttons = [[InlineKeyboardButton("Back to Edit Requirements", callback_data=f"ec_{campaign_id}_{page}", icon_custom_emoji_id="5985574171550160682")]]
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        except ValueError:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Please send a valid integer number.")
    elif state and state.startswith("waiting_for_jump_"):
        try:
            page = int(message.text.strip()) - 1
            if page < 0: page = 0
            
            # Construct a fake callback query to reuse the handlers
            fake_cb = CallbackQuery(
                id="fake",
                from_user=message.from_user,
                client=client,
                message=message,
                chat_instance="fake",
                data=f"my_{state.split('_')[3]}_{page}"
            )
            
            # Redirect to the correct handler based on type
            if "camp" in state:
                await my_campaigns_handler(client, fake_cb)
            else:
                await my_channels_handler(client, fake_cb)
                
            await db.users.update_one({"user_id": message.from_user.id}, {"$set": {"state": None}})
        except Exception as e:
            print(f"Jump error: {e}")
            await db.users.update_one({"user_id": message.from_user.id}, {"$set": {"state": None}})


@Client.on_callback_query(filters.regex("^creator_analytics$"))
async def creator_analytics_handler(client, callback_query):
    user_id = callback_query.from_user.id
    campaigns = await db.get_creator_campaigns(user_id)
    
    total_unlocks = sum(c.get('unlocks', 0) for c in campaigns)
    total_views = sum(c.get('views', 0) for c in campaigns)
    total_unique = sum(len(c.get('unique_users', [])) for c in campaigns)
    
    text = (
        "![📈](tg://emoji?id=6026121742315952530) **Deep Analytics Dashboard**\n"
        "──────────────────────\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Total Campaigns:** `{len(campaigns)}`\n"
        f"![👁](tg://emoji?id=6024008227564296298) **Total Views:** `{total_views}`\n"
        f"![🔑](tg://emoji?id=6019290828759898301) **Total Unlocks:** `{total_unlocks}`\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Unique Unlocked:** `{total_unique}`\n"
        f"![📈](tg://emoji?id=6026121742315952530) **Conversion Rate:** `{(total_unlocks/total_views*100 if total_views > 0 else 0):.2f}%`\n\n"
        "**Detailed analytics help you optimize your content strategy.**"
    )
    buttons = [[InlineKeyboardButton("Back", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")]]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_channel_connection(client, message):
    channel_input = message.text.strip()
    
    # Check if they pasted a private invite link
    if "+" in channel_input or "joinchat" in channel_input:
        await message.reply_text(
            "![🛑](tg://emoji?id=6028583295447472629) **Private Invite Links cannot be used directly.**\n"
            "──────────────────────\n"
            "Bots cannot join or look up private channels using invite links.\n\n"
            "![💡](tg://emoji?id=6019364380074843443) **Please choose one of the following methods:**\n"
            "1. **Auto-Detection (easiest):** Add the bot to your channel as an **Admin** using the **➕ Add Bot to Channel** button. It will link automatically!\n"
            "2. **Manual ID:** If you know the numerical ID of your channel (starts with `-100`), send it here (e.g., `-1003372145976`)."
        )
        return

    # Basic cleaning for links
    if "t.me/" in channel_input:
        channel_input = channel_input.split("t.me/")[1].replace("+", "")
        if "/" in channel_input: # Handle join links with hash
            channel_input = channel_input.split("/")[0]
        if not channel_input.startswith("-100"):
            channel_input = f"@{channel_input}" if not channel_input.startswith("@") else channel_input
    
    # Convert to int if it is a numeric ID
    try:
        clean_input = channel_input.replace("-", "")
        if clean_input.isdigit():
            channel_input = int(channel_input)
    except Exception:
        pass
    
    try:
        chat = await client.get_chat(channel_input)
        if chat.type not in [ChatType.CHANNEL, ChatType.SUPERGROUP]:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) This is not a channel or supergroup.")
            return

        # Check if bot is admin
        try:
            member = await client.get_chat_member(chat.id, "me")
            if member.status != ChatMemberStatus.ADMINISTRATOR:
                await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Bot is not an admin in this channel. Please add it as admin first.")
                return
        except Exception:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) Bot is not an admin in this channel or cannot access it.")
            return

        # Check if the user is an owner or admin of the channel
        try:
            user_member = await client.get_chat_member(chat.id, message.from_user.id)
            if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) You must be the Owner or an Administrator of this channel to connect it.")
                return
        except Exception:
            await message.reply_text("![🛑](tg://emoji?id=6028583295447472629) You must be an Administrator/Owner of this channel to connect it.")
            return

        # Save to DB
        await db.add_channel(message.from_user.id, chat.id, chat.title, chat.username)
        await db.set_creator(message.from_user.id, True)
        await db.users.update_one({"user_id": message.from_user.id}, {"$set": {"state": None}})
        
        text = (
            "![✅](tg://emoji?id=5219899949281453881) **Channel Connected Successfully!**\n"
            "──────────────────────\n"
            f"![📢](tg://emoji?id=6021726637857446455) **{chat.title}** (@{chat.username or 'private'})\n\n"
            "![👑](tg://emoji?id=6021428854889913572) **Creator Panel Activated!**\n"
            "Use ➕ **New Campaign** to create your first campaign!\n\n"
            "*Note: Creating campaigns is completely free.*"
        )
        buttons = [
            [InlineKeyboardButton("Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="6026121742315952530")],
            [
                InlineKeyboardButton("New Campaign", callback_data="new_campaign", icon_custom_emoji_id="5807718484901108517"),
                InlineKeyboardButton("My Channels", callback_data="mch_0", icon_custom_emoji_id="6021726637857446455")
            ],
            [InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]
        ]
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        print(f"Error in handle_channel_connection: {e}")
        await message.reply_text(
            "![🛑](tg://emoji?id=6028583295447472629) **Unable to Connect Channel**\n"
            "──────────────────────\n"
            "An unexpected error occurred while connecting the channel.\n\n"
            "💡 **Please ensure:**\n"
            "1. The bot is added as an **Admin** in your channel.\n"
            "2. The bot has **Post Messages** and **Invite Users via Link** permissions.\n"
            "3. You sent a correct username (e.g. `@MyChannel`) or ID (e.g. `-100123456789`).\n\n"
            "![⚠️](tg://emoji?id=5807700854060357972) If everything is correct and it still fails, please contact the administrator."
        )

@Client.on_message(filters.command("creator") & filters.private)
async def creator_dashboard_command(client, message):
    user_id = message.from_user.id
    channels = await db.get_creator_channels(user_id)
    campaigns = await db.get_creator_campaigns(user_id)
    
    text = (
        "![📈](tg://emoji?id=6026121742315952530) **Creator Dashboard**\n"
        "──────────────────────\n"
        f"![📢](tg://emoji?id=6021726637857446455) **Connected Channels:** {len(channels)}\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Active Campaigns:** {len(campaigns)}\n\n"
        "Select an option below to manage your campaigns."
    )
    buttons = [
        [InlineKeyboardButton("New Campaign", callback_data="new_campaign", icon_custom_emoji_id="5807718484901108517")],
        [InlineKeyboardButton("Connect Channel", callback_data="connect_channel", icon_custom_emoji_id="6021726637857446455")],
        [
            InlineKeyboardButton("My Campaigns", callback_data="mc_0", icon_custom_emoji_id="6025879072368761539"),
            InlineKeyboardButton("My Channels", callback_data="mch_0", icon_custom_emoji_id="6021726637857446455")
        ],
        [
            InlineKeyboardButton("Analytics", callback_data="creator_analytics", icon_custom_emoji_id="6026121742315952530"),
            InlineKeyboardButton("Share Links", callback_data="share_links", icon_custom_emoji_id="5807453545548487345")
        ],
        [InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex("^creator_dashboard$"))
async def creator_dashboard_handler(client, callback_query):
    user_id = callback_query.from_user.id
    channels = await db.get_creator_channels(user_id)
    campaigns = await db.get_creator_campaigns(user_id)
    
    text = (
        "![📈](tg://emoji?id=6026121742315952530) **Creator Dashboard**\n"
        "──────────────────────\n"
        f"![📢](tg://emoji?id=6021726637857446455) **Connected Channels:** {len(channels)}\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Active Campaigns:** {len(campaigns)}\n\n"
        "Select an option below to manage your campaigns."
    )
    buttons = [
        [InlineKeyboardButton("New Campaign", callback_data="new_campaign", icon_custom_emoji_id="5807718484901108517")],
        [InlineKeyboardButton("Connect Channel", callback_data="connect_channel", icon_custom_emoji_id="6021726637857446455")],
        [
            InlineKeyboardButton("My Campaigns", callback_data="mc_0", icon_custom_emoji_id="6025879072368761539"),
            InlineKeyboardButton("My Channels", callback_data="mch_0", icon_custom_emoji_id="6021726637857446455")
        ],
        [
            InlineKeyboardButton("Analytics", callback_data="creator_analytics", icon_custom_emoji_id="6026121742315952530"),
            InlineKeyboardButton("Share Links", callback_data="share_links", icon_custom_emoji_id="5807453545548487345")
        ],
        [InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^mc_(\d+)$"))
async def my_campaigns_handler(client, callback_query):
    page = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    campaigns = await db.get_creator_campaigns(user_id)
    
    if not campaigns:
        text = "![🛑](tg://emoji?id=6028583295447472629) You haven't created any campaigns yet."
        buttons = [
            [InlineKeyboardButton("Create New", callback_data="new_campaign", icon_custom_emoji_id="5807718484901108517")],
            [InlineKeyboardButton("Back", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")]
        ]
        await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Pagination Logic
    PER_PAGE = 5
    total_pages = (len(campaigns) + PER_PAGE - 1) // PER_PAGE
    if page >= total_pages:
        page = max(0, total_pages - 1)
        
    start = page * PER_PAGE
    current_campaigns = campaigns[start:start+PER_PAGE]

    text = (
        "![🎯](tg://emoji?id=6025879072368761539) **My Unlock Campaigns**\n"
        "──────────────────────\n"
        f"![📖](tg://emoji?id=6021526054294788288) **Page:** `{page + 1}` **of** `{total_pages}`\n\n"
        "Select a campaign to view details."
    )
    
    buttons = []
    for camp in current_campaigns:
        title = camp['title']
        if len(title) > 20:
            title = title[:17] + "..."
        buttons.append([InlineKeyboardButton(title, callback_data=f"ci_{camp['_id']}_{page}", icon_custom_emoji_id="6025879072368761539")])
    
    # Navigation Buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Prev", callback_data=f"mc_{page - 1}", icon_custom_emoji_id="5985574171550160682"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton("Jump", callback_data=f"jump_page_camp_{page}", icon_custom_emoji_id="6035242302937503656"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next", callback_data=f"mc_{page + 1}", icon_custom_emoji_id="5807453545548487345"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([InlineKeyboardButton("New Campaign", callback_data="new_campaign", icon_custom_emoji_id="5807718484901108517")])
    buttons.append([InlineKeyboardButton("Back to Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")])
    
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^ci_(.+)_(\d+)$"))
async def campaign_details_handler(client, callback_query):
    # Use removeprefix for clean ID extraction
    parts = callback_query.data.rsplit("_", 1)
    page = int(parts[1])
    campaign_id = parts[0].removeprefix("ci_")
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ Campaign not found.", show_alert=True)
        return
        
    if 'materials' in campaign:
        m_type = f"Multiple ({len(campaign['materials'])} files)"
    else:
        m_type = campaign.get('material', {}).get('type', 'Unknown').capitalize()
    bot_username = (await client.get_me()).username
    link = f"https://t.me/{bot_username}?start={campaign_id}"
    
    fj_channels = campaign['requirements'].get('force_join', [])
    channel_names = []
    for ch_id in fj_channels:
        ch = await db.get_channel(ch_id)
        if ch:
            channel_names.append(ch['title'])
        else:
            channel_names.append(str(ch_id))
            
    fj_status = ", ".join(channel_names) if channel_names else "None"
    ref_status = campaign['requirements'].get('referrals', 0)
    
    text = (
        f"![🎯](tg://emoji?id=6025879072368761539) **Campaign: {campaign['title']}**\n"
        "──────────────────────\n"
        f"![📦](tg://emoji?id=6024106569430472546) **Material:** `{m_type}`\n"
        f"![📢](tg://emoji?id=6021726637857446455) **Force Sub:** `{fj_status}`\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Ref Required:** `{ref_status}` users\n\n"
        f"![👁](tg://emoji?id=6024008227564296298) **Total Views:** `{campaign.get('views', 0)}`\n"
        f"![🔑](tg://emoji?id=6019290828759898301) **Total Unlocks:** `{campaign.get('unlocks', 0)}`\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Unique Unlocked:** `{len(campaign.get('unique_users', []))}`\n"
        f"![📈](tg://emoji?id=6026121742315952530) **Conversion:** `{(campaign.get('unlocks', 0)/campaign.get('views', 1)*100 if campaign.get('views', 0) > 0 else 0):.2f}%`\n\n"
        f"![🔗](tg://emoji?id=5807453545548487345) **Link:** `{link}`"
    )
    
    buttons = [
        [InlineKeyboardButton("Share Link", url=f"https://t.me/share/url?url={link}", icon_custom_emoji_id="5807453545548487345")],
        [InlineKeyboardButton("Edit Requirements", callback_data=f"ec_{campaign_id}_{page}", icon_custom_emoji_id="6021637109264160908")],
        [InlineKeyboardButton("Delete Campaign", callback_data=f"cd_{campaign_id}_{page}", icon_custom_emoji_id="6021413766669801212")],
        [InlineKeyboardButton("Back", callback_data=f"mc_{page}", icon_custom_emoji_id="5985574171550160682")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^mch_(\d+)$"))
async def my_channels_handler(client, callback_query):
    page = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id
    channels = await db.get_creator_channels(user_id)
    
    if not channels:
        text = "![🛑](tg://emoji?id=6028583295447472629) You haven't connected any channels yet."
        buttons = [
            [InlineKeyboardButton("Connect Channel", callback_data="connect_channel", icon_custom_emoji_id="6021726637857446455")],
            [InlineKeyboardButton("Back", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")]
        ]
        await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Pagination Logic
    PER_PAGE = 5
    total_pages = (len(channels) + PER_PAGE - 1) // PER_PAGE
    if page >= total_pages:
        page = max(0, total_pages - 1)
        
    start = page * PER_PAGE
    current_channels = channels[start:start+PER_PAGE]

    text = (
        "![📢](tg://emoji?id=6021726637857446455) **My Connected Channels**\n"
        "──────────────────────\n"
        f"![📖](tg://emoji?id=6021526054294788288) **Page:** `{page + 1}` **of** `{total_pages}`\n\n"
        "Select a channel to view stats or manage it."
    )
    
    buttons = []
    for ch in current_channels:
        title = ch['title']
        if len(title) > 20:
            title = title[:17] + "..."
        buttons.append([InlineKeyboardButton(title, callback_data=f"chi_{ch['channel_id']}_{page}", icon_custom_emoji_id="6021726637857446455")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Prev", callback_data=f"mch_{page - 1}", icon_custom_emoji_id="5985574171550160682"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton("Jump", callback_data=f"jump_page_ch_{page}", icon_custom_emoji_id="6035242302937503656"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next", callback_data=f"mch_{page + 1}", icon_custom_emoji_id="5807453545548487345"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([InlineKeyboardButton("Connect Another", callback_data="connect_channel", icon_custom_emoji_id="5807642902066634351")])
    buttons.append([InlineKeyboardButton("Back to Dashboard", callback_data="creator_dashboard", icon_custom_emoji_id="5985574171550160682")])
    
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^cd_(.+)_(\d+)$"))
async def campaign_delete_prompt(client, callback_query):
    parts = callback_query.data.rsplit("_", 1)
    page = int(parts[1])
    campaign_id = parts[0].removeprefix("cd_")
    
    text = "![⚠️](tg://emoji?id=5807700854060357972) **Are you sure you want to delete this campaign?**\n\nThis action cannot be undone."
    buttons = [
        [InlineKeyboardButton("Yes, Delete", callback_data=f"cdc_{campaign_id}_{page}", icon_custom_emoji_id="5219899949281453881")],
        [InlineKeyboardButton("Cancel", callback_data=f"ci_{campaign_id}_{page}", icon_custom_emoji_id="5807651380332076999")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^cdc_(.+)_(\d+)$"))
async def campaign_delete_confirm_handler(client, callback_query):
    parts = callback_query.data.rsplit("_", 1)
    page = int(parts[1])
    campaign_id = parts[0].removeprefix("cdc_")
    
    print(f"[BOT] Deletion confirmed for ID: {campaign_id} on page {page}")
    success = await db.delete_campaign(callback_query.from_user.id, campaign_id)
    
    if success:
        await callback_query.answer("✅ Campaign deleted successfully!", show_alert=True)
    else:
        await callback_query.answer("❌ Error: Campaign already deleted or not found.", show_alert=True)
    
    callback_query.data = f"mc_{page}"
    await my_campaigns_handler(client, callback_query)

@Client.on_callback_query(filters.regex(r"^jump_page_(camp|ch)_(\d+)$"))
async def jump_page_handler(client, callback_query):
    data = callback_query.data.split("_")
    type_ = data[2]
    current_page = int(data[3])
    
    await callback_query.answer("Send the page number you want to jump to.", show_alert=True)
    await db.users.update_one({"user_id": callback_query.from_user.id}, {"$set": {"state": f"waiting_for_jump_{type_}"}})

@Client.on_callback_query(filters.regex(r"^chi_(-?\d+)_(\d+)$"))
async def channel_info_handler(client, callback_query):
    data = callback_query.data.split("_")
    channel_id = int(data[1])
    page = int(data[2])
    
    channel = await db.get_channel(channel_id)
    if not channel:
        await callback_query.answer("❌ Channel not found.", show_alert=True)
        return
        
    campaigns = await db.campaigns.find({"requirements.force_join": channel_id}).to_list(length=None)
    total_views = sum(c.get('views', 0) for c in campaigns)
    total_unlocks = sum(c.get('unlocks', 0) for c in campaigns)
    
    username = channel.get('username')
    invite_link = None
    if not username:
        invite_link = await get_invite_link(client, channel_id)

    text = (
        f"![📢](tg://emoji?id=6021726637857446455) **Channel Info: {channel['title']}**\n"
        "──────────────────────\n"
        f"![🪪](tg://emoji?id=6021367625836140615) **ID:** `{channel_id}`\n"
    )
    if username:
        text += f"![🔗](tg://emoji?id=5807453545548487345) **Username:** `@{username}`\n\n"
    else:
        text += f"![🔗](tg://emoji?id=5807453545548487345) **Invite Link:** `{invite_link or 'Unavailable'}`\n\n"

    text += (
        f"![👁](tg://emoji?id=6024008227564296298) **Total Views:** `{total_views}`\n"
        f"![🔑](tg://emoji?id=6019290828759898301) **Total Unlocks:** `{total_unlocks}`\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Campaigns:** `{len(campaigns)}`\n"
    )
    
    # View Channel button URL mapping
    view_url = f"https://t.me/{username}" if username else invite_link
    buttons = []
    if view_url:
        buttons.append([InlineKeyboardButton("View Channel", url=view_url, icon_custom_emoji_id="5424892643760937442")])
        
    buttons.extend([
        [InlineKeyboardButton("Remove Channel", callback_data=f"cr_{channel_id}_{page}", icon_custom_emoji_id="6021413766669801212")],
        [InlineKeyboardButton("Back", callback_data=f"mch_{page}", icon_custom_emoji_id="5985574171550160682")]
    ])
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"^cr_(-?\d+)_(\d+)$"))
async def channel_remove_handler(client, callback_query):
    data = callback_query.data.split("_")
    channel_id = int(data[1])
    page = int(data[2])
    
    text = (
        "![⚠️](tg://emoji?id=5807700854060357972) **Are you sure you want to remove this channel?**\n\n"
        "This will remove it from all your campaigns' force-join requirements."
    )
    buttons = [
        [InlineKeyboardButton("Yes, Remove", callback_data=f"crc_{channel_id}_{page}", icon_custom_emoji_id="5219899949281453881")],
        [InlineKeyboardButton("Cancel", callback_data=f"chi_{channel_id}_{page}", icon_custom_emoji_id="5807651380332076999")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^crc_(-?\d+)_(\d+)$"))
async def channel_remove_confirm_handler(client, callback_query):
    data = callback_query.data.split("_")
    channel_id = int(data[1])
    page = int(data[2])
    
    await db.remove_channel(callback_query.from_user.id, channel_id)
    await callback_query.answer("✅ Channel removed successfully!", show_alert=True)
    
    # Update callback data so my_channels_handler can parse it
    callback_query.data = f"mch_{page}"
    await my_channels_handler(client, callback_query)

@Client.on_chat_join_request()
async def auto_detect_join_request(client, chat_join_request):
    chat_id = chat_join_request.chat.id
    user_id = chat_join_request.from_user.id
    print(f"DEBUG: ChatJoinRequest received from user {user_id} in chat {chat_id}")
    
    try:
        await db.add_join_request(user_id, chat_id)
        print(f"DEBUG: Saved pending join request for user {user_id} in {chat_id}")
    except Exception as e:
        print(f"Error saving join request to DB: {e}")

@Client.on_callback_query(filters.regex(r"^ec_(.+)_(\d+)$"))
async def edit_campaign_menu_handler(client, callback_query):
    parts = callback_query.data.rsplit("_", 1)
    page = int(parts[1])
    campaign_id = parts[0].removeprefix("ec_")
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ Campaign not found.", show_alert=True)
        return
        
    fj_channels = campaign['requirements'].get('force_join', [])
    request_channels = campaign['requirements'].get('request_join', [])
    channel_names = []
    for ch_id in fj_channels:
        ch = await db.get_channel(ch_id)
        style = "Request" if ch_id in request_channels else "Normal"
        if ch:
            channel_names.append(f"{ch['title']} ({style})")
        else:
            channel_names.append(f"{ch_id} ({style})")
            
    fj_status = ", ".join(channel_names) if channel_names else "None"
    ref_status = campaign['requirements'].get('referrals', 0)
    
    text = (
        f"![⚙️](tg://emoji?id=6021637109264160908) **Edit Requirements: {campaign['title']}**\n"
        "──────────────────────\n"
        f"![📢](tg://emoji?id=6021726637857446455) **Force Subscribe:** `{fj_status}`\n"
        f"![👥](tg://emoji?id=6021642336239360403) **Referrals Required:** `{ref_status}` referrals\n"
    )
    
    buttons = [
        [InlineKeyboardButton("Choose Channels", callback_data=f"ecch_{campaign_id}_{page}_0", icon_custom_emoji_id="6021726637857446455")],
        [InlineKeyboardButton("Edit Referral Count", callback_data=f"ecref_{campaign_id}_{page}", icon_custom_emoji_id="6021642336239360403")],
        [InlineKeyboardButton("Back to Details", callback_data=f"ci_{campaign_id}_{page}", icon_custom_emoji_id="5985574171550160682")]
    ]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^ecch_(.+)_(\d+)_(\d+)$"))
async def edit_campaign_channels_handler(client, callback_query):
    parts = callback_query.data.split("_")
    ch_page = int(parts[-1])
    page = int(parts[-2])
    campaign_id = "_".join(parts[1:-2])
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ Campaign not found.", show_alert=True)
        return
        
    user_id = callback_query.from_user.id
    channels = await db.get_creator_channels(user_id)
    
    # Pagination Logic for channels
    PER_PAGE = 5
    total_pages = (len(channels) + PER_PAGE - 1) // PER_PAGE
    if total_pages == 0:
        total_pages = 1
        
    start = ch_page * PER_PAGE
    current_channels = channels[start:start+PER_PAGE]
    
    text = (
        f"![📢](tg://emoji?id=6021726637857446455) **Choose Channels for Force Subscribe:**\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Campaign:** {campaign['title']}\n"
        "──────────────────────\n"
        f"![📖](tg://emoji?id=6021526054294788288) **Page:** `{ch_page + 1}` **of** `{total_pages}`\n\n"
        "Toggle channels below. If a channel is selected, you can toggle between Normal Link and Request Link styles."
    )
    
    buttons = []
    selected_channels = campaign['requirements'].get('force_join', [])
    request_channels = campaign['requirements'].get('request_join', [])
    for ch in current_channels:
        ch_id = ch['channel_id']
        is_selected = ch_id in selected_channels
        is_public = bool(ch.get('username'))
        type_str = "Public" if is_public else "Private"
        row = []
        if is_selected:
            row.append(InlineKeyboardButton(f"{ch['title']} ({type_str})", callback_data=f"tect_{campaign_id}_{page}_{ch_page}_{ch_id}", icon_custom_emoji_id="5219899949281453881"))
            if is_public:
                row.append(InlineKeyboardButton("Public Channel", callback_data=f"pubalert_{campaign_id}_{page}_{ch_page}_{ch_id}", icon_custom_emoji_id="5807928135139728476"))
            else:
                is_req = ch_id in request_channels
                link_type_text = "Request" if is_req else "Normal"
                link_type_icon = "5807557921843715576" if is_req else "5807453545548487345"
                row.append(InlineKeyboardButton(link_type_text, callback_data=f"telt_{campaign_id}_{page}_{ch_page}_{ch_id}", icon_custom_emoji_id=link_type_icon))
        else:
            row.append(InlineKeyboardButton(f"{ch['title']} ({type_str})", callback_data=f"tect_{campaign_id}_{page}_{ch_page}_{ch_id}", icon_custom_emoji_id="5807651380332076999"))
            
        buttons.append(row)
        
    # Navigation Buttons
    nav_buttons = []
    if ch_page > 0:
        nav_buttons.append(InlineKeyboardButton("Prev", callback_data=f"ecch_{campaign_id}_{page}_{ch_page - 1}", icon_custom_emoji_id="5985574171550160682"))
    if ch_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next", callback_data=f"ecch_{campaign_id}_{page}_{ch_page + 1}", icon_custom_emoji_id="5807453545548487345"))
        
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([InlineKeyboardButton("Done", callback_data=f"ec_{campaign_id}_{page}", icon_custom_emoji_id="5219899949281453881")])
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^tect_(.+)_(\d+)_(\d+)_(-?\d+)$"))
async def toggle_edit_campaign_channel_handler(client, callback_query):
    parts = callback_query.data.split("_")
    ch_id = int(parts[-1])
    ch_page = int(parts[-2])
    page = int(parts[-3])
    campaign_id = "_".join(parts[1:-3])
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ Campaign not found.", show_alert=True)
        return
        
    reqs = campaign.get('requirements', {})
    fj = reqs.get('force_join', [])
    
    if "request_join" not in reqs:
        reqs['request_join'] = []

    if ch_id in fj:
        fj.remove(ch_id)
        if ch_id in reqs['request_join']:
            reqs['request_join'].remove(ch_id)
    else:
        fj.append(ch_id)
        
    reqs['force_join'] = fj
    await db.update_campaign_requirements(campaign_id, reqs)
    
    # Refresh
    callback_query.data = f"ecch_{campaign_id}_{page}_{ch_page}"
    await edit_campaign_channels_handler(client, callback_query)

@Client.on_callback_query(filters.regex(r"^telt_(.+)_(\d+)_(\d+)_(-?\d+)$"))
async def toggle_edit_campaign_link_type_handler(client, callback_query):
    parts = callback_query.data.split("_")
    ch_id = int(parts[-1])
    ch_page = int(parts[-2])
    page = int(parts[-3])
    campaign_id = "_".join(parts[1:-3])
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ Campaign not found.", show_alert=True)
        return
        
    reqs = campaign.get('requirements', {})
    if "request_join" not in reqs:
        reqs['request_join'] = []
        
    if ch_id in reqs['request_join']:
        reqs['request_join'].remove(ch_id)
        await callback_query.answer("🔗 Switched to Normal Link style.", show_alert=False)
    else:
        reqs['request_join'].append(ch_id)
        await callback_query.answer("📥 Switched to Join Request Link style.", show_alert=False)
        
    await db.update_campaign_requirements(campaign_id, reqs)
    
    # Refresh
    callback_query.data = f"ecch_{campaign_id}_{page}_{ch_page}"
    await edit_campaign_channels_handler(client, callback_query)

@Client.on_callback_query(filters.regex(r"^pubalert_(.+)_(\d+)_(\d+)_(-?\d+)$"))
async def pub_channel_alert_edit_handler(client, callback_query):
    await callback_query.answer("⚠️ Join requests are only applicable for private channels!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^ecref_(.+)_(\d+)$"))
async def edit_campaign_referral_prompt(client, callback_query):
    parts = callback_query.data.rsplit("_", 1)
    page = int(parts[1])
    campaign_id = parts[0].removeprefix("ecref_")
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        await callback_query.answer("❌ Campaign not found.", show_alert=True)
        return
        
    user_id = callback_query.from_user.id
    current_ref = campaign['requirements'].get('referrals', 0)
    
    text = (
        f"![👥](tg://emoji?id=6021642336239360403) **Edit Referral Requirement**\n"
        f"![🎯](tg://emoji?id=6025879072368761539) **Campaign:** {campaign['title']}\n"
        "──────────────────────\n"
        f"![📈](tg://emoji?id=6026121742315952530) Current required referrals: `{current_ref}`\n\n"
        "Please send the new number of referrals required to unlock this content (send `0` to disable referrals)."
    )
    
    buttons = [[InlineKeyboardButton("Cancel", callback_data=f"ec_{campaign_id}_{page}", icon_custom_emoji_id="5807651380332076999")]]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    # Set user state
    await db.users.update_one(
        {"user_id": user_id}, 
        {"$set": {
            "state": f"waiting_for_edit_ref_{campaign_id}_{page}",
            "prompt_message_id": callback_query.message.id
        }}
    )
