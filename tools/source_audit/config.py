"""Stable machine-local paths; encrypted credential bytes are copied, never logged."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .calendar import document

DEFAULT_ROOT = Path(r'D:\动量策略\_data_source_service')


def initialize(root, credential_dir, legacy_us_run, legacy_wind_archive):
    root, credential_dir = Path(root).resolve(), Path(credential_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'secrets').mkdir(exist_ok=True)
    credentials = {}
    for provider in ('tiingo', 'wind'):
        source = credential_dir / ('.' + provider + '-token.dpapi')
        target = root / 'secrets' / (provider + '.dpapi')
        encrypted = source.read_bytes()
        # The existing format is encrypted hex; do not decrypt during transfer.
        bytes.fromhex(encrypted.decode('ascii').strip())
        if target.exists():
            if target.read_bytes() != encrypted:
                raise RuntimeError('Existing encrypted credential differs; no automatic replacement')
        else:
            with target.open('xb') as handle: handle.write(encrypted)
        credentials[provider] = str(target)
    (root / 'calendars').mkdir(exist_ok=True)
    for market, start in [('XNYS','2003-01-01'),('XSHG','2026-01-01')]:
        path = root / 'calendars' / (market.lower() + '_2026_sessions.json')
        payload = document(market,start,'2026-12-31')
        if not path.exists(): path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    config = {'schema_version':1,'store_root':str(root),'credentials':credentials,
        'legacy_us_run':str(Path(legacy_us_run).resolve()), 'legacy_wind_archive':str(Path(legacy_wind_archive).resolve()),
        'calendars':{'XNYS':str(root/'calendars/xnys_2026_sessions.json'),'XSHG':str(root/'calendars/xshg_2026_sessions.json')},
        'local_hourly_budgets':{'tiingo':30,'yahoo':30,'wind':30},
        'incremental_overlap_calendar_days':10,'full_revision_check_days':7,
        'same_cutoff_remote_refresh_hours':24,'purpose':'research_only','production_approved':False}
    path = root / 'config.json'
    if not path.exists(): path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    else: config = json.loads(path.read_text(encoding='utf-8'))
    (root/'.gitignore').write_text('*\n',encoding='ascii')
    (root/'README.txt').write_text('本地数据源共享存储。secrets 仅含当前 Windows 用户加密的 DPAPI 原件副本；不上传、不进入 Git。\n原聊天凭证仍保留，不自动删除或轮换。策略未接入该存储；仅供只读研究核验。\n',encoding='utf-8-sig')
    return config


def load(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if config.get('schema_version') != 1 or config.get('purpose') != 'research_only' or config.get('production_approved') is not False:
        raise ValueError('Unsupported or production configuration')
    root = Path(config['store_root']).resolve()
    for value in config['credentials'].values():
        if not Path(value).resolve().is_relative_to(root/'secrets'):
            raise ValueError('Credential path must remain in the configured encrypted store')
    return config
