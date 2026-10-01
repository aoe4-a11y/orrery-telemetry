# ORRERY-UP-1 改造対応表

台帳: R-005 / R-026 / R-061 / R-062 / R-068 / M-011 / M-018 / M-020。

採録時の owned は252件。e5039ffとの同名照合で7件差分・55件同名なし（owned .bak 4件を含めた生の同名なしは59件）。aliasを辿ると生成wrapper・旧optional sourceが含まれる。全307行を下に列挙する（stack内owned247件と外部owned5件を含む）。code/config .bak は37件（spawn8、supervisor13を含む）、env .bakは4件。失効した古い世代をすべて同時に動かすことはせず、現行コードの累積差分を移植し、旧世代bytesは復元可能な形で残した。

sandbox override の移植は701b298以降で、modern spawn/resume/service環境まで同じ明示設定を渡す。

forkだけの4 commit（81c3fd9 / cd092c4 / 5e43de6 / e5039ff）は a4830d5 のmerge ancestryで保持。hook trustのconfig生成は hooks/child_resume.py へ移した。

## 実装単位

| live file | 改造と扱い | 移植commit |
|---|---|---|
| `hooks/spawn_child.sh` | full permissions / R-061 / R-062 / Opus5.5 / Sonnet5.5 / uppercase footer / update dialog / canonical token 保護 / Codex0.159 trust を移植。token-only restart は361de55で認証済み binding に接続。 | a4830d5 + ef51345 |
| `hooks/watch_agent_mail_signals.sh` | ProudTuring/PinkTesla 宛 signal を終了、session無し24時間超のsignalを終了。新しい lease-owner と persistent-headless 経路は保持。 | a4830d5 + ef51345 |
| `hooks/settings.template.json` | R-068 send-message lint と Workflow usage warning を保持。固定HOMEは __AGENTSTACK_HOOKS_DIR__ へ戻してinstall先に展開。 | a4830d5 + ef51345 |
| `bin/lib/agentstack-scientists.sh` | AdjectiveScientist 形式（hyphen無し）を保持。 | a4830d5 + ef51345 |
| `bin/agentstack-doctor` | P-016 tmux TCC probe を保持。 | a4830d5 + ef51345 |
| `bin/agentstack-restart-seat` | 既定 gpt-6.1-sol。既存名・token を維持し、認証が失敗した場合は既存paneを kill しない。 | 361de55 + ef51345 |
| `bin/agentstack-spawn-codex` | 例示を gpt-6.1-sol に更新。事前登録・embed task など現行の動作は保持。 | a4830d5 + ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/mcp_server.py` | inbox limit 1000 をbranchのcore sourceに移植。古いコピーに無かったwhois・新しいagent_id照合は本家のものを保持。 | a4830d5 + ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/agent_mail_client.py` | CONTACT_REQUIRED等のserver errorを見せる改造は本家 _safe_error_text が同じ目的を実装済み。600字制限・secret redaction付きの本家側を採用。 | a4830d5 + ef51345 |

## 全件

本家で既に実装済みの error 表示は tag `2026.09.30.4` の
`integrations/codex_app/src/agentstack_codex_app/agent_mail_client.py:381-411` にある。
該当箇所は `_ERROR_TEXT_LIMIT = 600`、
`text = _SECRET_LIKE.sub("[redacted]", text.splitlines()[0])`、
`return f"ORRERY Mail tool call failed: {text}"`。
このため旧コピーの無制限の error 本文表示は再導入せず、本家の表示・redaction を使用する。

