# ORRERY-UP-4: Claude Code 2.1.308 footer

台帳: R-005・R-102・M-011・M-020・R-095。

ORRERY-UP-3（4f7a3cf）の上に、live と同義の footer 判定を移植した。
作業中・入力待ちの実 pane fixture と旧 Claude／Codex の回帰試験を含む。
提供された作業中 fixture には spinner 行も残っている。この修正は
permissions-mode footer を composer の状態行として認識させるもの。
spinner が見えない footer 単体の作業判定は、この変更の検証範囲外。

head がレビュー後に対話実行する入口（この駅では実行しない）:

```bash
/bin/bash <(git -C /Users/huyuhutaru/tools/orrery-telemetry show fork/warmgauss/orrery-up-4-claude2308-footer:scripts/run-mail-fetch-upgrade-from-ref.sh)
```

事前に fork の当該 ref を fetch する。入口の source ref も同じ branch を指す。
UP3 の古い source root と衝突させないため UP4 専用 reuse-key と owner branch を使う。
installer の承認・Mail 更新・本物の再起動は head が R-102 に従って行う。
README、install、hooks、両 CLI の規約は確認し、導入操作の契約は変わらないため変更不要。
