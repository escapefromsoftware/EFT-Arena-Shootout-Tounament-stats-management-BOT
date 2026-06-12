"""
JSONデータの管理（読み書き）
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
import os
from config.settings import DATA_FILE


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
