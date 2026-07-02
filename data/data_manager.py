"""
Tournament data storage.

Each tournament is stored as one SQLite database file:
    tournament_data/<game_id>.sqlite
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
import os
import re
import sqlite3

from config.settings import DATA_FILE, TOURNAMENT_DATA_DIR, TOURNAMENT_DB_EXTENSION


DEFAULT_SETTINGS = {
    "name": "",
    "format": "multi_stage",
    "participant_type": "team",
}
DEFAULT_TOURNAMENT = {
    "players": {},
    "teams": {},
    "recent_matches": [],
    "settings": DEFAULT_SETTINGS.copy(),
    "stages": [],
}
LEGACY_DB_EXTENSIONS = (".sql",)


def _empty_tournament():
    return {
        "players": {},
        "teams": {},
        "recent_matches": [],
        "settings": DEFAULT_SETTINGS.copy(),
        "stages": [],
    }


def _safe_file_stem(game_id):
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", str(game_id)).strip("_")
    return stem or "game"


def _db_path(game_id):
    return os.path.join(
        TOURNAMENT_DATA_DIR,
        f"{_safe_file_stem(game_id)}{TOURNAMENT_DB_EXTENSION}",
    )


def _connect(game_id):
    os.makedirs(TOURNAMENT_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_db_path(game_id))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tournament_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tournament_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY,
            discord_id TEXT,
            ingame_name TEXT NOT NULL DEFAULT '',
            kills INTEGER NOT NULL DEFAULT 0,
            deaths INTEGER NOT NULL DEFAULT 0,
            assists INTEGER NOT NULL DEFAULT 0,
            score INTEGER NOT NULL DEFAULT 0,
            rounds_mvp INTEGER NOT NULL DEFAULT 0,
            matches_mvp INTEGER NOT NULL DEFAULT 0,
            avg_win_time REAL NOT NULL DEFAULT 0,
            matches_played INTEGER NOT NULL DEFAULT 0,
            team_id TEXT
        );

        CREATE TABLE IF NOT EXISTS teams (
            team_id TEXT PRIMARY KEY,
            team_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_members (
            team_id TEXT NOT NULL,
            player_id TEXT NOT NULL,
            member_order INTEGER NOT NULL,
            PRIMARY KEY (team_id, player_id)
        );

        CREATE TABLE IF NOT EXISTS recent_matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_order INTEGER NOT NULL,
            saved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS match_teams (
            match_team_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            team_order INTEGER NOT NULL,
            team_index INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            avg_win_time REAL NOT NULL DEFAULT 0,
            team_rank INTEGER,
            team_id TEXT,
            team_name TEXT,
            FOREIGN KEY (match_id) REFERENCES recent_matches(match_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS match_players (
            match_player_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_team_id INTEGER NOT NULL,
            player_order INTEGER NOT NULL,
            player_id TEXT,
            discord_id TEXT,
            ingame_name TEXT NOT NULL DEFAULT '',
            kills INTEGER NOT NULL DEFAULT 0,
            deaths INTEGER NOT NULL DEFAULT 0,
            assists INTEGER NOT NULL DEFAULT 0,
            rounds_mvp INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (match_team_id) REFERENCES match_teams(match_team_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS stages (
            stage_id TEXT PRIMARY KEY,
            stage_order INTEGER NOT NULL,
            stage_name TEXT NOT NULL,
            stage_format TEXT NOT NULL,
            advance_count INTEGER NOT NULL DEFAULT 0,
            group_count INTEGER NOT NULL DEFAULT 0,
            settings_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS stage_points (
            stage_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            points INTEGER NOT NULL,
            PRIMARY KEY (stage_id, rank)
        );

        CREATE TABLE IF NOT EXISTS bracket_seeds (
            stage_id TEXT NOT NULL,
            seed INTEGER NOT NULL,
            participant_id TEXT,
            participant_name TEXT NOT NULL,
            PRIMARY KEY (stage_id, seed)
        );

        CREATE TABLE IF NOT EXISTS stage_standings (
            stage_id TEXT NOT NULL,
            participant_id TEXT,
            participant_name TEXT NOT NULL,
            rank INTEGER NOT NULL DEFAULT 0,
            points INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (stage_id, participant_name)
        );
        """
    )


