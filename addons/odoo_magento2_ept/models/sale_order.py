# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""For Odoo Magento2 Connector Module"""

from odoo import models, fields, _
import json

class SaleOrderLine(models.Model):
    """
    Describes Sale order line
    """
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
            price = self.__find_order_item_price(item, line, instance)
            customer_option = self.__get_custom_option(item, line)

            line_vals = self.with_context(custom_options=customer_option).prepare_order_line_vals(
                item, line, product, price, instance
            )

            order_line = self.create(line_vals)
            order_line.with_context(round=rounding)._compute_amount()
            self.__create_line_desc_note(customer_option, item.get('sale_order_id'))

        return True

    # ============================================================
    # PRICE LOGIC — FIXED
    # ============================================================
    def __find_order_item_price(self, item, order_line, instance):
        """
        IMPORTANT:
        Price must be taken strictly from Magento order line totals.
        No tax or price recomputation must happen in Odoo.
        """
        qty = float(order_line.get('qty_ordered', 1.0)) or 1.0

        if instance.is_order_base_currency:
            row_total = float(order_line.get('base_row_total', 0.0))
        else:
            row_total = float(order_line.get('row_total', 0.0))

        return row_total / qty

    # ============================================================
    # HELPERS
    # ============================================================
    @staticmethod
    def _find_option_desc(item, line_item_id):
        description = ""
        ept_option_title = item.get("extension_attributes").get('ept_option_title')
        if ept_option_title:
            for custom_opt_itm in ept_option_title:
                custom_opt = json.loads(custom_opt_itm)
                if line_item_id == int(custom_opt.get('order_item_id')):
                    for option_data in custom_opt.get('option_data'):
                        description += option_data.get('label') + " : " + option_data.get('value') + "\n"
        return description

    def find_order_item(self, items, instance, log_line, line_id):
        for item in items.get('items'):
            if item.get('product_type') == 'bundle' and 'bundle_ept' in list(self.env.context.keys()):
                continue

            product_sku = item.get('sku')
            magento_product = self.env['magento.product.product'].search([
                '|',
                ('magento_product_id', '=', item.get('product_id')),
                ('magento_sku', '=', product_sku),
                ('magento_instance_id', '=', instance.id)
            ], limit=1)

            if not magento_product:
                product_obj = self.env['product.product'].search([('default_code', '=', product_sku)])
                if not product_obj:
                    message = _(
                        "An order %s was skipped because the ordered product %s does not exist in Odoo."
                        % (items.get('increment_id'), product_sku)
                    )
                    log_line.create_common_log_line_ept(
                        message=message,
                        module='magento_ept',
                        order_ref=items.get('increment_id'),
                        magento_order_data_queue_line_id=line_id,
                        model_name=self._name,
                        magento_instance_id=instance.id
                    )
                    return False

                if len(product_obj) > 1:
                    message = _(
                        "An order %s was skipped because the ordered product %s exists multiple times in Odoo."
                        % (items.get('increment_id'), product_sku)
                    )
                    log_line.create_common_log_line_ept(
                        message=message,
                        module='magento_ept',
                        order_ref=items.get('increment_id'),
                        magento_order_data_queue_line_id=line_id,
                        model_name=self._name,
                        magento_instance_id=instance.id
                    )
                    return False

                odoo_product = product_obj
            else:
                odoo_product = magento_product.odoo_product_id

            item.update({'line_product': odoo_product})

        return True

    def __get_custom_option(self, item, line):
        custom_options = ''
        description = self._find_option_desc(item, line.get('item_id'))
        if description:
            product_name = _("Custom Option for Product : %s \n" % line.get('line_product').name)
            custom_options = product_name + description
        return custom_options

    def prepare_order_line_vals(self, item, line, product, price, instance):
        order_qty = float(line.get('qty_ordered', 1.0))
        sale_order = item.get('sale_order_id')
        order_line_ref = line.get('parent_item_id') or line.get('item_id')

        line_vals = {
            'order_id': sale_order.id,
            'product_id': product.id,
            'company_id': sale_order.company_id.id,
            'name': item.get('name'),
            'description': product.name or sale_order.name,
            'product_uom_id': product.uom_id.id,
            'order_qty': order_qty,
            'price_unit': price,
        }

        line_vals = self.create_sale_order_line_ept(line_vals)
        line_vals.update({'magento_sale_order_line_ref': order_line_ref})

        if instance.magento_apply_tax_in_order == 'create_magento_tax':
            tax_ids = item.get(f'order_tax_{line.get("item_id")}')
            if tax_ids:
                line_vals.update({'tax_ids': [(6, 0, tax_ids)]})
            else:
                line_vals.update({'tax_ids': False})

        store_view = item.get('store_view')
        magento_account = (
            instance.magento_analytic_account_id.id
            if instance.magento_analytic_account_id
            else store_view.magento_website_id.m_website_analytic_account_id.id
            if store_view and store_view.magento_website_id
            else False
        )

        if magento_account:
            line_vals.update({'analytic_distribution': {magento_account: 100}})

        return line_vals

    def __create_line_desc_note(self, description, sale_order):
        if description:
            self.env['sale.order.line'].create({
                'name': description,
                'display_type': 'line_note',
                'product_id': False,
                'product_uom_id': False,
                'price_unit': 0,
                'order_id': sale_order.id,
            })

    def create_sale_order_line_ept(self, vals):
        """
        Prepare order line values using Odoo onchange logic
        """
        sale_order_line = self.env['sale.order.line']

        order_line = {
            'order_id': vals.get('order_id'),
            'product_id': vals.get('product_id'),
            'company_id': vals.get('company_id'),
            'name': vals.get('description'),
            'product_uom_id': vals.get('product_uom_id'),
        }

        new_line = sale_order_line.new(order_line)
        new_line._compute_name()
        new_line._compute_tax_ids()
        new_line._onchange_product_id()
        new_line._compute_customer_lead()

        order_line = sale_order_line._convert_to_write(
            {name: new_line[name] for name in new_line._cache}
        )

        order_line.update({
            'order_id': vals.get('order_id'),
            'product_uom_qty': vals.get('order_qty', 0.0),
            'price_unit': vals.get('price_unit', 0.0),
            'discount': 0.0,
            'state': 'draft',
        })

        return order_line
