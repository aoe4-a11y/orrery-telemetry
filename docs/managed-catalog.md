# Native catalog and effort capabilities

runtime の任意導入は `install.sh --enable-dsh --dsh-node /absolute/node` / `--enable-hermes` で選びます。[導入と削除](install.md)を参照してください。

`dashboard.managed_catalog.standard_catalog(config_file, *, mode)` は標準 spawn の選択肢を返します。`hooks.harness_child.selection()` と同じ世代・設定の静的な検査を使い、model ごとに利用可能性と固定理由を返します。鍵・登録・provider API には接続しません。起動時にも共通 launcher が検査します。

provider ID は deepseek/strata、harness ID は dsh/hermes。manifest の同じ backend の正式 model を主と補助の候補に使い、generator の対応能力に従って公開します。未 opt-in は空配列、legacy 以外は unsupported_mode、Mac 以外は unsupported_platform です。私有 URL・account・実行 path を公開しません。

## effortの能力cache

manifestの手書きefforts/default_effortを能力の根拠にはしません。選択modelのharness entryがefforts/default_effort/effort_sourceを持ち、pickerと明示POSTの検証は同じentryを使います。未操作ではeffortを送らず、ハーネス既定を使います。provider共通配列は既定の利用可能harnessからの互換投影だけです。

install/updateは保存済み又は指定した manifestのmodelを対象に、固定Node・runtimeのローカルresolveModelInfoから段と既定を取得します。鍵・profile・discovery・モデルAPIを使わず、runtime世代のevidence/effort-capabilities.jsonへ保存します。runtime/modelが変わったcache・取得失敗はunknown（null/null/unknown）。選択肢だけを無効にし、未指定の起動を妨げません。opt-in offでは取得/投影しません。

dshの報告はsource=harnessで、Strataのserver報告ではありません。固定adapterの4段を自動取得し、Strataの公開sourceでmaxがhighと同じ段であることと、配置版を照合していないことを区別します。HermesのDeepSeek/Strata能力は初版unknownです。設定resolverの許容値からモデル能力を推測しません。

旧manifestやprivate backendに残る試行low/highは利用者設定の移行対象です。installerはprivate設定を無断書換せず、標準起動の未指定 effort 経路はこれらをハーネス既定として投影しません。
