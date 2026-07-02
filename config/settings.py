"""
OCRとゲーム設定の定数・座標定義
"""

import os
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv():
        return False
try:
    import pytesseract
except ModuleNotFoundError:
    pytesseract = None

# WindowsでTesseractを標準パスに入れている場合
# 環境変数 TESSERACT_CMD がある場合はそちらを優先
if pytesseract is not None:
    pytesseract.pytesseract.tesseract_cmd = os.getenv(
        "TESSERACT_CMD",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )

load_dotenv()
TOKEN = os.getenv("TOKEN")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(PROJECT_ROOT, "tournament_data.json")
TOURNAMENT_DATA_DIR = os.path.join(PROJECT_ROOT, "tournament_data")
TOURNAMENT_DB_EXTENSION = ".sqlite"
BOT_ADMIN_ID = [721546801743790110,1241016834791182377,907548165459296316]

# EFT:Arena リザルト画像OCR設定
# 元画像 1920x1080 を基準にした固定座標

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

# プレイヤー名OCR補正のしきい値
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