def _reset_tables(conn):
    conn.executescript(
        """
        DELETE FROM match_players;
        DELETE FROM match_teams;
        DELETE FROM recent_matches;
        DELETE FROM bracket_seeds;
        DELETE FROM stage_standings;
        DELETE FROM stage_points;
        DELETE FROM stages;
        DELETE FROM tournament_settings;
        DELETE FROM team_members;
        DELETE FROM teams;
        DELETE FROM players;
        DELETE FROM tournament_meta;
        """
    )


def _set_meta(conn, key, value):
    conn.execute(
        """
        INSERT INTO tournament_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _get_meta(conn, key):
    row = conn.execute(
        "SELECT value FROM tournament_meta WHERE key = ?",
        (key,),
    ).fetchone()
    return row["value"] if row else None


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_tournament_from_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _create_schema(conn)

    game_id = _get_meta(conn, "game_id") or Path(path).stem
    tournament = _empty_tournament()

    settings = DEFAULT_SETTINGS.copy()
    for row in conn.execute("SELECT key, value FROM tournament_settings"):
        settings[row["key"]] = row["value"]
    tournament["settings"] = settings

    for row in conn.execute("SELECT * FROM players ORDER BY rowid"):
        tournament["players"][row["player_id"]] = {
            "discord_id": row["discord_id"] or "",
            "ingame_name": row["ingame_name"] or "",
            "kills": row["kills"],
            "deaths": row["deaths"],
            "assists": row["assists"],
            "score": row["score"],
            "rounds_MVP": row["rounds_mvp"],
            "Matches_MVP": row["matches_mvp"],
            "AVG_WIN_time": row["avg_win_time"],
            "matches_played": row["matches_played"],
            "team_id": row["team_id"],
        }

    for row in conn.execute("SELECT * FROM teams ORDER BY rowid"):
        tournament["teams"][row["team_id"]] = {
            "team_name": row["team_name"],
            "members": [],
        }

    for row in conn.execute(
        """
        SELECT team_id, player_id
        FROM team_members
        ORDER BY team_id, member_order
        """
    ):
        team = tournament["teams"].get(row["team_id"])
        if team is not None:
            team["members"].append(row["player_id"])

    match_rows = conn.execute(
        "SELECT * FROM recent_matches ORDER BY match_order"
    ).fetchall()
    for match_row in match_rows:
        match = {"saved_at": match_row["saved_at"], "teams": []}
        team_rows = conn.execute(
            """
            SELECT * FROM match_teams
            WHERE match_id = ?
            ORDER BY team_order
            """,
            (match_row["match_id"],),
        ).fetchall()

        for team_row in team_rows:
            team = {
                "team_index": team_row["team_index"],
                "score": team_row["score"],
                "avg_win_time": team_row["avg_win_time"],
                "players": [],
                "rank": team_row["team_rank"],
                "team_id": team_row["team_id"],
                "team_name": team_row["team_name"],
            }
            player_rows = conn.execute(
                """
                SELECT * FROM match_players
                WHERE match_team_id = ?
                ORDER BY player_order
                """,
                (team_row["match_team_id"],),
            ).fetchall()
            for player_row in player_rows:
                team["players"].append(
                    {
                        "player_id": player_row["player_id"],
                        "discord_id": player_row["discord_id"] or "",
                        "ingame_name": player_row["ingame_name"] or "",
                        "kills": player_row["kills"],
                        "deaths": player_row["deaths"],
                        "assists": player_row["assists"],
                        "rounds_MVP": player_row["rounds_mvp"],
                    }
                )
            match["teams"].append(team)

        tournament["recent_matches"].append(match)

    stage_rows = conn.execute(
        "SELECT * FROM stages ORDER BY stage_order"
    ).fetchall()
    for stage_row in stage_rows:
        stage_id = stage_row["stage_id"]
        try:
            settings_json = json.loads(stage_row["settings_json"] or "{}")
        except json.JSONDecodeError:
            settings_json = {}

        scoring_rule = [
            {"rank": row["rank"], "points": row["points"]}
            for row in conn.execute(
                """
                SELECT rank, points
                FROM stage_points
                WHERE stage_id = ?
                ORDER BY rank
                """,
                (stage_id,),
            )
        ]
        bracket = [
            {
                "seed": row["seed"],
                "participant_id": row["participant_id"],
                "participant_name": row["participant_name"],
            }
            for row in conn.execute(
                """
                SELECT seed, participant_id, participant_name
                FROM bracket_seeds
                WHERE stage_id = ?
                ORDER BY seed
                """,
                (stage_id,),
            )
        ]
        standings = [
            {
                "participant_id": row["participant_id"],
                "participant_name": row["participant_name"],
                "rank": row["rank"],
                "points": row["points"],
                "wins": row["wins"],
                "losses": row["losses"],
                "status": row["status"],
            }
            for row in conn.execute(
                """
                SELECT participant_id, participant_name, rank, points, wins, losses, status
                FROM stage_standings
                WHERE stage_id = ?
                ORDER BY rank = 0, rank, points DESC, wins DESC, participant_name
                """,
                (stage_id,),
            )
        ]

        tournament["stages"].append(
            {
                "stage_id": stage_id,
                "name": stage_row["stage_name"],
                "format": stage_row["stage_format"],
                "advance_count": stage_row["advance_count"],
                "group_count": stage_row["group_count"],
                "settings": settings_json,
                "scoring_rule": scoring_rule,
                "bracket": bracket,
                "standings": standings,
            }
        )

    conn.close()
    return game_id, tournament


def _save_tournament_to_db(game_id, tournament):
    conn = _connect(game_id)
    try:
        _create_schema(conn)
        _reset_tables(conn)
        _set_meta(conn, "game_id", str(game_id))

        settings = DEFAULT_SETTINGS.copy()
        settings.update(tournament.get("settings", {}))
        settings["name"] = settings.get("name") or str(game_id)
        for key, value in settings.items():
            conn.execute(
                """
                INSERT INTO tournament_settings (key, value)
                VALUES (?, ?)
                """,
                (key, str(value)),
            )

        for player_id, player in tournament.get("players", {}).items():
            conn.execute(
                """
                INSERT INTO players (
                    player_id, discord_id, ingame_name, kills, deaths, assists,
                    score, rounds_mvp, matches_mvp, avg_win_time,
                    matches_played, team_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    str(player.get("discord_id", "")) if player.get("discord_id") is not None else "",
                    player.get("ingame_name", ""),
                    _to_int(player.get("kills")),
                    _to_int(player.get("deaths")),
                    _to_int(player.get("assists")),
                    _to_int(player.get("score")),
                    _to_int(player.get("rounds_MVP")),
                    _to_int(player.get("Matches_MVP")),
                    _to_float(player.get("AVG_WIN_time")),
                    _to_int(player.get("matches_played")),
                    player.get("team_id"),
                ),
            )

        for team_id, team in tournament.get("teams", {}).items():
            conn.execute(
                "INSERT INTO teams (team_id, team_name) VALUES (?, ?)",
                (team_id, team.get("team_name", "")),
            )
            for member_order, player_id in enumerate(team.get("members", [])):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO team_members (team_id, player_id, member_order)
                    VALUES (?, ?, ?)
                    """,
                    (team_id, player_id, member_order),
                )

        for match_order, match in enumerate(tournament.get("recent_matches", [])):
            cursor = conn.execute(
                "INSERT INTO recent_matches (match_order, saved_at) VALUES (?, ?)",
                (match_order, match.get("saved_at")),
            )
            match_id = cursor.lastrowid

            for team_order, team in enumerate(match.get("teams", [])):
                cursor = conn.execute(
                    """
                    INSERT INTO match_teams (
                        match_id, team_order, team_index, score, avg_win_time,
                        team_rank, team_id, team_name
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        team_order,
                        _to_int(team.get("team_index")),
                        _to_int(team.get("score")),
                        _to_float(team.get("avg_win_time")),
                        team.get("rank"),
                        team.get("team_id"),
                        team.get("team_name"),
                    ),
                )
                match_team_id = cursor.lastrowid

                for player_order, player in enumerate(team.get("players", [])):
                    conn.execute(
                        """
                        INSERT INTO match_players (
                            match_team_id, player_order, player_id, discord_id,
                            ingame_name, kills, deaths, assists, rounds_mvp
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            match_team_id,
                            player_order,
                            player.get("player_id"),
                            str(player.get("discord_id", "")) if player.get("discord_id") is not None else "",
                            player.get("ingame_name", ""),
                            _to_int(player.get("kills")),
                            _to_int(player.get("deaths")),
                            _to_int(player.get("assists")),
                            _to_int(player.get("rounds_MVP")),
                        ),
                    )

        for stage_order, stage in enumerate(tournament.get("stages", [])):
            stage_id = stage.get("stage_id") or str(stage_order + 1)
            conn.execute(
                """
                INSERT INTO stages (
                    stage_id, stage_order, stage_name, stage_format,
                    advance_count, group_count, settings_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stage_id,
                    stage_order,
                    stage.get("name", f"stage{stage_order + 1}"),
                    stage.get("format", "points_race"),
                    _to_int(stage.get("advance_count")),
                    _to_int(stage.get("group_count")),
                    json.dumps(stage.get("settings", {}), ensure_ascii=False),
                ),
            )

            for item in stage.get("scoring_rule", []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO stage_points (stage_id, rank, points)
                    VALUES (?, ?, ?)
                    """,
                    (stage_id, _to_int(item.get("rank")), _to_int(item.get("points"))),
                )

            for seed in stage.get("bracket", []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bracket_seeds (
                        stage_id, seed, participant_id, participant_name
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        stage_id,
                        _to_int(seed.get("seed")),
                        seed.get("participant_id"),
                        seed.get("participant_name", ""),
                    ),
                )

            for standing in stage.get("standings", []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO stage_standings (
                        stage_id, participant_id, participant_name,
                        rank, points, wins, losses, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stage_id,
                        standing.get("participant_id"),
                        standing.get("participant_name", ""),
                        _to_int(standing.get("rank")),
                        _to_int(standing.get("points")),
                        _to_int(standing.get("wins")),
                        _to_int(standing.get("losses")),
                        standing.get("status", ""),
                    ),
                )

        conn.commit()
    finally:
        conn.close()


def _iter_db_files():
    if not os.path.isdir(TOURNAMENT_DATA_DIR):
        return []
    return [
        os.path.join(TOURNAMENT_DATA_DIR, filename)
        for filename in os.listdir(TOURNAMENT_DATA_DIR)
        if filename.endswith(TOURNAMENT_DB_EXTENSION)
    ]


def _rename_legacy_db_files():
    if not os.path.isdir(TOURNAMENT_DATA_DIR):
        return

    for filename in os.listdir(TOURNAMENT_DATA_DIR):
        stem, extension = os.path.splitext(filename)
        if extension not in LEGACY_DB_EXTENSIONS:
            continue

        old_path = os.path.join(TOURNAMENT_DATA_DIR, filename)
        new_path = os.path.join(TOURNAMENT_DATA_DIR, f"{stem}{TOURNAMENT_DB_EXTENSION}")
        if os.path.exists(new_path):
            continue
        os.replace(old_path, new_path)


def _migrate_legacy_json_if_needed():
    _rename_legacy_db_files()

    if _iter_db_files() or not os.path.exists(DATA_FILE):
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        legacy_data = json.load(f)

    for game_id, tournament in legacy_data.get("tournaments", {}).items():
        _save_tournament_to_db(game_id, tournament)


def load_data():
    """全大会データを大会ごとのSQLiteファイルから読み込む。"""
    _rename_legacy_db_files()
    _migrate_legacy_json_if_needed()

    data = {"tournaments": {}}
    for path in _iter_db_files():
        game_id, tournament = _load_tournament_from_db(path)
        data["tournaments"][game_id] = tournament
    return data


def save_data(data):
    """全大会データを大会ごとのSQLiteファイルへ保存する。"""
    os.makedirs(TOURNAMENT_DATA_DIR, exist_ok=True)
    _rename_legacy_db_files()
    tournaments = data.setdefault("tournaments", {})

    active_paths = set()
    for game_id, tournament in tournaments.items():
        _save_tournament_to_db(game_id, tournament)
        active_paths.add(os.path.abspath(_db_path(game_id)))

    for path in _iter_db_files():
        if os.path.abspath(path) not in active_paths:
            os.remove(path)


def get_tournament(data, game_id):
    """ゲームIDからトーナメントデータを取得。なければ作る。"""
    tournament = data["tournaments"].setdefault(game_id, _empty_tournament())
    tournament.setdefault("players", {})
    tournament.setdefault("teams", {})
    tournament.setdefault("recent_matches", [])
    settings = DEFAULT_SETTINGS.copy()
    settings.update(tournament.get("settings", {}))
    settings["name"] = settings.get("name") or str(game_id)
    tournament["settings"] = settings
    tournament.setdefault("stages", [])
    return tournament
