# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""For Odoo Magento2 Connector Module"""
from collections import defaultdict
from odoo.tools import float_compare, OrderedSet
from odoo import models, fields, api


class StockRule(models.Model):
    _inherit = 'stock.rule'

    # mrp_production_ids = fields.One2many('mrp.production', 'procurement_group_id')

    @api.model
    def run(self, procurements, raise_user_error=True):
        """ If 'run' is called on a kit, this override is made in order to call
        the original 'run' method with the values of the components of that kit.
        """
        procurements_without_kit = []
        product_by_company = defaultdict(OrderedSet)
        for procurement in procurements:
            product_by_company[procurement.company_id].add(procurement.product_id.id)
        kits_by_company = {
            company: self.env['mrp.bom']._bom_find(self.env['product.product'].browse(product_ids), company_id=company.id, bom_type='phantom')
            for company, product_ids in product_by_company.items()
        }
        for procurement in procurements:
            bom_kit = kits_by_company[procurement.company_id].get(procurement.product_id)
            """
            [MOD][MAYURJ]
            --START--[28.09.2021]
            If the order is Magento order and we get is_magento_order the key in context
            Then we will update the BOM product. It happens when the multiple BOM available
            for any product at that time for the identification of actual BOM we have store
            the BOM ID in sale order line.
            """
            if 'is_magento_order' in self.env.context.keys() and procurement.values.get('sale_line_id', ''):
                order_line = self.env['sale.order.line'].browse(procurement.values.get('sale_line_id'))
                bom_kit = order_line.magento_bom_id
            """
            --OVER--[28.09.2021]
            """
            if bom_kit:
                order_qty = procurement.product_uom._compute_quantity(procurement.product_qty, bom_kit.product_uom_id, round=False)
                qty_to_produce = (order_qty / bom_kit.product_qty)
                _dummy, bom_sub_lines = bom_kit.explode(procurement.product_id, qty_to_produce,never_attribute_values=procurement.values.get("never_product_template_attribute_value_ids"))
                for bom_line, bom_line_data in bom_sub_lines:
                    bom_line_uom = bom_line.product_uom_id
                    quant_uom = bom_line.product_id.uom_id
                    # recreate dict of values since each child has its own bom_line_id
                    values = dict(procurement.values, bom_line_id=bom_line.id)
                    component_qty, procurement_uom = bom_line_uom._adjust_uom_quantities(bom_line_data['qty'], quant_uom)
                    procurements_without_kit.append(self.env['stock.rule'].Procurement(
                        bom_line.product_id, component_qty, procurement_uom,
                        procurement.location_id, procurement.name,
                        procurement.origin, procurement.company_id, values))
            else:
                procurements_without_kit.append(procurement)
        return super().run(procurements_without_kit, raise_user_error=raise_user_error)
