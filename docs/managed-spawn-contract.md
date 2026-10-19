# Managed spawn — 継続対話の要求と応答（I0）

この文書は対話の段で実装する契約。`provider=deepseek|strata` と `harness=dsh|hermes` の既定無効を維持し、既存Claude/Codex/Geminiの要求・登録・応答は変更しない。provider/model/harnessは別々に保持する。

**移行中:** 現在の一回実行のcontrollerが本契約へ移行するまで、未接続の機能をavailable/readyへ昇格させない。契約先行の区切りであり、このdocsだけで対話が動作済みという意味ではない。

## 1. 全経路の不変条件

- dsh/Hermesとも親あり／なしでnative対話。task報告・turn終了では停止しない。人/親のclose/retire・native自然終了・異常終了でのみfinalize。
- parent=null を正式に許可。operator agentを作らない。親whoisの起動前照合だけ省略。runtimeのretire確認はdashboard既存read contextで同じ子のwhoisを照合。
- 未指定の要求数・出力上限・effortはハーネス既定。試しrun-configで明示した上限は正整数を検査して適用。8要求・4096出力・660秒の対話寿命を既定にしない。個々の要求timeoutとruntime寿命を混ぜない。
- 選択backend以外の推論/補助通信を拒否。DeepSeekの受入はDeepSeekの許可endpoint、Strataは設定したStrataの許可endpoint＋必要な製品Mailのみで実施する。他backendのURLを使った観測を受入にしない。

## 2. public POST /api/spawn（flatの互換拡張）

新規field: task_mode="conversation"|"assignment"、report_policy="pane"|"mail"。
共通必須は attempt_id UUID、provider、model、harness、dir。async/worktreeは現行どおりtrueのみ。parentは文字列又はnull/省略、standaloneは親なしを表す既存field。

正規化規則:
1. standalone=trueならparentはnull（非空parentを同時指定ならcontradictory_parentで拒否）。standalone=false明示かつparentが空ならmissing_parent。両方省略かparent=nullならstandalone=true。
2. task_mode省略はexpected非空ならassignment、それ以外はconversation。task文字列は省略/空をconversationで許可、assignmentでは非空必須。
3. conversationはallowed_paths/expected省略を許可。allowed_pathsを渡す場合は初期コピーする既存literal相対fileの一覧（従来のpath検査を維持）。実行時の編集範囲は私有worktree全体。expectedを非空にして曖昧に混ぜずassignmentを使う。
4. assignmentはpromptのみ必須。allowed_paths/expectedは省略又は空を許す。scope指定時はexpectedのpathもscope内、scopeなしなら選んだworktree内のliteral相対pathとしてcontains/sha256を検査する。root外・.git・../等は拒否する。
5. report_policy省略はassignmentかつparentありならmail、それ以外はpane。正式taskのmail報告には実在するparent必須。ただしこれは成功判定の必須宛先であって、通常のMail送信の権限ではない。親なしでも任意の実在agentへの連絡を許す。conversationのmailは正式完了条件を作らない。
6. effort未指定はkeyを送らない。明示したときだけ選択model×harnessの能力cacheと照合。provider共通の手書き配列では検証しない。

親なしの普段の対話例:
```json
{"attempt_id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","provider":"strata","model":"configured-model","harness":"dsh","standalone":true,"task_mode":"conversation","report_policy":"pane","dir":"/source","worktree":true,"async":true}
```

親ありの正式な委任は従来のflat task/allowed_paths/expectedにtask_mode=assignmentを加える（省略時も推論）。報告後も同runtimeが次入力を待つ。

初期の私有worktreeとfileコピー方式は現行を維持する。conversationでコピー一覧なしなら空の私有作業dirから始める。UIは実際のworktreeを表示する。元sourceを直接編集しているように表示しない。会話だけでrootを外へ広げない。全repoコピー/元dirへの自動書戻しはこの契約へ黙って足さない。

## 3. status（GET attempt_idの形は維持）

既存state=pending|ready|failed、phase、finished、running、task_success/runtime_success/cleanup_successを維持し、次を追加する:
- task_mode、report_policy、parent（null可）、worktree（実私有作業dirの絶対path、生成前はnull）
- activity="starting"|"thinking"|"idle"|"stopping"|"exited"（分からなければnull）
- task_evaluation="not_applicable"|"pending"|"reported"|"failed"
- latest_turn={id,completed,at}又はnull（nativeイベントがある場合だけ）
- capabilities={interactive:true,followup_via_pane:true,followup_via_mail:false}（自動Mail配送の接続前）

conversationはtask_success=null/task_evaluation=not_applicable。assignmentのreported/failedは報告の評価で、finished=false/running=trueのまま。task失敗をruntime失敗と混同しない。終了後はruntime/cleanupが成功ならconversationをtask_success欠如だけでstate=failedにしない。ready/worker exit0をtask成功とは表示しない。

文言: “Additional instructions via pane; Mail supports reports only.”（日本語相当: paneから追加指示可、Mailは送信報告まで）。

## 4. adapterのJSON境界（既存prepare signatureは維持）

prepare(...,parent=None,task=...)のtask拡張:
```json
{"prompt":"","task_mode":"conversation","report_policy":"pane","allowed_paths":[],"expected":[]}
```
runnerのrun-configにもtask_mode/report_policy/parentを保存し、attempt.jsonは既存phase=runのまま（対話用の偽spike phaseは作らない）。task.jsonは同attempt/task IDとworktree、report_to=null可、scope_mode=worktree|filesを持つ。assignmentは宣言したscopeがあるときfiles、未指定ならworktree。conversationもworktree。conversationは起動時に架空の予約receiptを作らない。

