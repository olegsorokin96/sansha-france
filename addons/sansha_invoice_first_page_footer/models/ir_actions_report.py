"""Render the first invoice page and its continuation with distinct margins.

Opt-in: sansha_invoice_footer.enabled = True (System Parameters).
This works with Sansha's existing Bold v2 template; it does not replace views.
"""
import io
import logging
from collections import OrderedDict

from lxml import etree, html

from odoo import models, _
from odoo.exceptions import UserError
from odoo.tools.pdf import PdfFileReader, PdfFileWriter

from ..pagination import select_first_page

_logger = logging.getLogger(__name__)
_PREFIX = "sansha_invoice_footer."


def _has_class(node, name):
    return name in (node.get("class") or "").split()


def _parse(text):
    return html.document_fromstring(str(text))


def _serialize(tree):
    return html.tostring(tree, encoding="unicode", method="html")


def _table(tree):
    tables = tree.xpath('//table[@name="invoice_line_table"]')
    if len(tables) != 1:
        raise ValueError("Expected exactly one invoice_line_table")
    return tables[0]


def _rows(table):
    return table.xpath("./tbody/tr")


def _trim_siblings(node, before):
    """Trim through the article boundary, retaining styles and scripts."""
    while node is not None:
        parent = node.getparent()
        if parent is None:
            break
        siblings = list(parent)
        index = siblings.index(node)
        unwanted = siblings[:index] if before else siblings[index + 1:]
        for sibling in unwanted:
            if sibling.tag not in ("style", "script", "link"):
                # Preserve assets even if an inherited view wrapped them.
                assets = list(sibling.xpath(".//style | .//link"))
                for asset in assets:
                    asset.getparent().remove(asset)
                    parent.insert(0, asset)
                parent.remove(sibling)
        if _has_class(parent, "article"):
            break
        node = parent


def _split_body(body, first_count):
    """Partition rendered rows exactly once; keep totals only in continuation."""
    first = _parse(body)
    first_table = _table(first)
    all_rows = _rows(first_table)
    if not 0 <= first_count <= len(all_rows):
        raise ValueError("Invalid split position")
    for row in all_rows[first_count:]:
        row.getparent().remove(row)
    _trim_siblings(first_table, before=False)

    rest = _parse(body)
    rest_table = _table(rest)
    for row in _rows(rest_table)[:first_count]:
        row.getparent().remove(row)
    _trim_siblings(rest_table, before=True)
    if not _rows(rest_table):
        # All items fit on page one but totals need a continuation page.
        rest_table.getparent().remove(rest_table)
    return _serialize(first), _serialize(rest)


def _footer(footer, compact=False, total=None, offset=0):
    """Retain native footer positioning; remove legal text only in continuation."""
    tree = _parse(footer)
    # Remove the earlier hide-only workaround. Other scripts, including Odoo's
    # subst(), are preserved.
    for script in tree.xpath("//script"):
        if "sansha_invoice_first_page_footer" in (script.text or ""):
            script.getparent().remove(script)

    legal = [node for node in tree.iter()
             if _has_class(node, "sansha_invoice_first_page_footer")]
    if not legal:
        raise ValueError("Bold v2 legal footer marker is missing")
    for node in legal:
        node.attrib.pop("style", None)
        node.set("style", "line-height: 1.1;")
        if compact:
            node.clear()

    if not compact:
        # Pin legal typography instead of inheriting incidental footer/body
        # styles. A separate, larger page-one margin is reserved below.
        style = etree.Element("style", type="text/css")
        style.text = """
            .sansha_invoice_first_page_footer,
            .sansha_invoice_first_page_footer * {
                font-size: 7pt !important;
                line-height: 1.2 !important;
                white-space: normal !important;
            }
            .sansha_invoice_first_page_footer p {
                margin-top: 0 !important;
                margin-bottom: 3pt !important;
            }
            .sansha_invoice_first_page_footer p:last-child {
                margin-bottom: 0 !important;
            }
        """
        tree.find("head").append(style)

    if total is not None:
        # Avoid subst() replacing these counters with chunk-local page numbers.
        for node in tree.iter():
            classes = (node.get("class") or "").split()
            if "page" in classes:
                classes.remove("page")
                classes.append("sansha_final_page")
                node.text = str(offset + 1)
            if "topage" in classes:
                classes.remove("topage")
                node.text = str(total)
            if "class" in node.attrib:
                node.set("class", " ".join(classes))
        script = etree.Element("script", type="text/javascript")
        # wkhtmltopdf supplies sitepage for the page within this rendered chunk.
        # Run immediately: these spans are excluded from Odoo's subst() counters.
        script.text = """
            (function () {
                var match = window.location.search.match(/[?&]sitepage=([^&]+)/);
                if (!match) { match = window.location.search.match(/[?&]page=([^&]+)/); }
                var page = match ? parseInt(decodeURIComponent(match[1]), 10) : 1;
                if (!isFinite(page)) { page = 1; }
                var nodes = document.getElementsByClassName('sansha_final_page');
                for (var i = 0; i < nodes.length; i++) {
                    nodes[i].textContent = String(page + OFFSET);
                }
            }());
        """.replace("OFFSET", str(offset))
        tree.find("body").append(script)
    return _serialize(tree)


