# Seat lifecycle の限定配備と戻し方

これは配備手順であり、installer の実行許可ではありません。実施は head の再review後です。一般 installer・mail service の cutover・既存席の一括restartは使いません。

## 配備前

live の全payload差分表を更新し、未分類差分が0であることを確認します。生成設定・過去のmarketplace render・このinstallerが所有しないlocal工具はそのまま保持します。repoが先行するbranding/Windowsの差を古いliveへ戻しません。今回のmail-fetch/doctor/scientistsの取り込みは既にliveと同byteなので、同byteのfileは写しません。

headは新規spawnを一時止め、実行中launcherが0であることをPID・argv・lsofで確認します。dashboardの新規要求も止めます。変更対象ごとにliveの元path・SHA・modeを記録し、同じ暗号化volumeに独立fileのbackupを作って全SHAを照合します。期待SHAが変わっていれば、そのfileは上書きせず差分を読み直します。tokens・runtime・child home・env全体・global AGENTSは写しません。

## Stageとactivation

1. 候補commitを固定し、`$HOME/.agentstack/releases/seat-lifecycle/<commit>/hooks` に変更hookだけを置きます。少なくともspawn_child.sh・cleanup-child-agent.sh・seat_lifecycle.pyが対象です。未変更の依存hookは元のlive fileへ1fileずつsymlinkを置き、dirを丸ごとcopyしません。このreleaseは使用中に書き換えません。
2. 新しいseat_lifecycle.pyをglobal hooksにも追加し、set-ghostty-title.shの共通list lockとbin/lib/agentstack-register.shの名前lockを有効にします。**globalのcleanup-child-agent.shは旧byteのまま残します。** 既に動いている席の終端commandはこの旧pathを使い続けます。
3. 差分manifestで指定したbin helper・register lib・dashboard/server.pyだけを、backup照合後に同dirのtemporaryからatomic replaceします。未変更file・mail package・settingsの全体は上書きしません。env.shは既存exportを保持したまま、`AGENTSTACK_LIFECYCLE_HOOKS_DIR=<release>/hooks` の1keyだけをheadが追加します。新しいwrapper/restart/preregister/dashboardはこのkeyを優先します。
4. global spawn_child.shだけを、上記releaseを指定してexecする短いshimへ切り替えます。旧親がglobal pathを呼んでも新規spawnは新世代へ入ります。旧cleanupのpathは切り替えません。headがdashboardをその正確なserviceだけ再開してから、新規要求の停止を解除します。
5. 各destinationのSHA/mode、hook release、envの他key不変、旧cleanupのSHA不変を照合します。新規の合成席で両providerの起動・遅延終了・同名restartをheadの承認範囲で通し、既存席が旧cleanupを使うことも確認します。このlive検査は作者の隔離fixtureでは代用しません。

## Rollback

新規spawnを止めてlauncherが0と確認し、global spawn shim・dashboard・wrapperの入口を照合済みbackupへ戻します。envの上記1keyだけを以前の有無/値へ戻し、他keyは変えません。必要な正確なdashboard serviceだけを再開します。token/state/homeは戻したり消したりしません。

新世代で既に起動した席はrelease内のcleanupを参照しています。そのrelease・module・互換性を保つregister/list writerを、席が使っている間は残します。全ての依存が終わりheadが旧世代への復帰を受理した後だけ、残るglobal変更を元byteへ戻します。旧cleanup・旧env・旧source・backup・記録を消す操作は、この手順にありません。

今回の作者が実行した範囲はsource編集と隔離検査までです。stage・activation・liveでの通し起動は未実施です。
