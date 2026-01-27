# -*- coding: utf-8 -*-

from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    magento_item_id = fields.Char(string='Magento Item ID')

    # ------------------------------------------------------------
    # PRICE HANDLING
    # ------------------------------------------------------------

    def _get_magento_unit_price(self, item):
        """
        Safely determine Magento unit price (EXCL. TAX).

        Priority:
        1. row_total
        2. row_total_incl_tax
        3. price * qty
        """

        qty = float(item.get('qty_ordered') or 1.0)

        row_total = (
            item.get('row_total')
            or item.get('row_total_incl_tax')
        )

        try:
            row_total = float(row_total)
        except Exception:
            row_total = 0.0

        if not row_total:
            try:
                price = float(item.get('price') or 0.0)
                row_total = price * qty
            except Exception:
                row_total = 0.0

        if qty:
            return row_total / qty

        return 0.0

    # ------------------------------------------------------------
    # CREATE / UPDATE FROM MAGENTO
    # ------------------------------------------------------------

    @api.model
    def create_or_update_magento_order_line(
        self,
        order,
        item,
        product,
        tax_ids=False
    ):
        """
        Create or update sale.order.line from Magento item
        """

        qty = float(item.get('qty_ordered') or 0.0)

        price_unit = self._get_magento_unit_price(item)

        _logger.info(
            "[MAGENTO PRICE] SKU=%s qty=%s price_unit=%s",
            item.get('sku'),
            qty,
            price_unit
        )

        vals = {
            'order_id': order.id,
            'product_id': product.id,
            'name': item.get('name') or product.display_name,
            'product_uom_qty': qty,
            'price_unit': price_unit,
            'magento_item_id': item.get('item_id'),
        }

        if tax_ids:
            vals['tax_id'] = [(6, 0, tax_ids.ids)]

        line = self.search([
            ('order_id', '=', order.id),
            ('magento_item_id', '=', item.get('item_id')),
        ], limit=1)

        if line:
            line.write(vals)
            return line

        return self.create(vals)
