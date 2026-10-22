# 本家更新の要点（10行）

台帳: R-005 / R-026 / M-005 / M-011 / M-020。git上の静的照合と隔離測定を区別する。

1. tag `2026.10.22` は `15c00c54c9774c390bdafe332603292b506d76d2`。前回tag `2026.09.30.4` から723commit・587file。確認時のmasterは `bee6c8b7902e37ab45df33dcb74554cf5a593cdb` でtagより先。今回はtagを基準とする。
2. installer は `--mail keep` が既定。wrapperでも明示し、環境変数が `auto` でも稼働Mailを切り替えない。
3. `--mail update` は候補の隔離検証・DB backup後にbuildを切替。応答不良時に戻すのはbuildだけで、DBは自動で戻さない（`docs/agentstack-mail-update.md:124-145`）。
4. legacyの `db.py` は09.30.4から差分0。5e43de6からの明示DDL差分は `credential_generation INTEGER NOT NULL DEFAULT 0` 追加1行。Mail更新時には追加が必要になりうる。削除DDLではないが実DBへの適用・旧buildへの復帰は未測定。
5. namespace/globalの移行機能は追加されたが、CLIの `--global-config` 明示時だけglobal serverを起動する。通常のlegacyを維持し、今回の手順で有効化しない。
6. namespaceの移行試験は `activation: False`。candidateに新規書込みがあればrollbackを拒否し、forward fix/exportを要求する。今回この移行は行わない。
7. Codex子HOMEは既存hook信頼を同じworktreeや検証済み親HOMEから引継ぐ。所有者・mode・identity・proxy・lockを照合し、未承認hookを自動で信頼しない（`hooks/child_resume.py:1746`）。
8. spawn失敗cleanup・資格の削除・早期終了検知・resume/unretire・lock/lease回復が更新された。現行fleetは承認された世代別dispatcherを使うため、この本家側の改善は後続移植表に列挙する。
9. Codex apply_patchの予約guard、共通runtime client、base/tools選択と停止した子の道具変更が追加。既存のowner承認を省略して有効化しない。
10. dashboard APIは26。dsh/Hermes等のmanaged harness追加はopt-inで、今回のfleet更新で新しいprovider・資格・課金機能を導入しない。

## 後で移す物（head便35265）

| 本家改善 | 今回のfleetでの扱い | 後続の確認 |
|---|---|---|
| 失敗時のcleanupと資格の削除 | 本家coreを別pathで保存。既定は現行の世代所有権付き経路 | 古いcallbackが後継のtoken/state/paneを触れないことを本家coreへ移す |
| 早期終了の検知 | coreに保持、現行の起動判定を継続 | CLIの早期終了と成功判定の実process対照 |
| resumeとunretire | 本家の実装を保持。dispatcher起動世代のformal-state接続は未切替 | 古い三field stateからの同名・同資格の移行 |
| lockとleaseの回復 | 世代別releaseと本家の各実装を併存 | 再起動・SIGKILL・後継開始の競合対照 |

## 追加更新の提案

先にこのpayload更新を実端末で確認し、その後、稼働Mailのbuild更新を別の対話作業で検討する。本番DBのsnapshot互換性を検証してから、短い停止と各clientの再接続を含めて実行する。Codexのoptional予約guard/pluginは `/hooks` の人による確認が必要なので、別途現在の導入状態を確認する。native-TLS wrapperは今回保持し、解除はheadが修正版とネットワークの結果を確認した後とする。
