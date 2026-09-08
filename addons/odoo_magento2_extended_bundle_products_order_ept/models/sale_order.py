# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""For Odoo Magento2 Connector Module"""
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

    def action_confirm(self):
        """
        This method inherited for identify the Magento order and pass the context
        to manage the BOM.
        :return: super call.
        """
        if self.magento_instance_id:
            return super(SaleOrder, self.with_context({'is_magento_order': True})).action_confirm()
        return super(SaleOrder, self).action_confirm()

    def create_sale_order_ept(self, item, instance, log_line, line_id):
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
