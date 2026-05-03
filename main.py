from PIL import Image as PILImage
from io import BytesIO
import aiohttp
import os
from datetime import datetime
from typing import List, Dict
import discord
from discord.ext import commands
import json
import pytesseract
from pytesseract import Output
import sys
import re
import uuid
from dotenv import load_dotenv
import traceback
import cv2
import numpy as np
from PIL import Image as PILImage

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
load_dotenv()
TOKEN = os.getenv("TOKEN")

DATA_FILE = "tournament_data.json"

def load_data():
    """JSONファイルからデータを読み込む"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"tournaments": {}}
    data.setdefault("tournaments", {})
    return data

def save_data(data):
    """データをJSONファイルに保存"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_tournament(data, game_id):
    """ゲームIDからトーナメントデータを取得"""
    return data["tournaments"].setdefault(game_id, {"players": {}, "teams": {}})

def normalize_ingame_name(name):
    if not name:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9_]+", "", name)
    return normalized.lower()

def get_player_by_ingame_name(tournament, ingame_name):
    """トーナメント内のインゲーム名からプレイヤーを検索"""
    target_name = normalize_ingame_name(ingame_name)
    for player_id, player in tournament["players"].items():
        if normalize_ingame_name(player.get("ingame_name", "")) == target_name:
            return player_id, player
    return None, None

def get_player_by_discord_id(tournament, discord_id):
    """トーナメント内のDiscord IDからプレイヤーを検索"""
    for player_id, player in tournament["players"].items():
        if player["discord_id"] == discord_id:
            return player_id, player
    return None, None

def get_team_by_name(tournament, team_name):
    """トーナメント内のチーム名からチームを検索"""
    for team_id, team in tournament["teams"].items():
        if team["team_name"] == team_name:
            return team_id, team
    return None, None

def get_unassigned_players(tournament):
    return [(player_id, player) for player_id, player in tournament["players"].items() if not player.get("ingame_name")]

def ocr_crop(image, box, config):
    cropped = image.crop(box)
    text = pytesseract.image_to_string(cropped, lang="eng", config=config)
    return text.strip()

def parse_kda(text: str):
    nums = re.findall(r"\d+", text)
    if len(nums) >= 3:
        return int(nums[0]), int(nums[1]), int(nums[2])
    return None, None, None

def parse_int(text: str):
    text = re.sub(r"\D", "", text)
    return int(text) if text else None

def parse_time(text: str):
    text = text.replace(" ", "").replace(",",".")
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    text = re.sub(r"[^\d.]", "", text)
    try:
        return float(text)
    except ValueError:
        return None
    
def _safe_parse_int(text):
    """OCRのノイズを除去して整数を抽出数字がなければNoneを返す"""
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else None

def _safe_parse_time(text):
    """OCRのノイズを許容して秒数(float)に変換"""
    raw = (text or "").replace(" ", "").replace(",", ".").replace("@", "0")
    cleaned = re.sub(r"[^\d.:]", "", raw)

    if ":" in cleaned:
        m, sec = cleaned.split(":", 1)
        minutes = int(m) if m.isdigit() else 0
        sec_match = re.match(r"(\d+)(\.\d+)?", sec)
        seconds = float(sec_match.group(0)) if sec_match else 0.0
        return minutes * 60 + seconds
    
    num_match = re.match(r"(\d+)(\.\d+)?", cleaned)
    return float(num_match.group(0)) if num_match else None

def _normalize_player_row(row):
    """rowを（name, k d, a)の形式に正規化する。欠損時は空文字で補完"""
    if isinstance(row, dict):
        return (
            (row.get("name") or "").strip(),
            row.get("k", ""),
            row.get("d", ""),
            row.get("a", ""),
            row.get("rm", "")
        )
    
    if isinstance(row, (list, tuple)):
        items = list(row)
        if len(items) < 5:
            items += [""] * (5 - len(items))
        name, k, d, a, rm = items[:5]
        return (str(name).strip(), k, d, a, rm)
    
    return ("", "", "", "", "")

