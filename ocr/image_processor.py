"""
スコアボード画像の解析・処理
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import asyncio
from config.settings import ROWS_Y, TEAM_Y, COLS, NAME_CFG, DIGIT_CFG, TIME_CFG
from ocr.ocr_utils import (
    read_cell, read_digit_cell, _clean_player_name, _safe_parse_time
)


async def parse_scoreboard_image(rslt_img):
    """
    EFT:Arena Shootoutのリザルト画像専用パーサ。
    v2:
    - 数字は多数決OCRに変更
    - 斜線付き0を7と誤読する問題を軽減
    - 11を1に潰さない
    """
    players = []

    # ===== チーム単位のAVG WIN TIME / SCORE =====
    team_stats = []
    for y1, y2 in TEAM_Y:
        avg_box = (COLS["avg_win_time"][0], y1, COLS["avg_win_time"][1], y2)
        score_box = (COLS["score"][0], y1, COLS["score"][1], y2)

        # TIMEは文字列として読む
        avg_text = await read_cell(rslt_img, avg_box, TIME_CFG, field_type="time", scale=5)

        # SCOREは数字なので多数決
        score, score_raw = await read_digit_cell(
            rslt_img,
            score_box,
            DIGIT_CFG,
            field_type="score",
            scale=5,
            default=0,
            min_votes=1,
            max_value=999,
        )

        avg_win_time = _safe_parse_time(avg_text)

        team_stats.append({
            "avg_win_time": avg_win_time if avg_win_time is not None else 0.0,
            "score": score if score is not None else 0,
            "raw_avg": avg_text,
            "raw_score": score_raw,
        })

    # ===== プレイヤー単位 =====
    for row_index, (y1, y2) in enumerate(ROWS_Y):
        team_index = row_index // 2

        boxes = {
            "username": (COLS["username"][0], y1, COLS["username"][1], y2),
            "mvp": (COLS["mvp"][0], y1, COLS["mvp"][1], y2),
            "k": (COLS["k"][0], y1, COLS["k"][1], y2),
            "d": (COLS["d"][0], y1, COLS["d"][1], y2),
            "a": (COLS["a"][0], y1, COLS["a"][1], y2),
        }

        name_text = await read_cell(
            rslt_img,
            boxes["username"],
            NAME_CFG,
            field_type="name",
            scale=5,
        )

        name = _clean_player_name(name_text)
        if not name or len(name) < 2:
            continue

        # MVPは空欄が普通にあるので default=0
        # 空欄ノイズを拾わないよう min_votes=3
        rounds_mvp, mvp_raw = await read_digit_cell(
            rslt_img,
            boxes["mvp"],
            DIGIT_CFG,
            field_type="mvp",
            scale=6,
            default=0,
            min_votes=1,
            max_value=30,
        )

        # K/Dは基本必須。11などは本物として残す
        kills, k_raw = await read_digit_cell(
            rslt_img,
            boxes["k"],
            DIGIT_CFG,
            field_type="kda",
            scale=6,
            default=None,
            min_votes=1,
            max_value=30,
        )
        deaths, d_raw = await read_digit_cell(
            rslt_img,
            boxes["d"],
            DIGIT_CFG,
            field_type="kda",
            scale=6,
            default=None,
            min_votes=1,
            max_value=30,
        )

        # Aは0が斜線付きで7誤読されやすいので default=0 / min_votes=2
        assists, a_raw = await read_digit_cell(
            rslt_img,
            boxes["a"],
            DIGIT_CFG,
            field_type="assist",
            scale=6,
            default=0,
            min_votes=1,
            max_value=30,
        )

        # K/Dが読めない行だけスキップ。Aは読めなければ0で扱う。
        if kills is None or deaths is None:
            print(f"K/D read failed: row={row_index + 1}, name={name}, K={k_raw}, D={d_raw}, A={a_raw}")
            continue

        if assists is None:
            assists = 0

        if rounds_mvp is None:
            rounds_mvp = 0

        team = team_stats[team_index] if team_index < len(team_stats) else {
            "avg_win_time": 0.0,
            "score": 0,
            "raw_avg": "",
            "raw_score": "",
        }

        players.append({
            "ingame_name": name,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "score": team["score"],
            "avg_win_time": team["avg_win_time"],
            "team_index": team_index,
            "rounds_mvp": rounds_mvp,
            "raw": {
                "name": name_text,
                "mvp": mvp_raw,
                "k": k_raw,
                "d": d_raw,
                "a": a_raw,
                "avg": team.get("raw_avg", ""),
                "score": team.get("raw_score", ""),
            },
        })

    return players
