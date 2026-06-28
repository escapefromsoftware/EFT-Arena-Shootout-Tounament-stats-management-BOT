"""
/image 用の画像生成処理
"""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from data.match_manager import get_recent_matches
from data.player_manager import ensure_player_defaults


PROJECT_ROOT = Path(__file__).parent
BACKGROUND_DIR = PROJECT_ROOT / "backgrounds"
CANVAS_W, CANVAS_H = 1920, 1080


def format_time(seconds):
    """秒数を MM:SS.mmm フォーマットに変換。"""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "0:00.000"

    minutes = int(seconds // 60)
    sec = seconds - minutes * 60
    return f"{minutes}:{sec:06.3f}"


def _safe_game_id(game_id):
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(game_id))


def get_background_path(game_id):
    return BACKGROUND_DIR / f"{_safe_game_id(game_id)}.png"


def save_background_image(game_id, image_bytes):
    """大会ごとの背景画像を1枚だけ保存する。既存画像は上書き。"""
    BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image.save(get_background_path(game_id), format="PNG")


def _font(size, bold=False):
    font_names = [
        r"C:\Windows\Fonts\yumindb.ttf" if bold else r"C:\Windows\Fonts\yumin.ttf",
        r"C:\Windows\Fonts\YuGothB.ttc" if bold else r"C:\Windows\Fonts\YuGothR.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
    ]
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _default_background():
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), (20, 18, 18))
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(CANVAS_H):
        shade = int(36 - (y / CANVAS_H) * 18)
        draw.line((0, y, CANVAS_W, y), fill=(shade, shade - 3, shade - 2, 255))

    for i in range(80):
        x1 = (i * 97) % CANVAS_W
        y1 = (i * 53) % CANVAS_H
        x2 = x1 + 260 + (i % 7) * 35
        y2 = y1 - 190 - (i % 5) * 18
        alpha = 18 + (i % 5) * 6
        draw.line((x1, y1, x2, y2), fill=(120, 132, 128, alpha), width=2)

    draw.ellipse((1280, -260, 2240, 520), fill=(4, 3, 3, 120))
    return image.filter(ImageFilter.GaussianBlur(0.6))


def _load_background(game_id):
    path = get_background_path(game_id)
    if path.exists():
        image = Image.open(path).convert("RGB")
    else:
        image = _default_background()
    return image.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS).convert("RGBA")


def _text_size(draw, text, font):
    box = draw.textbbox((0, 0), str(text), font=font)
    return box[2] - box[0], box[3] - box[1]


def _center_text(draw, xy, text, font, fill=(235, 238, 238, 255)):
    x, y, w, h = xy
    tw, th = _text_size(draw, text, font)
    draw.text((x + (w - tw) / 2, y + (h - th) / 2), str(text), font=font, fill=fill)


def _left_fit_text(draw, xy, text, font, fill=(235, 238, 238, 255)):
    x, y, w, h = xy
    text = str(text)
    while _text_size(draw, text, font)[0] > w and len(text) > 3:
        text = text[:-4] + "..."
    _, th = _text_size(draw, text, font)
    draw.text((x, y + (h - th) / 2), text, font=font, fill=fill)


def _base_canvas(game_id, title):
    image = _load_background(game_id)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.rectangle((0, 0, CANVAS_W, CANVAS_H), fill=(0, 0, 0, 105))
    draw.rounded_rectangle((210, 155, 1710, 980), radius=18, fill=(8, 11, 13, 178), outline=(230, 190, 84, 120), width=2)
    image.alpha_composite(overlay)

    draw = ImageDraw.Draw(image, "RGBA")
    _center_text(draw, (0, 34, CANVAS_W, 56), game_id, _font(52, bold=True), (246, 216, 112, 255))
    _center_text(draw, (0, 112, CANVAS_W, 44), title, _font(30, bold=True), (230, 235, 235, 255))
    return image, draw