def ocr_crop(image, box, config):
    """crop領域をOCRしてテキストを返す"""
    cropped = image.crop(box)

    gray = cropped.convert("L")
    binary = gray.point(lambda p: 255 if p > 160 else 0, mode="1")

    text = pytesseract.image_to_string(binary, lang="eng", config=config, timeout=4)
    return (text or "").strip()

def _clean_player_name(text):
    """プレイヤー名OCRのノイズを軽く正規化"""
    raw = (text or "").strip()
    raw = raw.replace("|", "l").replace("I", "i")
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "", raw)
    return cleaned

def _parse_cell_int(text, default=0):
    v = _safe_parse_int(text)
    return v if isinstance(v, int) else default

@bot.command(name="commands")
async def help_command(ctx):
    if ctx.author.id != bot.user.id:
        await ctx.send(
            "📊 **トーナメントスタッツ管理Botのコマンド一覧** 📊\n"
            "```markdown\n"
            "!commands - コマンド一覧を表示\n"
            "!updateimage <game_id> - 画像添付からOCRでプレイヤーのKDAを読み取り更新\n"
            "!updatestats <game_id> <@discord_user> - プレイヤーのスタッツを手動で更新\n"
            "!setplayer <game_id> <@discord_user> <ingame_name> - プレイヤーのインゲーム名を設定\n"
            "!unassign <game_id> <@discord_user> - プレイヤーのインゲーム名を解除\n"
            "!remakeplayer <game_id> <ingame_name> <new_ingame_name> - プレイヤーのingame_nameを修正\n"
            "!playerstats <game_id> <@discord_user> - プレイヤーのスタッツを表示\n"
            "!resetkda <game_id> - トーナメント中の全プレイヤーのKDAをリセット\n"
            "!resetdata <game_id> - トーナメントのデータをリセット\n"
            "!rankings <game_id> <stat_type> - トーナメントランキングを表示\n"
            "stat_typeはKDA、KILLS、SCORE、MVP、AVG_WIN_TIMEのいずれかを指定\n"
            "!addplayer <game_id> <@discord_user> <ingame_name> - プレイヤーリストに追加\n"
            "!removeplayer <game_id> <@discord_user> - プレイヤーリストから削除\n"
            "!showplayers <game_id> - 参加プレイヤーのリストを表示\n"
            "!resetstats <game_id> <@discord_user> - プレイヤーのスタッツをリセット\n"
            "!teamstats <game_id> <team_name> - チームのスタッツを表示\n"
            "!maketeam <game_id> <team_name> <player1> <player2> ... - 新しいチームを作成\n"
            "!addteam <game_id> <team_name> <@discord_user> - チームにプレイヤーを追加\n"
            "!deleteteam <game_id> <team_name> - チームを削除\n"
            "!removeteam <game_id> <team_name> <@discord_user> - チームからプレイヤーを削除\n"
            "!exportstats <game_id> - 現在のトーナメントスタッツをJSON形式でエクスポート\n"
            "!importstats <game_id> <json_url> - JSON形式のスタッツをインポート\n"
            "!image <game_id> <stat_type> - 特定のスタッツを表示する画像を生成\n"
            "!backimage - !imageコマンドで使用する背景画像を設定\n"
            "!makegame <game_id> <team1> <team2> ... - 新しいゲームを作成\n"
            "!gamestats <game_id> - 特定のゲームのトーナメントスタッツを表示\n"
            "!deletegame <game_id> - ゲームとそのスタッツを削除\n"
            "```\n"
        )
    else:
        return

