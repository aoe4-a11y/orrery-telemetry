# Managed catalog（段1）

runtimeの任意導入は `install.sh --enable-dsh --dsh-node /absolute/node` / `--enable-hermes` でハーネスごとに選びます。未opt-inはruntime/adapterを取得せず、導入後も利用者のbackend/run-templateとavailability検査が揃うまで利用不可です。[導入と削除](install.md)を参照してください。

`dashboard.managed_catalog.catalog_providers(backends, availability, *, mode, enabled)`はA1のpublic metadataとbackend×harness準備状態から、既存providersへ追加する配列を返します。serverへの差し込みと実体/版/patchの準備判定はmanaged spawn controller側です。この関数はfile/API/鍵/登録へ触れません。

`load_catalog_inputs(config_file, *, mode)`はoperatorの私有manifestから(backends, availability, enabled)を返します。無指定/欠落/無効opt-inはoff、Mac以外はunsupported_platformです。runtime/template/model・製品helper/CLIを照合し、dshのNode版/固定package版/TUI patch hash、Hermesのcommitted interpreterを読み取ります。Nodeの版確認は鍵なしenvで`--version`を呼び、Hermesのtemplate継承は同じcommitted Pythonで既存の安全なprofile projectionを読取実行します（profile書込・key_cmd実行・provider importなし）。provider/Mail/Keychainへは接続しません。失敗理由は公開codeにし、私有参照やraw stderrをcatalogへ出しません。POST時のfull preflightを省略する証拠にはしません。

provider IDはdeepseek/strata、harness IDはdsh/hermes。既定無効は空配列、legacy以外は全harnessがunsupported_modeです。available=trueの最初のharnessをdefaultにし、準備できたものだけを選べます。起動時にもcontrollerが再検査します。

段1はcontext=null/context_source=unreported/context_note="Server-reported context not available yet"。runnerのconfigured_contextをserver報告へ昇格させません。補助はsameだけです。私有URL/account/実行pathなどはpublic応答にコピーしません。

無通信の確認：`python3 tests/test_managed_catalog.py`。4組、準備欠落、global拒否、既定切替、context未報告、私有参照非公開を確認します。

## effortの能力cache

manifestの手書きefforts/default_effortを能力の根拠にはしません。選択modelのharness entryがefforts/default_effort/effort_sourceを持ち、pickerと明示POSTの検証は同じentryを使います。未操作ではeffortを送らず、ハーネス既定を使います。provider共通配列は既定の利用可能harnessからの互換投影だけです。

install/updateは保存済み又は指定したmanaged manifestのmodelを対象に、固定Node・runtimeのローカルresolveModelInfoから段と既定を取得します。鍵・profile・discovery・モデルAPIを使わず、runtime世代のevidence/effort-capabilities.jsonへ保存します。runtime/modelが変わったcache・取得失敗はunknown（null/null/unknown）。選択肢だけを無効にし、未指定の起動を妨げません。opt-in offでは取得/投影しません。

dshの報告はsource=harnessで、Strataのserver報告ではありません。固定adapterの4段を自動取得し、Strataの公開sourceでmaxがhighと同じ段であることと、配置版を照合していないことを区別します。HermesのDeepSeek/Strata能力は初版unknownです。設定resolverの許容値からモデル能力を推測しません。

旧manifestやprivate backendに残る試行low/highは利用者設定の移行対象です。installerはprivate設定を無断書換せず、新しいmanagedの未指定effort経路はこれらをハーネス既定として投影しません。
