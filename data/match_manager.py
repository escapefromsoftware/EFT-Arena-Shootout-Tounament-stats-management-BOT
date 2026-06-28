"""
試合履歴の作成・保存
"""

from datetime import datetime, timezone

from data.player_manager import get_player_by_ingame_name


RECENT_MATCH_LIMIT = 5


def _get_registered_team(tournament, player_ids):
    """同じ登録チームに所属する選手群なら、そのチーム情報を返す。"""
    team_ids = {
        tournament["players"].get(player_id, {}).get("team_id")
        for player_id in player_ids
    }
    team_ids.discard(None)

    if len(team_ids) != 1:
        return None, None

    team_id = next(iter(team_ids))
    team = tournament.get("teams", {}).get(team_id, {})
    return team_id, team.get("team_name")


def build_match_record(tournament, parsed_players):
    """OCR解析結果から、1試合分の順位と選手戦績を作成する。"""
    teams = {}

    for parsed in parsed_players:
        team_index = int(parsed["team_index"])
        team = teams.setdefault(
            team_index,
            {
                "team_index": team_index,
                "score": int(parsed["score"]),
                "avg_win_time": float(parsed["avg_win_time"]),
                "players": [],
            },
        )

        player_id, player = get_player_by_ingame_name(
            tournament,
            parsed["ingame_name"],
        )
        team["players"].append(
            {
                "player_id": player_id,
                "discord_id": player.get("discord_id", "") if player else "",
                "ingame_name": parsed["ingame_name"],
                "kills": int(parsed["kills"]),
                "deaths": int(parsed["deaths"]),
                "assists": int(parsed["assists"]),
                "rounds_MVP": int(parsed["rounds_mvp"]),
            }
        )

    ranked_teams = sorted(
        teams.values(),
        key=lambda team: (-team["score"], team["team_index"]),
    )

    previous_score = None
    previous_rank = 0
    for position, team in enumerate(ranked_teams, 1):
        if team["score"] != previous_score:
            previous_rank = position
        team["rank"] = previous_rank
        previous_score = team["score"]

        player_ids = [
            player["player_id"]
            for player in team["players"]
            if player["player_id"]
        ]
        if len(player_ids) == len(team["players"]):
            team_id, team_name = _get_registered_team(tournament, player_ids)
        else:
            team_id, team_name = None, None
        team["team_id"] = team_id
        team["team_name"] = team_name

    return {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "teams": ranked_teams,
    }


def save_recent_match(tournament, parsed_players, limit=RECENT_MATCH_LIMIT):
    """試合履歴を新しい順で保存し、指定件数を超えた履歴を削除する。"""
    recent_matches = tournament.setdefault("recent_matches", [])
    if not isinstance(recent_matches, list):
        recent_matches = []
        tournament["recent_matches"] = recent_matches

    match = build_match_record(tournament, parsed_players)
    recent_matches.insert(0, match)
    del recent_matches[limit:]
    return match


def get_recent_matches(tournament, limit=RECENT_MATCH_LIMIT):
    """保存済みの試合履歴を新しい順で取得する。"""
    recent_matches = tournament.get("recent_matches", [])
    if not isinstance(recent_matches, list):
        return []
    return recent_matches[:limit]


def get_player_recent_results(tournament, player_id, limit=RECENT_MATCH_LIMIT):
    """指定プレイヤーが参加した直近の試合結果を取得する。"""
    results = []

    for match in get_recent_matches(tournament, limit):
        found = False
        for team in match.get("teams", []):
            for player in team.get("players", []):
                if player.get("player_id") != player_id:
                    continue

                results.append(
                    {
                        "saved_at": match.get("saved_at"),
                        "rank": team.get("rank"),
                        "score": team.get("score", 0),
                        "kills": player.get("kills", 0),
                        "deaths": player.get("deaths", 0),
                        "assists": player.get("assists", 0),
                        "rounds_MVP": player.get("rounds_MVP", 0),
                    }
                )
                found = True
                break

            if found:
                break

    return results[:limit]


def get_team_recent_results(tournament, team_id, limit=RECENT_MATCH_LIMIT):
    """指定チームの直近の試合結果とチーム合計KDAを取得する。"""
    results = []

    for match in get_recent_matches(tournament, limit):
        for team in match.get("teams", []):
            if team.get("team_id") != team_id:
                continue

            players = team.get("players", [])
            results.append(
                {
                    "saved_at": match.get("saved_at"),
                    "rank": team.get("rank"),
                    "score": team.get("score", 0),
                    "avg_win_time": team.get("avg_win_time", 0.0),
                    "kills": sum(player.get("kills", 0) for player in players),
                    "deaths": sum(player.get("deaths", 0) for player in players),
                    "assists": sum(player.get("assists", 0) for player in players),
                    "rounds_MVP": sum(player.get("rounds_MVP", 0) for player in players),
                }
            )
            break

    return results[:limit]
