"""
Discordボットコマンド定義
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
import traceback
import uuid
from io import BytesIO
from typing import Optional

import aiohttp
import discord
from discord.ext import commands
from PIL import Image as PILImage, ImageDraw

from config.settings import BASE_W, BASE_H, ROWS_Y, TEAM_Y, COLS, BOT_ADMIN_ID
from data.data_manager import load_data, save_data, get_tournament
from data.player_manager import (
    get_player_by_ingame_name, get_player_by_discord_id, get_team_by_name,
    ensure_player_defaults
)
from data.match_manager import (
    get_player_recent_results,
    get_team_recent_results,
    save_recent_match,
)
from ocr.image_processor import parse_scoreboard_image
from ocr.name_correction import apply_name_corrections
from ocr.ocr_utils import scale_box, format_time


def admin_check():
    """コマンド実行者が管理者かどうかをチェックするデコレーター。"""
    async def predicate(ctx):
        if ctx.author.id == BOT_ADMIN_ID:
            return True
        permissions = getattr(ctx.author, "guild_permissions", None)
        if permissions and permissions.administrator:
            return True
        return False
    return commands.check(predicate)


async def _download_first_attachment_image(ctx):
    """Discordの添付画像をダウンロードして返す。"""
    image_data = await ctx.read()
    return PILImage.open(BytesIO(image_data)).convert("RGB")


def _apply_parsed_players_to_data(tournament, parsed_players):
    """OCR解析結果をトーナメントデータに適用する。"""
    updated_count = 0
    result_lines = ["**更新内容:**"]

    for parsed in parsed_players:
        ingame_name = parsed["ingame_name"]
        ocr_name = parsed.get("raw", {}).get("ocr_name", ingame_name)
        name_note = f" ({ocr_name}→{ingame_name})" if ocr_name != ingame_name else ""
        rounds_mvp = parsed["rounds_mvp"]
        kills = parsed["kills"]
        deaths = parsed["deaths"]
        assists = parsed["assists"]
        avg_win_time = parsed["avg_win_time"]
        score = parsed["score"]

        player_id, player = get_player_by_ingame_name(tournament, ingame_name)

        if player_id:
            p = ensure_player_defaults(tournament["players"][player_id])
            p["kills"] += kills
            p["deaths"] += deaths
            p["assists"] += assists
            p["score"] += score
            p["rounds_MVP"] += rounds_mvp
            p["Matches_MVP"] += 0
            
            # AVG_WIN_timeを試合数で重み付き平均
            old_count = int(p.get("matches_played", 0) or 0)
            old_avg = float(p.get("AVG_WIN_time", 0) or 0)
            new_avg = ((old_avg * old_count) + float(avg_win_time)) / (old_count + 1)
            p["AVG_WIN_time"] = new_avg
            p["matches_played"] = old_count + 1

            result_lines.append(
                f"✅ {ingame_name}{name_note}: MVP={rounds_mvp}, "
                f"{kills}/{deaths}/{assists}, "
                f"SCORE={score}, AVG_WIN_TIME={format_time(avg_win_time)}"
            )
            updated_count += 1
        else:
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
                "matches_played": 1,
                "team_id": None,
            }
            result_lines.append(
                f"✅ {ingame_name}{name_note}: 新規プレイヤーとして自動保存しました（Discord未設定） "
                f"MVP={rounds_mvp}, {kills}/{deaths}/{assists}, "
                f"SCORE={score}, AVG_WIN_TIME={format_time(avg_win_time)}"
            )
            updated_count += 1

    return updated_count, "\n".join(result_lines)


async def send_long(ctx, message, limit=1900):
    """Discordの2000文字制限対策。"""
    if not message:
        return

    chunks = []
    current = ""
    for line in message.splitlines(True):
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)

    for chunk in chunks:
        await ctx.send(chunk)


def register_commands(bot):
    """すべてのコマンドを登録する。"""

    @bot.hybrid_command(name="commands", description="コマンド一覧を表示します")
    async def help_command(ctx):
        """コマンド一覧を表示。"""
        await ctx.send(
            "📊 **トーナメントスタッツ管理Botのコマンド一覧** 📊\n"
            "```markdown\n"
            "/commands - コマンド一覧を表示\n"
            "/updateimage <game_id> <image> - 画像からOCRでスタッツを更新\n"
            "/checkimage <image> [game_id] - OCR結果だけ表示。game_id指定時だけ登録済み名前に補正\n"
            "/debugocr <image> - 座標確認用の画像を返す\n"
            "/updatestats <game_id> <discord_user> <各スタッツ> - 累計スタッツを手動更新\n"
            "/setplayer <game_id> <@discord_user> <ingame_name> - インゲーム名を設定\n"
            "/unassign <game_id> <@discord_user> - インゲーム名を解除\n"
            "/remakeplayer <game_id> <old_ingame_name> <new_ingame_name> - ingame_nameを修正\n"
            "/playerstats <game_id> <@discord_user> - プレイヤーのスタッツを表示\n"
            "/resetstats <game_id> <@discord_user> - プレイヤーのスタッツをリセット\n"
            "/resetkda <game_id> - 全プレイヤーのKDAなどをリセット\n"
            "/resetdata <game_id> - トーナメントデータをリセット\n"
            "/rankings <game_id> <KD|KDA|KILLS|SCORE|MVP|AVG_WIN_TIME> - ランキング表示\n"
            "/addplayer <game_id> <@discord_user> <ingame_name> - プレイヤー追加\n"
            "/removeplayer <game_id> <@discord_user> - プレイヤー削除\n"
            "/showplayers <game_id> - 参加プレイヤー一覧\n"
            "/maketeam <game_id> <team_name> [user1...user8] - チーム作成\n"
            "/teamstats <game_id> <team_name> - チームスタッツ表示\n"
            "/addteam <game_id> <team_name> <@discord_user> - チームに追加\n"
            "/removeteam <game_id> <team_name> <@discord_user> - チームから削除\n"
            "/deleteteam <game_id> <team_name> - チーム削除\n"
            "/exportstats <game_id> - JSON出力\n"
            "/importstats <game_id> <json_url> - JSONインポート\n"
            "/makegame <game_id> [team1...team8] - ゲーム作成\n"
            "/gamestats <game_id> - ゲーム概要表示\n"
            "/deletegame <game_id> - ゲーム削除\n"
            "```"
        )

    @bot.hybrid_command(name="checkimage", description="画像をOCR解析します（保存なし）")
    @admin_check()
    async def checkimage(
        ctx,
        image: discord.Attachment,
        game_id: Optional[str] = None,
    ):
        """画像添付からOCR結果だけ表示。保存はしない。"""
        try:
            await ctx.send("🔍 OCRで画像を解析中...少々お待ちください。")
            rslt_img = await _download_first_attachment_image(image)
            if rslt_img is None:
                return

            parsed_players = await parse_scoreboard_image(rslt_img)

            tournament = None
            if game_id:
                data = load_data()
                tournament = get_tournament(data, game_id)
                parsed_players = apply_name_corrections(parsed_players, tournament)
            else:
                parsed_players = apply_name_corrections(parsed_players, None)

            if not parsed_players:
                await ctx.send("❌ OCRでプレイヤーを読み取れませんでした。")
                return

            title = "**OCR読み取り結果（保存なし）:**"
            if game_id:
                title += f" 名前補正あり game_id={game_id}"
            lines = [title]
            team_seen = {}
            for p in parsed_players:
                t = p["team_index"] + 1
                team_seen[t] = team_seen.get(t, 0) + 1
                raw_name = p.get("raw", {}).get("ocr_name", p["ingame_name"])
                name_part = p["ingame_name"]
                if raw_name and raw_name != p["ingame_name"]:
                    name_part = f"{raw_name} → {p['ingame_name']}"

                discord_part = ""
                if tournament:
                    _, player = get_player_by_ingame_name(tournament, p["ingame_name"])
                    if player:
                        discord_part = f" (<@{player['discord_id']}>)" if player["discord_id"] else " (Discord未設定)"
                    else:
                        discord_part = " (Discord未設定)"

                lines.append(
                    f"{t}-{team_seen[t]}: "
                    f"{name_part}{discord_part} | MVP={p['rounds_mvp']} | "
                    f"{p['kills']}/{p['deaths']}/{p['assists']} | "
                    f"AVG={format_time(p['avg_win_time'])} | SCORE={p['score']}"
                )

            await send_long(ctx, "\n".join(lines))

        except Exception as e:
            loc = "不明な場所"
            try:
                tb = traceback.extract_tb(e.__traceback__)
                if tb:
                    last = tb[-1]
                    loc = f"{last.filename}:{last.lineno}"
            except Exception:
                pass
            await ctx.send(f"❌ エラーが発生しました: {e} (場所: {loc})")

    @bot.hybrid_command(name="updateimage", description="画像からスタッツと試合履歴を更新します")
    @admin_check()
    async def updateimage(
        ctx,
        game_id: str,
        image: discord.Attachment,
    ):
        """画像添付からOCRでプレイヤーのKDA/MVP/Score/AvgWinTimeを読み取り更新。"""
        await ctx.send("🔍 OCRで画像を解析中...少々お待ちください。")
        try:
            rslt_img = await _download_first_attachment_image(image)
            if rslt_img is None:
                return

            parsed_players = await parse_scoreboard_image(rslt_img)

            if not parsed_players:
                await ctx.send("❌ OCRでプレイヤーを読み取れませんでした。先に `/checkimage` で確認してください。")
                return

            data = load_data()
            tournament = get_tournament(data, game_id)

            parsed_players = apply_name_corrections(parsed_players, tournament)

            updated_count, result_msg = _apply_parsed_players_to_data(tournament, parsed_players)
            save_recent_match(tournament, parsed_players)

            save_data(data)

            await ctx.send(f"✅ **{updated_count}人のプレイヤーのスタッツを更新しました！** (ゲーム: {game_id})")
            await send_long(ctx, result_msg)

        except Exception as e:
            loc = "不明な場所"
            try:
                tb = traceback.extract_tb(e.__traceback__)
                if tb:
                    last = tb[-1]
                    loc = f"{last.filename}:{last.lineno}"
            except Exception:
                pass
            await ctx.send(f"❌ エラーが発生しました: {e} (場所: {loc})")

    @bot.hybrid_command(name="debugocr", description="OCR対象範囲を画像上に表示します")
    @admin_check()
    async def debugocr(ctx, image: discord.Attachment):
        """座標確認用。添付画像にOCR対象の枠を描いて返す。"""
        try:
            await ctx.defer()
            img = await _download_first_attachment_image(image)
            if img is None:
                return

            debug = img.copy()
            draw = ImageDraw.Draw(debug)

            # プレイヤー行
            for y1, y2 in ROWS_Y:
                for key in ("username", "mvp", "k", "d", "a"):
                    x1, x2 = COLS[key]
                    box = scale_box((x1, y1, x2, y2), img)
                    draw.rectangle(box, outline="red", width=2)

            # チーム単位
            for y1, y2 in TEAM_Y:
                for key in ("avg_win_time", "score"):
                    x1, x2 = COLS[key]
                    box = scale_box((x1, y1, x2, y2), img)
                    draw.rectangle(box, outline="yellow", width=2)

            buf = BytesIO()
            debug.save(buf, format="PNG")
            buf.seek(0)
            await ctx.send(file=discord.File(buf, filename="ocr_debug_boxes.png"))

        except Exception as e:
            await ctx.send(f"❌ debugocrでエラー: {e}")

    @bot.hybrid_command(name="playerstats", description="プレイヤーのスタッツを表示します")
    async def playerstats(ctx, game_id: str, discord_user: discord.Member):
        """プレイヤーのスタッツを表示。"""
        data = load_data()
        tournament = get_tournament(data, game_id)

        player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

        if not player:
            await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
            return

        ensure_player_defaults(player)
        embed = discord.Embed(
            title=f"{player['ingame_name'] or discord_user.name or 'N/A'} のスタッツ (ゲーム: {game_id})",
            color=0x00ff00,
        )
        embed.add_field(name="Kills", value=player["kills"], inline=True)
        embed.add_field(name="Deaths", value=player["deaths"], inline=True)
        embed.add_field(name="Assists", value=player["assists"], inline=True)
        embed.add_field(name="K/D Ratio", value=f"{player['kills']}/{player['deaths']}" if player["deaths"] > 0 else "N/A", inline=True)
        embed.add_field(name="Score", value=player["score"], inline=True)
        embed.add_field(name="Rounds MVP", value=player.get("rounds_MVP", 0), inline=True)
        embed.add_field(name="Matches MVP", value=player.get("Matches_MVP", 0), inline=True)
        embed.add_field(name="Average Win Time", value=format_time(player.get("AVG_WIN_time", 0)), inline=True)
        embed.add_field(name="Matches Played", value=player.get("matches_played", 0), inline=True)
        embed.add_field(name="Discord", value=f"<@{player['discord_id']}>" if player["discord_id"] else "未設定", inline=False)
        embed.add_field(name="In-Game Name", value=player["ingame_name"] or "N/A", inline=False)

        if player.get("team_id"):
            embed.add_field(
                name="Team",
                value=tournament["teams"].get(player["team_id"], {}).get("team_name", "N/A"),
                inline=False,
            )

        recent_results = get_player_recent_results(tournament, player_id)
        if recent_results:
            recent_lines = [
                f"{index}. {result['rank']}位 | "
                f"KDA {result['kills']}/{result['deaths']}/{result['assists']} | "
                f"Score {result['score']} | MVP {result['rounds_MVP']}"
                for index, result in enumerate(recent_results, 1)
            ]
            recent_text = "\n".join(recent_lines)
        else:
            recent_text = "試合履歴はまだありません。"

        embed.add_field(name="直近5試合", value=recent_text, inline=False)
        await ctx.send(embed=embed)

    @bot.hybrid_command(name="updatestats", description="プレイヤーの累計スタッツを手動更新します")
    @admin_check()
    async def updatestats(
        ctx,
        game_id: str,
        discord_user: discord.Member,
        kills: int,
        deaths: int,
        assists: int,
        score: int,
        rounds_mvp: int,
        matches_mvp: int,
        avg_win_time_seconds: float,
    ):
        """プレイヤーのスタッツを手動更新。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

        if not player:
            await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
            return

        ensure_player_defaults(player)
        player["kills"] = kills
        player["deaths"] = deaths
        player["assists"] = assists
        player["score"] = score
        player["rounds_MVP"] = rounds_mvp
        player["Matches_MVP"] = matches_mvp
        player["AVG_WIN_time"] = avg_win_time_seconds

        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> のスタッツを更新しました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="setplayer", description="Discordユーザーとゲーム内名を紐付けます")
    @admin_check()
    async def setplayer(ctx, game_id: str, discord_user: discord.Member, *, ingame_name: str):
        """プレイヤーのインゲーム名を設定。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

        if not player:
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
                "AVG_WIN_time": 0.0,
                "matches_played": 0,
                "team_id": None,
            }
            save_data(data)
            await ctx.send(f"✅ <@{discord_user.id}> を新規追加し、インゲーム名を '{ingame_name}' に設定しました。")
            return

        player["ingame_name"] = ingame_name
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> のインゲーム名を '{ingame_name}' に設定しました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="unassign", description="ゲーム内名の紐付けを解除します")
    @admin_check()
    async def unassign(ctx, game_id: str, discord_user: discord.Member):
        """プレイヤーのインゲーム名を解除。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

        if not player:
            await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません。")
            return

        player["ingame_name"] = ""
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> のインゲーム名を解除しました。")

    @bot.hybrid_command(name="remakeplayer", description="登録済みのゲーム内名を修正します")
    @admin_check()
    async def remakeplayer(ctx, game_id: str, old_ingame_name: str, *, new_ingame_name: str):
        """プレイヤーのインゲーム名を修正。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        player_id, player = get_player_by_ingame_name(tournament, old_ingame_name)

        if not player:
            await ctx.send(f"❌ '{old_ingame_name}' が見つかりません。")
            return

        player["ingame_name"] = new_ingame_name
        save_data(data)
        await ctx.send(f"✅ '{old_ingame_name}' を '{new_ingame_name}' に修正しました。")

    @bot.hybrid_command(name="addplayer", description="トーナメントへプレイヤーを追加します")
    @admin_check()
    async def addplayer(ctx, game_id: str, discord_user: discord.Member, *, ingame_name: str):
        """プレイヤーを追加。"""
        data = load_data()
        tournament = get_tournament(data, game_id)

        _, existing = get_player_by_discord_id(tournament, discord_id=discord_user.id)
        if existing:
            await ctx.send(f"⚠️ <@{discord_user.id}> はすでに登録されています。`/setplayer`で変更してください。")
            return

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
            "AVG_WIN_time": 0.0,
            "matches_played": 0,
            "team_id": None,
        }
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> をプレイヤーリストに追加しました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="removeplayer", description="トーナメントからプレイヤーを削除します")
    @admin_check()
    async def removeplayer(ctx, game_id: str, discord_user: discord.Member):
        """プレイヤーを削除。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

        if not player_id:
            await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
            return

        for team in tournament.get("teams", {}).values():
            if player_id in team.get("members", []):
                team["members"].remove(player_id)

        del tournament["players"][player_id]
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> をプレイヤーリストから削除しました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="showplayers", description="参加プレイヤー一覧を表示します")
    async def showplayers(ctx, game_id: str):
        """参加プレイヤー一覧を表示。"""
        data = load_data()
        tournament = get_tournament(data, game_id)

        player_list = []
        for player in tournament.get("players", {}).values():
            ensure_player_defaults(player)
            name = player["ingame_name"] or "N/A"
            discord_part = f" (<@{player['discord_id']}>)" if player["discord_id"] else " (Discord未設定)"
            player_list.append(f"- {name}{discord_part}")

        if player_list:
            await send_long(ctx, f"参加プレイヤーのリスト (ゲーム: {game_id}):\n" + "\n".join(player_list))
        else:
            await ctx.send(f"参加プレイヤーはいません (ゲーム: {game_id})。")

    @bot.hybrid_command(name="resetstats", description="指定プレイヤーのスタッツをリセットします")
    @admin_check()
    async def resetstats(ctx, game_id: str, discord_user: discord.Member):
        """指定プレイヤーのスタッツをリセット。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

        if not player:
            await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
            return

        ensure_player_defaults(player)
        player["kills"] = 0
        player["deaths"] = 0
        player["assists"] = 0
        player["score"] = 0
        player["rounds_MVP"] = 0
        player["Matches_MVP"] = 0
        player["AVG_WIN_time"] = 0.0
        player["matches_played"] = 0

        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> のスタッツをリセットしました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="resetkda", description="全プレイヤーのスタッツをリセットします")
    @admin_check()
    async def resetkda(ctx, game_id: str):
        """全プレイヤーのKDA/Score/MVP/AVG_WIN_TIMEをリセット。"""
        data = load_data()
        tournament = get_tournament(data, game_id)

        for player in tournament.get("players", {}).values():
            ensure_player_defaults(player)
            player["kills"] = 0
            player["deaths"] = 0
            player["assists"] = 0
            player["score"] = 0
            player["rounds_MVP"] = 0
            player["Matches_MVP"] = 0
            player["AVG_WIN_time"] = 0.0
            player["matches_played"] = 0

        save_data(data)
        await ctx.send(f"✅ 全プレイヤーのKDA/Score/MVP/AVG_WIN_TIMEをリセットしました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="resetdata", description="トーナメントデータをリセットします")
    @admin_check()
    async def resetdata(ctx, game_id: str):
        """ゲーム内のプレイヤー/チームデータをリセット。"""
        data = load_data()
        data["tournaments"][game_id] = {
            "players": {},
            "teams": {},
            "recent_matches": [],
        }
        save_data(data)
        await ctx.send(f"✅ トーナメントのデータをリセットしました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="rankings", description="指定項目のランキングを表示します")
    async def rankings(ctx, game_id: str, stat_type: str = "KD"):
        """ランキングを表示。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        players = [ensure_player_defaults(p) for p in tournament.get("players", {}).values()]

        st = stat_type.upper()

        if st == "KD":
            players.sort(key=lambda p: p["kills"] / max(p["deaths"], 1), reverse=True)
        elif st == "KILLS":
            players.sort(key=lambda p: p["kills"], reverse=True)
        elif st == "SCORE":
            players.sort(key=lambda p: p["score"], reverse=True)
        elif st == "MVP":
            players.sort(key=lambda p: p.get("rounds_MVP", 0) + p.get("Matches_MVP", 0), reverse=True)
        elif st == "AVG_WIN_TIME":
            players.sort(key=lambda p: p.get("AVG_WIN_time", float("inf")))
        elif st == "KDA":
            players.sort(key=lambda p: (p["kills"], -p["deaths"], p["assists"]), reverse=True)
        elif st == "TEAMKD":
            team_kd = {}
            for p in players:
                team_id = p.get("team_id")
                if team_id:
                    team_kd.setdefault(team_id, []).append(p["kills"] / max(p["deaths"], 1))

            team_avg_kd = {team_id: sum(kds) / len(kds) for team_id, kds in team_kd.items()}
            players.sort(key=lambda p: team_avg_kd.get(p.get("team_id"), 0), reverse=True)
        elif st == "TEAMSCORE":
            team_score = {}
            for p in players:
                team_id = p.get("team_id")
                if team_id:
                    team_score[team_id] = team_score.get(team_id, 0) + p["score"]

            players.sort(key=lambda p: team_score.get(p.get("team_id"), 0), reverse=True)
        else:
            await ctx.send("❌ 無効なstat_typeです。KD、KILLS、SCORE、MVP、AVG_WIN_TIME、KDA、teamKD、teamscoreを指定してください。")
            return

        lines = [f"**{st}ランキング (ゲーム: {game_id}):**"]
        for i, player in enumerate(players[:10], 1):
            name = player["ingame_name"] or (f"<@{player['discord_id']}>" if player["discord_id"] else "N/A")
            if st == "AVG_WIN_TIME":
                value = format_time(player.get("AVG_WIN_time", 0))
            elif st == "SCORE":
                value = player["score"]
            elif st == "MVP":
                value = player.get("rounds_MVP", 0) + player.get("Matches_MVP", 0)
            elif st == "KILLS":
                value = player["kills"]
            elif st == "KDA":
                value = f"{player['kills']}/{player['deaths']}/{player['assists']} ({player['kills'] / max(player['deaths'], 1):.2f})"
            elif st == "KD":
                value = f"{player['kills']}/{player['deaths']} ({player['kills'] / max(player['deaths'], 1):.2f})"
            elif st == "TEAMKD":
                team_id = player.get("team_id")
                team_name = tournament["teams"].get(team_id, {}).get("team_name", "N/A") if team_id else "N/A"
                value = f"{team_name} (K/D: {player['kills'] / max(player['deaths'], 1):.2f})"
            elif st == "TEAMSCORE":
                team_id = player.get("team_id")
                team_name = tournament["teams"].get(team_id, {}).get("team_name", "N/A") if team_id else "N/A"
                team_score = sum(p["score"] for p in players if p.get("team_id") == team_id)
                value = f"{team_name} (合計スコア: {team_score})"
            else:
                value = f"{player['kills']}/{player['deaths']} ({player['kills'] / max(player['deaths'], 1):.2f})"
            lines.append(f"{i}. {name}: {value}")

        await send_long(ctx, "\n".join(lines))

    @bot.hybrid_command(name="maketeam", description="チームを作成してメンバーを追加します")
    @admin_check()
    async def maketeam(
        ctx,
        game_id: str,
        team_name: str,
        user1: Optional[discord.Member] = None,
        user2: Optional[discord.Member] = None,
        user3: Optional[discord.Member] = None,
        user4: Optional[discord.Member] = None,
        user5: Optional[discord.Member] = None,
        user6: Optional[discord.Member] = None,
        user7: Optional[discord.Member] = None,
        user8: Optional[discord.Member] = None,
    ):
        """チームを作成し、指定メンバーを追加。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        discord_users = [
            user
            for user in (user1, user2, user3, user4, user5, user6, user7, user8)
            if user is not None
        ]

        _, existing_team = get_team_by_name(tournament, team_name)
        if existing_team:
            await ctx.send(f"⚠️ チーム '{team_name}' はすでに存在します (ゲーム: {game_id})。")
            return

        team_id = str(uuid.uuid4())
        tournament["teams"][team_id] = {"team_name": team_name, "members": []}

        for discord_user in discord_users:
            player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
            if player_id:
                tournament["teams"][team_id]["members"].append(player_id)
                tournament["players"][player_id]["team_id"] = team_id
            else:
                await ctx.send(f"⚠️ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")

        save_data(data)
        await ctx.send(f"✅ チーム '{team_name}' を作成しました (ゲーム: {game_id})。")

    @bot.hybrid_command(name="teamstats", description="チームのスタッツを表示します")
    async def teamstats(ctx, game_id: str, team_name: str):
        """チームスタッツを表示。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        team_id, team = get_team_by_name(tournament, team_name)

        if not team:
            await ctx.send(f"❌ チーム '{team_name}' が見つかりません (ゲーム: {game_id})。")
            return

        member_ids = team.get("members", [])
        total_kills = 0
        total_deaths = 0
        total_assists = 0
        total_score = 0
        total_mvp = 0
        member_list = []

        for pid in member_ids:
            p = tournament["players"].get(pid)
            if not p:
                continue
            ensure_player_defaults(p)
            total_kills += p["kills"]
            total_deaths += p["deaths"]
            total_assists += p["assists"]
            total_score += p["score"]
            total_mvp += p.get("rounds_MVP", 0) + p.get("Matches_MVP", 0)
            member_list.append(p["ingame_name"] or (f"<@{p['discord_id']}>" if p["discord_id"] else "N/A"))

        embed = discord.Embed(title=f"{team_name} のチームスタッツ (ゲーム: {game_id})", color=0x0000ff)
        embed.add_field(name="Total Kills", value=total_kills, inline=True)
        embed.add_field(name="Total Deaths", value=total_deaths, inline=True)
        embed.add_field(name="Total Assists", value=total_assists, inline=True)
        embed.add_field(name="K/D Ratio", value=f"{total_kills}/{total_deaths} ({total_kills / max(total_deaths, 1):.2f})" if total_deaths > 0 else "N/A", inline=True)
        embed.add_field(name="Total Score", value=total_score, inline=True)
        embed.add_field(name="Total MVP", value=total_mvp, inline=True)
        embed.add_field(name="Members", value=", ".join(member_list) or "なし", inline=False)

        recent_results = get_team_recent_results(tournament, team_id)
        if recent_results:
            recent_lines = [
                f"{index}. {result['rank']}位 | Score {result['score']} | "
                f"KDA {result['kills']}/{result['deaths']}/{result['assists']} | "
                f"AVG {format_time(result['avg_win_time'])}"
                for index, result in enumerate(recent_results, 1)
            ]
            recent_text = "\n".join(recent_lines)
        else:
            recent_text = "試合履歴はまだありません。"

        embed.add_field(name="直近5試合", value=recent_text, inline=False)
        await ctx.send(embed=embed)

    @bot.hybrid_command(name="addteam", description="プレイヤーをチームへ追加します")
    @admin_check()
    async def addteam(ctx, game_id: str, team_name: str, discord_user: discord.Member):
        """チームにプレイヤーを追加。"""
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
            await ctx.send(f"⚠️ <@{discord_user.id}> はすでにチーム '{team_name}' に所属しています。")
            return

        team.setdefault("members", []).append(player_id)
        tournament["players"][player_id]["team_id"] = team_id
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> をチーム '{team_name}' に追加しました。")

    @bot.hybrid_command(name="removeteam", description="プレイヤーをチームから外します")
    @admin_check()
    async def removeteam(ctx, game_id: str, team_name: str, discord_user: discord.Member):
        """チームからプレイヤーを削除。"""
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

        if player_id not in team.get("members", []):
            await ctx.send(f"⚠️ <@{discord_user.id}> はチーム '{team_name}' に所属していません。")
            return

        team["members"].remove(player_id)
        tournament["players"][player_id]["team_id"] = None
        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> をチーム '{team_name}' から削除しました。")

    @bot.hybrid_command(name="deleteteam", description="チームを削除します")
    @admin_check()
    async def deleteteam(ctx, game_id: str, team_name: str):
        """チームを削除。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        team_id, team = get_team_by_name(tournament, team_name)

        if not team:
            await ctx.send(f"❌ チーム '{team_name}' が見つかりません (ゲーム: {game_id})。")
            return

        for player_id in team.get("members", []):
            if player_id in tournament.get("players", {}):
                tournament["players"][player_id]["team_id"] = None

        del tournament["teams"][team_id]
        save_data(data)
        await ctx.send(f"✅ チーム '{team_name}' を削除しました。")

    @bot.hybrid_command(name="exportstats", description="トーナメントデータをJSON出力します")
    @admin_check()
    async def exportstats(ctx, game_id: str):
        """ゲームデータをJSONで出力。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        text = json.dumps(tournament, ensure_ascii=False, indent=2)

        if len(text) < 1900:
            await ctx.send(f"```json\n{text}\n```")
        else:
            buf = BytesIO(text.encode("utf-8"))
            await ctx.send(file=discord.File(buf, filename=f"{game_id}_stats.json"))

    @bot.hybrid_command(name="importstats", description="URLからトーナメントデータを取り込みます")
    @admin_check()
    async def importstats(ctx, game_id: str, json_url: str):
        """URLからJSONをインポート。"""
        try:
            await ctx.defer()
            async with aiohttp.ClientSession() as session:
                async with session.get(json_url) as resp:
                    resp.raise_for_status()
                    imported_data = await resp.json()

            data = load_data()
            data["tournaments"][game_id] = imported_data
            save_data(data)
            await ctx.send(f"✅ スタッツをインポートしました (ゲーム: {game_id})。")

        except Exception as e:
            await ctx.send(f"❌ インポートに失敗しました: {e}")

    @bot.hybrid_command(name="makegame", description="ゲームとチームを作成します")
    @admin_check()
    async def makegame(
        ctx,
        game_id: str,
        team1: Optional[str] = None,
        team2: Optional[str] = None,
        team3: Optional[str] = None,
        team4: Optional[str] = None,
        team5: Optional[str] = None,
        team6: Optional[str] = None,
        team7: Optional[str] = None,
        team8: Optional[str] = None,
    ):
        """ゲームを作成。任意でチーム名も作成。"""
        data = load_data()
        tournament = get_tournament(data, game_id)
        teams = [
            team_name
            for team_name in (team1, team2, team3, team4, team5, team6, team7, team8)
            if team_name
        ]

        for team_name in teams:
            _, existing = get_team_by_name(tournament, team_name)
            if existing:
                continue
            team_id = str(uuid.uuid4())
            tournament["teams"][team_id] = {"team_name": team_name, "members": []}

        save_data(data)
        await ctx.send(f"✅ ゲーム '{game_id}' を作成しました。チーム: {', '.join(teams) if teams else 'なし'}")

    @bot.hybrid_command(name="gamestats", description="ゲームの概要を表示します")
    async def gamestats(ctx, game_id: str):
        """ゲーム概要を表示。"""
        data = load_data()
        tournament = get_tournament(data, game_id)

        total_players = len(tournament.get("players", {}))
        total_teams = len(tournament.get("teams", {}))

        embed = discord.Embed(title=f"ゲーム '{game_id}' の概要", color=0xffa500)
        embed.add_field(name="プレイヤー数", value=total_players, inline=True)
        embed.add_field(name="チーム数", value=total_teams, inline=True)
        await ctx.send(embed=embed)

    @bot.hybrid_command(name="deletegame", description="ゲームと全データを削除します")
    @admin_check()
    async def deletegame(ctx, game_id: str):
        """ゲームデータを削除。"""
        data = load_data()

        if game_id not in data.get("tournaments", {}):
            await ctx.send(f"❌ ゲーム '{game_id}' が見つかりません。")
            return

        del data["tournaments"][game_id]
        save_data(data)
        await ctx.send(f"✅ ゲーム '{game_id}' とそのスタッツを削除しました。")

    @bot.hybrid_command(name="image", description="ランキング画像を生成します（未実装）")
    @admin_check()
    async def image(ctx, game_id: str, stat_type: str):
        """画像生成 placeholder。"""
        await ctx.send(f"画像生成機能は未実装です (ゲーム: {game_id}, タイプ: {stat_type})。")

    @bot.hybrid_command(name="backimage", description="背景画像を設定します（未実装）")
    @admin_check()
    async def backimage(ctx, game_id: str):
        """背景画像設定 placeholder。"""
        await ctx.send(f"背景画像設定機能は未実装です (ゲーム: {game_id})。")

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ このコマンドを実行する権限がありません。")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ 引数が不足しています。コマンドの使い方を確認してください。")
        elif isinstance(error, commands.CommandNotFound):
            await ctx.send("❌ コマンドが見つかりません。`/commands` で利用可能なコマンドを確認してください。")
        else:
            loc = "不明な場所"
            try:
                tb = traceback.extract_tb(error.__traceback__)
                if tb:
                    last = tb[-1]
                    loc = f"{last.filename}:{last.lineno}"
            except Exception:
                pass
            await ctx.send(f"❌ コマンドの実行中にエラーが発生しました: {error} (場所: {loc})")
