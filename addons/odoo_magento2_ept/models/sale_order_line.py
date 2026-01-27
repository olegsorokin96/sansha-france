# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""For Odoo Magento2 Connector Module"""

from odoo import models, fields, _
import json

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    magento_sale_order_line_ref = fields.Char(
        string="Magento Sale Order Line Reference",
        help="Magento Sale Order Line Reference"
    )

    # ============================================================
    # MAIN ENTRY
    # ============================================================

    def create_order_line(self, item, instance, log_line, line_id):
        order_lines = item.get('items')
        rounding = bool(instance.magento_tax_rounding_method == 'round_per_line')

        for line in order_lines:
            if line.get('product_type') in ['configurable', 'bundle']:
                continue

            product = line.get('line_product')
            price_unit = self._get_ht_unit_price_from_magento(line, instance)
            customer_option = self._get_custom_option(item, line)

            line_vals = self.with_context(
                custom_options=customer_option
            ).prepare_order_line_vals(
                item, line, product, price_unit, instance
            )

            order_line = self.create(line_vals)
            order_line.with_context(round=rounding)._compute_amount()

            self._create_line_desc_note(customer_option, item.get('sale_order_id'))

        return True

    # ============================================================
    # PRICE LOGIC (HT ONLY – ODOO APPLIES TAX)
    # ============================================================

    def _get_ht_unit_price_from_magento(self, order_line, instance):
        """
        ALWAYS return HT unit price from Magento.
        Odoo will apply VAT.
        """
        if instance.is_order_base_currency:
            row_total = self._get_price_field(order_line, 'base_row_total')
        else:
            row_total = self._get_price_field(order_line, 'row_total')

        qty = float(order_line.get('qty_ordered') or 1.0)
        return (row_total / qty) if qty else 0.0

    @staticmethod
    def _get_price_field(item, field):
        if "parent_item" in item:
            return item.get('parent_item', {}).get(field, 0.0)
        return item.get(field, 0.0)

    # ============================================================
    # PRODUCT MATCHING
    # ============================================================

    def find_order_item(self, items, instance, log_line, line_id):
        for item in items.get('items'):
            if item.get('product_type') == 'bundle' and 'bundle_ept' in self.env.context:
                continue

            product_sku = item.get('sku')
            magento_product = self.env['magento.product.product'].search([
                '|',
                ('magento_product_id', '=', item.get('product_id')),
                ('magento_sku', '=', product_sku),
                ('magento_instance_id', '=', instance.id)
            ], limit=1)

            if magento_product:
                odoo_product = magento_product.odoo_product_id
            else:
                odoo_product = self.env['product.product'].search(
                    [('default_code', '=', product_sku)], limit=1
                )
                if not odoo_product:
                    message = _(
                        "Order %s skipped: product %s not found in Odoo."
                    ) % (items.get('increment_id'), product_sku)
                    log_line.create_common_log_line_ept(
                        message=message,
                        module='magento_ept',
                        order_ref=items.get('increment_id'),
                        magento_order_data_queue_line_id=line_id,
                        model_name=self._name,
                        magento_instance_id=instance.id
                    )
                    return False

            item.update({'line_product': odoo_product})

        return True

    # ============================================================
    # ORDER LINE VALUES
    # ============================================================

    def prepare_order_line_vals(self, item, line, product, price, instance):
        order_qty = float(line.get('qty_ordered', 1.0))
        sale_order = item.get('sale_order_id')
        order_line_ref = line.get('parent_item_id') or line.get('item_id')

        vals = {
            'order_id': sale_order.id,
            'product_id': product.id,
            'company_id': sale_order.company_id.id,
            'name': product.name,
            'product_uom_id': product.uom_id.id,
            'product_uom_qty': order_qty,
            'price_unit': price,
            'magento_sale_order_line_ref': order_line_ref,
        }

        # TAXES (unchanged – Odoo logic)
        if instance.magento_apply_tax_in_order == 'create_magento_tax':
            tax_ids = item.get(f'order_tax_{line.get("item_id")}')
            if tax_ids:
                vals.update({'tax_ids': [(6, 0, tax_ids)]})
            else:
                vals.update({'tax_ids': False})

        # ANALYTIC ACCOUNT (unchanged)
        store_view = item.get('store_view')
        analytic_account = (
            instance.magento_analytic_account_id.id
            if instance.magento_analytic_account_id
            else store_view.magento_website_id.m_website_analytic_account_id.id
            if store_view and store_view.magento_website_id.m_website_analytic_account_id
            else False
        )
        if analytic_account:
            vals.update({
                'analytic_distribution': {analytic_account: 100}
            })

        return vals

    # ============================================================
    # CUSTOM OPTIONS / NOTES
    # ============================================================

    def _get_custom_option(self, item, line):
        description = self._find_option_desc(item, line.get('item_id'))
        if description:
            return _("Custom Option for Product:\n%s") % description
        return ''

    @staticmethod
    def _find_option_desc(item, line_item_id):
        description = ""
        ext = item.get("extension_attributes", {})
        options = ext.get('ept_option_title', [])
        for opt in options:
            data = json.loads(opt)
            if line_item_id == int(data.get('order_item_id')):
                for o in data.get('option_data', []):
                    description += f"{o.get('label')} : {o.get('value')}\n"
        return description

    def _create_line_desc_note(self, description, sale_order):
        if description:
            self.env['sale.order.line'].create({
                'order_id': sale_order.id,
                'name': description,
                'display_type': 'line_note',
                'price_unit': 0.0,
            })
