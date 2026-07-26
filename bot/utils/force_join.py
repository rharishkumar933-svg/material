from pyrogram.errors import UserNotParticipant
from pyrogram.enums import ChatMemberStatus
from bot.database.mongo import db

async def is_user_member(client, chat_id, user_id, use_request_link=False):
    try:
        member = await client.get_chat_member(chat_id, user_id)
        if member.status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        ]:
            return True
        return False
    except UserNotParticipant:
        # Check if they have a pending invite request for request-based channels
        if use_request_link:
            try:
                pending = await db.get_join_request(user_id, chat_id)
                if pending:
                    # User requested to join (pending in DB), allow them to unlock!
                    return True
            except Exception as e:
                print(f"Error checking pending join request in membership check: {e}")
        return False
    except Exception as e:
        print(f"Error checking membership: {e}")
        return False

async def get_invite_link(client, chat_id, use_request_link=False):
    try:
        channel = await db.get_channel(chat_id)
        if use_request_link:
            # If join request link is requested, check cache or create one
            if channel and channel.get('request_invite_link'):
                return channel.get('request_invite_link')
                
            link = await client.create_chat_invite_link(chat_id, creates_join_request=True)
            request_link = link.invite_link
            
            if channel:
                await db.channels.update_one(
                    {"channel_id": chat_id},
                    {"$set": {"request_invite_link": request_link}}
                )
            return request_link
        else:
            # If normal link is requested
            if channel and channel.get('username'):
                return f"https://t.me/{channel['username']}"
                
            if channel and channel.get('normal_invite_link'):
                return channel.get('normal_invite_link')
                
            chat = await client.get_chat(chat_id)
            if chat.invite_link:
                normal_link = chat.invite_link
            else:
                link = await client.create_chat_invite_link(chat_id)
                normal_link = link.invite_link
                
            if channel:
                await db.channels.update_one(
                    {"channel_id": chat_id},
                    {"$set": {"normal_invite_link": normal_link}}
                )
            return normal_link
    except Exception as e:
        print(f"Error getting invite link: {e}")
        # Fallback to public link if it has a username, or fallback to standard chat invite link
        try:
            channel = await db.get_channel(chat_id)
            if channel and channel.get('username'):
                return f"https://t.me/{channel['username']}"
        except:
            pass
        return None

