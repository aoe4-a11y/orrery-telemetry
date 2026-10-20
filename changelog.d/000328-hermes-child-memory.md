### Hermes の子ごとに記憶の保存先を分離

新しい Hermes の子は project と正式な名前で決まる永続 HOME を使い、別の子の
MEMORY/USER を共有しません。同じ identity の標準 resume は保存 HOME と正確な
native session ID を維持します。共通の記憶・認証・利用者設定はコピーせず、
通常の exit で子 HOME を削除しません。

旧共有 HOME の resume は理由付きで停止し、旧データを保持します。適用には旧 resume
中断の明示了承が必要です。HOME/pin の検査は resume 設定の更新より先に行います。
実 CLI での記憶の復帰は、会話履歴とは分けて受け入れ確認します。
