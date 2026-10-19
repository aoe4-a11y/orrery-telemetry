### 旧 managed 経路の削除

- API 25: 旧 `attempt_id` による起動要求と `spawn-status` の attempt 照会を廃止しました。専用の managed controller と、usage 必須・通信先制限を含む旧 dsh/Hermes runtime 層を削除しました。DeepSeek と Local は標準の起動、名前による状態照会、native resume、共通の後片付けを使います。
