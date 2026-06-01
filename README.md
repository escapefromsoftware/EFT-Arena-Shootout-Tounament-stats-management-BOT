# プロジェクト名　EFT:Arena Shootout Tounament stats management BOT

## 概要
このプロジェクトはEFT:ArenaのKDA,score,Average win timeをリザルト画面から自動的に集計し、
ゲーム内IDとDiscord Userと紐付けて結果を出力することができます。
また、結果のランキング、画像の生成を出力することができます。

## 使い方
Discordの以下の招待リンクからメッセージの送信、メッセージの管理、ファイル添付、メッセージ履歴を読む、全員宛にメンション
スラッシュコマンドを使用の権限を付けてサーバーに招待
https://discord.com/oauth2/authorize?client_id=1496700919071379537&permissions=6755916985120848&integration_type=0&scope=bot

ファイル構成は以下のように行ってください
project/
 ├ .env
 ├ main.py
 ├ Tounament_data_json(使用前はなくても可能)
.envは TOKEN = '{YOUR_TOKEN}'としてください。

!updateimageをする前にゲーム内ユーザー名とディスコードユーザー名を!setplayerで紐付けておいてください。
紐付けいないと正しくスタッツが保存されない可能性があります。

!commands - コマンド一覧を表示

!updateimage <game_id> - 画像添付からOCRでプレイヤーのKDAを読み取り更新
!updateimage <game_id>と同時にshoot outのリザルト画面をアップロードすることによってインゲームネームのプレイヤーにスタッツを加算します。(画像のアスペクト比は16:9にしてください。ほかの解像度の場合正しく読み取ることができません。)

!updatestats <game_id> <discord_ID> - プレイヤーのスタッツを手動で更新
!updateimageで更新できなかった内容を手動で更新することができます。

!setplayer <game_id> <discord_ID> <ingame_name> - プレイヤーのインゲーム名を設定

!unassign <game_id> <discord_ID> - プレイヤーのインゲーム名を解除

!playerstats <game_id> <discord_ID> - プレイヤーのスタッツを表示
discord_IDとインゲームネームと紐付けられたプレイヤーのスタッツを表示することができます。
※discord_IDとインゲームネームを!setplayerで紐付ける必要があります。

!resetkda <game_id> - トーナメント中の全プレイヤーのKDAをリセット

!resetdata <game_id> - トーナメントのデータをリセット

!rankings <game_id> <stat_type> - トーナメントランキングを表示
トーナメント中のスタッツのランキングを表示することができます。
※stat_typeはKDA、KILLS、SCORE、MVP、AVG_WIN_TIMEのいずれかを指定してください。

!addplayer <game_id> <discord_ID> - プレイヤーリストに追加

!removeplayer <game_id> <discord_ID> - プレイヤーリストから削除

!showplayers <game_id> - 参加プレイヤーのリストを表示

!resetstats <game_id> <discord_ID> - プレイヤーのスタッツをリセット
※事前に!setplayerでdiscord_ID紐付ける必要があります。

!teamstats <game_id> <team_name> - チームのスタッツを表示

!maketeam <game_id> <team_name> <player1> <player2> ... - 新しいチームを作成

!addteam <game_id> <team_name> <discord_ID> - チームにプレイヤーを追加

!deleteteam <game_id> <team_name> - チームを削除

!removeteam <game_id> <team_name> <discord_ID> - チームからプレイヤーを削除

!exportstats <game_id> - 現在のトーナメントスタッツをJSON形式でエクスポート

!importstats <game_id> <json_url> - JSON形式のスタッツをインポート

!image <game_id> <stat_type> - 特定のスタッツを表示する画像を生成
※現在未実装（いつかやる多分）

!backimage - !imageコマンドで使用する背景画像を設定
※現在未実装（いつかやる多分）

!makegame <game_id> <team1> <team2> ... - 新しいゲームを作成
game_idは大会名と一緒です。（例:OALと入れるとgame_idはOALです。）

!gamestats <game_id> - 特定のゲームのトーナメントスタッツを表示

!deletegame <game_id> - ゲームとそのスタッツを削除

　
様々なプログラミングコンテストに出す作品として考えていますので、積極的なフィードバックお待ちしています。
バグ修正やフィードバックはDiscord:@h1m4j1n_fps か X:@h1m4j1n_fps まで

-------------------------------------------------------------------------------------------
# 更新履歴

### ver 0.3.1
- β版に移行
- エラーメッセージを追加
- !updatestatsで一定時間レスポンスがないとタイムアウトする仕様に変更

### ver 0.3.0
KDAからKDに変更
AVG_WIN_TIMEを正確に読み取れるように変更
既に登録されたインゲームIDから候補を見つけ出し、スタッツを紐付けしやすいよう修正
ランキングまたはスタッツ出力で一人一人のK/Dを表示できるように
ランキングでチームごとのランキングを出力できるように

### ver 0.2.1
管理者権限の修正（大会に向けての緊急措置）

### ver 0.2.0
!debugocr,!checkimageを追加

### ver 0.1.0
!updateimageでOCRを利用したスタッツの自動更新をできる機能を実装
(正確性に欠けるため、ミスが生じた場合は手動でスタッツの変更をしてください)

### ver 0.0.2
Discord User nameとインゲームネームのリンクを解除する機能を実装

### ver 0.0.1
プロジェクト作成
大会プレイヤーの記録保存を実装
大会の作成、プレイヤーの追加、削除、Discord user nameを利用した名前のリンク機能を実装
プレイヤーのスタッツをリセット、チームを追加、削除、メンバーを追加、削除できる機能を実装
プレイヤーのスタッツを手動で変更できる機能を実装

-----------------------------------------------------
##　ロードマップ

### ver 0.4.0(6月上旬)
試合履歴
- 試合ごとの順位保存
- 試合ごとのKDA保存
- playerstats/teamstatsで直近5試合表示

### ver 0.5.0(6月中旬)
OCR確認
- 保存前確認
- 手動修正
- unknown player対応

### ver 0.6.0(6月下旬)
大会形式追加
- format: points_race / bracket
- participant_type追加
- scoring_rule追加

### ver 0.7.0(7月上旬)
BG対応
- bracket作成
- 勝敗報告
- 勝者自動進出
- ブラケット表示

### ver 1.0.0(7月中旬)
画像出力
- ランキング画像
- 試合順位画像
- プレイヤーKDA画像
- ブラケット画像

### ver 1.1.0(8月中)
Web版
- Web管理画面
- OCRアップロード
- 確認・修正
- ランキング/ブラケット表示

### ver 2.0.0(8月下旬)
EFT:Arena以外のゲームに対応
----------------------------------------------
credit:
プロジェクト長、BOT製作：H1m4j1N
協力:THEOZE,magutororo



