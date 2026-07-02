# プロジェクト名　EFT:Arena Shootout Tournament stats management BOT

## 概要
このプロジェクトはEFT:ArenaのKDA,score,Average win timeをリザルト画面から自動的に集計し、
ゲーム内IDとDiscord Userと紐付けて結果を出力することができます。
また、結果のランキング、画像の生成を出力することができます。

## データ保存
大会データは `tournament_data/<game_id>.sqlite` に大会ごとに分けて保存します。
中身はSQLiteデータベースです。
旧形式の `tournament_data.json` が残っている場合、初回起動時に各大会ファイルへ自動移行します。
`/exportstats` と `/importstats` は引き続きJSON形式で入出力できます。

## 使い方
Discordの以下の招待リンクからメッセージの送信、メッセージの管理、ファイル添付、メッセージ履歴を読む、全員宛にメンション
スラッシュコマンドを使用の権限を付けてサーバーに招待
https://discord.com/oauth2/authorize?client_id=1496700919071379537&permissions=6755916985120848&integration_type=0&scope=bot

/updateimageをする前にゲーム内ユーザー名とDiscordユーザーを/setplayerで紐付けておいてください。
紐付けいないと正しくスタッツが保存されない可能性があります。

/commands - コマンド一覧を表示

/updateimage <game_id> <image> [stage_name] - 画像からOCRでプレイヤーのKDAを読み取り更新
/updateimageのimage欄にshoot outのリザルト画面を指定すると、インゲームネームのプレイヤーにスタッツを加算します。(画像のアスペクト比は16:9にしてください。ほかの解像度の場合正しく読み取ることができません。)
stage_nameを指定すると、OCR結果の順位を参照して該当ステージの順位表も自動更新します。
points_raceでは/setpointsで設定した順位ポイントを加算します。
group_stage/swissでは1位を勝ち、それ以外を負けとして加算します。

/updatestats <game_id> <discord_user> <各スタッツ> - プレイヤーのスタッツを手動で更新
/updateimageで更新できなかった内容を入力欄から手動で更新できます。

/setplayer <game_id> <discord_user> <ingame_name> - プレイヤーのインゲーム名を設定

/unassign <game_id> <discord_user> - プレイヤーのインゲーム名を解除

/playerstats <game_id> <discord_user> - プレイヤーのスタッツを表示
Discordユーザーとインゲームネームを紐付けたプレイヤーのスタッツを表示できます。
※Discordユーザーとインゲームネームを/setplayerで紐付ける必要があります。

/resetkda <game_id> - トーナメント中の全プレイヤーのKDAをリセット

/resetdata <game_id> - トーナメントのデータをリセット

/rankings <game_id> <stat_type> - トーナメントランキングを表示
トーナメント中のスタッツのランキングを表示することができます。
※stat_typeはKDA、KILLS、SCORE、MVP、AVG_WIN_TIMEのいずれかを指定してください。

/addplayer <game_id> <discord_user> <ingame_name> - プレイヤーリストに追加

/removeplayer <game_id> <discord_user> - プレイヤーリストから削除

/showplayers <game_id> - 参加プレイヤーのリストを表示

/resetstats <game_id> <discord_user> - プレイヤーのスタッツをリセット
※事前に/setplayerでDiscordユーザーを紐付ける必要があります。

/teamstats <game_id> <team_name> - チームのスタッツを表示

/maketeam <game_id> <team_name> [user1...user8] - 新しいチームを作成

/addteam <game_id> <team_name> <discord_user> - チームにプレイヤーを追加

/deleteteam <game_id> <team_name> - チームを削除

/removeteam <game_id> <team_name> <discord_user> - チームからプレイヤーを削除

/exportstats <game_id> - 現在のトーナメントスタッツをJSON形式でエクスポート

/importstats <game_id> <json_url> - JSON形式のスタッツをインポート

/image <game_id> <ranking|match|player|team> [target] [@discord_user] - スタッツ画像を生成
image_typeには、作りたい画像の種類を指定します。
- ranking: ランキング画像。targetにKD/KDA/KILLS/SCORE/MVP/AVG_WIN_TIMEを指定
- match: 直近試合画像。targetに直近試合番号 1〜5 を指定
- player: プレイヤー成績画像。@discord_userに対象プレイヤーを指定。targetは不要
- team: チーム成績画像。targetにチーム名を指定
player/team画像では、ステージ順位表がある場合に全体暫定順位を表示します。
points_race形式では全体暫定順位に加えて所持ポイントも表示します。

例:
/image KCARZCUP ranking KD
/image KCARZCUP match 1
/image KCARZCUP player @username
/image KCARZCUP team TeamA

/backimage <game_id> <image> - /imageコマンドで使用する背景画像を設定
※1つのトーナメントにつき保存できる背景画像は1枚です。再設定すると上書きされます。

