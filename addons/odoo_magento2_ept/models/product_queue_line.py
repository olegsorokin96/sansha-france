# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods to store sync/ Import product queue line
"""
import json
from datetime import datetime
from odoo import models, fields, _


class MagentoProductQueueLine(models.Model):
    """
    Describes sync/ Import product Queue Line
    """
    _name = "sync.import.magento.product.queue.line"
    _description = "Sync/ Import Product Queue Line"
    _rec_name = "product_sku"
    queue_id = fields.Many2one(comodel_name="sync.import.magento.product.queue", ondelete="cascade")
    instance_id = fields.Many2one(comodel_name='magento.instance',
                                  string='Instance',
                                  help="Products imported from or Synced to this Magento Instance.")
    state = fields.Selection([("draft", "Draft"), ("failed", "Failed"), ("done", "Done"),
                              ("cancel", "Cancelled")], default="draft", copy=False)
    product_sku = fields.Char(string="SKU", help="SKU of imported product.", copy=False)
    data = fields.Text(string="", help="Product Data imported from magento.", copy=False)
    processed_at = fields.Datetime(help="Shows Date and Time, When the data is processed",
                                   copy=False)
    log_lines_ids = fields.One2many("common.log.lines.ept", "magento_import_product_queue_line_id",
                                    help="Log lines created against which line.")
    do_not_update_existing_product = fields.Boolean(string="Do not update existing Products?",
                                                    help="If checked and Product(s) found in "
                                                         "odoo/magento layer, then not "
                                                         "update the Product(s)")

    def create_product_queue_line(self, **kwargs):
        queueline = self.search([('instance_id', '=', kwargs.get('instance_id')),
                                 ('product_sku', '=', kwargs.get('product', {}).get('sku')),
                                 ('state', '=', 'draft')], limit=1, order='id desc')
        if queueline:
            queueline.write({'data': json.dumps(kwargs.get('product'))})
            return queueline

        values = self.__prepare_product_queue_line_values(**kwargs)
        return self.create(values)

    @staticmethod
    def __prepare_product_queue_line_values(**kwargs):
        return {
            'product_sku': kwargs.get('product', {}).get('sku'),
            'instance_id': kwargs.get('instance_id'),
            'data': json.dumps(kwargs.get('product')),
            'queue_id': kwargs.get('queue_id', False),
            'state': 'draft',
            'do_not_update_existing_product': kwargs.get('is_update', False)
        }

    def magento_create_product_queue(self, instance):
        """
        This method used to create a product queue as per the split requirement of the
        queue. It is used for process the queue manually
        :param instance: instance of Magento
        """
        product_queue_vals = {
            'instance_id': instance and instance.id or False,
            'state': 'draft'
        }
        product_queue_data_id = self.env["sync.import.magento.product.queue"].create(
            product_queue_vals)
        return product_queue_data_id

    def auto_import_magento_product_queue_data(self):
        """
        This method used to process synced magento product data in batch of 50 queue lines.
        This method is called from cron job.
        """
        query = """ SELECT queue_id FROM sync_import_magento_product_queue_line WHERE state = 'draft'
                    GROUP BY queue_id, create_date
                    ORDER BY create_date ASC
                """
        self.env.cr.execute(query)
        queue_ids = [queue.get('queue_id') for queue in self.env.cr.dictfetchall()]
        queues = self.env[self.queue_id._name].browse(queue_ids)
        queues.filtered(lambda q: not q.is_action_require)
        queues.process_product_queues()
        return True

    def process_queue_line(self):
        for line in self:
            item = json.loads(line.data)
            is_processed = self.import_products(item, line)
            if is_processed:
                line.write({'state': 'done', 'processed_at': datetime.now(), 'data': False})
            else:
                line.write({'state': 'failed', 'processed_at': datetime.now()})
            self.env.cr.commit()
        return True

    def import_products(self, item, line):
        instance = line.instance_id
        m_product = self.env['magento.product.product']
        attribute = item.get('extension_attributes', {})
        if item.get('type_id') == 'simple':
            product = self.env['product.product']
            m_product = self.env['magento.product.product']
            product = product.search([('default_code', '=', item.get('sku'))], limit=1)
            if product:
                if 'simple_parent_id' in list(attribute.keys()):
                    return m_product.with_context(is_child=True).search_product_in_layer(line, item)
                return m_product.search_product_in_layer(line, item)
                # return m_product._map_product_in_layer(line, item, product)
            elif 'simple_parent_id' in list(attribute.keys()):
                m_product = m_product.search([('magento_product_id', '=', item.get('id'))], limit=1)
                if not m_product or 'is_order' in list(self.env.context.keys()) or line.do_not_update_existing_product:
                    # This case only runs when we get the simple product which are used as an
                    # Child product of any configurable product in Magento.
                    items = m_product.get_products(instance, [attribute.get('simple_parent_id')], line)
                    for item in items:
                        return m_product.import_configurable_product(line, item)
            else:
                # This case identifies that we get only simple product which are not set as an
                # Child product of any configurable product.
                return m_product.search_product_in_layer(line, item)
        elif item.get('type_id') == 'configurable':
            return m_product.import_configurable_product(line, item)
        elif item.get('type_id') in ['virtual', 'downloadable']:
            return m_product.search_service_product(item, line)
        else:
            # We are not allowing to import other types of products. Add log for that.
            return self.__search_product(line, item)
        return True

    def __search_product(self, line, item):
        log_line = self.env['common.log.lines.ept']
        product = self.env['product.product']
        product = product.search([('default_code', '=', item.get('sku'))], limit=1)
        if not product:
            message = _(f"""
            Order '{item.get('increment_id')}' has been skipped because the product type 
            '{item.get('type_id')}' SKU '{item.get('sku')}' is not found in Odoo. \n
            Please create the product in Odoo with the same SKU to import the order. \n
            Note: \n
            - In the case where the Magento product type is a group, please create a Storable or 
            Service type product with the same SKU for every child product of the Magento group. \n
            - Create a Service type product in Odoo if the Magento group's child product is virtual 
            or downloadable, and if the child product is simple in Magento, create a storable \n
            type product in Odoo with the same SKU. 
            """)
            if 'is_order' in (self.env.context.keys()):
                log_line.create_common_log_line_ept(message=message, module='magento_ept', order_ref=item.get('increment_id', ''),
                                                    res_id=line.id, model_name=line._name,
                                                    magento_order_data_queue_line_id= line.id,
                                                    default_code=item.get('sku'),
                                                    magento_instance_id=line.instance_id.id)
            else:
                log_line.create_common_log_line_ept(message=message, module='magento_ept', order_ref=item.get('increment_id', ''),
                                                    res_id=line.id, model_name=line._name,
                                                    magento_import_product_queue_line_id=line.id,
                                                    default_code=item.get('sku'),
                                                    magento_instance_id=line.instance_id.id)
            line.queue_id.write({'is_process_queue': False})
            self.env.cr.commit()
            return False
        return True
