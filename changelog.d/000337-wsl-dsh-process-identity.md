### Linux の dsh が稼働中でも終了済みと表示される問題を修正

Linux で Node の process 名が `MainThread` になる場合も、pane の子孫にある dsh の生存判定を行います。実行引数が正規の dsh entry と一致することを引き続き必須とし、無関係な process や他の provider の判定は変えません。