/makegame <game_id> [team1...team8] - 新しいゲームを作成
game_idは大会名と一緒です。（例:OALと入れるとgame_idはOALです。）

/addstage <game_id> <stage_name> <format> <advance_count> [group_count] - 大会ステージを追加
formatは points_race / single_elimination / double_elimination / swiss / group_stage を指定できます。
advance_countは次ステージへ進出する人数またはチーム数です。
group_stageの場合はgroup_countでグループ数を指定できます。

/setpoints <game_id> <stage_name> <points> - ステージの順位ポイントを設定
例: /setpoints KCARZCUP stage1 1:10,2:7,3:5,4:3

/seedbracket <game_id> <stage_name> <random|manual> [entries] - トーナメント表のシードを設定
randomでは登録済みチームまたはプレイヤーからランダムにシードを作成します。
manualではentriesに TeamA,TeamB,TeamC のように順番を指定します。

/showgameconfig <game_id> - 大会形式、ステージ、ポイント、シード設定を表示

/setstanding <game_id> <stage_name> <participant_name> [rank] [points] [wins] [losses] [status] - 順位表を更新
points_raceではpoints、group_stage/swissではwins/losses、トーナメント形式ではrank/statusを主に使用します。
例: /setstanding KCARZCUP stage1 TeamA 0 12 0 0
例: /setstanding KCARZCUP Swiss TeamA 0 0 3 1
例: /setstanding KCARZCUP Final TeamA 1 0 0 0 WINNER

/standings <game_id> <stage_name> [text|image] - ステージ順位を表示
画像出力は1枚20チームまで、最大80チームまで生成します。
左側に1〜10位、右側に11〜20位を表示します。

/gamestats <game_id> - 特定のゲームのトーナメントスタッツを表示

/deletegame <game_id> - ゲームとそのスタッツを削除

　
様々なプログラミングコンテストに出す作品として考えていますので、積極的なフィードバックお待ちしています。
バグ修正やフィードバックはDiscord:@h1m4j1n_fps か X:@h1m4j1n_fps まで

-------------------------------------------------------------------------------------------
# 更新履歴

### ver 0.6.0
- json管理からSQLite管理に変更
大会形式追加
- format: points_race / bracket
- participant_type追加
- scoring_rule追加

### ver 0.5.0
画像出力
- ランキング画像
- 試合順位画像
- プレイヤーKDA画像

### ver 0.4.3
/updateimageにてスタッツを保存するか否かを選択するよう変更しました。

### ver 0.4.2
- !コマンドから/コマンドに変更

### ver 0.4.1
- !commandsの文言を修正

### ver 0.4.0
- ファイル整理などをしてメンテナンスアップデートをしやすいように変更
- 試合履歴
- 試合ごとの順位保存
- 試合ごとのKDA保存
- playerstats/teamstatsで直近5試合表示

### ver 0.3.1
- β版に移行
- エラーメッセージを追加
- !updatestatsで一定時間レスポンスがないとタイムアウトする仕様に変更

### ver 0.3.0
- KDAからKDに変更
- AVG_WIN_TIMEを正確に読み取れるように変更
- 既に登録されたインゲームIDから候補を見つけ出し、スタッツを紐付けしやすいよう修正
- ランキングまたはスタッツ出力で一人一人のK/Dを表示できるように変更
- ランキングでチームごとのランキングを出力できるように変更

### ver 0.2.1
管理者権限の修正（大会に向けての緊急措置）

### ver 0.2.0
!debugocr,!checkimageを追加

### ver 0.1.0
- !updateimageでOCRを利用したスタッツの自動更新をできる機能を実装
(正確性に欠けるため、ミスが生じた場合は手動でスタッツの変更をしてください)

### ver 0.0.2
Discord User nameとインゲームネームのリンクを解除する機能を実装

### ver 0.0.1
- プロジェクト作成
- 大会プレイヤーの記録保存を実装
- 大会の作成、プレイヤーの追加、削除、Discord user nameを利用した名前のリンク機能を実装
- プレイヤーのスタッツをリセット、チームを追加、削除、メンバーを追加、削除できる機能を実装
- プレイヤーのスタッツを手動で変更できる機能を実装

-----------------------------------------------------
## ロードマップ

### ver 0.7.0(7月中旬)
BG対応
- bracket作成
- 勝敗報告
- 勝者自動進出
- ブラケット表示
- ブラケット画像

### ver 1.0.0(8月中)
Web版
- Web管理画面
- OCRアップロード
- 確認・修正
- ランキング/ブラケット表示

### ver 1.1.0(未定)
- OBSプラグイン追加

### ver 2.0.0(8月下旬)
EFT:Arena以外のゲームに対応

----------------------------------------------
### credit:
- プロジェクト長、BOT製作：H1m4j1N
- 協力:THEOZE,magutororo,KCARZ
