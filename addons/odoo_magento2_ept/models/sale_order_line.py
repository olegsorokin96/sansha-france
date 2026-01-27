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

    def create_order_line(self, item, instance, log_line, line_id):
        order_lines = item.get('items')
        rounding = bool(instance.magento_tax_rounding_method == 'round_per_line')

        for line in order_lines:
            if line.get('product_type') in ['configurable', 'bundle']:
                continue

            product = line.get('line_product')

            # 🔴 ВАЖНО: цена берётся ТОЛЬКО отсюда
            price = self.__find_order_item_price(item, line)

            customer_option = self.__get_custom_option(item, line)

            line_vals = self.with_context(
                custom_options=customer_option
            ).prepare_order_line_vals(
                item, line, product, price, instance
            )

            order_line = self.create(line_vals)
            order_line.with_context(round=rounding)._compute_amount()
            self.__create_line_desc_note(customer_option, item.get('sale_order_id'))

        return True

    # ============================================================
    # 🔥 ГЛАВНОЕ ИСПРАВЛЕНИЕ — ТОЛЬКО ЗДЕСЬ
    # ============================================================
    def __find_order_item_price(self, item, order_line):
        """
        Берём Magento → Price (unit price excluding tax)
        = row_total / qty_ordered
        """
        qty = float(order_line.get('qty_ordered') or 1.0)

        # row_total ВСЕГДА без налога
        row_total = float(order_line.get('row_total') or 0.0)

        if qty:
            return row_total / qty

        return 0.0

    @staticmethod
    def _find_option_desc(item, line_item_id):
        description = ""
        ept_option_title = item.get("extension_attributes", {}).get('ept_option_title')
        if ept_option_title:
            for custom_opt_itm in ept_option_title:
                custom_opt = json.loads(custom_opt_itm)
                if line_item_id == int(custom_opt.get('order_item_id')):
                    for option_data in custom_opt.get('option_data'):
                        description += (
                            option_data.get('label') + " : " +
                            option_data.get('value') + "\n"
                        )
        return description

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
                product_obj = self.env['product.product'].search(
                    [('default_code', '=', product_sku)], limit=1
                )
                if not product_obj:
                    log_line.create_common_log_line_ept(
                        message=f"Product {product_sku} not found in Odoo",
                        module='magento_ept',
                        order_ref=items.get('increment_id'),
                        magento_order_data_queue_line_id=line_id,
                        model_name=self._name,
                        magento_instance_id=instance.id
                    )
                    return False
                odoo_product = product_obj

            item.update({'line_product': odoo_product})

        return True

    def __get_custom_option(self, item, line):
        description = self._find_option_desc(item, line.get('item_id'))
        if description:
            return _("Custom Option for Product : %s\n%s") % (
                line.get('line_product').name, description
            )
        return ""

    def prepare_order_line_vals(self, item, line, product, price, instance):
        order_qty = float(line.get('qty_ordered') or 1.0)
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

        return vals

    def __create_line_desc_note(self, description, sale_order):
        if description:
            self.env['sale.order.line'].create({
                'name': description,
                'display_type': 'line_note',
                'order_id': sale_order.id,
            })

