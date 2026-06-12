"""
プレイヤー名のOCR補正機能
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import re
from difflib import SequenceMatcher
from config.settings import NAME_MATCH_THRESHOLD, NAME_MATCH_MARGIN


def normalize_ingame_name(name):
    """ゲーム内名前を正規化（小文字、英数字_のみ）。"""
    if not name:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9_]+", "", str(name))
    return normalized.lower()


def _coerce_text(value):
    """値をテキストに変換。"""
    return str(value or "")


def _name_similarity(a, b):
    """
    OCR名と登録名の近さを計算。
    通常の文字列類似度 + 正規化名の類似度の高い方を使う。
    """
    a = _coerce_text(a)
    b = _coerce_text(b)
    if not a or not b:
        return 0.0

    raw_ratio = SequenceMatcher(None, a, b).ratio()
    norm_ratio = SequenceMatcher(None, normalize_ingame_name(a), normalize_ingame_name(b)).ratio()
    return max(raw_ratio, norm_ratio)


def correct_ocr_name(ocr_name, registered_names=None, threshold=NAME_MATCH_THRESHOLD, margin=NAME_MATCH_MARGIN):
    """
    OCRで読んだ名前を、登録済みingame_nameにだけ補正する。

    重要:
    - registered_names が空なら補正しない
    - MANUAL aliasのような未登録名への補正はしない
    - 最高候補がthreshold以上でも、2位との差が小さい場合は補正しない
    """
    name = _coerce_text(ocr_name).strip()
    if not name:
        return name, 0.0, "empty"

    registered_names = [str(n) for n in (registered_names or []) if n]
    if not registered_names:
        return name, 0.0, "no_registered_names"

    scored = []
    for registered in registered_names:
        score = _name_similarity(name, registered)
        scored.append((score, registered))

    scored.sort(reverse=True, key=lambda x: x[0])

    best_score, best_name = scored[0]
    second_score = scored[1][0] if len(scored) >= 2 else 0.0

    if best_score < threshold:
        return name, best_score, "below_threshold"

    if len(scored) >= 2 and (best_score - second_score) < margin:
        return name, best_score, "ambiguous"

    return best_name, best_score, "matched_registered"


def apply_name_corrections(parsed_players, tournament=None, threshold=NAME_MATCH_THRESHOLD):
    """
    parse_scoreboard_image() の結果に名前補正をかける。
    補正先は tournament に登録済みの ingame_name のみ。
    補正前の名前は raw["ocr_name"] に残す。
    """
    from data.player_manager import get_registered_ingame_names
    
    registered_names = get_registered_ingame_names(tournament) if tournament else []

    corrected = []
    for player in parsed_players:
        p = dict(player)
        raw = dict(p.get("raw", {}))

        before = p.get("ingame_name", "")
        after, score, reason = correct_ocr_name(before, registered_names, threshold=threshold)

        raw["ocr_name"] = before
        raw["corrected_name"] = after
        raw["name_match_score"] = round(float(score), 3)
        raw["name_match_reason"] = reason

        p["ingame_name"] = after
        p["raw"] = raw
        corrected.append(p)

    return corrected