status(state)はterminalをruntime-exitのみから判定（turn-endではfalse）。readyは実process一致plugin-ready＋full preflightのまま。task_successはterminalまで待たず、正式assignmentの証拠がそろった時点で返す。task報告後もterminal=false。
finalize(state,parent_call=...)のparent_callは名前互換のcallback引数として残してよいが、意味はdashboardのread-only whois。親なしでも必須の同じ照合を行う。

各正式assignmentの確定報告は task-reports/<task_id>.json に当時のturn/成果物hash/usage/送信receipt参照と判定を保存し、以後の自由対話で再評価・上書きしない。reported後のturnは新assignmentが投入されるまではtaskなしとして扱い、同じtask_idの新しいturnが古い完了証拠へ混ざらない。plugin-ready/readyはattempt単位、task報告はtask_id単位を照合する。追加の正式委任だけ新しいtask_idを発行する。

親なしでもsend_message/fetch_inbox等、同じ製品child_toolsが生成するClaude/Codex相当のMail toolを渡す。report_policy=paneは完了判定でMailを必須にしない意味だけで、tool権限は削らない。send_messageの宛先をparentだけへ制限するguardを外す。正式taskの完了判定時にだけ指定report_toへのverified receiptを照合する。初期roster/egressのwire_toolsはread/write＋実際に生成された製品Mail schemaの集合で照合し、古い3件固定にしない。予約のtrusted管理経路も同じ製品proxyを使う。

completion第5条件:
- conversation: task全体が適用外。success=null、evaluation=not_applicable、mail_receipt=not_applicable。
- assignment/pane: binding/turn/providerを必須、artifactはexpected指定時だけ適用、第5はnot_applicable。checksに文字列を入れてtruthy成功にせずapplicable_checksを明示して集計する。
- assignment/mail: 既存のverified server send receipt必須。親captureが存在すれば両方一致必須。
- 旧taskにmode/policyが無いときはassignment/mailとして読取互換。新旧のruntime cleanupの証拠条件は同じ。

## 5. 動的予約・終了証拠

private copyでの暫定予約名は `_managed_workspaces/<attempt_id>/<relative-file>`。ledgerに実worktree内のrelative_pathを併記する。実sourceを予約した証拠にはせず、実dir/git worktree対応時は既存子のpath規則へ統合する。

conversationはroot内read、writeはexact fileごとの製品reserve/renew→receipt検証→同期guard→実行→release。assignmentは宣言scopeも重ねる。モデル自身に予約の有無を判断させずtrusted管理処理にする。
新しいreceiptsは同attemptのreservation-ledger.jsonへ記録（agent_name、attempt_id、receipts、released_ids）。receipt行は製品id/path_pattern/expires_ts/ownerそのまま。ledgerを空で作成しても「実予約があった」とは記録しない。既存taskの起動時receiptとledgerの実ID集合をruntime評価でまとめ、成功確認済みのreleaseだけを差し引く。
レコードのsourceはproduct-bound-proxy。終了時のrelease-receiptは実際に取得したID全集合と実released_ids、confirmedを記録。task_successと無関係に回収する。

retire-receiptは旧parent-bound-whoisと新dashboard-bound-whoisの両方を読めるが、新規controllerのwhois証拠は後者。同attempt/agent/cleanup_exit_code/retired_at/confirmedの照合を維持。親owner tokenや新Mail transportは不要。

## 6. I5能力cache（能力取得との接続）

非秘密cacheはversion/runtime hash/model/harness/source/取得時刻、efforts/default_effortを含む。dshはresolveModelInfo由来、Hermesの設定resolverはmodel×route能力の証明ではない。初版DeepSeek/Strataはsource=unknown、efforts/default_effort=nullとし推測しない。Strataはsource=harnessでserver報告と表示しない。catalogはmodel.harnesses[]の各entryへefforts/default_effort/effort_sourceを投影し、UIは選んだharnessの値を使う。古いprovider共通値は互換用でありmanaged POSTの根拠にしない。default_effortが分かっても未操作のUIはeffortを送らない。
loaderは dashboard.managed_capabilities.load_effort_capability(template, *, harness, backend_id, model)。戻り値は efforts/default_effort/effort_source の3field（unknownはnull/null/unknown）。catalogとPOSTは同じharness entryを検査する。

## Mode ごとの互換（Hermes 対話の結合前）

各 model.harnesses[] は `interactive: bool` と `task_modes` を持つ。`task_modes` は conversation/assignment を key とし、値は available/reason/requires_parent/requires_scope/requires_expected/report_policies。旧 Hermes の conversation だけ available=false、reason=interactive_not_ready。assignment は既存どおり available=true、requires_parent=true、report_policies=[mail] として残す。controller はこの経路に限り task 入力を prompt/allowed_paths/expected の3fieldへ投影する。親なし又は pane 報告の assignment は対応前として登録前に拒否する。

I1 dsh と I2 完了後の Hermes は両 mode が available、requires_parent=false、report_policies=[pane,mail]。ただし mail を task の完了条件にする場合は report_to の親を必要とする。通常の Mail tool の権限を mode で削らない。

親なしの正式な Mail 報告は、実在する宛先を利用者が明示し whois で確認する形を後続で受け付ける。最小段ではその report_to 選択は未対応であり、mail を完了条件にする経路は親への報告だけ。これは互換上の暫定で、恒久的な親必須仕様ではない。親なしの通常 send_message は既に許可し、pane 報告で起動できる。

新dshの各modeは requires_scope=false・requires_expected=false。旧Hermes assignmentだけ両方trueを公開する。assignmentのexpectedがありallowed_paths=[]なら、expected.pathはworktree内のliteral相対pathとして検査する。成果物検査の未指定は適用外であり、架空の成果物成功に置き換えない。