| installed file | owned | 採録 SHA-256 | 対応source / 保存先 | 扱い / commit |
|---|---|---|---|---|
| `VERSION` | yes | `9d8c94f1ad3ea96b1e2ac4914fda4cb93c76b4a3e0d8cc6dd8976d6c0b227d15` | `VERSION` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/__pycache__/agentstack-supervisor.cpython-314.pyc` | yes | `b19e1d43f1f684d60e9f7bf5802735692269ff73a456540e8d15bf7812fcb1f9` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `bin/agent-start` | yes | `218a276f4d05b437f5ebe2a5099398f60d969ea1f2f1834a7d3b6ebcb6e8e916` | `bin/agent-start` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agent-start-codex` | yes | `2fc78f2580fdec0de96e7e975578c6361e80ac31e9f1d615235d5cd211ce6eb9` | `bin/agent-start-codex` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-await-reply` | yes | `954850e9cf05a958aa4a17358d61b9dad251a83e74f95658b7d2bbcc68d09f6d` | `bin/agentstack-await-reply` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-check-seats` | yes | `3db06eeaf4d34ff1e6783786ad9413605e882144ac67fdf63ca41de98691a1f8` | `bin/agentstack-check-seats` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-claude-setup` | yes | `302242bba34af79b29a84308057feddd99dc8f97299436f73b2855d49cb9580c` | `bin/agentstack-claude-setup` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-codex-bootstrap` | yes | `8f8a56210ab98939d5920ffb5bae32f4860fb3fff0d97a2254791e7f0382061d` | `bin/agentstack-codex-bootstrap` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-codex-setup` | yes | `db509add05145e40e5e82068aaf8af3b708b8cba91d1e336010f55e757fd2783` | `bin/agentstack-codex-setup` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-doctor` | yes | `87c88f3b540a2465ae71538dbeaa8242dd08836d8ceb4045cf0e277810cb7e7a` | `scripts/doctor.sh` | 直接改造の差分を移植 / ef51345 |
| `bin/agentstack-doctor.bak-20260920-tmux-tcc` | no | `c0392571a04247ed3e7a94aeee366dee0df8f245fa59dfa6d5c8006c2444c545` | `docs/orrery-up-1/backup-generations/bin/agentstack-doctor.bak-20260920-tmux-tcc` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-doctor.bak-argv4` | yes | `efb3cd9925f17ca1f5a60c3381235df6bc221a30d84b2300d0a1129e3144d8d6` | `docs/orrery-up-1/backup-generations/bin/agentstack-doctor.bak-argv4` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-mailctl` | yes | `52e495afed5a5c1f2a96322413d4fd9fafb1243e26b8c88a14a728ae24d1d08d` | `bin/agentstack-mailctl` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-memory-guard` | no | `3842a57bbd9eb8a717c664cd4c71897975b2bdaee1a3a3397209c15370b64e9a` | `bin/agentstack-memory-guard` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-memory-guard.bak-20260926-v1` | no | `10347a56f78f2389d82d0685f3553e21c0c4b8596d98cffc71f4c2cea0bb623f` | `docs/orrery-up-1/backup-generations/bin/agentstack-memory-guard.bak-20260926-v1` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-memory-guard.bak-20260926-v2` | no | `ea8c9aa4d330489c37714697615e5e7f5b60c70c0c4af2d5631bcff9e0a5d8fe` | `docs/orrery-up-1/backup-generations/bin/agentstack-memory-guard.bak-20260926-v2` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-merge-claude-mcp` | yes | `e3d8331aa9d2ab4b5eb93355cbc61770c0f72d5eaeecd14212a422b7767810ae` | `scripts/lib/merge_claude_mcp.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-merge-settings` | yes | `15b430474d0c7d47fb6edfa043dcbda5d6b90183d1feadfb6049a75177862190` | `scripts/lib/merge_settings.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-owner-checkin.py` | no | `e360c0730e323fde06fb5e06ed51e1e8009bb60ff8359d0e377840885fef5a52` | `bin/agentstack-owner-checkin.py` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-preregister-child` | yes | `3b97dfec2b773b4230bb82e0ad880928b1ed33827eb6f8ed8a4f28e038ff681a` | `bin/agentstack-preregister-child` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-reap-idle-seats` | yes | `a2e7aaca91775542fca5cc739b1b054b1afcf79da244e0b94a09b6070f8ed6b7` | `bin/agentstack-reap-idle-seats` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-reap-idle-seats.bak-20260920-two-strikes` | no | `ce4d4c7730d7408f7539e41974d7e61da164ad3a0277bd2b3855db0828cae351` | `docs/orrery-up-1/backup-generations/bin/agentstack-reap-idle-seats.bak-20260920-two-strikes` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-reregister` | yes | `0f4430af4698e09778cf96a07465ad77f0262910769ed4f81a0ffadf4f62a72f` | `bin/agentstack-reregister` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-restart-seat` | yes | `69a4a1b2277375a55b87344badc718249c0835e4061e7a906c702dbd1b771cee` | `bin/agentstack-restart-seat` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-rule-mirror-check` | no | `c3a432b102ef3479811e21ecc40b240f376693a80ac729337cb6549594854f84` | `bin/agentstack-rule-mirror-check` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-seat-cost.py` | yes | `21b1b08194b8b158434f6b9211d9bf9696daba37d93b15f0361280238e38edd1` | `bin/agentstack-seat-cost.py` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-seat-stall-watch.py` | no | `398b6f388a8123e6f308a44596e8eb20c7ba84777f0e8d6a752cfd29abf4f9fe` | `bin/agentstack-seat-stall-watch.py` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-selftest` | yes | `0a49d89978e68a12fae6a15ed9b66df5061d8660fe38f0c43d2dce9444fde07f` | `scripts/selftest.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-spawn-codex` | yes | `1ab6d348bb9934a9f6c90a1d24a8290214e4d73bad8374368fd9edfaf1599bd4` | `bin/agentstack-spawn-codex` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-supervisor.py` | yes | `a3a9cd6e8908499d0e6495b11ef8ccdffdfeb86519a3093d452d462b61198eb4` | `bin/agentstack-supervisor.py` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260912` | no | `53bc3149c2c3becbc1339d0d411d7e399e07bd0a29d013892788d66548043939` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260912` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260918-nudge-cap` | no | `3d3e755ba6adb088f138bbdf31deffe4cbfa1fd4424327e39b64426448541026` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260918-nudge-cap` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260920-R062` | no | `0f1f50042bc92efcf48c131815ada31d9d6f0633096b82adee8c4f426595d65d` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260920-R062` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260921-heartbeat` | no | `97b302f38009a96ff1948da11a5a296e4ac14611a3e9933dfd9ed63b6b337293` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260921-heartbeat` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-R068` | no | `ecb087b28f7c9f0a56a31ea522d02dd69c1b64922e0d4aedb1a237cdf8c44d8f` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-R068` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-autoack` | no | `383484b956333c3eeca9a78e30c3208f842de17203ce086fe80c83338bed3318` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-autoack` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-autoack2` | no | `1dc53c375f922faaf79c4b86cc31cb92938c8633dafa8cc6cb000c4f89daab27` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-autoack2` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-codexto` | no | `5e7465c7a7bbfeada9f677450d5966c7337ab02d08cb124a39c4ce99f94b7164` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-codexto` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-dispatchnudge` | no | `c27cf67ef8a9b9f3b58e53f377dda42ebb21b6ce3265d051f0e8810059a84e45` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-dispatchnudge` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-nudgeid` | no | `f00cf46e27714c031aa41b694a055d1261991e78d60eda0fe0876d5d3bc7689b` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-nudgeid` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-stale24h` | no | `8b1b5e9886e59563cc4d6e8c6b350a5a226d4c5f3246039680173b875225d3eb` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-stale24h` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-throttle` | no | `33caff46ba05cb4934d00556aa8cf7f4ad4a4404d01ca17122dbb8c067dae9f4` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-throttle` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-supervisor.py.bak-20260923-window15` | no | `6fac7071a938331d7fab4e39deb1b8cd42d86a74b7543cb4480af2f185f82974` | `docs/orrery-up-1/backup-generations/bin/agentstack-supervisor.py.bak-20260923-window15` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/agentstack-tmux-server-migrate` | no | `5d6989ac78c454f5a80561f86d8cb7933668784ceaf32bb03c7c978ecd18de1f` | `bin/agentstack-tmux-server-migrate` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/agentstack-uninstall` | yes | `aaab54b4fc8a8e8f137a38196adfec364c356ea15dbb3ca6ecb791256eb8cafe` | `scripts/uninstall.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/agentstack-unstick-seats.sh` | yes | `497c04e0acaf098bb02000c08907c9a9223e85e3fafaa30496d5bb958ade62e0` | `bin/agentstack-unstick-seats.sh` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/codex-stats` | no | `79e330ec8a0e4f7ef883bb7b84ed8993eb6a717c779f806a3429c340c745e3e5` | `bin/codex-stats` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/head-send` | no | `72fa772b13ca951e7a5a6007966c2129e91807995f8af3893c66e42e8ddc5277` | `bin/head-send` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/lib/__pycache__/mcp_endpoint.cpython-314.pyc` | yes | `39930d6b580812cf6623621c9f2eb0e51a72ebbb8ec894139d684d506215a3f0` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `bin/lib/agentstack-launch.sh` | yes | `d352560da842f90a4f0016e5c004c9501adc0ede8227b4ebca32ad77889d8a17` | `bin/lib/agentstack-launch.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/lib/agentstack-register.sh` | yes | `81d4fb88da669755c0a9c2eb715356ae10cf76d260f4c56600814ca64fdaab39` | `bin/lib/agentstack-register.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/lib/agentstack-scientists.sh` | yes | `a9a3785e31c8e8e20a2ef2055dd9d08fb920bd85f0058e1cf31784d88e1aa22e` | `bin/lib/agentstack-scientists.sh` | 直接改造の差分を移植 / ef51345 |
| `bin/lib/agentstack-scientists.sh.bak-20260920-nohyphen` | no | `65adb369be19b43c854184ae35fdf4c876d21165c3135d5670875821306e145e` | `docs/orrery-up-1/backup-generations/bin/lib/agentstack-scientists.sh.bak-20260920-nohyphen` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/lib/mcp_endpoint.py` | yes | `ceda5e108e94fca1c2e1d7f3d4dd08c681893ec7813ba9a13e5d47d931141c4a` | `scripts/lib/mcp_endpoint.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `bin/orrery-audit-evidence` | yes | `00787c6dc3745b65915c89795c8d56782d551fee89e5999e7f70eb203abe92db` | `bin/orrery-audit-evidence` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/orrery-audit-evidence.bak-20260921-K4` | no | `1bba217b7c5f0eab61aacbe4daa572e7594aaad5f8ac3df4aaf94f3c795d8d00` | `docs/orrery-up-1/backup-generations/bin/orrery-audit-evidence.bak-20260921-K4` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/orrery-audit-login` | yes | `a2fe50efb42e728436fb338779c00ce8853af67b80f583a8b6f831fcdc03c23c` | `bin/orrery-audit-login` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/orrery-audit-run` | yes | `dad3071b0c1fd809bb54c5e37c0121d6600d66edf70cd66296c79f620c0cb6a9` | `bin/orrery-audit-run` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/orrery-ci` | no | `39a6d608bf8bbc0abc7ac3c98e08586b253f259e7b40c0a198c62d2b2085d06e` | `bin/orrery-ci` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/orrery-head-tripwire` | no | `dfea95e521b07c4a95b6aa3942eb937d0c79defc4071060410218733ea3c530b` | `bin/orrery-head-tripwire` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/orrery-head-tripwire.bak-20260912` | no | `bbccdca27dc4a8c4fffb59c79ac6a48aedf60bd62668bf5092abcdaf86d877f7` | `docs/orrery-up-1/backup-generations/bin/orrery-head-tripwire.bak-20260912` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/owner-quote-index` | no | `12cb0015e0ebc7b0bc9461d3e18e8667fd4e1a39340f01a5660abaffe0d66d6e` | `bin/owner-quote-index` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/owner-sheet-health` | no | `3d5c7d7c974a36902052cc7171d9192c69efe47a7a66090c08246872851b6dc4` | `bin/owner-sheet-health` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/owner-sheet-server.py` | no | `4370418963fac34f020881dfcb820dcade3e18fc87f027c12a8d0ac59ee55cc4` | `bin/owner-sheet-server.py` | 追加コードをinstall対象へ移した / ef51345 |
| `bin/owner-sheet-server.py.bak-20260920` | no | `fb8addd2e410973d44a50c1f936ce5f824c83783cb4ecedca801fada34d28569` | `docs/orrery-up-1/backup-generations/bin/owner-sheet-server.py.bak-20260920` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/owner-sheet-server.py.bak-20260920-s2` | no | `074371f7e4a6f2cb1554c19799580b2cc5641fdc5c54ece5198b511cb9943f52` | `docs/orrery-up-1/backup-generations/bin/owner-sheet-server.py.bak-20260920-s2` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/owner-sheet-server.py.bak-20260922-500` | no | `1b4d67e5b08710146ce5bad10d2e593d8cea91da58f42a980ffd1b05d55bf94c` | `docs/orrery-up-1/backup-generations/bin/owner-sheet-server.py.bak-20260922-500` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/owner-sheet-server.py.bak-20260922-prev` | no | `c50fc6259248e1109022d59b6a56f2317726679595e225fde8123a83bc3b5104` | `docs/orrery-up-1/backup-generations/bin/owner-sheet-server.py.bak-20260922-prev` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `bin/simulator-window-guard` | no | `06585f5176d047e7e177377c9183fa56833280657c205751969d42b31b3cb8fc` | `bin/simulator-window-guard` | 追加コードをinstall対象へ移した / ef51345 |
| `claude/CLAUDE.md` | yes | `b46c3537f3804cb5f0a8a5522494a3f1e1580cef3a7e24bab01338a55b9bdc00` | `claude/CLAUDE.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `codex/AGENTS.md` | yes | `a29b08eec9a144627c6f1d007c42d2254493d402df836606d4f80378351d1028` | `codex/AGENTS.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/__pycache__/graph_data.cpython-314.pyc` | yes | `4c4d96dd6cd201dd515aa0cfc2bcbc17d24b7c46f3bf884a27ee30c1792bf33c` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `dashboard/agentctl.sh` | yes | `7e7b760a335e31db2ad3414b9c7832573c0965b78342af9e7c4eda9a2958767e` | `dashboard/agentctl.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/agentdashboard.plist.template` | yes | `613627e2f5c9645ec8bfaa48a8f1f0bf54de79d2cbd42afd69a93a58ac8c0635` | `dashboard/agentdashboard.plist.template` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/assets/anthropic.svg` | yes | `e6ce2f7fd33ebc903182ab46b967608571021cd9d9f8472232f45d62c3df40d2` | `dashboard/assets/anthropic.svg` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/assets/openai.svg` | yes | `955168c5b8c0de266b32d2ba7e76b44303898e934d29a56199643d302a926aac` | `dashboard/assets/openai.svg` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/PORTRAITS.txt` | yes | `208086852128e6f3ab98af902a620238d3326461aa661efa1781bed38eb34569` | `dashboard/demo/PORTRAITS.txt` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/PORTRAITS_CLEARED.txt` | yes | `8fdb0b628171e9b395d6b461d2329e25471af8b03585673a85991b26b3200fbb` | `dashboard/demo/PORTRAITS_CLEARED.txt` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/STORY_CONTRACT.md` | yes | `50c5c603a046ecbd90d039b5db056ca764cadc2424e7c2ea58ae4a3c0e6702b6` | `dashboard/demo/STORY_CONTRACT.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/build.sh` | yes | `4a417738b5dd1d6891a2ba62d5a9738b9ccd31404f3098cf975b97edb8598162` | `dashboard/demo/build.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/demo_api.js` | yes | `2464de22f1446b9c735d9b3062b59d01713da460c559a7270ef4bb7f662fa280` | `dashboard/demo/demo_api.js` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/demo_tour.js` | yes | `ae86bcf3cca30399d35e15a3549b27f3a735facfed630c978c7c60cc0318601c` | `dashboard/demo/demo_tour.js` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/story_bugreport.js` | yes | `f07e2f4289e9fd44ad7d86786bb69f6686f28d521ceada9eaf9c652f378d33f3` | `dashboard/demo/story_bugreport.js` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/story_research.js` | yes | `50991feaa0aed61bc2710d1a927d66910b07082173b8f806590a2a2f8bafe669` | `dashboard/demo/story_research.js` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/demo/test_demo_shapes.js` | yes | `164a8cb7466fc9e64a15b576411d96df41ed658c4683b5a9b6b19b772b71c21e` | `dashboard/demo/test_demo_shapes.js` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/graph_data.py` | yes | `bde99f77ff8b7ea0a1862ec797da3c7d8fa1b69da567756cfb2ce959dee590ae` | `dashboard/graph_data.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/index.html` | yes | `5384b7346f77c030531e8ad8489d9ee8855804b54ceda116e8cf70f06cdb8c47` | `dashboard/index.html` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Archimedes.png` | yes | `dccb2d870bba9f51d80a819c0d8d47f394d5e5ed4c64afe61eff9daed8146b54` | `dashboard/portraits_64/Archimedes.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Arrhenius.png` | yes | `8dea11e631ad7057f1541f482aa3735b1be3dfa42d32d9ed50cf9f22a3286c9d` | `dashboard/portraits_64/Arrhenius.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Bell.png` | yes | `b533129b82c36b9ae2559ff62dc1aed044f70c8547f2771379df34bbdcd8d895` | `dashboard/portraits_64/Bell.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Bohr.png` | yes | `5e85ace97334fb1447243820b412827db119bd4afc726c79f3e8ead9a025773f` | `dashboard/portraits_64/Bohr.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Boltzmann.png` | yes | `9fa71726825a4f28a2075ca2f00748f978cef51794445855bd14ce2a4c63ae42` | `dashboard/portraits_64/Boltzmann.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Bose.png` | yes | `f02a5a714e70f7d98dc50f40b1451416b332c9298184a43106286d6d913ff11c` | `dashboard/portraits_64/Bose.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Copernicus.png` | yes | `880408dd2d6c69d21e5bdf74fee28593eb6cb66d0103ebc3f2242073f77a6fd3` | `dashboard/portraits_64/Copernicus.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Curie.png` | yes | `b94f3fbedb489ef94374a9be0ce98d0ec5d91516efdd3b7164a46d83ee53d8f2` | `dashboard/portraits_64/Curie.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Darwin.png` | yes | `b4d3bd2c6bdea0d5394a20fd7f284e1eae3a6dbbb8d2ac5f1459c4917c884bad` | `dashboard/portraits_64/Darwin.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Dirac.png` | yes | `baad272d4ace8fe31b84a1e4bf219674bf62853bed8b28666e19632b4da16259` | `dashboard/portraits_64/Dirac.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Edison.png` | yes | `554451fbcc3300591459e9573e331aa9663d0a2da8d589961125c311dd4de138` | `dashboard/portraits_64/Edison.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Einstein.png` | yes | `434ce7a34d4a3866a7c25729924f17d2939275824a21e560042865b6e9534642` | `dashboard/portraits_64/Einstein.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Euler.png` | yes | `8c6b4b1ba2ff1c1ff1b53222dd1278724ed15a626b71be5fb71ee001e7e0650f` | `dashboard/portraits_64/Euler.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Fabre.png` | yes | `e6bd5b75827ee41b8aa4d345ce3abf301c6f81d05956687bc149671973b1364b` | `dashboard/portraits_64/Fabre.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Faraday.png` | yes | `86e2441184db63cb8ba3b87f177c17bcb0f3f80bf75ff5d06e59ca231ded4ce0` | `dashboard/portraits_64/Faraday.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Fermi.png` | yes | `3801333bbea369985bf034fbb33b5f1bb47b8aca559afdd6e5d55c75d9ed6973` | `dashboard/portraits_64/Fermi.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Feynman.png` | yes | `e8cdfa52d97ad278884556dabb518f4f68f415f6c038736c323c1a26ca4346cf` | `dashboard/portraits_64/Feynman.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Franklin.png` | yes | `95dd66e740166d6dbb3f076a8974a4fc2521703fc02b9051c227b72273b72816` | `dashboard/portraits_64/Franklin.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Galileo.png` | yes | `92e88e075633670eb432a3785105b2390ea56b0baaebdfc17e2a7ca936929a4a` | `dashboard/portraits_64/Galileo.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Gauss.png` | yes | `72714000c277b9766efbc3a1f4d84d79442472f9e2b5c888c02e49662cabc7a1` | `dashboard/portraits_64/Gauss.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Goodall.png` | yes | `3fdb3122744e3013058164f0eece7c1454a0fea15497d545b97d5240640be3fe` | `dashboard/portraits_64/Goodall.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Guericke.png` | yes | `c827bcff89735841220b9411ea33f012d3f7dfce7e35a6a9aaac089cc3cf55f5` | `dashboard/portraits_64/Guericke.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Hooke.png` | yes | `66dd844a3bb3c3250d2cc48171c41f0915c46aacc919faef6f3d5d0df50139a3` | `dashboard/portraits_64/Hooke.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Hopper.png` | yes | `08d58bbe144033f0efc1ba8c13746ae8a4f79ff7969185d2cdad1f653cde88e3` | `dashboard/portraits_64/Hopper.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Hubble.png` | yes | `41686b53d559f6a5543a1216407b351ace8134e2754f8878090e21e7f0fa9a5a` | `dashboard/portraits_64/Hubble.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Kepler.png` | yes | `cd03c472e0da498f23d8aacaff81e1b58723a2c85c23fbfd900c90e81bfe96cf` | `dashboard/portraits_64/Kepler.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Koch.png` | yes | `5d61a987d2e0fe20fa6cb2aaf095c3ed8317088eb5f3c8a7f0b3454e2c79f535` | `dashboard/portraits_64/Koch.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Lamarr.png` | yes | `8e652d1a417fb36dba6c0e708dc131b4ccd33c296e42c6e00f06f5795583ff27` | `dashboard/portraits_64/Lamarr.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Langmuir.png` | yes | `00ec466f4250c98b1186ea1cdd0947201f63937fe7a79623fcee14ffca231033` | `dashboard/portraits_64/Langmuir.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Lavoisier.png` | yes | `3f900de80a418f2bef3978257bf0384c33d04a855748c630283624228f6a374e` | `dashboard/portraits_64/Lavoisier.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Leeuwenhoek.png` | yes | `e1c13e835f113270b1d0a16286eabe4f80d79209fc1b957cd4b764545ceff5e0` | `dashboard/portraits_64/Leeuwenhoek.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Linnaeus.png` | yes | `385f77eeed38d9a64c2fca52eb9d6443c64f17ab0efd56a603c62c40953043a2` | `dashboard/portraits_64/Linnaeus.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Lovelace.png` | yes | `95db46b70e22c04c81ae96478c9d6913c1d28a0230017bdc26729e1bd1e308df` | `dashboard/portraits_64/Lovelace.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Maxwell.png` | yes | `da7293bd8fee4fa3d6bdd44ecc8050640de28c7b10ebe415727db4ec0b8d9d5d` | `dashboard/portraits_64/Maxwell.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Mendel.png` | yes | `9191395e8de0e0e3a1c772d88d85820e5332048024657189a4e98c75c985015f` | `dashboard/portraits_64/Mendel.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Mendeleev.png` | yes | `849bc8109c932f9d480a8b1c2ea292cb1fba23c0e9c5ae5dde8ad87afd9929d7` | `dashboard/portraits_64/Mendeleev.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Newton.png` | yes | `46d6142e49a74f8ff3ecbeac0822127480f53c8252714d4be11e53cc78683dad` | `dashboard/portraits_64/Newton.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Noether.png` | yes | `fd0b9473918a57213bbd5353423c0424c8201f668448f73774becbc3619f9dee` | `dashboard/portraits_64/Noether.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Ostwald.png` | yes | `77b080dc0cb9a16c623d2a467294368e81105c69287b84b8ca5e75cbb225f555` | `dashboard/portraits_64/Ostwald.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Pascal.png` | yes | `0090e51414ab0bb876e8b3bfba76544185a4719f8268b661da40682b331dd018` | `dashboard/portraits_64/Pascal.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Pasteur.png` | yes | `7d734fd25a064e0e227e48b5e27cd622de5c4d58e340d0ea4ab157e488bd45d2` | `dashboard/portraits_64/Pasteur.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Pauling.png` | yes | `355bb6ea072fe31c9d4d5aa3723c2f59ac5298b62ed25d2b8e50f4d00d4f746c` | `dashboard/portraits_64/Pauling.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Planck.png` | yes | `9617bbdf7534acba7e3115cb0bd604f5b423e0f479d8896ab5e8b2ace113c2c1` | `dashboard/portraits_64/Planck.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Ramanujan.png` | yes | `93b75fbf89d6d195b28040394ac4c6619eba49b576d7cdfb007fde97ad940675` | `dashboard/portraits_64/Ramanujan.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Somerville.png` | yes | `011192c708cda3ca6095298fe82710c36e67ff9a0a0106f613f3ba439cf0a93e` | `dashboard/portraits_64/Somerville.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Tesla.png` | yes | `bee7221cb8518ea66abde5d960f836d3cb3c0a48d2018420b4869867533f834a` | `dashboard/portraits_64/Tesla.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Turing.png` | yes | `5b5e3829565180576e5069be7a5efe507155d26fec3cd902cc0896eeeb721ae6` | `dashboard/portraits_64/Turing.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Vesalius.png` | yes | `673f14866f7751d27b8e0c6db350c86aa10d4948c4eade6f11259e28ce5d2288` | `dashboard/portraits_64/Vesalius.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Watt.png` | yes | `94ff3f1508f23bb713bb6d69cb23ba4d7a5508d4ded8aafb64d98f45653e752c` | `dashboard/portraits_64/Watt.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_64/Yukawa.png` | yes | `cdf024b361c8a25828ace1a669abf8b9c8a7e607f1207316afbebf27a0bcf8b1` | `dashboard/portraits_64/Yukawa.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Archimedes.png` | yes | `fe8b04f32821e2786d78f11b13dc2592aec8fdcc9d5e5927a9c0a6d1055c783d` | `dashboard/portraits_pixel/Archimedes.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Arrhenius.png` | yes | `d15cf9ae71efada69ece0bd4bc6e41c129b7f390707eae55e1405fa78c5b3f01` | `dashboard/portraits_pixel/Arrhenius.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Bell.png` | yes | `89e597bd85e43fa3ce4ec8952cbc18d9f4b0483212e70d52c6ed594388cac2b8` | `dashboard/portraits_pixel/Bell.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Bohr.png` | yes | `b92c059e0f7bb4ccf88c5a2f0ef0586fc4d05080cdf06ff23cd356fb130b4096` | `dashboard/portraits_pixel/Bohr.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Boltzmann.png` | yes | `c5493765db455742c6e07c80e846efa0b6b82f5c57a26891eda99d44007fb19f` | `dashboard/portraits_pixel/Boltzmann.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Bose.png` | yes | `62e0965ba64d4cf136c35d4ff7d64641520fa0a4cbd0a040076def984babd933` | `dashboard/portraits_pixel/Bose.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Copernicus.png` | yes | `1f95a91f1171d3bafa75755a3c8043ccb4daaed2f2821e66bf90e6819dcc9191` | `dashboard/portraits_pixel/Copernicus.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Curie.png` | yes | `5a37a8c5e803d40f79031477e75d7dce56e42114481b8980fecf6a4c6a0b535e` | `dashboard/portraits_pixel/Curie.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Darwin.png` | yes | `b715deb5d01df41a720f95773cca3c3f5292a917234d4f7dd43ff77d5d343cb6` | `dashboard/portraits_pixel/Darwin.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Dirac.png` | yes | `ce9f1435bd44f4d173a452cec089f498f694db9dedca9f937879ce6b10597061` | `dashboard/portraits_pixel/Dirac.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Edison.png` | yes | `4c657dc601a9d234bc81f99e508ab0d571f2e6a210880d581d0bb17a24c0fdfe` | `dashboard/portraits_pixel/Edison.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Einstein.png` | yes | `62d2b8c0ef59cc56f5f436af29d8e789c15a02e0a2111949435d472a08a22bf5` | `dashboard/portraits_pixel/Einstein.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Euler.png` | yes | `276b0c01b3d94070c4bea773b467adfb676f39159825c0a9da710c89fcc3bcc3` | `dashboard/portraits_pixel/Euler.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Fabre.png` | yes | `e7fa1bee8ad5302c7a4930531528229641e0d0026ee2d44d93bb9f1278454d63` | `dashboard/portraits_pixel/Fabre.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Faraday.png` | yes | `dc920c2e3915b2e2ad52207861784a6dfdd05a4474cb1d843f2feb4413806f46` | `dashboard/portraits_pixel/Faraday.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Fermi.png` | yes | `587a05657b10dafe547fad97e14191a8b717bb47ba710600cdbffe7fc7df76df` | `dashboard/portraits_pixel/Fermi.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Feynman.png` | yes | `1ee77c10e61549fa0cd78f747674a6added9094cdd3e7e0a30c29e6e3953510a` | `dashboard/portraits_pixel/Feynman.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Franklin.png` | yes | `0f0aa7a1fa41483ca98754e0cb615f807de7f3d3b13f91f47a31e745f5abdb86` | `dashboard/portraits_pixel/Franklin.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Galileo.png` | yes | `e6615493e304e41ce10d2221199db129b0681b655c72a799bc58b9a93f1c286d` | `dashboard/portraits_pixel/Galileo.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Gauss.png` | yes | `0845372d53ae34a7518726c86a679594f0c88be1d24801873d333dad0f5cfca2` | `dashboard/portraits_pixel/Gauss.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Goodall.png` | yes | `c2e4a656ee69619ea1c3d931cc4840e640d30f8f2ef6abca1d6b08fb5148bf3d` | `dashboard/portraits_pixel/Goodall.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Guericke.png` | yes | `602c7ac7449fdcb4f485c1cd570547eeb15ab7ceed3fcbae3fd860b8ae52d2bf` | `dashboard/portraits_pixel/Guericke.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Hooke.png` | yes | `d11b7c344d3ba93a7c7d4191f0946704feb30ac08ee9fe97110304a52279064a` | `dashboard/portraits_pixel/Hooke.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Hopper.png` | yes | `1298449f5d7dd9be55f113cef8e7fc2478ad7ce074ec8022fc3335778954de37` | `dashboard/portraits_pixel/Hopper.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Hubble.png` | yes | `6f6c3f962e776c4b3a3b8be0ceb68377309d45fa8c0af65d863bced505637d38` | `dashboard/portraits_pixel/Hubble.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Kepler.png` | yes | `d02c9137b1d45ab30b582c84eab4ff907827cc085d3eb1a915f54ce2d8bda223` | `dashboard/portraits_pixel/Kepler.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Koch.png` | yes | `68a626912ab6975416eb2d7edef1b39f7baa0ae8f78678eb195c65c24d18f765` | `dashboard/portraits_pixel/Koch.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Lamarr.png` | yes | `085307fc73211cd479672d7b6978a56daadf276379f4ab723920e23fe8ce8c10` | `dashboard/portraits_pixel/Lamarr.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Langmuir.png` | yes | `7ca896b95d32280c55dfa3683fa21c6b3bccc6759cf7d190b8d07a15f03e245f` | `dashboard/portraits_pixel/Langmuir.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Lavoisier.png` | yes | `9ea68a8f3c58c568c8b69c637365ec361d369cd33885e4204eebfdcd6200fc82` | `dashboard/portraits_pixel/Lavoisier.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Leeuwenhoek.png` | yes | `240f2ce18ed15a686881fca81bfdfdee74399da5998dfb123e2a1e7610206399` | `dashboard/portraits_pixel/Leeuwenhoek.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Linnaeus.png` | yes | `389591afb3c0740b95cdc35896e67ef1b5a5d820e4523bccc43cd89b5b84847c` | `dashboard/portraits_pixel/Linnaeus.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Lovelace.png` | yes | `448db162e0cc642be37380debd3c405b729cc203ac28b9654492d5f796333d54` | `dashboard/portraits_pixel/Lovelace.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Maxwell.png` | yes | `7aed01b97db5787f54b197d1bec8c05ea563450bfa186c0b7f00771e6a09d9a4` | `dashboard/portraits_pixel/Maxwell.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Mendel.png` | yes | `827cdb048d512c53889ef6fbd890cd0970ce1c8c368e73078145f2281851ac1b` | `dashboard/portraits_pixel/Mendel.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Mendeleev.png` | yes | `b08fa69a0c2cba8050b96de321bcb91d234621fea61e990b89a5f5cbc275bcf6` | `dashboard/portraits_pixel/Mendeleev.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Newton.png` | yes | `43712a0c0016f747f438b77d2b6ef8a4300e57ef593aebbb5c026c38b6cf82e5` | `dashboard/portraits_pixel/Newton.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Noether.png` | yes | `d721aa8d3d57f47d5655e0043d8807136c2d57410b03ef2903dd488d1298b4b6` | `dashboard/portraits_pixel/Noether.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Ostwald.png` | yes | `84b3382afb0701d0ab2cc78d4983cbad906ae8f20ceeb4e0b56df44d33930902` | `dashboard/portraits_pixel/Ostwald.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Pascal.png` | yes | `3acc71ab771cfc796ec6fc91b405a23320994615ae58e98fbb43bb53224d874b` | `dashboard/portraits_pixel/Pascal.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Pasteur.png` | yes | `dc407cd23985529923621ea21ef6408aa1a1689e1d16303e7594e3c5af6d8f57` | `dashboard/portraits_pixel/Pasteur.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Pauling.png` | yes | `be593406a9d381fbc899c287bab8570140e6eb835264d76729bd82fac4c2f281` | `dashboard/portraits_pixel/Pauling.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Planck.png` | yes | `49929cb97015f00d05ec0ad9ae80aaf6cb72963456ffac3b83a43ae77facf554` | `dashboard/portraits_pixel/Planck.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Ramanujan.png` | yes | `3cc66365383b3ac9fb135316d592b1ced3e11360d5669081abf871308af2cd20` | `dashboard/portraits_pixel/Ramanujan.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Somerville.png` | yes | `5fabec6744d8870cff8d718fbc859f9e15bbfbc31e1c645e499d22689e6e4761` | `dashboard/portraits_pixel/Somerville.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Tesla.png` | yes | `62d3a21eef619cd2ef98fff569702482fd3646f1f0ed5528566466e417f9ee0f` | `dashboard/portraits_pixel/Tesla.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Turing.png` | yes | `22b80e9ec893adca495de2345e918742672d589579ad5b7473a96e5bb0c703eb` | `dashboard/portraits_pixel/Turing.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Vesalius.png` | yes | `e269e8bb9718c2153246a63035801e41a48c6bfea1d6cdb5d46f231ea1c97676` | `dashboard/portraits_pixel/Vesalius.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Watt.png` | yes | `56a887237480671fe83b9e63086773351acdb60d45b4f6e25d448d7f29c03bff` | `dashboard/portraits_pixel/Watt.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/portraits_pixel/Yukawa.png` | yes | `8b8a8e3a2b4eef8657ff006695482a5565ef266b604340138686b5d4007b392b` | `dashboard/portraits_pixel/Yukawa.png` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/providers/__init__.py` | yes | `16482a46947620d22e1d7a164f2d12eafa47652b5a77ad69ef094ac2575b4053` | `dashboard/providers/__init__.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/providers/__pycache__/__init__.cpython-314.pyc` | yes | `a73769eeeb9e5a610abfadcf8951430f65c537dc2bf03a65882c4141a1e04651` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `dashboard/providers/__pycache__/base.cpython-314.pyc` | yes | `18520c541b9e35a0a02dd5a895fa8dc3992a370fa58c447d248271747352c3b2` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `dashboard/providers/__pycache__/codex_app.cpython-314.pyc` | yes | `23fa58832d2732392f958913a40c70d61ef36c5d479bcd28cd1a5c7660683817` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `dashboard/providers/base.py` | yes | `cdf5b4c29236db038b1183d2c19ce4fd1ad9ff4b60bb2786949b255a9dc2762e` | `dashboard/providers/base.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/providers/codex_app.py` | yes | `66effe7da040352466702aed13ad9350b4467fc40c7b402858f6b072cac032a5` | `dashboard/providers/codex_app.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/providers/tmux.py` | yes | `5be7622686436498ed126eabdaf9622c6b6a4e1f1910d8282981b67c1fde04e1` | `dashboard/providers/tmux.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/scientist_portraits.json` | yes | `af161cf37d30eee2e645d2b06f04209eb2a05fb9a51ebc3c05c8cec45135a207` | `dashboard/scientist_portraits.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/server.py` | yes | `09389de1261a2dea579df3da9453f79ff41bcc7de0647cd706d4c9eccdbeb7ac` | `dashboard/server.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/service_runner.py` | yes | `f9ccba3cf53d76d248726a308bc5009a96da2449d15a38432d9a37c8e73a47af` | `dashboard/service_runner.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/theme_controller.js` | yes | `46a34df03579a0118c22343250363d89187255cf51c104270e754e32997013e0` | `dashboard/theme_controller.js` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/theme_core.js` | yes | `adea0f070c669595001b4dfd5db54cf7e3382b8bf49db162b902594131c6c50e` | `dashboard/theme_core.js` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/theme_effect_manifest.json` | yes | `eeeae36bfbe333b7d990b1f3a15609dbd3b9249107c99a2ee0fc35f82ae22ef3` | `dashboard/theme_effect_manifest.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `dashboard/theme_light.css` | yes | `6c98aa5d43ce69213ee3961c542a1c7e86c56703a53e7dd024033f2e1f01fba1` | `dashboard/theme_light.css` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `env.sh` | yes | `1cfd3c709b57419c71a41729178cb26ea88767246440669a99f3b8289867c108` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `hooks/README.md` | yes | `277f703807d953f5b36c2c6901c0abf3071b2a774d8e9bf49951dd115c96bbde` | `hooks/README.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/check-agent-registered.sh` | yes | `d38609bf286da0daf065e08fc800424dd4df2518e2be9aec9b9d78e69a8fb39a` | `hooks/check-agent-registered.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/check-file-reservation.sh` | yes | `6eb04ebd02141ea24c02ff41be70c260b8d8dfcd9084eee96eedc04bc6a1e76b` | `hooks/check-file-reservation.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/cleanup-child-agent.sh` | yes | `81b2a40d3d4bbe430fb26f9cc6dabc40116fa1f83e6bcb0d633ab1d6706f4711` | `hooks/cleanup-child-agent.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/head-send-lint.py` | no | `40864dd2bfc6d70accdd11a9ff71938c78bd48982a16e0d7a0a2c5551348411b` | `hooks/head-send-lint.py` | 追加コードをinstall対象へ移した / ef51345 |
| `hooks/invalidate-release-debounce.sh` | yes | `b58b191a0ae96ef09d53f8a7c7f32bb8985dc6ac1dabf43951bf18e5f459b551` | `hooks/invalidate-release-debounce.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/mark-agent-registered.sh` | yes | `c0eced401896e1b0097f5fa616c30618190961cb22daaa709c17ee8d3442c65e` | `hooks/mark-agent-registered.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/monitor_child_agent.sh` | yes | `6e4b2adfcbc277196412c4ce70579dfbb08bef9e3eb8d113a6b7266ac5861ac0` | `hooks/monitor_child_agent.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/project-context.sh` | yes | `db1c66fae9bbe59cfd0bb9b298d56aaea021cf6f66fd1c729909df49e877f6b9` | `hooks/project-context.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/record-session-index.py` | yes | `93d6588b59fab780cb54c0b20ffab790899fccb6c1a478033b747173fb62fd77` | `hooks/record-session-index.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/release-all-reservations.sh` | yes | `c9242da506aa6e0a7436fd476de1e22491676d8406f5812304bd5ae67c2df6ce` | `hooks/release-all-reservations.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/release-file-reservation-worker.py` | yes | `fdb7871a31e4d69a73f6ef386c639485dd141b520000a0b2d877e79e43fa07a9` | `hooks/release-file-reservation-worker.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/release-file-reservation.sh` | yes | `666660dd20e345bd57ce9efb70716d07bdcea18544d8d62aa735269e09228180` | `hooks/release-file-reservation.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/reservation-common.sh` | yes | `58a3b5c9920dd27d4e078e8f282411def82465bf23fb822b219d6b10968febf1` | `hooks/reservation-common.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/resolve-agent-name.sh` | yes | `3c17d81fe544bebdf40062ede9683d4721ae5d30973a380438930ea086743f62` | `hooks/resolve-agent-name.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/rotate_runtime_logs.sh` | no | `bd9189302fcc3c59729331fff61d2b6be4d57930a68a474c17d0de0ddb0246ff` | `hooks/rotate_runtime_logs.sh` | 追加コードをinstall対象へ移した / ef51345 |
| `hooks/session-identity-policy.sh` | yes | `66b59914d51ca2a9421a08a76fc99f956bf570e6319af70490f74b238a8a7072` | `hooks/session-identity-policy.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/session-start-reminder.sh` | yes | `830e65eb13f0b30484d802b8c1fd484f3a7f9f0d8fb2ba462ec7463208fcbed0` | `hooks/session-start-reminder.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/set-ghostty-title.sh` | yes | `d17c1702e89b33f2ac972be0b1c65bd9af8e3d34841480825b9333a53a7f01a6` | `hooks/set-ghostty-title.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `hooks/settings.template.json` | yes | `ecf15e98a736cda0f9856e8c2fa9d7c66029fe9e4d2469ad44b17535380848a1` | `hooks/settings.template.json` | 直接改造の差分を移植 / ef51345 |
| `hooks/settings.template.json.bak-20260923-R068` | no | `75a9d7cebd14206ca659706fe21498f0b9abb0cdbbf356de9f744df7f32abf0e` | `docs/orrery-up-1/backup-generations/hooks/settings.template.json.bak-20260923-R068` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh` | yes | `f4f7bfb056157d8b14faac713a6eecf43711f33a0dd1a11f966f10b3c037038d` | `hooks/spawn_child.sh` | 新しい本家の構造へ手で移植 / ef51345 |
| `hooks/spawn_child.sh.bak-20260912-fullperm` | no | `f1f52389dcc207ce3bded479c4014fb20c06f355f84e3636674e994b521d42e0` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20260912-fullperm` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh.bak-20260920-R061` | no | `e51909c97f6ac7ad90fec8f7600722d4b47729389478a239657ab91fa1c879b3` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20260920-R061` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh.bak-20260920-R062` | no | `d143f5223fe734afbdf1e035659fa97497ca6dcb67b5599a521c483ef4c5e2d1` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20260920-R062` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh.bak-20260923-opus55` | no | `cfb1d8e12e52f7992394874e2fd9332b4ed77aa92af34d45ef908f986731eccf` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20260923-opus55` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh.bak-20260924-readycase` | no | `cc156b9c48e3fed03c053415895fcb47dd6cbf5a0e1a05c7cbe8ef2ecd0bf66f` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20260924-readycase` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh.bak-20260925-update-token` | no | `ab3fcc20b08f047c10a4efb9348bd689fcf66d2259716258f427e6d1be683f5e` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20260925-update-token` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh.bak-20260929-sonnet55` | no | `c6d8b0aa87b1c77340954038e6f5597c43bccc056a7d2197008410754d9b82bf` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20260929-sonnet55` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/spawn_child.sh.bak-20261001-codex0159-trust` | no | `058cadb676e8c89e1d5cf3cc133f21a59fcf0eb7fde7f51a1f8e141d43c94a07` | `docs/orrery-up-1/backup-generations/hooks/spawn_child.sh.bak-20261001-codex0159-trust` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/task-file-lint.py` | no | `b269417574cc8976805c708168ba34204455b29b44066c662dbc479175f4c70f` | `hooks/task-file-lint.py` | 追加コードをinstall対象へ移した / ef51345 |
| `hooks/usage-throttle-warn.py` | no | `1bed2c2e42707f6ed0ba275f9d5ef6b2932e6c36178d403f4c081cce24ae5813` | `hooks/usage-throttle-warn.py` | 追加コードをinstall対象へ移した / ef51345 |
| `hooks/watch_agent_mail_signals.sh` | yes | `d8fd7754707d94ea3e9871441b61719310789fd6fb324372a0c58678aea5c1e5` | `hooks/watch_agent_mail_signals.sh` | 新しい本家の構造へ手で移植 / ef51345 |
| `hooks/watch_agent_mail_signals.sh.bak-20260912` | no | `1cc3fce31b759e104fedfa83e21d09ab8719b7a4c82dcb00eafed396b3dc0813` | `docs/orrery-up-1/backup-generations/hooks/watch_agent_mail_signals.sh.bak-20260912` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `hooks/watch_agent_mail_signals.sh.bak-20260920-stale-signals` | no | `d637a5a640a900d87caec91fa8e1bcca643cf12374e93733e984948d74fc9e4f` | `docs/orrery-up-1/backup-generations/hooks/watch_agent_mail_signals.sh.bak-20260920-stale-signals` | 旧世代bytesを保存（現行世代が実行対象） / ef51345 |
| `install-state.json` | yes | `7ca10ddd198934db2960b1b978db798eff3ffb1aa823e32fe7c93bcc0128060d` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `integrations/codex_app/README.md` | yes | `7d7323304be3550ba9bd6a2e20cf1d5811fd44a49e5bed684664c2a1e26724f3` | `integrations/codex_app/README.md` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit eb28ee92bf8ebd13bf8b81d24274a7c0f1552a8d / ef51345 |
| `integrations/codex_app/bin/doctor-codex-app-integration` | yes | `1977708a525fd4bd6e8dec40ab321b08daac2a4cedc81905d9f04424fa2a54bb` | `scripts/doctor-codex-app-integration.sh` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit 3f24c1c9c05391ffa81c33451c994664026bc3a2 / ef51345 |
| `integrations/codex_app/bin/run-bridge` | yes | `98ab2956799f46457a3d6051cb3490d8ee44f5f549297ad55e16be08c7b6292e` | `scripts/run-codex-app-bridge.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/bin/uninstall-codex-app-integration` | yes | `7496f4ca2ef780e4bdd0cffdd58cfec8845dcd1c061eafc58b13145783bd6255` | `scripts/uninstall-codex-app-integration.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/env.sh` | yes | `2ac323330e7ca4f86b70cf32961c58b4fd0c9463d2d5d95cb9b88c6703c72d72` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `integrations/codex_app/env.sh.bak-20260927-wakepoll` | no | `f7914f70da291ee3770f40c24b414760879019c9920fa04d1390386a8684debc` | `env-histories.json` | 生成envの旧世代。hashと非秘密差分を保存 / ef51345 |
| `integrations/codex_app/env.sh.bak-headwiring-20260908T083501Z` | yes | `72490f8fca62f5a03efd985784c979abf0c93200f852db8248789d8313ecc845` | `env-histories.json` | 生成envの旧世代。hashと非秘密差分を保存 / ef51345 |
| `integrations/codex_app/env.sh.bak-skipgit-20260904T204712Z` | yes | `72490f8fca62f5a03efd985784c979abf0c93200f852db8248789d8313ecc845` | `env-histories.json` | 生成envの旧世代。hashと非秘密差分を保存 / ef51345 |
| `integrations/codex_app/env.sh.bak-skipgit-revert-20260905T051851Z` | yes | `f7914f70da291ee3770f40c24b414760879019c9920fa04d1390386a8684debc` | `env-histories.json` | 生成envの旧世代。hashと非秘密差分を保存 / ef51345 |
| `integrations/codex_app/env.sh.sample` | yes | `a8bb326d14351ce4a592da304d55f4b148bf63cee0e4f9a83189ec8c706ea002` | `integrations/codex_app/env.sh.sample` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/export-manifest.txt` | yes | `97e730ef99d3e345be2ceceec4b907aeaeb31d9114fffe0418153f357580f15a` | `integrations/codex_app/export-manifest.txt` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/install-state.json` | yes | `439ab0a4cbff94da5ae8f309f52f233286d91031092de028e2113332a4e6fa53` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `integrations/codex_app/launchd/org.agentstack.codex-app-bridge.plist` | yes | `744b28606387eb39dfea256f9c90542ab509312429793f6cdf6bd70488cc3c58` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `integrations/codex_app/launchd/org.agentstack.codex-app-bridge.plist.template` | yes | `195e737ea734a38c233c70c60d8b3aa349b36b776ac9dd65209c8f8b3a83f36e` | `integrations/codex_app/launchd/org.agentstack.codex-app-bridge.plist.template` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/.agents/plugins/marketplace.json` | yes | `a885a1f39e508fe3aaf44a226281e9e6f5eeb011d44c4892be33e8e864ef1b82` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/.codex-plugin/plugin.json` | yes | `385eef4050e0035977b26c674a7908d0d66b13f7253303f1f5bb5507036d8b74` | `integrations/codex_app/plugin/.codex-plugin/plugin.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/.mcp.json` | yes | `edeb56d607efa7e9647702bfc118f299de1667332a97d7fdba55ab3309737a5f` | `integrations/codex_app/plugin/.mcp.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/hooks/hooks.json` | yes | `124a624f9d208284355ca64618874cc8863c5eacfec4a4028920bcd3ae8c07d8` | `integrations/codex_app/plugin/hooks/hooks.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/schemas/README.md` | yes | `0d8b5aeddf04943ee887b11e912d996789816f08be3aa27aec143fdc0f8e447e` | `integrations/codex_app/schemas/README.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/schemas/binding-record-v1.json` | yes | `3895fed4e17dd2fc0159575a77fef613e3b3266ff972b4c01259e95cab20130e` | `integrations/codex_app/schemas/binding-record-v1.json` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit b333c9f62860c80b6fdf3bf0dd3797c98ebce15e / ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/schemas/migrations/001_delivery_state.sql` | yes | `fd636110385352cb566c1b9ab9fc5dc7dd798e54cb561a004e6f5c1a1c570454` | `integrations/codex_app/schemas/migrations/001_delivery_state.sql` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/schemas/runtime-event-v1.json` | yes | `996ef8b2ab8399b3b48f3e4cf8102ffbb44151a312ad28666cf09e680a220567` | `integrations/codex_app/schemas/runtime-event-v1.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/scripts/run-hook.sh` | yes | `1790afd561d2ab15b16b39f86ead8fba9af4434899a04adfa118c57e9caeb0c8` | `integrations/codex_app/plugin/scripts/run-hook.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/scripts/run-mcp.sh` | yes | `d15305d52bdadc618c37284da368f949be66e08ae708c61b754665755b819f21` | `integrations/codex_app/plugin/scripts/run-mcp.sh` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit e099b511a61a4d548878161520a73830d82c91ae / ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/skills/coordinate/SKILL.md` | yes | `e660004e0be87cdaaa6bf13867ce09ab174b6db914be134f6d6a762aee868a0d` | `integrations/codex_app/plugin/skills/coordinate/SKILL.md` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit 3a9742336e760bbfab9602b0c177e367722c0778 / ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/__init__.py` | yes | `eb462df8b29bdba105524e721c673c7c0b44f6dfbbd31191f0c5df24250cc2cf` | `integrations/codex_app/src/agentstack_codex_app/__init__.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/agent_mail_client.py` | yes | `fb7cadd6030374cad56309d4e531f698a2c37295f706934f78bdbfc2d1b084af` | `integrations/codex_app/src/agentstack_codex_app/agent_mail_client.py` | 本家の同等機能を採用 / ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/daemon.py` | yes | `0431947308a91de15c906fc8066193ab67ca484cf06c131c7ee74654d523b299` | `integrations/codex_app/src/agentstack_codex_app/daemon.py` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit eb28ee92bf8ebd13bf8b81d24274a7c0f1552a8d / ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/delivery.py` | yes | `4c6a15c3cb9c60898694e00700918f70cea918cf15417ce7683193a6ba97dba9` | `integrations/codex_app/src/agentstack_codex_app/delivery.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/hook_entry.py` | yes | `83ecbca98c63f33ff2f89604f0757c0dfe87eca9c63aaa046809ccdfcb8a26cf` | `integrations/codex_app/src/agentstack_codex_app/hook_entry.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/identity_store.py` | yes | `64871a119b2fb0487ffead92bf091007ba8e3da77060cdaeed8d5ee80073a992` | `integrations/codex_app/src/agentstack_codex_app/identity_store.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/mcp_server.py` | yes | `7291d7d206d9903cf5da8e4592fb287d586e5fcc29462d4a79910dee2e46980e` | `integrations/codex_app/src/agentstack_codex_app/mcp_server.py` | 新しい本家の構造へ手で移植 / ef51345 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/protocol.py` | yes | `7fbae82ee44be8c53fe7726386ed533e2aa4494094a4f412f1e759baf218ef27` | `integrations/codex_app/src/agentstack_codex_app/protocol.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/snapshot.py` | yes | `7989d448b48fbc4f4a222eb10e856a0eb02049edf9af8904792e4812c06fae19` | `integrations/codex_app/src/agentstack_codex_app/snapshot.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/marketplace/plugins/agentstack-codex-app/src/agentstack_codex_app/wake.py` | yes | `3e556049626c565e76838e25bd61d5179612eaeefa005f338fe71a79c2e3bad7` | `integrations/codex_app/src/agentstack_codex_app/wake.py` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit d2f8c2f5cfb1cb1c3308056e2b855f42de71a41b / ef51345 |
| `integrations/codex_app/plugin/.codex-plugin/plugin.json` | yes | `385eef4050e0035977b26c674a7908d0d66b13f7253303f1f5bb5507036d8b74` | `integrations/codex_app/plugin/.codex-plugin/plugin.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/plugin/.mcp.json` | yes | `edeb56d607efa7e9647702bfc118f299de1667332a97d7fdba55ab3309737a5f` | `integrations/codex_app/plugin/.mcp.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/plugin/hooks/hooks.json` | yes | `124a624f9d208284355ca64618874cc8863c5eacfec4a4028920bcd3ae8c07d8` | `integrations/codex_app/plugin/hooks/hooks.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/plugin/scripts/run-hook.sh` | yes | `1790afd561d2ab15b16b39f86ead8fba9af4434899a04adfa118c57e9caeb0c8` | `integrations/codex_app/plugin/scripts/run-hook.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/plugin/scripts/run-mcp.sh` | yes | `49e9e2653989583c7385401eb21b5a8d69765da3f65364d372690a6246dc052e` | `integrations/codex_app/plugin/scripts/run-mcp.sh` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/plugin/skills/coordinate/SKILL.md` | yes | `377e7e181550fa32e0b1519d31b287ab2ac4e57939e7c6e4e11cd6e2f19e5421` | `integrations/codex_app/plugin/skills/coordinate/SKILL.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/pyproject.toml` | yes | `294e049f74c43135e8f3249abd22a4f1b8500b01c438ebd6183d9bce147ceb02` | `integrations/codex_app/pyproject.toml` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit b333c9f62860c80b6fdf3bf0dd3797c98ebce15e / ef51345 |
| `integrations/codex_app/schemas/README.md` | yes | `0d8b5aeddf04943ee887b11e912d996789816f08be3aa27aec143fdc0f8e447e` | `integrations/codex_app/schemas/README.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/schemas/binding-record-v1.json` | yes | `3895fed4e17dd2fc0159575a77fef613e3b3266ff972b4c01259e95cab20130e` | `integrations/codex_app/schemas/binding-record-v1.json` | 旧commitとbytes一致。本家の新しい同じsourceへ更新。一致commit b333c9f62860c80b6fdf3bf0dd3797c98ebce15e / ef51345 |
| `integrations/codex_app/schemas/migrations/001_delivery_state.sql` | yes | `fd636110385352cb566c1b9ab9fc5dc7dd798e54cb561a004e6f5c1a1c570454` | `integrations/codex_app/schemas/migrations/001_delivery_state.sql` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/schemas/runtime-event-v1.json` | yes | `996ef8b2ab8399b3b48f3e4cf8102ffbb44151a312ad28666cf09e680a220567` | `integrations/codex_app/schemas/runtime-event-v1.json` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/__init__.py` | yes | `eb462df8b29bdba105524e721c673c7c0b44f6dfbbd31191f0c5df24250cc2cf` | `integrations/codex_app/src/agentstack_codex_app/__init__.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/agent_mail_client.py` | yes | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/daemon.py` | yes | `87cca91b96accde7a49434fc1e21ab21f8c85fb38585ffe43dedaf167a51a426` | `integrations/codex_app/src/agentstack_codex_app/daemon.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/delivery.py` | yes | `4c6a15c3cb9c60898694e00700918f70cea918cf15417ce7683193a6ba97dba9` | `integrations/codex_app/src/agentstack_codex_app/delivery.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/hook_entry.py` | yes | `83ecbca98c63f33ff2f89604f0757c0dfe87eca9c63aaa046809ccdfcb8a26cf` | `integrations/codex_app/src/agentstack_codex_app/hook_entry.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/identity_store.py` | yes | `64871a119b2fb0487ffead92bf091007ba8e3da77060cdaeed8d5ee80073a992` | `integrations/codex_app/src/agentstack_codex_app/identity_store.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/mcp_server.py` | yes | `56a3f518979e2ba1559637ec8a0d2a66ac5ff721c2de493a3d842e58585330cd` | `integrations/codex_app/src/agentstack_codex_app/mcp_server.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/protocol.py` | yes | `7fbae82ee44be8c53fe7726386ed533e2aa4494094a4f412f1e759baf218ef27` | `integrations/codex_app/src/agentstack_codex_app/protocol.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/snapshot.py` | yes | `7989d448b48fbc4f4a222eb10e856a0eb02049edf9af8904792e4812c06fae19` | `integrations/codex_app/src/agentstack_codex_app/snapshot.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `integrations/codex_app/src/agentstack_codex_app/wake.py` | yes | `0e041894bc388e87db5ef0fc1b3588e8ca0bf36f55a65556333df6ded9498e13` | `integrations/codex_app/src/agentstack_codex_app/wake.py` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `mail-service/renders/95c14223266a8e8a599b6a68d84ca1f7e2026bb7-7e795c6f7e8c2856f78e/run-agentstack-mail.sh` | yes | `ab9b3001d98ca2e93ebe7e31c660a24a1051620a760f5f933038348491d0bca3` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `mail-service/renders/95c14223266a8e8a599b6a68d84ca1f7e2026bb7-7e795c6f7e8c2856f78e/service.env` | yes | `e5cbeec947408444b934971768cbeab81dd5db2f15e0c0573d29639c0ec6f526` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `runtime/claude-mcp-merge-result.json` | yes | `90abbc49b965a9afb55af7b76de3cae2907da14e3b5a861f117a809aaf025fd5` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `runtime/settings-merge-result.json` | yes | `41e460cb12bba6b0da2611b7a1619dc165484824c128a701a64e36febbdc561a` | `生成/保持` | 生成物。installerが再生成、またはcore範囲外として保持 / 2026.09.30.4 |
| `skills/delegate/SKILL.md` | yes | `52ca6d867bc5942a4cebe046b66d391758d90f543035a0fa67cfbb98dc35053f` | `skills/delegate/SKILL.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |
| `skills/log/SKILL.md` | yes | `007a7a9784db6ebc3241719da4ae84e4452324fe4dd10723b9e43224d70a8db1` | `skills/log/SKILL.md` | 元sourceと一致。直接改造無し / 2026.09.30.4 |

