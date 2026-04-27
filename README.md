#プロジェクト名　EFT:Arena Shootout Tounament stats management BOT

##概要
このプロジェクトはEFT:ArenaのKDA,score,Average win timeをリザルト画面から自動的に集計し、
ゲーム内IDとDiscord Userと紐付けて結果を出力することができます。
また、結果のランキング、画像の生成を出力することができます。

##使い方
Discordの以下の招待リンクからメッセージの送信、メッセージの管理、ファイル添付、メッセージ履歴を読む、全員宛にメンション
スラッシュコマンドを使用の権限を付けてサーバーに招待
https://discord.com/oauth2/authorize?client_id=1496700919071379537&permissions=2147723264&integration_type=0&scope=bot

ファイル構成は以下のように行ってください
project/
 ├ .env
 ├ main.py
 ├ Tounament_data_json(使用前はなくても可能)
.envは TOKEN = '{YOUR_TOKEN}'としてください。

!commands - コマンド一覧を表示

!updateimage <game_id> - 画像添付からOCRでプレイヤーのKDAを読み取り更新
!updateimage <game_id>と同時にshoot outのリザルト画面をアップロードすることによってインゲームネームのプレイヤーにスタッツを加算します。
※現在正しく動作しないため使用不可

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
※現在未実装

!backimage - !imageコマンドで使用する背景画像を設定
※現在未実装

!makegame <game_id> <team1> <team2> ... - 新しいゲームを作成
game_idは大会名と一緒です。（例:OALと入れるとgame_idはOALです。）

!gamestats <game_id> - 特定のゲームのトーナメントスタッツを表示

!deletegame <game_id> - ゲームとそのスタッツを削除


バグ修正やフィードバックはDiscord:@h1m4j1n_fps か X:@h1m4j1n_fps まで

-------------------------------------------------------------------------------------------
##更新履歴

###0.1.0-alpha
!updateimageでOCRを利用したスタッツの自動更新をできる機能を実装

###0.0.2-alpha
Discord User nameとインゲームネームのリンクを解除する機能を実装

###ver 0.0.1-alpha
プロジェクト作成
大会プレイヤーの記録保存を実装
大会の作成、プレイヤーの追加、削除、Discord user nameを利用した名前のリンク機能を実装
プレイヤーのスタッツをリセット、チームを追加、削除、メンバーを追加、削除できる機能を実装
プレイヤーのスタッツを手動で変更できる機能を実装




