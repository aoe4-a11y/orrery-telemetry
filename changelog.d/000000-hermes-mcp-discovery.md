### Hermes の Mail tools を標準の MCP discovery につなぐ

Hermes の子で、起動時に Mail が configured と表示されても tools が登録されない問題を修正しました。選んだ MCP 設定を子の overlay に加え、native の起動判定が読む同じ private HOME の config.yaml にも生成します。選ばなかった server は無効にし、再選択・設定更新にも追随します。MCP 節以外の YAML、memory、HOME と resume の session ID は保持します。native 本体・導入世代・資格情報の guard と公開 API 世代は変更しません。
