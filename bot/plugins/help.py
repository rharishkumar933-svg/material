from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

@Client.on_callback_query(filters.regex("^help_info$"))
async def help_handler(client, callback_query):
    text = (
        "![❓](tg://emoji?id=5807800879553715710) **Material Unlock Bot - Help**\n"
        "──────────────────────\n"
        "This bot helps content creators grow their channels by locking exclusive content behind a join requirement.\n\n"
        "![📖](tg://emoji?id=6021526054294788288) **How it works:**\n"
        "1. **Creators** connect their channel and create a 'Campaign'.\n"
        "2. They get a link (e.g., `t.me/bot?start=xyz`).\n"
        "3. When a **User** clicks the link, they must join the required channels and/or refer friends to unlock the content.\n"
        "4. Once unlocked, the material is sent but deleted after 1 minute for privacy.\n\n"
        "![🛠](tg://emoji?id=6021401276904905698) **Features:**\n"
        "• Force Join (Public/Private/Join Request)\n"
        "• Referral Tracking\n"
        "• Detailed Analytics for Creators\n"
        "• Auto-deletion of unlocked content\n\n"
        "Need more help? Contact @Admin" # Placeholder
    )
    buttons = [[InlineKeyboardButton("Back", callback_data="main_menu", icon_custom_emoji_id="5985574171550160682")]]
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
