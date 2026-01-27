# -*- coding: utf-8 -*-

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.model
    def prepare_magento_order_line_vals(self, order, item):
        """
        Create sale.order.line values from Magento order item.

        IMPORTANT:
        - Magento confirmed:
            price = unit price EXCLUDING tax
            price_incl_tax = unit price INCLUDING tax
        - We MUST use `price`
        - NO recalculation
        - NO division
        - NO tax logic here
        """

        # Quantity
        qty = float(item.get("qty_ordered", 0.0))

        # UNIT PRICE — SINGLE SOURCE OF TRUTH
        price_unit = float(item.get("price", 0.0))

        # DEBUG LOG (do NOT remove while testing)
        _logger.warning(
            "[MAGENTO LINE] sku=%s qty=%s price=%s full_item=%s",
            item.get("sku"),
            qty,
            price_unit,
            item
        )

        vals = {
            "order_id": order.id,
            "product_id": self._get_product_from_magento_item(item).id,
            "name": item.get("name") or item.get("sku"),
            "product_uom_qty": qty,
            "price_unit": price_unit,
        }

        return vals

    def _get_product_from_magento_item(self, item):
        """
        Product resolution logic (unchanged).
        Assumes SKU mapping already works.
        """
        sku = item.get("sku")
        product = self.env["product.product"].search(
            [("default_code", "=", sku)],
            limit=1
        )

        if not product:
            raise ValueError(f"Product with SKU {sku} not found in Odoo")

        return product