def _page_count(content):
    return PdfFileReader(io.BytesIO(content)).numPages


def _join(first, rest):
    writer = PdfFileWriter()
    # Keep readers and streams alive until writer.write() has finished.
    streams = [io.BytesIO(first), io.BytesIO(rest)]
    readers = [PdfFileReader(stream) for stream in streams]
    for reader in readers:
        writer.appendPagesFromReader(reader)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _sansha_pagination_enabled(self, report_ref):
        params = self.env["ir.config_parameter"].sudo()
        enabled = params.get_param(_PREFIX + "enabled", "").lower() in (
            "1", "true", "yes",
        )
        if not enabled or not report_ref:
            return False
        report = self._get_report(report_ref)
        names = params.get_param(
            _PREFIX + "report_names",
            "account.report_invoice,account.report_invoice_with_payments",
        )
        return report.model == "account.move" and report.report_name in {
            name.strip() for name in names.split(",") if name.strip()
        }

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        # Render a batch one invoice at a time so the native attachment logic
        # still receives one complete PDF stream for each account.move.
        if (res_ids and len(res_ids) > 1
                and self._sansha_pagination_enabled(report_ref)):
            if len(set(res_ids)) != len(res_ids):
                raise UserError(_("Print each invoice once per batch."))
            streams = OrderedDict()
            for record_id in res_ids:
                streams.update(super()._render_qweb_pdf_prepare_streams(
                    report_ref, dict(data or {}), res_ids=[record_id],
                ))
            return streams
        return super()._render_qweb_pdf_prepare_streams(
            report_ref, data, res_ids=res_ids,
        )

    def _run_wkhtmltopdf(
        self, bodies, report_ref=False, header=None, footer=None,
        landscape=False, specific_paperformat_args=None, set_viewport_size=False,
    ):
        render = super()._run_wkhtmltopdf
        common = dict(
            report_ref=report_ref, header=header, landscape=landscape,
            set_viewport_size=set_viewport_size,
        )
        arguments = dict(specific_paperformat_args or {})
        if not self._sansha_pagination_enabled(report_ref):
            return render(bodies, footer=footer,
                          specific_paperformat_args=arguments, **common)
        bodies = list(bodies)
        if len(bodies) != 1 or not footer:
            raise UserError(_("Sansha pagination requires one invoice body and its Bold footer."))

        paperformat = self._get_report(report_ref).get_paperformat()
        original_bottom = arguments.get(
            "data-report-margin-bottom", paperformat.margin_bottom,
        )
        # A readable legal block needs more room on page one only. Do not
        # alter the shared A4 record or the continuation's 12 mm margin.
        arguments["data-report-margin-bottom"] = max(float(original_bottom), 70)

        try:
            body = bodies[0]
            table = _table(_parse(body))
            rows = _rows(table)
            full_footer = _footer(footer)
            # Render page one with the readable legal block's reserved margin.
            original = render(
                [body], footer=full_footer,
                specific_paperformat_args=arguments, **common,
            )
            if _page_count(original) == 1:
                return original

            cache = {}

            def fits(count):
                if count not in cache:
                    first_body, _rest_body = _split_body(body, count)
                    cache[count] = render(
                        [first_body], footer=full_footer,
                        specific_paperformat_args=arguments, **common,
                    )
                return _page_count(cache[count]) == 1

            count = select_first_page(
                len(rows), fits,
                lambda index: _has_class(rows[index], "o_line_section"),
            )
            first_body, rest_body = _split_body(body, count)
            small_arguments = dict(arguments)
            small_arguments["data-report-margin-bottom"] = 12
            # The original first page starts with the address block's own
            # spacing. After removing it the table needs explicit clearance
            # below Bold's large logo and company header.
            original_top = arguments.get(
                "data-report-margin-top", paperformat.margin_top,
            )
            small_arguments["data-report-margin-top"] = float(original_top) + 10
            compact_footer = _footer(footer, compact=True)
            rest_pdf = render(
                [rest_body], footer=compact_footer,
                specific_paperformat_args=small_arguments, **common,
            )
            total = 1 + _page_count(rest_pdf)
            first_pdf = render(
                [first_body], footer=_footer(footer, total=total),
                specific_paperformat_args=arguments, **common,
            )
            rest_pdf = render(
                [rest_body], footer=_footer(footer, compact=True, total=total, offset=1),
                specific_paperformat_args=small_arguments, **common,
            )
            if _page_count(first_pdf) != 1 or 1 + _page_count(rest_pdf) != total:
                raise ValueError("Pagination changed while rendering final counters")
            _logger.info(
                "Sansha invoice pagination: %s/%s rows on page one; %s pages",
                count, len(rows), total,
            )
            return _join(first_pdf, rest_pdf)
        except (ValueError, etree.ParserError) as error:
            _logger.exception("Sansha invoice pagination failed")
            raise UserError(_(
                "Cannot paginate this invoice safely: %s. "
                "Disable sansha_invoice_footer.enabled to restore standard printing.",
                str(error),
            )) from error
