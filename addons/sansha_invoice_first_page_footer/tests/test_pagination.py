from odoo.tests.common import BaseCase as TestCase

from ..pagination import select_first_page
from ..models.ir_actions_report import _split_body, _footer, _parse, _has_class


BODY = """<html><head><style>td {font-size: 10px}</style></head>
<body><div class="article" data-oe-model="account.move">
<div class="address">SHIPPING AND BILLING</div><h2>INV/TEST</h2>
<style>.invoice_main {width: 100%}</style>
<div class="invoice_main"><div class="page">
<div id="informations">INVOICE DATES</div>
<table name="invoice_line_table"><thead><tr><th>Description</th></tr></thead>
<tbody>
<tr id="r0"><td>Product one with a long description</td></tr>
<tr id="r1" class="o_line_section"><td>SECTION</td></tr>
<tr id="r2"><td>Product two</td></tr>
<tr id="r3"><td>SECTION SUBTOTAL</td></tr>
<tr id="r4"><td>SHIPPING CHARGE</td></tr>
</tbody></table>
<div id="right-elements">TOTAL 100.00</div>
<div id="payment_term">BANK AND TAX NOTES</div>
</div></div></div></body></html>"""

FOOTER = """<html><head><script>function subst() {}</script></head>
<body onload="subst()"><div id="minimal_layout_report_footers">
<div class="footer"><div class="o_footer_content">
<div><div class="sansha_invoice_first_page_footer" style="line-height: 1.1">
<span>LEGAL TEXT AND BANK DETAILS</span></div></div>
<div>INV/TEST Page <span class="text-muted page"></span> /
<span class="topage"></span></div></div>
<script>(function () { var blocks = document.getElementsByClassName(
'sansha_invoice_first_page_footer'); }());</script></div></div></body></html>"""


class TestPaginationSelection(TestCase):
    def test_capacities(self):
        for rows in (0, 1, 10, 143, 1000):
            for capacity in (0, 1, 7, 40, 1001):
                with self.subTest(rows=rows, capacity=capacity):
                    self.assertEqual(
                        select_first_page(rows, lambda count: count <= capacity),
                        min(rows, capacity),
                    )

    def test_does_not_orphan_section(self):
        self.assertEqual(select_first_page(
            10, lambda count: count <= 5, lambda index: index == 4,
        ), 4)

    def test_rejects_oversized_fixed_header(self):
        with self.assertRaises(ValueError):
            select_first_page(10, lambda count: False)

    def test_uses_logarithmic_probes(self):
        calls = []
        result = select_first_page(10000, lambda count: calls.append(count) or count <= 40)
        self.assertEqual(result, 40)
        self.assertLess(len(calls), 20)


class TestPaginationHtml(TestCase):
    def test_every_row_is_preserved_once(self):
        for cut in range(6):
            first, rest = map(_parse, _split_body(BODY, cut))
            first_ids = first.xpath('//tbody/tr/@id')
            rest_ids = rest.xpath('//tbody/tr/@id')
            self.assertEqual(first_ids + rest_ids, ["r%s" % i for i in range(5)])
            self.assertFalse(first.xpath('//*[@id="right-elements"]'))
            self.assertTrue(rest.xpath('//*[@id="right-elements"]'))
            self.assertTrue(rest.xpath('//*[@id="payment_term"]'))
            self.assertTrue(first.xpath('//*[@id="informations"]'))
            self.assertFalse(rest.xpath('//*[@id="informations"]'))
            self.assertFalse(rest.xpath('//div[@class="address"]'))
            self.assertTrue(rest.xpath("//style"))

    def test_totals_only_continuation_has_no_empty_table(self):
        _first, rest = _split_body(BODY, 5)
        self.assertFalse(_parse(rest).xpath("//table"))
        self.assertIn("TOTAL 100.00", rest)

    def test_footer_preserves_legal_only_on_first(self):
        first = _footer(FOOTER, total=3)
        rest = _footer(FOOTER, compact=True, total=3, offset=1)
        self.assertIn("LEGAL TEXT AND BANK DETAILS", first)
        self.assertIn("font-size: 7pt !important", first)
        self.assertIn("margin-bottom: 3pt !important", first)
        self.assertNotIn("LEGAL TEXT AND BANK DETAILS", rest)
        self.assertNotIn("font-size: 7pt !important", rest)
        self.assertIn("INV/TEST", first)
        self.assertIn("INV/TEST", rest)
        self.assertIn("function subst()", rest)
        self.assertIn("page + 1", rest)
        self.assertIn("sansha_final_page", rest)
        self.assertFalse(any(_has_class(node, "page") or _has_class(node, "topage")
                             for node in _parse(rest).iter()))

    def test_missing_footer_marker_is_an_error(self):
        with self.assertRaises(ValueError):
            _footer("<html><body>No legal marker</body></html>")
