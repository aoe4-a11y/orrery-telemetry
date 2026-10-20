### Ubuntu WSL 向けに非秘密の資格参照を共通化

明示した Secret Service の参照を dsh・Hermes・DeepSeek 残高に共通で渡す内部 reader と、Linux の静的な catalog 検査を追加しました。既存の Mac 設定は維持し、参照の競合や取得失敗で別の資格へ切り替えません。選択資格の直接抽出は既存 guard で拒否します。実 WSL の構築・認証・Mail・終了と再開は受け入れ前です。公開 login CLI、Windows bridge、設定の自動移行は追加しません。
