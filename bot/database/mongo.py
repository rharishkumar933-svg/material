from motor.motor_asyncio import AsyncIOMotorClient
from bot.config import Config
import re
import uuid
from datetime import datetime
from bson import ObjectId

class Database:
    def __init__(self):
        self.client = AsyncIOMotorClient(Config.MONGODB_URL)
        self.db = self.client[Config.DATABASE_NAME]
        self.users = self.db["users"]
        self.channels = self.db["channels"]
        self.campaigns = self.db["campaigns"]
        self.unlocks = self.db["unlocks"]
        self.join_requests = self.db["join_requests"]

    # --- User Operations ---
    async def get_user(self, user_id):
        return await self.users.find_one({"user_id": user_id})

    async def add_user(self, user_id, username=None, referrer=None, campaign_id=None):
        if not await self.get_user(user_id):
            user_data = {
                "user_id": user_id,
                "username": username,
                "is_creator": False,
                "is_banned": False,
                "referrer": referrer,
                "referral_count": 0,
                "campaign_referrals": {}, # Track campaign_id -> list of referred user_ids
                "total_unlocks": 0,
                "unlocked_campaigns": [], # Track campaign IDs
                "joined_at": None # Can be added if needed
            }
            await self.users.insert_one(user_data)
            if referrer:
                await self.users.update_one({"user_id": referrer}, {"$inc": {"referral_count": 1}})
                if campaign_id:
                    await self.users.update_one(
                        {"user_id": referrer},
                        {"$addToSet": {f"campaign_referrals.{campaign_id}": user_id}}
                    )

    async def track_unlock(self, user_id, campaign_id):
        await self.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {"total_unlocks": 1},
                "$addToSet": {"unlocked_campaigns": campaign_id}
            }
        )

    async def set_creator(self, user_id, status=True):
        await self.users.update_one({"user_id": user_id}, {"$set": {"is_creator": status}})

    async def remove_channel(self, creator_id, channel_id):
        # Verify ownership before deletion
        res = await self.channels.delete_one({"channel_id": channel_id, "creator_id": creator_id})
        if res.deleted_count > 0:
            # Delete all campaigns that require this channel for force-join
            await self.campaigns.delete_many({"requirements.force_join": channel_id, "creator_id": creator_id})
            return True
        return False

    # --- Channel Operations ---
    async def add_channel(self, creator_id, channel_id, title, username=None):
        await self.channels.update_one(
            {"channel_id": channel_id},
            {"$set": {"creator_id": creator_id, "title": title, "username": username}},
            upsert=True
        )

    async def get_creator_channels(self, creator_id):
        return await self.channels.find({"creator_id": creator_id}).to_list(length=100)

    async def get_channel(self, channel_id):
        return await self.channels.find_one({"channel_id": channel_id})

    # --- Campaign Operations ---
    async def create_campaign(self, creator_id, data):
        title = data.get("title", "Untitled")
        # Generate short slug (max 10 characters)
        slug = re.sub(r'[^a-zA-Z0-9]', '_', title.strip())
        if not slug:
            slug = "content"
        else:
            slug = slug[:10].strip("_")
            if not slug: slug = "content"
        
        # Check uniqueness
        if await self.campaigns.find_one({"_id": slug}):
            slug = f"{slug}_{uuid.uuid4().hex[:4]}"
            
        campaign = {
            "_id": slug,
            "creator_id": creator_id,
            "title": title,
            "material": data.get("material"),
            "materials": data.get("materials"),
            "requirements": data.get("requirements", {}),
            "views": 0,
            "unlocks": 0,
            "protect_content": data.get("protect_content", False)
        }
        await self.campaigns.insert_one(campaign)
        return slug

    async def get_campaign(self, campaign_id):
        # Try direct ID (slug)
        res = await self.campaigns.find_one({"_id": campaign_id})
        if res: return res
        
        try:
            return await self.campaigns.find_one({"_id": ObjectId(campaign_id)})
        except:
            return None

    async def delete_campaign(self, creator_id, campaign_id):
        print(f"[DB] Attempting to delete campaign: {campaign_id} for creator {creator_id}")
        # Try direct ID with creator verification
        res = await self.campaigns.delete_one({"_id": campaign_id, "creator_id": creator_id})
        if res.deleted_count > 0:
            print(f"[DB] Successfully deleted (String ID): {campaign_id}")
            return True
        
        try:
            res = await self.campaigns.delete_one({"_id": ObjectId(campaign_id), "creator_id": creator_id})
            if res.deleted_count > 0:
                print(f"[DB] Successfully deleted (ObjectId): {campaign_id}")
                return True
        except Exception as e:
            print(f"[DB] ObjectId error for {campaign_id}: {e}")
            
        print(f"[DB] Deletion FAILED (Security or Not Found) for: {campaign_id}")
        return False

    async def get_creator_campaigns(self, creator_id):
        return await self.campaigns.find({"creator_id": creator_id}).to_list(length=100)

    async def increment_campaign_stats(self, campaign_id, field="views", user_id=None):
        # If user_id is provided, we track unique unlocks
        update_query = {"$inc": {field: 1}}
        if field == "unlocks" and user_id:
            update_query["$addToSet"] = {"unique_users": user_id}
            
        # Try direct ID
        res = await self.campaigns.update_one({"_id": campaign_id}, update_query)
        if res.modified_count > 0: return
        
        try:
            await self.campaigns.update_one({"_id": ObjectId(campaign_id)}, update_query)
        except:
            pass

    # --- Join Request & Auto-Approve Operations ---
    async def add_join_request(self, user_id, chat_id):
        await self.join_requests.update_one(
            {"user_id": user_id, "chat_id": chat_id},
            {"$set": {"status": "pending"}},
            upsert=True
        )

    async def get_join_request(self, user_id, chat_id):
        return await self.join_requests.find_one({"user_id": user_id, "chat_id": chat_id, "status": "pending"})

    async def approve_join_request(self, user_id, chat_id):
        await self.join_requests.delete_one({"user_id": user_id, "chat_id": chat_id})

    async def toggle_request_link(self, channel_id, status: bool, link: str = None):
        update_data = {"use_request_link": status}
        if link:
            update_data["request_invite_link"] = link
                
        await self.channels.update_one(
            {"channel_id": channel_id},
            {"$set": update_data}
        )

    async def update_campaign_requirements(self, campaign_id, requirements):
        res = await self.campaigns.update_one({"_id": campaign_id}, {"$set": {"requirements": requirements}})
        if res.modified_count > 0: return
        try:
            await self.campaigns.update_one({"_id": ObjectId(campaign_id)}, {"$set": {"requirements": requirements}})
        except:
            pass

    # --- Global Stats ---
    async def get_global_stats(self):
        total_users = await self.users.count_documents({})
        total_creators = await self.users.count_documents({"is_creator": True})
        total_campaigns = await self.campaigns.count_documents({})
        return {
            "total_users": total_users,
            "total_creators": total_creators,
            "total_campaigns": total_campaigns
        }

    # --- Settings Operations ---
    async def get_setting(self, key, default=None):
        setting = await self.db["settings"].find_one({"_id": key})
        return setting.get("value", default) if setting else default

    async def set_setting(self, key, value):
        await self.db["settings"].update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

    # --- Ads Operations ---
    async def add_ad(self, title, chat_id, message_id):
        await self.db["ads"].insert_one({
            "title": title,
            "chat_id": chat_id,
            "message_id": message_id,
            "created_at": datetime.now()
        })

    async def get_all_ads(self):
        return await self.db["ads"].find({}).to_list(length=100)

    async def get_ad(self, ad_id):
        try:
            return await self.db["ads"].find_one({"_id": ObjectId(ad_id)})
        except:
            return None

    async def delete_ad_data(self, ad_id):
        try:
            await self.db["ads"].delete_one({"_id": ObjectId(ad_id)})
        except:
            pass

    async def get_random_ad(self):
        enabled = await self.get_setting("ads_enabled", False)
        if not enabled:
            return None
        count = await self.db["ads"].count_documents({})
        if count == 0:
            return None
        import random
        cursor = self.db["ads"].find({}).skip(random.randint(0, count - 1)).limit(1)
        ads = await cursor.to_list(length=1)
        return ads[0] if ads else None

db = Database()
