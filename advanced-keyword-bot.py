from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext, CommandHandler
import json
import logging
from functools import wraps
from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd
from collections import defaultdict

class MessageStats:
    def __init__(self):
        self.stats_file = 'message_stats.json'
        self.stats = self.load_stats()

    def load_stats(self) -> dict:
        try:
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                'users': {},  # 用户基本信息
                'messages': defaultdict(list)  # 消息记录
            }

    def save_stats(self):
        with open(self.stats_file, 'w', encoding='utf-8') as f:
            json.dump(self.stats, f, indent=2, ensure_ascii=False)

    def record_message(self, user_id: int, username: str, date: datetime):
        # 更新用户信息
        if str(user_id) not in self.stats['users']:
            self.stats['users'][str(user_id)] = {
                'username': username,
                'first_seen': date.isoformat()
            }

        # 记录消息
        self.stats['messages'][str(user_id)].append(date.isoformat())
        self.save_stats()

    def get_user_stats(self, user_id: str, period: str) -> int:
        if user_id not in self.stats['messages']:
            return 0

        messages = self.stats['messages'][user_id]
        now = datetime.now()
        
        if period == 'day':
            start_time = now - timedelta(days=1)
        elif period == 'week':
            start_time = now - timedelta(weeks=1)
        elif period == 'month':
            start_time = now - timedelta(days=30)
        else:
            return len(messages)

        count = sum(1 for msg_time in messages 
                   if datetime.fromisoformat(msg_time) > start_time)
        return count

    def get_leaderboard(self, period: str, limit: int = 10) -> List[dict]:
        stats = []
        for user_id in self.stats['messages']:
            count = self.get_user_stats(user_id, period)
            username = self.stats['users'][user_id]['username']
            stats.append({
                'user_id': user_id,
                'username': username,
                'count': count
            })
        
        # 按消息数量排序
        stats.sort(key=lambda x: x['count'], reverse=True)
        return stats[:limit]

class KeywordBot:
    def __init__(self, config_path: str = 'config.json'):
        # ... (保留原有的初始化代码) ...
        self.message_stats = MessageStats()

    async def edit_keyword(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        if not self.check_permission(user_id, PermissionLevel.ADMIN):
            await update.message.reply_text("抱歉，你没有权限执行此操作。")
            return

        args = context.args
        if len(args) < 3:
            await update.message.reply_text(
                "用法：/edit_keyword <关键词> <权限级别> <新回复内容>\n"
                "权限级别: PUBLIC, MEMBER, ADMIN, OWNER"
            )
            return

        keyword = args[0]
        if keyword not in self.keywords:
            await update.message.reply_text(f"关键词 '{keyword}' 不存在。")
            return

        try:
            permission_level = PermissionLevel[args[1].upper()]
        except KeyError:
            await update.message.reply_text("无效的权限级别。请使用: PUBLIC, MEMBER, ADMIN, OWNER")
            return

        response = ' '.join(args[2:])

        # 更新关键词
        self.keywords[keyword].update({
            'response': response,
            'permission_level': permission_level.name,
            'updated_by': user_id,
            'updated_at': str(update.message.date)
        })
        self.save_data()

        await update.message.reply_text(
            f"关键词 '{keyword}' 已更新\n"
            f"新权限级别: {permission_level.name}\n"
            f"新回复内容: {response}"
        )

    async def delete_keyword(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        if not self.check_permission(user_id, PermissionLevel.ADMIN):
            await update.message.reply_text("抱歉，你没有权限执行此操作。")
            return

        args = context.args
        if len(args) < 1:
            await update.message.reply_text("用法：/delete_keyword <关键词>")
            return

        keyword = args[0]
        if keyword not in self.keywords:
            await update.message.reply_text(f"关键词 '{keyword}' 不存在。")
            return

        # 删除关键词
        deleted_keyword = self.keywords.pop(keyword)
        self.save_data()

        await update.message.reply_text(
            f"关键词 '{keyword}' 已删除\n"
            f"原权限级别: {deleted_keyword['permission_level']}\n"
            f"原回复内容: {deleted_keyword['response']}"
        )

    async def show_leaderboard(self, update: Update, context: CallbackContext):
        args = context.args
        period = 'day'  # 默认显示日榜
        if args and args[0] in ['day', 'week', 'month']:
            period = args[0]

        leaderboard = self.message_stats.get_leaderboard(period)
        
        period_text = {
            'day': '日榜',
            'week': '周榜',
            'month': '月榜'
        }[period]

        if not leaderboard:
            await update.message.reply_text(f"当前{period_text}暂无数据")
            return

        response = f"发言{period_text}排行榜：\n\n"
        for i, user in enumerate(leaderboard, 1):
            response += f"{i}. {user['username']}: {user['count']}条消息\n"

        await update.message.reply_text(response)

    async def message_handler(self, update: Update, context: CallbackContext):
        if update.message.chat.id not in self.config['allowed_group_ids']:
            return

        # 记录消息统计
        user = update.message.from_user
        self.message_stats.record_message(
            user.id,
            user.username or user.first_name,
            update.message.date
        )

        # 处理关键词回复
        text = update.message.text.strip().lower()
        for keyword, data in self.keywords.items():
            if keyword.lower() in text:
                required_level = PermissionLevel[data['permission_level']]
                if self.check_permission(user.id, required_level):
                    await update.message.reply_text(data['response'])
                    self.logger.info(f"User {user.id} triggered keyword '{keyword}'")
                    return

def main():
    bot = KeywordBot()
    application = Application.builder().token(bot.config['bot_token']).build()
    
    # 注册消息处理器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.message_handler))
    
    # 关键词管理命令
    application.add_handler(CommandHandler("add_keyword", bot.add_keyword))
    application.add_handler(CommandHandler("edit_keyword", bot.edit_keyword))
    application.add_handler(CommandHandler("delete_keyword", bot.delete_keyword))
    application.add_handler(CommandHandler("list_keywords", bot.list_keywords))
    
    # 用户角色管理命令
    application.add_handler(CommandHandler("set_role", bot.set_user_role))
    
    # 排行榜命令
    application.add_handler(CommandHandler("leaderboard", bot.show_leaderboard))
    
    # 运行机器人
    application.run_polling()

if __name__ == "__main__":
    main()
