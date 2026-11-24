# Sansha invoice first-page legal footer (Odoo 19)

The legal text remains at the bottom of page one. The continuation uses a
12 mm bottom margin, so invoice lines can occupy the former footer area.
Continuation top margins add 10 mm to clear the existing Bold logo/header.
Existing QWeb views and shared A4 paper formats are not modified.

## Install on staging

1. Add this addon directory to the existing repository's addons directory.
2. Deploy the code to Odoo.sh staging.
3. In Apps, Update Apps List. Remove the Apps filter and install
   **Sansha Invoice First Page Legal Footer**.
4. In Settings > Technical > Parameters > System Parameters, create:

   Key: `sansha_invoice_footer.enabled`
   Value: `True`

5. Print **PDF without Payment** for the long test invoice.

Prerequisites: the existing Sansha Bold v2 template must still contain the
`sansha_invoice_first_page_footer` class around `company.report_footer`.
Retain the tested first-page A4 bottom margin (currently 40 mm).

By default this applies only to account.move reports named
`account.report_invoice` or `account.report_invoice_with_payments`.
If the report has a different Template Name, specify a comma-separated list
in `sansha_invoice_footer.report_names`. Do not use the displayed report title.
Sale quotations, purchase orders and other report models are excluded.

## How it works

- Print a full invoice using the existing paper format. Return single-page
  invoices without splitting.
- For a multipage invoice, search for a prefix of rendered table rows that
  actually fits a single page, using wkhtmltopdf itself to measure.
- Keep every row exactly once. Move totals, payment details and tax notes to
  the continuation. Never leave a new section heading alone on page one.
- Print the remaining rows and totals with a 12 mm bottom margin and a compact
  footer. Merge both PDFs with continuous page numbering.
- Batch prints are rendered per invoice, preserving Odoo's attachment handling.

No fixed rows-per-page limit and no guessed description heights are used.
Several PDF renders are required per multipage invoice; printing is slower.
This is intended for the existing Sansha invoice template, not arbitrary
report layouts. A changed or unsupported template raises an explicit error.
Duplicate invoice IDs in a single print batch are rejected.

## Verification before production

Local validation covers Python syntax and the pure row-selection algorithm.
HTML splitting and footer tests require Odoo's lxml environment; run:

```
odoo-bin -d TEST_DATABASE -u sansha_invoice_first_page_footer --test-enable --test-tags /sansha_invoice_first_page_footer --stop-after-init
```

Actual PDF rendering must still be checked on Odoo.sh with its fonts and
wkhtmltopdf. Check:

- the original long invoice, including its shipping charge;
- a one-page invoice;
- an invoice with descriptions wrapping across multiple lines;
- sections, section subtotals, notes and discounted items;
- two invoices in one batch, with counters restarting per invoice;
- Print with Payments and attached / electronically signed invoice workflows.

Compare quantities, item count and all monetary totals against the existing
print. Verify that no text overlaps the legal block or page counters.

## Disable

Set `sansha_invoice_footer.enabled` to `False`. Standard printing resumes
immediately, using the current QWeb views and unchanged shared A4 format.
