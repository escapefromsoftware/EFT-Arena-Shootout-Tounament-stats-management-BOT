"""
EFTA Tournament Stats Bot
Discordボット - トーナメントスタッツ管理

構成:
- config/settings.py: OCR設定・定数
- ocr/: OCR処理モジュール
- data/: データ管理モジュール
- commands/: コマンド定義
"""

import sys
import os
from pathlib import Path

# プロジェクト直下をPythonパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import discord
from discord.ext import commands

from config.settings import TOKEN
from commands.bot_commands import register_commands


# ボット設定
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# Botイベント
# =========================

@bot.event
async def on_ready():
    """ボットがログインしたときの処理。"""
    print(f"Logged in as {bot.user} / {bot.user.id}")


# コマンド登録
register_commands(bot)


if __name__ == "__main__":
    bot.run(TOKEN)
