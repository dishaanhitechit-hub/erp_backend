"""One-time: turn advances LINKED to a BRR / journal (old model) into Advance
Adjustments. Run after migration a7c9e1b3d5f2.

    python scripts/convert_advance_links.py            # dry run, shows what would happen
    python scripts/convert_advance_links.py --apply    # writes
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app  # noqa: E402


def main():
    apply = "--apply" in sys.argv
    app = create_app()
    with app.app_context():
        from app.modules.finance.advance_adjustment.service import convert_legacy_links
        report = convert_legacy_links(user_id=None, apply=apply)
        print(json.dumps(report, indent=2, default=str))
        print(f"{len(report)} linked advance request(s) — {'APPLIED' if apply else 'dry run, nothing written'}")


if __name__ == "__main__":
    main()
