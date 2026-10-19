### Fixed
- Claude・Codex の直接登録後の起動失敗で、停止と予約解放・retire を確認してから後片付けするようにしました。確認できない場合は復旧用の state・資格・worktree を残し、非0で終了します。
