"""
OCR処理用ユーティリティ関数
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import re
import asyncio
import pytesseract
from PIL import Image as PILImage, ImageOps, ImageFilter
from collections import Counter

from config.settings import BASE_W, BASE_H


def _coerce_text(value):
    """値をテキストに変換。コルーチンの場合は空文字列。"""
    if asyncio.iscoroutine(value):
        return ""
    return str(value or "")


def _safe_parse_int(text):
    """テキストから整数を安全に抽出。"""
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


def format_time(seconds):
    """秒数を MM:SS.mmm フォーマットに変換。"""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "0:00.000"

    minutes = int(seconds // 60)
    sec = seconds - minutes * 60
    return f"{minutes}:{sec:06.3f}"


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
    """同期的にOCR処理を実行。"""
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
    """非同期でOCR処理を実行。"""
    return await asyncio.to_thread(_ocr_crop_sync, image, box, config, field_type, scale)


async def read_cell(image, base_box, config, field_type="text", scale=4):
    """セルを読み取る（座標自動スケーリング付き）。"""
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
    """数字セルを読み取る（多数決）。"""
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