def _finalize(image):
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_table(draw, x, y, columns, rows, row_h=54, row_text_colors=None):
    header_font = _font(24, bold=True)
    row_font = _font(25)
    line_color = (246, 216, 112, 70)
    header_color = (246, 216, 112, 255)
    text_color = (236, 240, 240, 255)
    table_width = sum(width for _, width, _ in columns)

    draw.rounded_rectangle(
        (x - 2, y - 2, x + table_width + 2, y + row_h * (len(rows) + 1) + 2),
        radius=8,
        fill=(5, 8, 10, 185),
        outline=(246, 216, 112, 80),
        width=1,
    )
    draw.rectangle((x, y, x + table_width, y + row_h), fill=(34, 31, 22, 220))
    cx = x
    for label, width, align in columns:
        if align == "left":
            _left_fit_text(draw, (cx + 16, y, width - 24, row_h), label, header_font, header_color)
        else:
            _center_text(draw, (cx, y, width, row_h), label, header_font, header_color)
        cx += width

    for index, row in enumerate(rows):
        ry = y + row_h * (index + 1)
        row_fill = (15, 19, 21, 205) if index % 2 == 0 else (8, 12, 14, 175)
        draw.rectangle((x, ry, x + table_width, ry + row_h), fill=row_fill)
        draw.line((x, ry, x + table_width, ry), fill=line_color, width=1)
        current_text_color = (
            row_text_colors[index]
            if row_text_colors and index < len(row_text_colors) and row_text_colors[index]
            else text_color
        )
        cx = x
        for col_index, (_, width, align) in enumerate(columns):
            value = row[col_index]
            if align == "left":
                _left_fit_text(draw, (cx + 16, ry, width - 24, row_h), value, row_font, current_text_color)
            else:
                _center_text(draw, (cx, ry, width, row_h), value, row_font, current_text_color)
            cx += width


def _player_display(player):
    player = ensure_player_defaults(player)
    return player.get("ingame_name") or str(player.get("discord_id") or "N/A")


def _player_team_name(tournament, player):
    team_id = ensure_player_defaults(player).get("team_id")
    if not team_id:
        return "-"
    return tournament.get("teams", {}).get(team_id, {}).get("team_name") or "-"


def _stat_value(player, stat_type):
    player = ensure_player_defaults(player)
    stat = stat_type.upper()
    if stat == "KD":
        return player["kills"] / max(player["deaths"], 1)
    if stat == "KDA":
        return (player["kills"] + player["assists"]) / max(player["deaths"], 1)
    if stat == "KILLS":
        return player["kills"]
    if stat == "SCORE":
        return player["score"]
    if stat == "MVP":
        return player.get("rounds_MVP", 0) + player.get("Matches_MVP", 0)
    if stat == "AVG_WIN_TIME":
        return -float(player.get("AVG_WIN_time", 0) or 0)
    return player["kills"] / max(player["deaths"], 1)


def render_ranking_image(tournament, game_id, stat_type):
    stat = (stat_type or "KD").upper()
    image, draw = _base_canvas(game_id, f"{stat} Ranking")
    players = [ensure_player_defaults(player) for player in tournament.get("players", {}).values()]
    players.sort(key=lambda player: _stat_value(player, stat), reverse=True)

    rows = []
    for rank, player in enumerate(players[:10], 1):
        kd = player["kills"] / max(player["deaths"], 1)
        value = format_time(player.get("AVG_WIN_time", 0)) if stat == "AVG_WIN_TIME" else f"{_stat_value(player, stat):.2f}"
        if stat in ("KILLS", "SCORE", "MVP"):
            value = str(int(_stat_value(player, stat)))
        rows.append([
            rank,
            _player_display(player),
            _player_team_name(tournament, player),
            f"{player['kills']}/{player['deaths']}/{player['assists']}",
            player.get("score", 0),
            player.get("rounds_MVP", 0) + player.get("Matches_MVP", 0),
            f"{kd:.2f}",
            value,
        ])

    columns = [
        ("Rank", 110, "center"),
        ("Player", 360, "left"),
        ("Team", 230, "left"),
        ("K/D/A", 170, "center"),
        ("Score", 120, "center"),
        ("MVP", 105, "center"),
        ("KD", 105, "center"),
        (stat, 200, "center"),
    ]
    rank_colors = [
        (255, 215, 88, 255),
        (214, 222, 228, 255),
        (205, 127, 50, 255),
    ]
    table_x = (CANVAS_W - sum(width for _, width, _ in columns)) // 2
    _draw_table(draw, table_x, 230, columns, rows, row_text_colors=rank_colors)
    return _finalize(image)


def render_match_image(tournament, game_id, match_number):
    matches = get_recent_matches(tournament)
    match = matches[match_number - 1]
    image, draw = _base_canvas(game_id, f"Recent Match #{match_number}")

    rows = []
    for team in match.get("teams", []):
        players = team.get("players", [])
        player_names = " / ".join(player.get("ingame_name", "N/A") for player in players)
        kills = sum(player.get("kills", 0) for player in players)
        deaths = sum(player.get("deaths", 0) for player in players)
        assists = sum(player.get("assists", 0) for player in players)
        mvp = sum(player.get("rounds_MVP", 0) for player in players)
        rows.append([
            team.get("rank", ""),
            team.get("team_name") or f"Team {int(team.get('team_index', 0)) + 1}",
            player_names,
            mvp,
            f"{kills}/{deaths}/{assists}",
            format_time(team.get("avg_win_time", 0)),
            team.get("score", 0),
        ])

    columns = [
        ("Rank", 120, "center"),
        ("Team", 220, "left"),
        ("Players", 470, "left"),
        ("MVP", 120, "center"),
        ("K/D/A", 180, "center"),
        ("AVG_WIN_TIME", 220, "center"),
        ("Score", 130, "center"),
    ]
    _draw_table(draw, 250, 210, columns, rows, row_h=72)
    return _finalize(image)


