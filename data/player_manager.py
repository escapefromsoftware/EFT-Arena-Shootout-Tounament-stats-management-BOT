"""
プレイヤー情報の取得・検索
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import re


def normalize_ingame_name(name):
    """ゲーム内名前を正規化（小文字、英数字_のみ）。"""
    if not name:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9_]+", "", str(name))
    return normalized.lower()


def ensure_player_defaults(player):
    """古いJSONにも新しいキーを後付けする。"""
    player.setdefault("discord_id", "")
    player.setdefault("ingame_name", "")
    player.setdefault("kills", 0)
    player.setdefault("deaths", 0)
    player.setdefault("assists", 0)
    player.setdefault("score", 0)
    player.setdefault("rounds_MVP", 0)
    player.setdefault("Matches_MVP", 0)
    player.setdefault("AVG_WIN_time", 0.0)
    player.setdefault("matches_played", 0)
    player.setdefault("team_id", None)
    return player


def get_player_by_ingame_name(tournament, ingame_name):
    """ゲーム内名前からプレイヤーを検索。"""
    target_name = normalize_ingame_name(ingame_name)
    for player_id, player in tournament.get("players", {}).items():
        ensure_player_defaults(player)
        if normalize_ingame_name(player.get("ingame_name", "")) == target_name:
            return player_id, player
    return None, None


def get_player_by_discord_id(tournament, discord_id):
    """DiscordIDからプレイヤーを検索。"""
    for player_id, player in tournament.get("players", {}).items():
        ensure_player_defaults(player)
        if str(player.get("discord_id")) == str(discord_id):
            return player_id, player
    return None, None


def get_team_by_name(tournament, team_name):
    """チーム名からチームを検索。"""
    for team_id, team in tournament.get("teams", {}).items():
        if team.get("team_name") == team_name:
            return team_id, team
    return None, None


def get_unassigned_players(tournament):
    """ingame_name が未設定のプレイヤー一覧を返す。"""
    return [
        (player_id, ensure_player_defaults(player))
        for player_id, player in tournament.get("players", {}).items()
        if not player.get("ingame_name")
    ]


def get_registered_ingame_names(tournament):
    """トーナメントに登録済みのingame_name一覧を返す。"""
    names = []
    for player in tournament.get("players", {}).values():
        ensure_player_defaults(player)
        name = player.get("ingame_name")
        if name:
            names.append(str(name))
    return names
