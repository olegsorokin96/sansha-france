# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""For Odoo Magento2 Connector Module.

Custom Sansha behavior for Magento bundle orders:
- do NOT create/find a parent bundle product in Odoo;
- import the selected child SKUs as normal sale order lines;
- split the Magento parent bundle price equally between the child lines;
- put any rounding remainder on the last child line so totals remain exact.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @staticmethod
    def __find_discount_tax_percent(items):
        percent = False
        for item in items:
            if item.get('product_type') == 'bundle':
                continue
            percent = item.get('tax_percent') if 'tax_percent' in item.keys() and item.get('tax_percent') > 0 else False
            if percent:
                break
        return percent

    @staticmethod
    def _bundle_split_amount(total, count, index, precision='0.01'):
        """Split a monetary total equally, preserving the exact total after rounding."""
        if not count:
            return 0.0
        total_dec = Decimal(str(total or 0))
        quantum = Decimal(precision)
        regular = (total_dec / Decimal(count)).quantize(quantum, rounding=ROUND_HALF_UP)
        if index < count - 1:
            return float(regular)
        return float(total_dec - (regular * Decimal(count - 1)))

    def _expand_magento_bundles_to_children(self, item):
        """Replace Magento bundle parent lines with their selected child SKU lines.

        Magento dynamic-price bundles in our stores carry the whole price/tax on the
        parent line while selected simple children have price 0.  The connector's
        standard bundle extension expects a parent Odoo product/BoM.  Sansha does not
        maintain those dynamic Pack SKUs in Odoo, so we flatten each bundle instead.

        Example: Bundle EUR 29.90 incl. tax with 3 children becomes 9.97, 9.97,
        9.96 incl. tax.  Ex-tax/base/tax amounts are split independently so the
        Magento totals are preserved exactly.
        """
        original_items = item.get('items') or []
        bundle_parents = {
            line.get('item_id'): line
            for line in original_items
            if line.get('product_type') == 'bundle' and line.get('item_id')
        }
        if not bundle_parents:
            return item

        children_by_parent = {}
        for line in original_items:
            parent_id = line.get('parent_item_id')
            if parent_id in bundle_parents:
                children_by_parent.setdefault(parent_id, []).append(line)

        # Fields whose values belong to the priced bundle parent and must be
        # distributed across the physical child products.
        monetary_fields = (
            'price', 'base_price', 'price_incl_tax', 'base_price_incl_tax',
            'original_price', 'base_original_price',
            'row_total', 'base_row_total', 'row_total_incl_tax', 'base_row_total_incl_tax',
            'tax_amount', 'base_tax_amount',
            'discount_amount', 'base_discount_amount',
            'discount_tax_compensation_amount', 'base_discount_tax_compensation_amount',
            'row_invoiced', 'base_row_invoiced',
            'tax_invoiced', 'base_tax_invoiced',
            'discount_invoiced', 'base_discount_invoiced',
            'discount_tax_compensation_invoiced', 'base_discount_tax_compensation_invoiced',
        )

        flattened = []
        processed_parents = set()

        for line in original_items:
            # Parent bundle is replaced by its children at this exact position.
            if line.get('product_type') == 'bundle':
                parent_id = line.get('item_id')
                children = children_by_parent.get(parent_id, [])
                if not children:
                    # Keep it unchanged if Magento unexpectedly supplied no children;
                    # standard connector validation will then report the real problem.
                    flattened.append(line)
                    continue

                count = len(children)
                parent_qty = float(line.get('qty_ordered') or 1.0)
                for idx, source_child in enumerate(children):
                    child = deepcopy(source_child)
                    child.pop('parent_item', None)
                    child.pop('parent_item_id', None)

                    # Child quantity already represents the ordered physical quantity.
                    # Parent qty is only used to convert parent unit prices to the
                    # corresponding child unit price when bundle qty > 1.
                    child_qty = float(child.get('qty_ordered') or 1.0)
                    qty_ratio = child_qty / parent_qty if parent_qty else 1.0
                    if not qty_ratio:
                        qty_ratio = 1.0

                    for field in monetary_fields:
                        if field not in line:
                            continue
                        value = line.get(field) or 0.0
                        split_value = self._bundle_split_amount(value, count, idx)

                        # price/original_price are unit amounts; row/tax/discount
                        # fields are totals. For normal bundle selections qty_ratio=1.
                        if field in (
                            'price', 'base_price', 'price_incl_tax', 'base_price_incl_tax',
                            'original_price', 'base_original_price',
                        ):
                            split_value = split_value / qty_ratio
                        child[field] = split_value

                    # Make tax detection treat children like the priced parent.
                    child['tax_percent'] = line.get('tax_percent', child.get('tax_percent', 0))
                    child['discount_percent'] = line.get('discount_percent', child.get('discount_percent', 0))
                    child['free_shipping'] = line.get('free_shipping', child.get('free_shipping', 0))

                    flattened.append(child)

                processed_parents.add(parent_id)
                continue

            # Original bundle children were already inserted above; do not duplicate.
            if line.get('parent_item_id') in processed_parents or line.get('parent_item_id') in bundle_parents:
                continue

            flattened.append(line)

        item['items'] = flattened
        return item

    def action_confirm(self):
        """Identify Magento orders and pass context used by the connector."""
        if self.magento_instance_id:
            return super(SaleOrder, self.with_context({'is_magento_order': True})).action_confirm()
        return super(SaleOrder, self).action_confirm()

    def create_sale_order_ept(self, item, instance, log_line, line_id):
        # IMPORTANT: flatten bundles BEFORE find_order_item(). This prevents the base
        # connector from trying to find the dynamic Pack6-... parent SKU in Odoo.
        item = self._expand_magento_bundles_to_children(item)

        is_processed = self._find_price_list(item, log_line, line_id, instance)
        order_line = self.env['sale.order.line']
        if is_processed:
            customers = self.__update_partner_dict(item, instance)
            data = self.env['magento.res.partner.ept'].create_magento_customer(customers, True)
            item.update(data)
            is_processed = self.__find_order_warehouse(item, log_line, line_id)
            if is_processed:
                is_processed = order_line.with_context(bundle_ept=True).find_order_item(item, instance, log_line, line_id)
                is_processed = self.__find_order_tax(item, instance, log_line, line_id)
                if is_processed:
                    vals = self._prepare_order_dict(item, instance)
                    magento_order = self.create(vals)
                    item.update({'sale_order_id': magento_order})
                    is_processed = order_line.create_order_line(item, instance, log_line, line_id)
                    if not is_processed:
                        magento_order.unlink()
                        return False
                    self.__create_discount_order_line(item, instance)
                    self.__create_shipping_order_line(item, instance)
                    self.__process_order_workflow(item, log_line)
        return is_processed
