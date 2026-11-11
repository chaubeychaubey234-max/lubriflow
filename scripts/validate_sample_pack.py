"""Read-only sample-pack validation. Never imports journals or enables providers."""

import argparse, csv, io, json, hashlib
from decimal import Decimal as D
from pathlib import Path
from zipfile import ZipFile


def validate(path):
    with ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist()) > 20_000_000:
            raise ValueError("Archive exceeds sample size limit")

        def rows(name):
            return list(
                csv.DictReader(
                    io.StringIO(z.read("erp_sample_pack/data/" + name + ".csv").decode("utf-8-sig"))
                )
            )

        def total(rs, key):
            return sum((D(r[key]) for r in rs), D(0))

        expected = json.loads(z.read("erp_sample_pack/validation/expected_totals.json"))
        tb, stock, assets = rows("trial_balance"), rows("opening_stock"), rows("asset_register")
        po = rows("purchase_orders")[0]
        grn = rows("goods_receipts")[0]
        invoice = rows("supplier_invoices")[0]
        journals = rows("journal_entries")
        groups = {r["journal_id"] for r in journals}
        actual = dict(
            opening_trial_balance_debit_inr=total(tb, "debit_inr"),
            opening_trial_balance_credit_inr=total(tb, "credit_inr"),
            opening_inventory_inr=total(stock, "extended_value_inr"),
            purchase_order_001_net_inr=D(po["qty"]) * D(po["unit_price_inr"]),
            accepted_grn_001_qty=D(grn["accepted_qty"]),
            supplier_invoice_001_gross_inr=D(invoice["gross_inr"]),
            sales_invoice_001_gross_inr=D(rows("sales_invoices")[0]["total_inr"]),
            advance_001_unapplied_inr=D(rows("customer_advances")[0]["amount_inr"])
            - D(rows("customer_advances")[0]["applied_inr"]),
            asset_net_book_value_total_inr=total(assets, "net_book_value_inr"),
            bank_statement_ending_inr=D(rows("bank_statement")[-1]["closing_balance_inr"]),
            journal_entries_balanced=all(
                total([r for r in journals if r["journal_id"] == k], "debit_inr")
                == total([r for r in journals if r["journal_id"] == k], "credit_inr")
                for k in groups
            ),
        )
        checks = [
            dict(
                name=k,
                expected=v,
                actual=str(actual[k]) if isinstance(actual[k], D) else actual[k],
                passed=actual[k] == (D(str(v)) if not isinstance(v, bool) else v),
            )
            for k, v in expected.items()
        ]
        for r in stock:
            checks.append(
                dict(
                    name="stock extension " + r["sku"],
                    passed=D(r["qty"]) * D(r["unit_cost_inr"]) == D(r["extended_value_inr"]),
                )
            )
        for r in assets:
            checks.append(
                dict(
                    name="asset net " + r["asset_id"],
                    passed=D(r["gross_cost_inr"]) - D(r["accumulated_depreciation_inr"])
                    == D(r["net_book_value_inr"]),
                )
            )
        bank = rows("bank_statement")
        running = D(bank[0]["closing_balance_inr"])
        for r in bank[1:]:
            running += D(r["money_in_inr"]) - D(r["money_out_inr"])
            checks.append(
                dict(
                    name="bank running balance " + r["bank_txn_id"],
                    passed=running == D(r["closing_balance_inr"]),
                )
            )
        issues = []
        if D(grn["accepted_qty"]) * D(po["unit_price_inr"]) == D(invoice["taxable_inr"]):
            issues.append(
                "AT-003 is ambiguous: invoice net equals accepted receipt value. Invoice has no line quantity; supply the intended mismatch (quantity, rate, tax or billed amount). Do not infer a mismatch from a legitimate partial receipt."
            )
        issues.extend(
            [
                "ADV-001 has 5,000 applied but no linked allocation document; preserve 15,000 as a fixture expectation, not an imported accounting balance.",
                "Opening trial balance and October journals are separate fixtures; combining them risks double-counting.",
                "WO-001 has 75 completed and 2 scrapped but material movements cover only 75 units. Partial output is supported; scrap disposition and its material/cost treatment still require clarification.",
                "BOM scrap_pct=0.02 has no explicit fraction-versus-percent convention; clarify before calculating requirements.",
                "India/INR and illustrative GST are sandbox configuration only; they do not replace Dubai settings or constitute tax approval.",
            ]
        )
        return dict(
            archive_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            scope="Read-only fixture arithmetic and consistency audit; no business UAT or production import",
            checks=checks,
            issues=issues,
            acceptance=[
                dict(r, status="NOT EXECUTED — fixture arithmetic does not prove workflow acceptance")
                for r in rows("acceptance_tests")
            ],
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = validate(args.archive)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                passed=sum(c["passed"] for c in result["checks"]),
                checks=len(result["checks"]),
                issues=result["issues"],
            ),
            indent=2,
        )
    )
    if not all(c["passed"] for c in result["checks"]):
        raise SystemExit(1)
