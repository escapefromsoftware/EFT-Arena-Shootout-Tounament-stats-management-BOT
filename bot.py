from PIL import Image as PILImage, ImageOps, ImageFilter, ImageDraw
from io import BytesIO
import aiohttp
import asyncio
import json
import os
import re
import traceback
import uuid
from collections import Counter
from difflib import SequenceMatcher
from dotenv import load_dotenv

import discord
from discord.ext import commands
import pytesseract


# =========================
# 基本設定
# =========================

# WindowsでTesseractを標準パスに入れている場合
# 環境変数 TESSERACT_CMD がある場合はそちらを優先
pytesseract.pytesseract.tesseract_cmd = os.getenv(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

load_dotenv()
TOKEN = os.getenv("TOKEN")
DATA_FILE = "tournament_data.json"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
BOT_adiminater_ID = 721546801743790110  # 管理者ID。コマンド使用制限などに利用予定


# =========================
# EFT:Arena リザルト画像OCR設定
# 元画像 1920x1080 を基準にした固定座標
# =========================

BASE_W, BASE_H = 1920, 1080

# 最大8チーム = 16人まで対応
# 1920x1080基準。もしゲーム側の表示位置が変わる場合は !debugocr で確認。
ROWS_Y = [
    (180, 209),  # team1 player1
    (225, 254),  # team1 player2
    (276, 305),  # team2 player1
    (321, 350),  # team2 player2
    (372, 401),  # team3 player1
    (417, 446),  # team3 player2
    (468, 497),  # team4 player1
    (513, 542),  # team4 player2
    (564, 593),  # team5 player1
    (609, 638),  # team5 player2
    (660, 689),  # team6 player1
    (705, 734),  # team6 player2
    (756, 785),  # team7 player1
    (801, 830),  # team7 player2
    (852, 881),  # team8 player1
    (897, 926),  # team8 player2
]

TEAM_Y = [
    (205, 232),  # team1
    (301, 328),  # team2
    (397, 424),  # team3
    (493, 520),  # team4
    (589, 616),  # team5
    (685, 712),  # team6
    (781, 808),  # team7
    (877, 904),  # team8
]

COLS = {
    "username": (680, 850),
    "mvp": (1007, 1025),
    "k": (1078, 1110),
    "d": (1132, 1160),
    "a": (1185, 1212),
    "avg_win_time": (1260, 1315),
    "score": (1350, 1392),
}

NAME_CFG = (
    "--oem 3 --psm 7 "
    "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
DIGIT_CFG = "--oem 3 --psm 10 -c tessedit_char_whitelist=0123456789"
DIGIT_LINE_CFG = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
TIME_CFG = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789:."


# =========================
# プレイヤー名OCR補正
# =========================
# 方針:
# - !addplayer / !setplayer で登録済みの ingame_name にだけ補正する
# - 未登録の名前には補正しない
# - 一部プレイヤーだけ登録していても、無理やり近い登録名へ寄せすぎない
#
# しきい値:
# 0.88〜0.94くらいで調整。
# 高いほど誤補正が減るが、補正されにくくなる。
NAME_MATCH_THRESHOLD = 0.90

# 1位候補と2位候補の差がこれ未満なら、曖昧なので補正しない
NAME_MATCH_MARGIN = 0.06


# =========================
# JSON データ管理
# =========================

def load_data():
    """JSONファイルからデータを読み込む。なければ初期化。"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"tournaments": {}}

    data.setdefault("tournaments", {})
    return data


def save_data(data):
    """JSONファイルへ保存。"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_tournament(data, game_id):
    """ゲームIDからトーナメントデータを取得。なければ作る。"""
    return data["tournaments"].setdefault(game_id, {"players": {}, "teams": {}})


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


# =========================
# 検索/正規化
# =========================

def normalize_ingame_name(name):
    if not name:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9_]+", "", str(name))
    return normalized.lower()


def get_player_by_ingame_name(tournament, ingame_name):
    target_name = normalize_ingame_name(ingame_name)
    for player_id, player in tournament.get("players", {}).items():
        ensure_player_defaults(player)
        if normalize_ingame_name(player.get("ingame_name", "")) == target_name:
            return player_id, player
    return None, None


def get_player_by_discord_id(tournament, discord_id):
    for player_id, player in tournament.get("players", {}).items():
        ensure_player_defaults(player)
        if str(player.get("discord_id")) == str(discord_id):
            return player_id, player
    return None, None


def get_team_by_name(tournament, team_name):
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


# =========================
# OCR用ユーティリティ
# =========================

def _coerce_text(value):
    if asyncio.iscoroutine(value):
        return ""
    return str(value or "")


def _safe_parse_int(text):
    digits = re.sub(r"\D", "", _coerce_text(text))
    return int(digits) if digits else None


def _safe_parse_time(text):
    """
    OCR結果を秒数(float)へ変換。
    例:
      "0:22.370" -> 22.37
      "22.370"  -> 22.37
    """
    raw = _coerce_text(text)
    raw = raw.replace(" ", "").replace(",", ".")
    raw = raw.replace("O", "0").replace("o", "0").replace("@", "0")
    cleaned = re.sub(r"[^\d:.]", "", raw)

    if ":" in cleaned:
        m, sec = cleaned.split(":", 1)
        minutes = int(m) if m.isdigit() else 0
        sec_match = re.search(r"\d+(?:\.\d+)?", sec)
        seconds = float(sec_match.group(0)) if sec_match else 0.0
        return minutes * 60 + seconds

    num_match = re.search(r"\d+(?:\.\d+)?", cleaned)
    return float(num_match.group(0)) if num_match else None


def format_time(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "0:00.000"

    minutes = int(seconds // 60)
    sec = seconds - minutes * 60
    return f"{minutes}:{sec:06.3f}"


def _clean_player_name(text):
    """
    ユーザー名のOCRノイズ除去。
    Iを全部iにするような強い補正は、MIKO_nano等を壊すのでやらない。
    """
    raw = _coerce_text(text).strip()
    raw = raw.replace("|", "l")
    candidates = re.findall(r"[A-Za-z0-9_]{2,}", raw)
    if not candidates:
        return ""
    return max(candidates, key=len)


def scale_box(box, image):
    """1920x1080基準のboxを、実画像サイズに合わせて拡大縮小する。"""
    x1, y1, x2, y2 = box
    w, h = image.size
    sx = w / BASE_W
    sy = h / BASE_H
    return (
        int(x1 * sx),
        int(y1 * sy),
        int(x2 * sx),
        int(y2 * sy),
    )


def _ocr_score(field_type, txt):
    """複数OCR候補から一番マシな結果を選ぶためのスコア。"""
    t = _coerce_text(txt).strip()

    if field_type in ("digit", "score", "mvp", "kda"):
        digits = re.sub(r"\D", "", t)
        return len(digits) * 10 - len(t)

    if field_type == "time":
        # 0:22.370 みたいな形式に近いほど高評価
        cleaned = re.sub(r"[^\d:.]", "", t)
        score = len(cleaned)
        if ":" in cleaned:
            score += 10
        if "." in cleaned:
            score += 5
        return score

    # name
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", t)
    return len(cleaned) * 10 - abs(len(t) - len(cleaned))


def _make_ocr_variants(cropped, scale=4):
    """
    暗い背景・明るい文字用の前処理候補を複数作る。
    Tesseractは「白背景に黒文字」の方が安定しやすいので反転も作る。
    """
    w, h = cropped.size
    up = cropped.resize(
        (max(1, int(w * scale)), max(1, int(h * scale))),
        PILImage.Resampling.LANCZOS,
    )

    gray = ImageOps.grayscale(up)
    gray = ImageOps.autocontrast(gray)

    variants = [gray]

    # 軽くシャープ
    variants.append(gray.filter(ImageFilter.SHARPEN))

    # threshold -> 反転（白背景黒文字）
    for th in (90, 110, 130, 150, 170):
        bw = gray.point(lambda p, t=th: 255 if p > t else 0).convert("L")
        variants.append(bw)
        variants.append(ImageOps.invert(bw))

    return variants


def _ocr_crop_sync(image, box, config, field_type="text", scale=4):
    cropped = image.crop(box)
    variants = _make_ocr_variants(cropped, scale=scale)

    best = ""
    best_score = -10**9

    for img in variants:
        try:
            txt = pytesseract.image_to_string(
                img,
                lang="eng",
                config=config,
                timeout=3,
            )
        except Exception:
            txt = ""

        score = _ocr_score(field_type, txt)
        if score > best_score:
            best = txt
            best_score = score

    return _coerce_text(best).strip()


async def ocr_crop_async(image, box, config, field_type="text", scale=4):
    return await asyncio.to_thread(_ocr_crop_sync, image, box, config, field_type, scale)


async def read_cell(image, base_box, config, field_type="text", scale=4):
    return await ocr_crop_async(
        image,
        scale_box(base_box, image),
        config,
        field_type=field_type,
        scale=scale,
    )


def _parse_digit_candidates(texts):
    """OCR候補文字列リストをint候補へ変換する。"""
    values = []
    for txt in texts:
        values.append(_safe_parse_int(txt))
    return values


def _digit_vote_from_texts(texts, default=None, min_votes=2, max_value=30):
    """
    数字OCRの候補を多数決で決める。
    重要:
    - 斜線付き0はTesseractが7と誤読しやすい
    - 1回だけ出た7は信用せず、default=0なら0にする
    - 11は本物の可能性があるので、11 -> 1 のような圧縮はしない
    """
    values = _parse_digit_candidates(texts)
    counts = Counter(v for v in values if v is not None)

    if not counts:
        return default

    value, votes = counts.most_common(1)[0]

    # 票が少なすぎる数字はノイズ扱い
    # 例: 斜線付き0が1回だけ7として出るケース
    if votes < min_votes:
        return default

    # 77, 55, 33 のような重複誤読だけ補正
    # 11はmax_value以下なので潰さない
    if max_value is not None and value > max_value:
        s = str(value)
        if len(s) >= 2 and len(set(s)) == 1:
            collapsed = int(s[0])
            if collapsed <= max_value:
                return collapsed
        return default

    return value


def _looks_like_slashed_zero(cropped):
    """
    EFT:Arenaの斜線付き0判定。
    Tesseractが 0 を 2 / 7 に読みやすいので、画像特徴で補正する。
    """
    try:
        up = cropped.resize(
            (max(1, cropped.width * 8), max(1, cropped.height * 8)),
            PILImage.Resampling.LANCZOS,
        )
        gray = ImageOps.autocontrast(ImageOps.grayscale(up))

        # 明るい文字だけを抽出
        pixels = gray.load()
        w, h = gray.size
        bright = []
        for y in range(h):
            for x in range(w):
                if pixels[x, y] > 120:
                    bright.append((x, y))

        if not bright:
            return False

        xs = [p[0] for p in bright]
        ys = [p[1] for p in bright]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)

        bw = x1 - x0 + 1
        bh = y1 - y0 + 1
        if bw <= 0 or bh <= 0:
            return False

        # bbox内での領域別の明るさ割合
        def ratio(xa, xb, ya, yb):
            xa = max(x0, min(x1, xa))
            xb = max(x0, min(x1, xb))
            ya = max(y0, min(y1, ya))
            yb = max(y0, min(y1, yb))
            total = max(1, (xb - xa + 1) * (yb - ya + 1))
            count = 0
            for yy in range(ya, yb + 1):
                for xx in range(xa, xb + 1):
                    if pixels[xx, yy] > 120:
                        count += 1
            return count / total

        left_mid = ratio(x0, x0 + bw // 3, y0 + bh // 4, y0 + (bh * 3) // 4)
        right_mid = ratio(x0 + (bw * 2) // 3, x1, y0 + bh // 4, y0 + (bh * 3) // 4)
        top = ratio(x0, x1, y0, y0 + bh // 4)
        bottom = ratio(x0, x1, y0 + (bh * 3) // 4, y1)

        # 0は左・右・上・下の枠が全部そこそこ濃い
        return left_mid > 0.45 and right_mid > 0.45 and top > 0.45 and bottom > 0.45

    except Exception:
        return False


def _ocr_digit_vote_sync(image, box, config, field_type="digit", scale=6, default=None, min_votes=2, max_value=30):
    """
    数字専用OCR v3。
    v2の「大量のthreshold候補」より、EFT:Arenaのフォントでは
    autocontrast + sharpen + psm複数の方が安定したため変更。
    """
    cropped = image.crop(box)

    # scoreは2桁/1桁が混じるので少し小さめscale
    if field_type == "score":
        scale = 5
    else:
        scale = 6

    up = cropped.resize(
        (max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale))),
        PILImage.Resampling.LANCZOS,
    )

    gray = ImageOps.autocontrast(ImageOps.grayscale(up))
    sharp = gray.filter(ImageFilter.SHARPEN)

    # psm 6/7/10はスコアの「1」に強い
    # psm 8/13はMVPの黄色数字やスコアの「31」に強い
    psm_list = (6, 7, 8, 10, 13)

    texts = []
    for psm in psm_list:
        cfg = f"--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789"
        try:
            txt = pytesseract.image_to_string(
                sharp,
                lang="eng",
                config=cfg,
                timeout=3,
            )
        except Exception:
            txt = ""
        texts.append(_coerce_text(txt).strip())

    value = _digit_vote_from_texts(
        texts,
        default=default,
        min_votes=min_votes,
        max_value=max_value,
    )

    # Assists欄の斜線付き0対策。
    # 0 が 2 / 7 に化けた場合だけ画像特徴で0に戻す。
    if field_type == "assist" and value in (2, 7):
        if _looks_like_slashed_zero(cropped):
            value = 0

    # K/D/A/MVP欄でも、空欄でない斜線付き0を読んだ場合の保険
    if field_type in ("kda", "mvp") and value in (2, 7):
        # mvpは空欄も多いが、0表示は基本ないのでmvpでは強く補正しない
        if field_type == "kda" and _looks_like_slashed_zero(cropped):
            value = 0

    raw = " / ".join(t for t in texts if t)
    return value, raw


async def read_digit_cell(image, base_box, config, field_type="digit", scale=6, default=None, min_votes=2, max_value=30):
    value, raw = await asyncio.to_thread(
        _ocr_digit_vote_sync,
        image,
        scale_box(base_box, image),
        config,
        field_type,
        scale,
        default,
        min_votes,
        max_value,
    )
    return value, raw


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
            DIGIT_LINE_CFG,
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


def update_avg_win_time(player, avg_win_time):
    """AVG_WIN_timeを試合数で重み付き平均する。"""
    ensure_player_defaults(player)
    old_count = int(player.get("matches_played", 0) or 0)
    old_avg = float(player.get("AVG_WIN_time", 0) or 0)

    new_avg = ((old_avg * old_count) + float(avg_win_time)) / (old_count + 1)
    player["AVG_WIN_time"] = new_avg
    player["matches_played"] = old_count + 1


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


def adimin_check():
    """コマンド実行者が管理者かどうかをチェックするデコレーター。"""
    async def predicate(ctx):

        if ctx.author.id == BOT_adiminater_ID:
            return True
        
        if ctx.author.guild_permissions.administrator:
            return True
        
        return False
    
    return commands.check(predicate)


# =========================
# Botイベント
# =========================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} / {bot.user.id}")


# =========================
# コマンド
# =========================

@bot.command(name="commands")
async def help_command(ctx):
    await ctx.send(
        "📊 **トーナメントスタッツ管理Botのコマンド一覧** 📊\n"
        "```markdown\n"
        "!commands - コマンド一覧を表示\n"
        "!updateimage <game_id> - 画像添付からOCRでスタッツを更新\n"
        "!checkimage [game_id] - OCR結果だけ表示。game_id指定時だけ登録済み名前に補正\n"
        "!debugocr - 画像添付から座標確認用のcrop画像を返す\n"
        "!updatestats <game_id> <@discord_user> - プレイヤーのスタッツを手動更新\n"
        "!setplayer <game_id> <@discord_user> <ingame_name> - インゲーム名を設定\n"
        "!unassign <game_id> <@discord_user> - インゲーム名を解除\n"
        "!remakeplayer <game_id> <old_ingame_name> <new_ingame_name> - ingame_nameを修正\n"
        "!playerstats <game_id> <@discord_user> - プレイヤーのスタッツを表示\n"
        "!resetstats <game_id> <@discord_user> - プレイヤーのスタッツをリセット\n"
        "!resetkda <game_id> - 全プレイヤーのKDAなどをリセット\n"
        "!resetdata <game_id> - トーナメントデータをリセット\n"
        "!rankings <game_id> <KDA|KILLS|SCORE|MVP|AVG_WIN_TIME> - ランキング表示\n"
        "!addplayer <game_id> <@discord_user> <ingame_name> - プレイヤー追加\n"
        "!removeplayer <game_id> <@discord_user> - プレイヤー削除\n"
        "!showplayers <game_id> - 参加プレイヤー一覧\n"
        "!maketeam <game_id> <team_name> <@user1> <@user2> ... - チーム作成\n"
        "!teamstats <game_id> <team_name> - チームスタッツ表示\n"
        "!addteam <game_id> <team_name> <@discord_user> - チームに追加\n"
        "!removeteam <game_id> <team_name> <@discord_user> - チームから削除\n"
        "!deleteteam <game_id> <team_name> - チーム削除\n"
        "!exportstats <game_id> - JSON出力\n"
        "!importstats <game_id> <json_url> - JSONインポート\n"
        "!makegame <game_id> <team1> <team2> ... - ゲーム作成\n"
        "!gamestats <game_id> - ゲーム概要表示\n"
        "!deletegame <game_id> - ゲーム削除\n"
        "```"
    )


async def _download_first_attachment_image(ctx):
    if not ctx.message.attachments:
        await ctx.send("❌ 画像を添付してください。")
        return None

    attachment = ctx.message.attachments[0]

    async with aiohttp.ClientSession() as session:
        async with session.get(attachment.url) as resp:
            resp.raise_for_status()
            image_data = await resp.read()

    return PILImage.open(BytesIO(image_data)).convert("RGB")


def _apply_parsed_players_to_data(tournament, parsed_players):
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

        # 未設定プレイヤーが1人だけなら自動紐付け
        if not player_id:
            unassigned = get_unassigned_players(tournament)
            if len(unassigned) == 1:
                player_id, player = unassigned[0]
                player["ingame_name"] = ingame_name
                result_lines.append(
                    f"ℹ️ {ingame_name}: 未設定プレイヤーにインゲーム名を自動保存しました "
                    f"(<@{player['discord_id']}>)."
                )

        if player_id:
            p = ensure_player_defaults(tournament["players"][player_id])
            p["kills"] += kills
            p["deaths"] += deaths
            p["assists"] += assists
            p["score"] += score
            p["rounds_MVP"] += rounds_mvp
            p["Matches_MVP"] += 0
            update_avg_win_time(p, avg_win_time)

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


@bot.command(name="checkimage")
@adimin_check()
async def checkimage(ctx, game_id: str = None):
    """画像添付からOCR結果だけ表示。保存はしない。"""
    try:
        rslt_img = await _download_first_attachment_image(ctx)
        await ctx.send("🔍 OCRで画像を解析中...少々お待ちください。")
        if rslt_img is None:
            return

        parsed_players = await parse_scoreboard_image(rslt_img)

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

            lines.append(
                f"{t}-{team_seen[t]}: "
                f"{name_part} | MVP={p['rounds_mvp']} | "
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


@bot.command(name="updateimage")
@adimin_check()
async def updateimage(ctx, game_id: str):
    """画像添付からOCRでプレイヤーのKDA/MVP/Score/AvgWinTimeを読み取り更新。"""
    await ctx.send("🔍 OCRで画像を解析中...少々お待ちください。")
    try:
        rslt_img = await _download_first_attachment_image(ctx)
        if rslt_img is None:
            return

        parsed_players = await parse_scoreboard_image(rslt_img)

        if not parsed_players:
            await ctx.send("❌ OCRでプレイヤーを読み取れませんでした。先に `!checkimage` で確認してください。")
            return

        data = load_data()
        tournament = get_tournament(data, game_id)

        # 登録済みプレイヤー名 + MANUAL_NAME_ALIASES でOCR名を補正
        parsed_players = apply_name_corrections(parsed_players, tournament)

        updated_count, result_msg = _apply_parsed_players_to_data(tournament, parsed_players)

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


@bot.command(name="debugocr")
@commands.has_permissions(administrator=True)
async def debugocr(ctx):
    """
    座標確認用。
    添付画像にOCR対象の枠を描いて返す。
    """
    try:
        img = await _download_first_attachment_image(ctx)
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


@bot.command(name="playerstats")
async def playerstats(ctx, game_id: str, discord_user: discord.Member):
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

    await ctx.send(embed=embed)


@bot.command(name="updatestats")
@adimin_check()
async def updatestats(ctx, game_id: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    #5分入力がなければタイムアウト
    try:
        message = await bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=300)
    except asyncio.TimeoutError:
        await ctx.send("❌ 入力がタイムアウトしました。もう一度コマンドを実行してください。")
        return

    if not player:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
        return

    ensure_player_defaults(player)
    await ctx.send(
        f"現在のスタッツ: "
        f"Kills={player['kills']}, Deaths={player['deaths']}, Assists={player['assists']}, "
        f"Score={player['score']}, Rounds MVP={player.get('rounds_MVP', 0)}, "
        f"Matches MVP={player.get('Matches_MVP', 0)}, "
        f"AVG_WIN_time={format_time(player.get('AVG_WIN_time', 0))}\n"
        "更新したいスタッツを以下の形式で入力してください:\n"
        "`Kills Deaths Assists Score RoundsMVP MatchesMVP AVG_WIN_time_seconds`\n"
        "例: `5 2 3 10 1 0 22.370`"
    )

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    message = await bot.wait_for("message", check=check)

    try:
        parts = message.content.split()
        if len(parts) != 7:
            raise ValueError("7個の値が必要です")

        kills, deaths, assists, score, rounds_mvp, matches_mvp = map(int, parts[:6])
        avg_win_time = float(parts[6])

        player["kills"] = kills
        player["deaths"] = deaths
        player["assists"] = assists
        player["score"] = score
        player["rounds_MVP"] = rounds_mvp
        player["Matches_MVP"] = matches_mvp
        player["AVG_WIN_time"] = avg_win_time

        save_data(data)
        await ctx.send(f"✅ <@{discord_user.id}> のスタッツを更新しました (ゲーム: {game_id})。")

    except ValueError as e:
        await ctx.send(f"❌ 入力形式が正しくありません: {e}")


@bot.command(name="setplayer")
@adimin_check()
async def setplayer(ctx, game_id: str, discord_user: discord.Member, *, ingame_name: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

    if not player:
        # 存在しなければ追加する
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


@bot.command(name="unassign")
@adimin_check()
async def unassign(ctx, game_id: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

    if not player:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません。")
        return

    player["ingame_name"] = ""
    save_data(data)
    await ctx.send(f"✅ <@{discord_user.id}> のインゲーム名を解除しました。")


@bot.command(name="remakeplayer")
@adimin_check()
async def remakeplayer(ctx, game_id: str, old_ingame_name: str, *, new_ingame_name: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_ingame_name(tournament, old_ingame_name)

    if not player:
        await ctx.send(f"❌ '{old_ingame_name}' が見つかりません。")
        return

    player["ingame_name"] = new_ingame_name
    save_data(data)
    await ctx.send(f"✅ '{old_ingame_name}' を '{new_ingame_name}' に修正しました。")


@bot.command(name="addplayer")
@adimin_check()
async def addplayer(ctx, game_id: str, discord_user: discord.Member, *, ingame_name: str):
    data = load_data()
    tournament = get_tournament(data, game_id)

    _, existing = get_player_by_discord_id(tournament, discord_id=discord_user.id)
    if existing:
        await ctx.send(f"⚠️ <@{discord_user.id}> はすでに登録されています。`!setplayer`で変更してください。")
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


@bot.command(name="removeplayer")
@adimin_check()
async def removeplayer(ctx, game_id: str, discord_user: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)
    player_id, player = get_player_by_discord_id(tournament, discord_id=discord_user.id)

    if not player_id:
        await ctx.send(f"❌ プレイヤー <@{discord_user.id}> が見つかりません (ゲーム: {game_id})。")
        return

    # チームからも外す
    for team in tournament.get("teams", {}).values():
        if player_id in team.get("members", []):
            team["members"].remove(player_id)

    del tournament["players"][player_id]
    save_data(data)
    await ctx.send(f"✅ <@{discord_user.id}> をプレイヤーリストから削除しました (ゲーム: {game_id})。")


@bot.command(name="showplayers")
async def showplayers(ctx, game_id: str):
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


@bot.command(name="resetstats")
@adimin_check()
async def resetstats(ctx, game_id: str, discord_user: discord.Member):
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


@bot.command(name="resetkda")
@adimin_check()
async def resetkda(ctx, game_id: str):
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


@bot.command(name="resetdata")
@adimin_check()
async def resetdata(ctx, game_id: str):
    data = load_data()
    data["tournaments"][game_id] = {"players": {}, "teams": {}}
    save_data(data)
    await ctx.send(f"✅ トーナメントのデータをリセットしました (ゲーム: {game_id})。")


@bot.command(name="rankings")
async def rankings(ctx, game_id: str, stat_type: str = "KD"):
    data = load_data()
    tournament = get_tournament(data, game_id)
    players = [ensure_player_defaults(p) for p in tournament.get("players", {}).values()]

    st = stat_type.upper()

    if st == "KD":
        players.sort(key=lambda p: (p["kills"] ) / max(p["deaths"], 1), reverse=True)
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
    elif st == "teamKD":
        # チームごとの平均K/Dでソート
        team_kd = {}
        for p in players:
            team_id = p.get("team_id")
            if team_id:
                kd = (p["kills"] ) / max(p["deaths"], 1)
                if team_id not in team_kd:
                    team_kd[team_id] = []
                team_kd[team_id].append(kd)

        team_avg_kd = {team_id: sum(kds) / len(kds) for team_id, kds in team_kd.items()}
        players.sort(key=lambda p: team_avg_kd.get(p.get("team_id"), 0), reverse=True)
    elif st == "teamscore":
        # チームごとのスコアでソート
        team_score = {}
        for p in players:
            team_id = p.get("team_id")
            if team_id:
                score = p["score"]
                if team_id not in team_score:
                    team_score[team_id] = 0
                team_score[team_id] += score

        players.sort(key=lambda p: team_score.get(p.get("team_id"), 0), reverse=True)
    else:
        await ctx.send("❌ 無効なstat_typeです。KD、KILLS、SCORE、MVP、AVG_WIN_TIME、teamKD、teamscoreを指定してください。")
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
        elif st == "teamKD":
            team_id = player.get("team_id")
            team_name = tournament["teams"].get(team_id, {}).get("team_name", "N/A") if team_id else "N/A"
            value = f"{team_name} (平均K/D: {((player['kills'] ) / max(player['deaths'], 1)):.2f})"
        elif st == "teamscore":
            team_id = player.get("team_id")
            team_name = tournament["teams"].get(team_id, {}).get("team_name", "N/A") if team_id else "N/A"
            team_score = sum(p["score"] for p in players if p.get("team_id") == team_id)
            value = f"{team_name} (合計スコア: {team_score})"
        else:
            value = f"{player['kills']}/{player['deaths']} ({player['kills'] / max(player['deaths'], 1):.2f})"
        lines.append(f"{i}. {name}: {value}")

    await send_long(ctx, "\n".join(lines))


@bot.command(name="maketeam")
@adimin_check()
async def maketeam(ctx, game_id: str, team_name: str, *discord_users: discord.Member):
    data = load_data()
    tournament = get_tournament(data, game_id)

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


@bot.command(name="teamstats")
async def teamstats(ctx, game_id: str, team_name: str):
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

    await ctx.send(embed=embed)


@bot.command(name="addteam")
@adimin_check()
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
        await ctx.send(f"⚠️ <@{discord_user.id}> はすでにチーム '{team_name}' に所属しています。")
        return

    team.setdefault("members", []).append(player_id)
    tournament["players"][player_id]["team_id"] = team_id
    save_data(data)
    await ctx.send(f"✅ <@{discord_user.id}> をチーム '{team_name}' に追加しました。")


@bot.command(name="removeteam")
@adimin_check()
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

    if player_id not in team.get("members", []):
        await ctx.send(f"⚠️ <@{discord_user.id}> はチーム '{team_name}' に所属していません。")
        return

    team["members"].remove(player_id)
    tournament["players"][player_id]["team_id"] = None
    save_data(data)
    await ctx.send(f"✅ <@{discord_user.id}> をチーム '{team_name}' から削除しました。")


@bot.command(name="deleteteam")
@adimin_check()
async def deleteteam(ctx, game_id: str, team_name: str):
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


@bot.command(name="exportstats")
@adimin_check()
async def exportstats(ctx, game_id: str):
    data = load_data()
    tournament = get_tournament(data, game_id)
    text = json.dumps(tournament, ensure_ascii=False, indent=2)

    if len(text) < 1900:
        await ctx.send(f"```json\n{text}\n```")
    else:
        buf = BytesIO(text.encode("utf-8"))
        await ctx.send(file=discord.File(buf, filename=f"{game_id}_stats.json"))


@bot.command(name="importstats")
@adimin_check()
async def importstats(ctx, game_id: str, json_url: str):
    try:
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


@bot.command(name="makegame")
@adimin_check()
async def makegame(ctx, game_id: str, *teams: str):
    data = load_data()
    tournament = get_tournament(data, game_id)

    for team_name in teams:
        _, existing = get_team_by_name(tournament, team_name)
        if existing:
            continue
        team_id = str(uuid.uuid4())
        tournament["teams"][team_id] = {"team_name": team_name, "members": []}

    save_data(data)
    await ctx.send(f"✅ ゲーム '{game_id}' を作成しました。チーム: {', '.join(teams) if teams else 'なし'}")


@bot.command(name="gamestats")
async def gamestats(ctx, game_id: str):
    data = load_data()
    tournament = get_tournament(data, game_id)

    total_players = len(tournament.get("players", {}))
    total_teams = len(tournament.get("teams", {}))

    embed = discord.Embed(title=f"ゲーム '{game_id}' の概要", color=0xffa500)
    embed.add_field(name="プレイヤー数", value=total_players, inline=True)
    embed.add_field(name="チーム数", value=total_teams, inline=True)
    await ctx.send(embed=embed)


@bot.command(name="deletegame")
@adimin_check()
async def deletegame(ctx, game_id: str):
    data = load_data()

    if game_id not in data.get("tournaments", {}):
        await ctx.send(f"❌ ゲーム '{game_id}' が見つかりません。")
        return

    del data["tournaments"][game_id]
    save_data(data)
    await ctx.send(f"✅ ゲーム '{game_id}' とそのスタッツを削除しました。")


# 画像生成はまだ未実装のまま置いておく
@bot.command(name="image")
@adimin_check()
async def image(ctx, game_id: str, stat_type: str):
    await ctx.send(f"画像生成機能は未実装です (ゲーム: {game_id}, タイプ: {stat_type})。")


@bot.command(name="backimage")
@adimin_check()
async def backimage(ctx, game_id: str):
    await ctx.send(f"背景画像設定機能は未実装です (ゲーム: {game_id})。")

#コマンドが不明な場合のエラーハンドリング
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ コマンドが見つかりません。`!commands` で利用可能なコマンドを確認してください。")
    else:
        await ctx.send(f"❌ エラーが発生しました: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(".env に TOKEN がありません。例: TOKEN=xxxxxxxx")
  
    bot.run(TOKEN)