@bot.command(name="updateimage")
@commands.has_permissions(administrator=True)
async def updateimage(ctx, game_id: str):
    """画像添付からOCRでプレイヤーのKDAを読み取り更新"""
    if not ctx.message.attachments:
        await ctx.send("❌ 画像を添付してください。")
        return
    
    try:
        
        attachment = ctx.message.attachments[0]

        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                resp.raise_for_status()
                image_data = await resp.read()

        rslt_img = PILImage.open(BytesIO(image_data)).convert("RGB")

        players = []

        base_y = 175
        row_height = 70

        #最大8チーム（16行を2人ずつ処理。空行が続けば終了
        max_teams = 8
        empty_team_streak = 0
        for i in range(0, max_teams * 2, 2):
            y1 = base_y + i * row_height
            y2 = y1 + row_height
            y3 = base_y + (i + 1) * row_height
            y4 = y3 + row_height

            # 中央を計算
            mid_y = (y1 + y3) // 2
            mid_y2 = mid_y + 50  # 高さ調整

            # ===== teamプレイヤー1 =====
            name1 = ocr_crop(rslt_img, (680, y1, 930, y2), "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
            k1 = ocr_crop(rslt_img, (1070, y1, 1120, y2), "--psm 7")
            d1 = ocr_crop(rslt_img, (1120, y1, 1170, y2), "--psm 7")
            a1 = ocr_crop(rslt_img, (1170, y1, 1220, y2), "--psm 7")
            rm1 = ocr_crop(rslt_img, (930, y1, 1070, y2), "--psm 7 -c tessedit_char_whitelist=0123456789")  # MVPは数字のみ

            # ===== teamプレイヤー2 =====
            name2 = ocr_crop(rslt_img, (680, y3, 930, y4), "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
            k2 = ocr_crop(rslt_img, (1070, y3, 1120, y4), "--psm 7")
            d2 = ocr_crop(rslt_img, (1120, y3, 1170, y4), "--psm 7")
            a2 = ocr_crop(rslt_img, (1170, y3, 1220, y4), "--psm 7")
            rm2 = ocr_crop(rslt_img, (930, y3, 1070, y4), "--psm 7 -c tessedit_char_whitelist=0123456789")  # MVPは数字のみ

            n1 = _clean_player_name(name1)
            n2 = _clean_player_name(name2)
            if not n1 and not n2:
                empty_team_streak += 1
                if empty_team_streak >=2:
                    break
            else:
                empty_team_streak = 0


            # ===== チーム情報（中央で取得） =====
            avg_win_time_text = ocr_crop(rslt_img, (1230, mid_y, 1330, mid_y2), "--psm 7")
            score_text = ocr_crop(
                rslt_img,
                (1330, mid_y, 1410, mid_y2),
                "--psm 7 -c tessedit_char_whitelist=0123456789",
            )

            team_index = i // 2
            avg_win_time = _safe_parse_time(avg_win_time_text)
            if avg_win_time is None and "parse_time" in globals():
                    avg_win_time = parse_int(avg_win_time_text)
            if avg_win_time is None:
                avg_win_time = 0

            score = _safe_parse_int(score_text)
            if score is None and "parse_int" in globals():
                score = parse_int(score_text)
            if score is None:
                score = 0


            # ===== プレイヤー登録 =====
            player_rows = (
                {"name": name1, "k": k1, "d": d1, "a": a1, "rm": rm1},
                {"name": name2, "k": k2, "d": d2, "a": a2, "rm": rm2},
            )
            for row in player_rows:
                name, k, d, a, rm = _normalize_player_row(row)
                if not name or len(name) < 2:
                    continue

                kills = _parse_cell_int(k,default=None)
                deaths = _parse_cell_int(d, default=None)
                assists = _parse_cell_int(a, default=None)

                if None in (kills, deaths, assists):
                    k2, d2, a2 = parse_kda(f"{k} {d} {a}")
                    kills = kills if kills is not None else k2
                    deaths = deaths if deaths is not None else d2
                    assists = assists if assists is not None else a2

                if not all(isinstance(v, int) for v in (kills, deaths, assists)):
                    continue

                rounds_mvp = _safe_parse_int(rm)
                if rounds_mvp is None:
                    rounds_mvp = 0
                players.append({
                    "ingame_name": name,
                    "kills": kills ,
                    "deaths": deaths ,
                    "assists": assists ,
                    "score": score,
                    "avg_win_time": avg_win_time ,
                    "team_index": team_index ,
                    "rounds_mvp": rounds_mvp 
                })

        data = load_data()
        tournament = get_tournament(data, game_id)
        updated_count = 0
        result_msg = "**更新内容:**\n"
        
        for parsed in players:
            ingame_name = parsed["ingame_name"]
            rounds_mvp = parsed["rounds_mvp"]
            kills = parsed["kills"]
            deaths = parsed["deaths"]
            assists = parsed["assists"]
            avg_win_time = parsed["avg_win_time"]
            score = parsed["score"]
            
            player_id, player = get_player_by_ingame_name(tournament, ingame_name)
            if not player_id:
                unassigned = get_unassigned_players(tournament)
                if len(unassigned) == 1:
                    player_id, player = unassigned[0]
                    player["ingame_name"] = ingame_name
                    result_msg += f"ℹ️ {ingame_name}: 未設定プレイヤーにインゲーム名を自動保存しました (<@{player['discord_id']}>).\n"
            
            if player_id:
                p = tournament["players"][player_id]
                p["kills"] += kills
                p["deaths"] += deaths
                p["assists"] += assists
                p["score"] += score
                p["rounds_MVP"] += rounds_mvp
                p["Matches_MVP"] += 0
                p["AVG_WIN_time"] = (p["AVG_WIN_time"] + avg_win_time) / 2

                result_msg += (
                    f"{ingame_name}: MVP={rounds_mvp}, {kills}/{deaths}/{assists}, SCORE={score}, AVG_WIN_TIME={avg_win_time}\n"
                )
                updated_count += 1
            else:
                # 既存プレイヤーに紐づかない場合は、プレースホルダとして保存
                new_player_id = str(uuid.uuid4())
                tournament["players"][new_player_id] = {
                    "discord_id": "",
                    "ingame_name": ingame_name,
                    "kills": kills,
                    "deaths": deaths,
                    "assists": assists,
                    "score": score,
                    "rounds_MVP": rounds_mvp,
                    "Matches_MVP": 0,
                    "AVG_WIN_time": avg_win_time,
                    "team_id": None
                }
                result_msg += f"✅ {ingame_name}: 新規プレイヤーとして自動保存しました（Discord未設定）\n"
                updated_count += 1

        save_data(data)
        await ctx.send(f"✅ **{updated_count}人のプレイヤーのKDAを更新しました！** (ゲーム: {game_id})")
        await ctx.send(result_msg)

    except Exception as e:
        try:
            tb = traceback.format_tb(e.__traceback__)
            last = tb[-1] if tb else None
            loc = f"{last.filename}:{last.lineno}"if last else "不明な場所"
        except Exception:
            loc = "不明な場所"

        await ctx.send(f"❌ エラーが発生しました: {str(e)} (場所: {loc})")
        

@bot.command(name="playerstats")
async def playerstats(ctx, game_id: str, discord_user: discord.Member):
    """プレイヤーのスタッツを表示"""
    data = load_data()
    tournament = get_tournament(data, game_id)

    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    
    if player:
        embed = discord.Embed(title=f"{player['ingame_name'] or discord_user.name or 'N/A'} のスタッツ (ゲーム: {game_id})", color=0x00ff00)
        embed.add_field(name="Kills", value=player["kills"], inline=True)
        embed.add_field(name="Deaths", value=player["deaths"], inline=True)
        embed.add_field(name="Assists", value=player["assists"], inline=True)
        embed.add_field(name="Discord", value=f"<@{player['discord_id']}>", inline=False)
        embed.add_field(name="In-Game Name", value=player["ingame_name"] or "N/A", inline=False)
        embed.add_field(name="Score", value=player["score"], inline=False)
        embed.add_field(name="Rounds MVP", value=player.get("rounds_MVP", 0), inline=True)
        embed.add_field(name="Matches MVP", value=player.get("Matches_MVP", 0), inline=True)
        embed.add_field(name="Average Win Time", value=player.get("AVG_WIN_time", 0), inline=True)
        if player["team_id"]:
            embed.add_field(name="Team", value=tournament["teams"].get(player["team_id"], {}).get("team_name", "N/A"), inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")

@bot.command(name="updatestats")
@commands.has_permissions(administrator=True)
async def updatestats(ctx, game_id: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    if not player:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
        return
    await ctx.send(f"現在のスタッツ: Kills: {player['kills']}, Deaths: {player['deaths']}, Assists: {player['assists']}, Score: {player['score']}, Rounds MVP: {player.get('rounds_MVP', 0)}, Matches MVP: {player.get('Matches_MVP', 0)}, Average Win Time: {player.get('AVG_WIN_time', 0)}です。\n更新したいスタッツを以下の形式で入力してください: Kills Deaths Assists Score RoundsMVP MatchesMVP AVG_WIN_time (例: 5 2 3 10 1 2 3)")
    message = await bot.wait_for('message', check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
    try:
        kills, deaths, assists, score, rounds_mvp, matches_mvp, avg_win_time = map(int, message.content.split())
        player["kills"] = kills
        player["deaths"] = deaths
        player["assists"] = assists
        player["score"] = score
        player["rounds_MVP"] = rounds_mvp
        player["Matches_MVP"] = matches_mvp
        player["AVG_WIN_time"] = avg_win_time
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}>のスタッツを更新しました (ゲーム: {game_id})。")
    except ValueError:
        await ctx.send("❌ 入力形式が正しくありません。")

@bot.command(name="setplayer")
@commands.has_permissions(administrator=True)
async def setplayer(ctx, game_id: str, discord_user: discord.Member, *, ingame_name: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    if not player:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
        return
    player["ingame_name"] = ingame_name
    save_data(data)
    await ctx.send(f"✅ <@{discord_user.id}>のインゲーム名を '{ingame_name}' に設定しました (ゲーム: {game_id})。")

@bot.command(name = "resetdata")
@commands.has_permissions(administrator=True)
async def resetdata(ctx, game_id: str):
    data = load_data()
    data["tournaments"][game_id] = {"players": {}, "teams": {}}
    save_data(data)
    await ctx.send(f"✅ トーナメントのデータをリセットしました (ゲーム: {game_id})。")

@bot.command(name="rankings")
async def rankings(ctx, game_id: str, stat_type: str = "KDA"):
    data = load_data()
    tournament = get_tournament(data, game_id)
    players = list(tournament["players"].values())
    if stat_type.upper() == "KDA":
        players.sort(key=lambda p: (p["kills"] + p["assists"]) / max(p["deaths"], 1), reverse=True)
    elif stat_type.upper() == "KILLS":
        players.sort(key=lambda p: p["kills"], reverse=True)
    elif stat_type.upper() == "SCORE":
        players.sort(key=lambda p: p["score"], reverse=True)
    elif stat_type.upper() == "MVP":
        players.sort(key=lambda p: max(p.get("rounds_MVP", 0), p.get("Matches_MVP", 0)), reverse=True)
    elif stat_type.upper() == "AVG_WIN_TIME":
        players.sort(key=lambda p: p.get("AVG_WIN_time", float('inf')))
    else:
        await ctx.send("❌ 無効なstat_typeです。KDA、KILLSまたはSCOREを指定してください。")
        return
    ranking_msg = f"**{stat_type}ランキング (ゲーム: {game_id}):**\n"
    for i, player in enumerate(players[:10], 1):
        player_name = player['ingame_name'] or f"<@{player['discord_id']}>"
        ranking_msg += f"{i}. {player_name}: {player['kills']}/{player['deaths']}/{player['assists']}\n"
    await ctx.send(ranking_msg)

@bot.command(name="addplayer")
@commands.has_permissions(administrator=True)
async def addplayer(ctx, game_id: str, discord_user: discord.Member, *, ingame_name: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id = str(uuid.uuid4())
    tournament["players"][player_id] = {
        "discord_id": discord_user.id,
        "ingame_name": ingame_name,
        "kills": 0,
        "deaths": 0,
        "assists": 0,
        "score": 0,
        "rounds_MVP": 0,
        "Matches_MVP": 0,
        "AVG_WIN_time": 0,
        "team_id": None
    }
    save_data(data)
    await ctx.send(f"✅ <@{discord_user.id}>をプレイヤーリストに追加しました (ゲーム: {game_id})。")

@bot.command(name="removeplayer")
@commands.has_permissions(administrator=True)
async def removeplayer(ctx, game_id: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    if player_id:
        del tournament["players"][player_id]
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}>をプレイヤーリストから削除しました (ゲーム: {game_id})。")
    else:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")

@bot.command(name="showplayers")
async def showplayers(ctx, game_id: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_list = [f"{player['ingame_name']} (<@{player['discord_id']}>)" if player['ingame_name'] else f"<@{player['discord_id']}>" for player in tournament.get("players", {}).values()]
    if player_list:
        await ctx.send(f"参加プレイヤーのリスト (ゲーム: {game_id}):\n" + "\n".join(player_list))
    else:
        await ctx.send(f"参加プレイヤーはいません (ゲーム: {game_id})。")

@bot.command(name="resetstats")
@commands.has_permissions(administrator=True)
async def resetstats(ctx, game_id: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    if player_id:
        player["kills"] = 0
        player["deaths"] = 0
        player["assists"] = 0
        player["score"] = 0
        player["rounds_MVP"] = 0
        player["Matches_MVP"] = 0
        player["AVG_WIN_time"] = 0
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}>のスタッツをリセットしました (ゲーム: {game_id})。")
    else:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")

@bot.command(name="teamstats")
async def teamstats(ctx, game_id: str, team_name: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    team_id, team = get_team_by_name(tournament, team_name)
    if team:
        total_kills = sum(tournament["players"][pid]["kills"] for pid in team["members"])
        total_deaths = sum(tournament["players"][pid]["deaths"] for pid in team["members"])
        total_assists = sum(tournament["players"][pid]["assists"] for pid in team["members"])
        total_score = sum(tournament["players"][pid]["score"] for pid in team["members"])
        embed = discord.Embed(title=f"{team_name}のチームスタッツ (ゲーム: {game_id})", color=0x0000ff)
        embed.add_field(name="Total Kills", value=total_kills, inline=True)
        embed.add_field(name="Total Deaths", value=total_deaths, inline=True)
        embed.add_field(name="Total Assists", value=total_assists, inline=True)
        embed.add_field(name="Total Score", value=total_score, inline=True)
        member_list = [f"{tournament['players'][pid]['ingame_name']} (<@{tournament['players'][pid]['discord_id']}>)" if tournament['players'][pid]['ingame_name'] else f"<@{tournament['players'][pid]['discord_id']}>" for pid in team["members"]]
        embed.add_field(name="Members", value=", ".join(member_list), inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"❌ チーム '{team_name}' が見つかりません (ゲーム: {game_id})。")

@bot.command(name="maketeam")
@commands.has_permissions(administrator=True)
async def maketeam(ctx, game_id: str, team_name: str, *discord_users: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    team_id, existing_team = get_team_by_name(tournament, team_name)
    if existing_team:
        await ctx.send(f"⚠️ チーム '{team_name}' はすでに存在します (ゲーム: {game_id})。")
        return
    team_id = str(uuid.uuid4())
    tournament["teams"][team_id] = {
        "team_name": team_name,
        "members": []
    }
    for discord_user in discord_users:
        player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
        if player_id:
            tournament["teams"][team_id]["members"].append(player_id)
            tournament["players"][player_id]["team_id"] = team_id
        else:
            await ctx.send(f"⚠️ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
    save_data(data)
    await ctx.send(f"✅ チーム '{team_name}' を作成しました (ゲーム: {game_id})。")

@bot.command(name="addteam")
@commands.has_permissions(administrator=True)
async def addteam(ctx, game_id: str, team_name: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    team_id, team = get_team_by_name(tournament, team_name)
    if not team:
        await ctx.send(f"❌ チーム '{team_name}' が見つかりません (ゲーム: {game_id})。")
        return
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    if not player:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
        return
    if player_id in team.get("members", []):
        await ctx.send(f"⚠️ <@{discord_user.id}>はすでにチーム '{team_name}' に所属しています (ゲーム: {game_id})。")
        return
    team.setdefault("members", []).append(player_id)
    tournament["players"][player_id]["team_id"] = team_id
    save_data(data)
    await ctx.send(f"✅ <@{discord_user.id}>をチーム '{team_name}' に追加しました (ゲーム: {game_id})。")

@bot.command(name="deleteteam")
@commands.has_permissions(administrator=True)
async def deleteteam(ctx, game_id: str, team_name: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    team_id, team = get_team_by_name(tournament, team_name)
    if team:
        for player_id in team.get("members", []):
            tournament["players"][player_id]["team_id"] = None
        del tournament["teams"][team_id]
        save_data(data)
        await ctx.send(f"✅ チーム '{team_name}' を削除しました (ゲーム: {game_id})。")
    else:
        await ctx.send(f"❌ チーム '{team_name}' が見つかりません (ゲーム: {game_id})。")

@bot.command(name="removeteam")
@commands.has_permissions(administrator=True)
async def removeteam(ctx, game_id: str, team_name: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    team_id, team = get_team_by_name(tournament, team_name)
    if not team:
        await ctx.send(f"❌ チーム '{team_name}' が見つかりません (ゲーム: {game_id})。")
        return
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    if not player:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
        return
    if player_id in team.get("members", []):
        team["members"].remove(player_id)
        tournament["players"][player_id]["team_id"] = None
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}>をチーム '{team_name}' から削除しました (ゲーム: {game_id})。")
    else:
        await ctx.send(f"⚠️ <@{discord_user.id}>はチーム '{team_name}' に所属していません (ゲーム: {game_id})。")

@bot.command(name="exportstats")
@commands.has_permissions(administrator=True)
async def exportstats(ctx, game_id: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    await ctx.send(f"```json\n{json.dumps(tournament, ensure_ascii=False, indent=2)}\n```")

@bot.command(name="importstats")
@commands.has_permissions(administrator=True)
async def importstats(ctx, game_id: str, json_url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(json_url) as resp:
                imported_data = await resp.json()
        data = load_data()
        data["tournaments"][game_id] = imported_data
        save_data(data)
        await ctx.send(f"✅ スタッツをインポートしました (ゲーム: {game_id})。")
    except Exception as e:
        await ctx.send(f"❌ インポートに失敗しました: {str(e)}")

@bot.command(name="image")
@commands.has_permissions(administrator=True)
async def image(ctx, game_id: str, stat_type: str):
    # 画像生成の実装（Pillowなどを使ってランキング画像を作成）
    await ctx.send(f"画像生成機能は未実装です (ゲーム: {game_id}, タイプ: {stat_type})。")

@bot.command(name="backimage")
@commands.has_permissions(administrator=True)
async def backimage(ctx):
    # 背景画像設定の実装
    await ctx.send("背景画像設定機能は未実装です。")

@bot.command(name="makegame")
@commands.has_permissions(administrator=True)
async def makegame(ctx, game_id: str, *teams: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    # チームを追加（必要に応じて拡張）
    for team_name in teams:
        team_id = str(uuid.uuid4())
        tournament["teams"][team_id] = {"team_name": team_name, "members": []}
    save_data(data)
    await ctx.send(f"✅ ゲーム '{game_id}' を作成しました。(game_id: {game_id}, チーム: {', '.join(teams)})")

@bot.command(name="gamestats")
async def gamestats(ctx, game_id: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    total_players = len(tournament["players"])
    total_teams = len(tournament["teams"])
    embed = discord.Embed(title=f"ゲーム '{game_id}' の概要", color=0xffa500)
    embed.add_field(name="プレイヤー数", value=total_players, inline=True)
    embed.add_field(name="チーム数", value=total_teams, inline=True)
    await ctx.send(embed=embed)

@bot.command(name="deletegame")
@commands.has_permissions(administrator=True)
async def deletegame(ctx, game_id: str):
    data = load_data()
    if game_id in data["tournaments"]:
        del data["tournaments"][game_id]
        save_data(data)
        await ctx.send(f"✅ ゲーム '{game_id}' とそのスタッツを削除しました。")
    else:
        await ctx.send(f"❌ ゲーム '{game_id}' が見つかりません。")

bot.run(TOKEN)