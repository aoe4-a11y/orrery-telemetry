### DeepSeek・Local を標準の子エージェント起動へ合流

DeepSeek・Local の選択したモデルと harness を catalog の能力で照合し、Claude・Codex と同じ `spawn_child.sh` へ渡します。モデル名から backend を推測せず、harness と backend を明示します。名前・親・作業場所・worktree・端末の選択と、名前による起動状況の確認は共通です。未指定の effort を試運転の値で補わず、別 helper の未対応指定は起動前に拒否します。

API generation を 22 から 23 へ更新します。標準 `/api/spawn` は DeepSeek・Local でも `child_name` / `tmux_session` を返し、managed attempt の応答を混ぜません。通常の catalog から managed 専用の表示項目を除きます。第1段階の経路の変更であり、runtime の受け入れや tool の開放の完了を示すものではありません。
