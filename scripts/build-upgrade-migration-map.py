#!/usr/bin/env python3
"""Join every UP1 table row to the refreshed inventory and committed source."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/orrery-up-2'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def commit(path):
    return subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', path], cwd=ROOT, text=True).strip()

def main():
    inventory = json.loads((OUT / 'inventory.json').read_text())
    old = {r['installed']: r for r in json.loads((ROOT / 'docs/orrery-up-1/inventory.json').read_text())['rows']}
    by_path = {r['installed']: r for r in inventory['rows']}
    for row in inventory['rows']:
        path = row['installed']
        prior = old.get(path, {})
        destination = row.get('source') or row.get('archive') or prior.get('archive')
        if row.get('archive') and row['disposition'] == 'historical-code-preserved':
            destination = row['archive']
        if prior.get('disposition') == 'historical-generation-preserved' and not row.get('archive'):
            destination = prior.get('archive') or prior.get('source')
        if row['disposition'] in ('env-history-retained-hash-only', 'literal-values-and-codex-comments-preserved'):
            destination = 'scripts/install.sh' if path == 'env.sh' else 'scripts/fleet-upgrade-backup.py'
        if row['state'] == 'generated-excluded' or path.startswith('@home/') and not destination:
            row['preservation'] = '生成物または外部設定をinstaller範囲外で保持。コードの再導入なし'
            row['migration_commit'] = commit('scripts/install.sh')
        elif destination and (ROOT / destination).exists():
            row['preserved_at'] = destination
            row['migration_commit'] = commit(destination)
            row['preservation'] = row['disposition']
            p = ROOT / destination
            raw = p.readlink().as_posix().encode() if p.is_symlink() else p.read_bytes()
            row['destination_sha256'] = sha(raw)
        else:
            row['migration_commit'] = commit('scripts/install.sh')
            row['preservation'] = '生成設定・既存optional配置を上書きせず保持（隔離diffを参照）'
        if path.startswith('integrations/codex_app/') and not path.startswith(('integrations/codex_app/src/', 'integrations/codex_app/plugin/')):
            row['preservation'] = '既存optional配置を非上書きで保持。対応sourceは参照のみ（隔離diffで旧bytes一致）'
            row['migration_commit'] = commit('scripts/install.sh')
        if prior.get('disposition') == 'upstream-equivalent-safe-error-details':
            row['preservation'] = '本家の600字上限とredaction付きerror表示を採用（引用参照）'
        if row['disposition'] == 'versioned-compatibility-default':
            row['preservation'] = '現行世代bytesを保存し既定dispatcherから実行。本家coreは.upstream別path'
    previous = []
    for number, line in enumerate((ROOT / 'docs/orrery-up-1/migration-map.md').read_text().splitlines(), 1):
        if not line.startswith('| `'):
            continue
        path = re.search(r'`([^`]+)`', line).group(1)
        target = by_path.get(path)
        # The nine implementation summaries use source aliases, not install aliases.
        if target is None:
            target = next((r for r in inventory['rows'] if r.get('source') == path), None)
        if target is None:
            raise ValueError('UP1 row has no migration: ' + path)
        previous.append({'up1_line': number, 'up1_row_sha256': sha(line.encode()), 'installed': path,
                         'up2_installed': target['installed'], 'migration_commit': target['migration_commit'],
                         'preservation': target['preservation']})
    assert len(previous) == 316, len(previous)
    (OUT / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'up1-row-map.json').write_text(json.dumps(previous, ensure_ascii=False, indent=2) + '\n')
    lines = ['# ORRERY-UP-2 改造対応表', '',
             '旧inventory307行を照合。変更20・同一277・生成物除外10・削除0。新規68を加えて375行。',
             '新規のうちenv履歴4件はUP1の別表に既出。元のmigration-mapの316データ行はup1-row-map.jsonに行番号・行hash付きで全件対応。', '',
             'Mail DB・runtime資格情報・生成bytecodeは対象外。保持は現行コードの移植、旧世代bytesの保管、外部設定の非上書きを区別する。', '',
             '本家同等実装: tag2026.10.22の `integrations/codex_app/src/agentstack_codex_app/agent_mail_client.py:422` の `_ERROR_TEXT_LIMIT = 600`、449行の `text = _SECRET_LIKE.sub("[redacted]", text.splitlines()[0])`、452行の `return f"ORRERY Mail tool call failed: {text}"` を採用。旧コピーの無制限error本文表示を重ねない。', '',
             'spawnについてはhead便35265の裁定で現行release5 regular file・3 symlinkを採録。本家coreを捨てず別pathに保存する。後続項目はupstream-changes.mdを参照。', '',
             '| installed | 状態 | 現行SHA-256 | 対応source / 保存先 | 扱い | commit |',
             '|---|---|---|---|---|---|']
    for row in inventory['rows']:
        values = [row['installed'], row['state'], row.get('sha256', '生成物・未読'), row.get('preserved_at', 'installer対象外'), row['preservation'], row['migration_commit']]
        lines.append('| ' + ' | '.join('`' + v.replace('|', '/') + '`' for v in values) + ' |')
    external=json.loads((OUT/'external-config.json').read_text())
    lines += ['', '## 外部のgit設定（file件数の外）', '', '| 設定 | 値 | 値SHA-256 | 扱い / commit |', '|---|---|---|---|', '| `http.sslCAInfo` | `'+external['git_http_sslCAInfo']+'` | `'+external['git_setting_value_sha256']+'` | head便35273。ownerのglobal設定を保持しinstallerは書換えない / `6fa4e24990359b0504e1cd8a7f92c731fe3980b4` |']
    (OUT / 'migration-map.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'rows': len(inventory['rows']), 'up1_table_rows': len(previous)}))

if __name__ == '__main__':
    main()