## 本家側の根拠

旧optionalの9行は inventory.json の historical_commit を `git show <commit>:<source>` して採録bytesと完全一致させている。README/pyproject/schemaの3差分は branding の旧字句で、実行動作の変更ではない。原本は live-code/ に保存。

`integrations/codex_app/src/agentstack_codex_app/agent_mail_client.py` の `_safe_error_text` は `text[: _ERROR_TEXT_LIMIT - 1]` と `_SECRET_LIKE.sub("[redacted]", ...)` を適用し、`_decode_tool_response` は `raise AgentMailError(_safe_error_text(rpc_result))` でserverの理由を返す。現行の「server理由を隠さない」改造と同等の目的を持つため、安全な本家実装を採用した。

`hooks/child_resume.py:stage_registration` は変更前のtoken/stateを undo record に残し、`finish_registration(... rollback=True)` で失敗時に戻す。現行spawnの CANONICAL_TOKEN_PREEXISTED による保護はこれで保持される。

生成 env / runtime JSON / pyc / service.env は実行コードの改造として複製しない。runtime credential と Mail DBは読まず、元の稼働環境にも触れない。envのcustom exportは scripts/install.sh:write_env_file でliteralとして保持。optional envはcore installerが上書きしない。

## stack 外部の owned 5件

`@home/` は `/Users/huyuhutaru/` を指す。skill link はlink先文字列のSHA、plistはfile bytesのSHA。これらはpayload外の生成物で、対話installerの管理対象・owner rollback snapshot対象である。Mail serviceは稼働listener再利用時に更新されない。

