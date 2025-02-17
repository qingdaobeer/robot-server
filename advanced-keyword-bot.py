from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext, CommandHandler
import json
import logging
from enum import Enum
from typing import List
from datetime import datetime, timedelta
from collections import defaultdict

class PermissionLevel(Enum):
    PUBLIC = "PUBLIC"  # ✅ Add this line
    MEMBER = "MEMBER"
    ADMIN = "ADMIN"
    OWNER = "OWNER"

class MessageStats:
    def __init__(self):
        self.stats_file = "message_stats.json"
        self.stats = self.load_stats()

    def load_stats(self) -> dict:
        try:
            with open(self.stats_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"users": {}, "messages": defaultdict(list)}

    def save_stats(self):
        with open(self.stats_file, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=2, ensure_ascii=False)

    def record_message(self, user_id: int, username: str, date: datetime):
        """记录用户的发言数据"""
        user_id_str = str(user_id)

        # ✅ Ensure user exists in 'users' section
        if user_id_str not in self.stats["users"]:
            self.stats["users"][user_id_str] = {
                "username": username,
                "first_seen": date.isoformat()
            }

        # ✅ Ensure user exists in 'messages' section
        if user_id_str not in self.stats["messages"]:
            self.stats["messages"][user_id_str] = []

        # ✅ Now it's safe to append
        self.stats["messages"][user_id_str].append(date.isoformat())

        # Save the updated stats
        self.save_stats()

    def get_user_stats(self, user_id: str, period: str) -> int:
        if user_id not in self.stats["messages"]:
            return 0

        messages = self.stats["messages"][user_id]
        now = datetime.now()
        start_time = now - {
            "day": timedelta(days=1),
            "week": timedelta(weeks=1),
            "month": timedelta(days=30),
        }.get(period, timedelta(days=99999))

        return sum(1 for msg_time in messages if datetime.fromisoformat(msg_time) > start_time)

    def get_leaderboard(self, period: str, limit: int = 10) -> List[dict]:
        return sorted(
            [
                {
                    "user_id": user_id,
                    "username": self.stats["users"][user_id]["username"],
                    "count": self.get_user_stats(user_id, period),
                }
                for user_id in self.stats["messages"]
            ],
            key=lambda x: x["count"],
            reverse=True,
        )[:limit]

class KeywordBot:
    def __init__(self, config_path: str = "config.json"):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except FileNotFoundError:
            print("❌ Error: config.json file not found!")
            self.config = {"bot_token": "", "allowed_group_ids": []}

        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)

        self.message_stats = MessageStats()

        try:
            with open("keywords.json", "r", encoding="utf-8") as f:
                self.keywords = json.load(f)
        except FileNotFoundError:
            self.keywords = {}

        try:
            with open("user_roles.json", "r", encoding="utf-8") as f:
                self.user_roles = json.load(f)
        except FileNotFoundError:
            self.user_roles = {}

    def save_data(self):
        with open("keywords.json", "w", encoding="utf-8") as f:
            json.dump(self.keywords, f, indent=2, ensure_ascii=False)

    def check_permission(self, user_id: int, required_level):
        if not hasattr(self, "user_roles"):
            self.user_roles = {}

        user_role = self.user_roles.get(str(user_id), "MEMBER")

        role_hierarchy = {"MEMBER": 1, "ADMIN": 2, "OWNER": 3}

        return role_hierarchy.get(user_role, 1) >= role_hierarchy.get(required_level.name, 1)

    async def add_keyword(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        if not self.check_permission(user_id, PermissionLevel.ADMIN):
            await update.message.reply_text("抱歉，你没有权限执行此操作。")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text("用法：/add_keyword <关键词> <回复内容>")
            return

        keyword = args[0]
        response = " ".join(args[1:])

        if keyword in self.keywords:
            await update.message.reply_text(f"关键词 '{keyword}' 已存在。")
            return

        self.keywords[keyword] = {"response": response, "permission_level": "PUBLIC"}
        self.save_data()
        await update.message.reply_text(f"关键词 '{keyword}' 已添加，回复内容: {response}")

    async def message_handler(self, update: Update, context: CallbackContext):
        self.logger.info(f"🔹 Received message: {update.message.text}")
        self.logger.info(f"🔹 Available keywords: {list(self.keywords.keys())}")

        if update.message.chat.id not in self.config['allowed_group_ids']:
            self.logger.info(f"❌ Chat ID {update.message.chat.id} not allowed.")
            return

        user = update.message.from_user
        self.message_stats.record_message(
            user.id,
            user.username or user.first_name,
            update.message.date
        )

        text = update.message.text.strip().lower()
        self.logger.info(f"🔹 Checking message text: {text}")

        for keyword, data in self.keywords.items():
            self.logger.info(f"🔹 Checking keyword: {keyword}")

            if keyword.lower() in text:
                self.logger.info(f"✅ Keyword '{keyword}' matched!")

                permission_str = data.get('permission_level', 'PUBLIC')  # Default to PUBLIC
                try:
                    required_level = PermissionLevel[permission_str]
                except KeyError:
                    self.logger.error(f"❌ Invalid permission level: {permission_str}")
                    required_level = PermissionLevel.PUBLIC  # Fallback

                if self.check_permission(user.id, required_level):
                    self.logger.info(f"✅ User {user.id} has permission. Sending response...")
                    await update.message.reply_text(data['response'])
                    return
                else:
                    self.logger.info(f"❌ User {user.id} does NOT have permission.")




def main():
    bot = KeywordBot()
    application = Application.builder().token(bot.config["bot_token"]).build()

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.message_handler))
    application.add_handler(CommandHandler("add_keyword", bot.add_keyword))

    application.run_polling()

if __name__ == "__main__":
    main()
