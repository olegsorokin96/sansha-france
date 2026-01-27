# -*- coding: utf-8 -*-

from odoo import models, api
from odoo.tools.float_utils import float_round


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model
    def _prepare_order_line_vals(
        self, item, order, instance, product, qty, price, name
    ):
        """
        Prepare sale.order.line values.
        IMPORTANT:
        price MUST be tax EXCLUDED for Odoo.
        We override price logic to always use Magento row_total / qty.
        """

        # --- SAFE QTY ---
        qty = float(qty or 1.0)

        # --- MAGENTO VALUES ---
        # row_total in Magento is ALWAYS tax EXCLUDED
        row_total = item.get('row_total') or 0.0

        # --- FINAL UNIT PRICE (EXCL TAX) ---
        price_unit = row_total / qty if qty else 0.0

        # rounding according to product price precision
        price_unit = float_round(
            price_unit,
            precision_rounding=order.currency_id.rounding
        )

        vals = {
            'order_id': order.id,
            'product_id': product.id,
            'name': name,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'price_unit': price_unit,
        }

        # taxes are applied normally by Odoo
        if product.taxes_id:
            vals['tax_id'] = [(6, 0, product.taxes_id.ids)]

        return vals

    def __find_order_item_price(self, item, order_line, instance):
        """
        OVERRIDDEN LOGIC:
        Always return unit price EXCLUDING TAX.
        Magento row_total is subtotal without tax.
        """

        qty = float(order_line.get('qty_ordered') or 1.0)
        row_total = order_line.get('row_total') or 0.0

        if qty:
            return row_total / qty

        return 0.0