| installed file | owned | 採録 SHA-256 | 扱い / commit |
|---|---|---|---|
| `@home/.claude/skills/delegate` | yes | `9d218cc2dfb68528ad6ed9336b1214d923908e048e931714bca9ebdf56c3f95c` | 生成link/service定義。owner snapshot保存、install管理規則で保持/再生成 / 2026.09.30.4 |
| `@home/.claude/skills/log` | yes | `f25b180b2b5f2e9e9ee62c71b976b0a41fdbac613d6a19964c4bdf14aff0c7ec` | 生成link/service定義。owner snapshot保存、install管理規則で保持/再生成 / 2026.09.30.4 |
| `@home/Library/LaunchAgents/org.agentstack.agentdashboard.plist` | yes | `4e09bb45d77266f1ad472b7da2c3341b74189c69895beaff4e143f7ad17e4f0b` | 生成link/service定義。owner snapshot保存、install管理規則で保持/再生成 / 2026.09.30.4 |
| `@home/Library/LaunchAgents/org.agentstack.mail-watcher.plist` | yes | `5d7c7b0890086d77b8f7dbbbe830a90e82e8ade77496fe2008da1f9c5c62c820` | 生成link/service定義。owner snapshot保存、install管理規則で保持/再生成 / 2026.09.30.4 |
| `@home/Library/LaunchAgents/org.agentstack.mail.plist` | yes | `254b4a722b79e33dc780ea6837d68f77882d2bf4517bdc2b021f0d73af98fa52` | 生成link/service定義。owner snapshot保存、install管理規則で保持/再生成 / 2026.09.30.4 |

## R-068 設定

`config/head-send-lint.json` の検査条件・引用元path・既定headをそのままsourceへ保存し、installerは既存file/linkを上書きせず、無い場合だけseedする。旧調整前JSONも復元可能なbytesで保存。configはowner制御で、core owned-file一覧へ追加しない。owner rollback snapshotには含める。

| installed file | owned | 採録 SHA-256 | 保存先 / commit |
|---|---|---|---|
| `config/head-send-lint.json` | no | `bc6a1f2de96bd75ac7e7f4bfc2aaac989f07b6bd0bfcfee636f9ad54c9d5283f` | `config/head-send-lint.json` / config保存commit |
| `config/head-send-lint.json.bak-20260923-tune1` | no | `38ac876e0ec482b53bfee33b6992357a11cb0a018583b48cd438523b775a74e3` | `docs/orrery-up-1/backup-generations/config/head-send-lint.json.bak-20260923-tune1` / config保存commit |
