#!/usr/bin/env python3
"""
fix_grn_accounting_entries.py

GRN documents are stock-management-only documents.  Any accounting entries
(Dr CC / Cr Vendor) already in accounting_ledger under source_type='grn' are
erroneous double-posts — the linked Purchase Bill already created the same
Dr CC / Cr Vendor entries.

This script reverses every un-cancelled GRN accounting posting by calling
reverse_posting(), which:
  - creates a matching reversal entry (Dr/Cr swapped, same date)
  - marks the original as is_reversed=True
  - preserves the full audit trail (nothing is deleted)

Usage:
  cd erp_backend
  python3 scripts/fix_grn_accounting_entries.py --dry-run   # preview only
  python3 scripts/fix_grn_accounting_entries.py             # apply
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DRY_RUN = "--dry-run" in sys.argv


def main():
    from app import create_app
    from app.extensions import db
    from app.models.accounting import AccountingLedger, AccountingLedgerLine
    from app.modules.finance.accounting.posting_engine import reverse_posting

    app = create_app()
    with app.app_context():

        # 1. Find every active (non-cancelled) GRN accounting posting
        grn_postings = (
            AccountingLedger.query
            .filter(
                AccountingLedger.source_type == "grn",
                AccountingLedger.is_reversal.is_(False),
                AccountingLedger.is_reversed.is_(False),
            )
            .order_by(AccountingLedger.posting_date, AccountingLedger.id)
            .all()
        )

        total = len(grn_postings)
        print(f"\nGRN accounting entries to reverse: {total}")

        if not grn_postings:
            print("Nothing to do — no active GRN accounting postings found.")
            return 0

        # 2. Show a preview table
        print(f"\n{'Ledger ID':<12} {'GRN ID':<10} {'Voucher No':<24} {'Date':<12} {'Project':<16} {'Dr Total':>12}")
        print("-" * 90)
        for p in grn_postings:
            print(
                f"{p.id:<12} {p.source_id:<10} {(p.voucher_no or ''):<24} "
                f"{str(p.posting_date or ''):<12} {(p.project_code or ''):<16} "
                f"{float(p.total_debit or 0):>12,.2f}"
            )
        print("-" * 90)
        total_dr = sum(float(p.total_debit or 0) for p in grn_postings)
        print(f"{'TOTAL':<58} {total_dr:>12,.2f}")

        if DRY_RUN:
            print(f"\n[DRY RUN] {total} GRN postings would be reversed. Run without --dry-run to apply.")
            return 0

        # 3. Confirm
        print(f"\nAbout to reverse {total} GRN accounting entries. This cannot be undone (reversals are permanent).")
        answer = input("Type 'yes' to proceed: ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            return 1

        # 4. Reverse each posting
        success_ids = []
        error_rows = []

        for posting in grn_postings:
            try:
                sp = db.session.begin_nested()
                reversal = reverse_posting(
                    source_type="grn",
                    source_id=posting.source_id,
                    user_id=None,
                    remarks="Correction: GRN is stock-only; reversing erroneous Dr CC / Cr Vendor entry",
                )
                if reversal is None:
                    sp.rollback()
                    error_rows.append((posting.id, posting.source_id, "reverse_posting returned None"))
                else:
                    sp.commit()
                    success_ids.append(posting.id)
                    print(f"  OK  ledger_id={posting.id}  grn_id={posting.source_id}  → reversal {reversal.voucher_no}")
            except Exception as exc:
                db.session.rollback()
                error_rows.append((posting.id, posting.source_id, str(exc)))
                print(f"  ERR ledger_id={posting.id}  grn_id={posting.source_id}  → {exc}")

        # 5. Commit and report
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            print(f"\nFinal commit failed: {exc}")
            return 2

        print(f"\n{'='*60}")
        print(f"Reversed : {len(success_ids)}")
        print(f"Errors   : {len(error_rows)}")
        if error_rows:
            print("\nFailed entries:")
            for lid, gid, msg in error_rows:
                print(f"  ledger_id={lid}  grn_id={gid}  reason={msg}")

        return 0 if not error_rows else 2


if __name__ == "__main__":
    sys.exit(main())
