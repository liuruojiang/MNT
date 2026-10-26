"""Initialize stable encrypted paths and import locations without changing strategies."""
import argparse
import json
from pathlib import Path
from source_audit.config import initialize,DEFAULT_ROOT

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    p.add_argument('--credential-dir',type=Path,required=True,help='Directory containing existing .tiingo-token.dpapi and .wind-token.dpapi')
    p.add_argument('--legacy-us-run',type=Path,required=True)
    p.add_argument('--legacy-wind-archive',type=Path,required=True)
    args=p.parse_args()
    try:
        c=initialize(args.root,args.credential_dir,args.legacy_us_run,args.legacy_wind_archive)
        print(json.dumps({'config':str(Path(c['store_root'])/'config.json'),'encrypted_credentials_copied_or_already_present':True,'originals_retained':True,'production_changed':False},ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'initialization_failed':type(exc).__name__,'credentials_overwritten':False}))
        return 2

if __name__=='__main__': raise SystemExit(main())