def _team_member_names(tournament, team_id):
    members = []
    for player_id, player in tournament.get("players", {}).items():
        player = ensure_player_defaults(player)
        if player.get("team_id") == team_id:
            members.append(_player_display(player))
    return members


def _draw_recent_results(draw, title, recent_results, x=980, y=300):
    draw.text((x, y - 54), title, font=_font(30, bold=True), fill=(246, 216, 112, 255))
    columns = [
        ("#", 70, "center"),
        ("Rank", 110, "center"),
        ("K/D/A", 180, "center"),
        ("Score", 120, "center"),
        ("MVP", 100, "center"),
    ]
    rows = []
    for index, result in enumerate(recent_results, 1):
        rows.append([
            index,
            result.get("rank", "-"),
            f"{result.get('kills', 0)}/{result.get('deaths', 0)}/{result.get('assists', 0)}",
            result.get("score", 0),
            result.get("rounds_MVP", "-"),
        ])
    if not rows:
        rows.append(["-", "-", "No data", "-", "-"])
    _draw_table(draw, x, y, columns, rows, row_h=58)


def render_player_image(tournament, game_id, player_id, player, recent_results):
    player = ensure_player_defaults(player)
    image, draw = _base_canvas(game_id, "Player Stats")

    team_name = "未所属"
    team_id = player.get("team_id")
    if team_id:
        team_name = tournament.get("teams", {}).get(team_id, {}).get("team_name", "未所属")
    members = _team_member_names(tournament, team_id) if team_id else []

    draw.text((300, 238), _player_display(player), font=_font(48, bold=True), fill=(246, 216, 112, 255))
    rows = [
        ("ingame_name", player.get("ingame_name", "")),
        ("kills", player.get("kills", 0)),
        ("deaths", player.get("deaths", 0)),
        ("assists", player.get("assists", 0)),
        ("score", player.get("score", 0)),
        ("rounds_MVP", player.get("rounds_MVP", 0)),
        ("Matches_MVP", player.get("Matches_MVP", 0)),
        ("AVG_WIN_time", format_time(player.get("AVG_WIN_time", 0))),
        ("matches_played", player.get("matches_played", 0)),
        ("teammember", ", ".join(members) if members else team_name),
    ]
    _draw_table(draw, 300, 320, [("Item", 260, "left"), ("Value", 360, "left")], rows, row_h=52)
    _draw_recent_results(draw, "Recent 5 Matches", recent_results)
    return _finalize(image)


def render_team_image(tournament, game_id, team_id, team, recent_results):
    image, draw = _base_canvas(game_id, "Team Stats")
    members = []
    for player_id in team.get("members", []):
        player = tournament.get("players", {}).get(player_id)
        if player:
            members.append(ensure_player_defaults(player))

    kills = sum(player.get("kills", 0) for player in members)
    deaths = sum(player.get("deaths", 0) for player in members)
    assists = sum(player.get("assists", 0) for player in members)
    score = sum(player.get("score", 0) for player in members)
    rounds_mvp = sum(player.get("rounds_MVP", 0) for player in members)
    matches_mvp = sum(player.get("Matches_MVP", 0) for player in members)
    matches_played = sum(player.get("matches_played", 0) for player in members)
    avg = sum(float(player.get("AVG_WIN_time", 0) or 0) for player in members) / max(len(members), 1)

    draw.text((300, 238), team.get("team_name", "N/A"), font=_font(48, bold=True), fill=(246, 216, 112, 255))
    rows = [
        ("team_name", team.get("team_name", "")),
        ("kills", kills),
        ("deaths", deaths),
        ("assists", assists),
        ("score", score),
        ("rounds_MVP", rounds_mvp),
        ("Matches_MVP", matches_mvp),
        ("AVG_WIN_time", format_time(avg)),
        ("matches_played", matches_played),
        ("teammember", ", ".join(_player_display(player) for player in members) or "なし"),
    ]
    _draw_table(draw, 300, 320, [("Item", 260, "left"), ("Value", 360, "left")], rows, row_h=52)
    _draw_recent_results(draw, "Recent 5 Matches", recent_results)
    return _finalize(image)
