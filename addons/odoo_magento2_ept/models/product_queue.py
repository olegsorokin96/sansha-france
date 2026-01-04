# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes methods for sync/ Import product queues.
"""
import math
import logging
import time
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .api_request import req, create_search_criteria
from ..python_library.php import Php

_logger = logging.getLogger('MagentoProductQueue')


class MagentoProductQueue(models.Model):
    """
    Describes sync/ Import product queues.
    """
    _name = "sync.import.magento.product.queue"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Sync/ Import Product Queue"

    name = fields.Char(help="Sequential name of imported/ Synced products.", copy=False)
    instance_id = fields.Many2one(comodel_name='magento.instance', string='Instance',
                                  help="Product imported from or Synced to this Magento Instance.")
    state = fields.Selection([('draft', 'Draft'), ('partially_completed', 'Partially Completed'),
                              ('completed', 'Completed'), ('failed', 'Failed')
                              ], default='draft', copy=False, help="Status of Order Data Queue",
                             compute="_compute_queue_state", store=True)
    log_lines_ids = fields.One2many("common.log.lines.ept", compute="_compute_log_lines",
                                    help="Log lines of Common log book for particular product "
                                         "queue")
    line_ids = fields.One2many("sync.import.magento.product.queue.line", "queue_id",
                               help="Queue Lines")
    total_count = fields.Integer(string='Total Records',
                                 compute='_compute_record',
                                 help="Returns total number of Import product queue lines")
    draft_count = fields.Integer(string='Draft Records',
                                 compute='_compute_record',
                                 help="Returns total number of draft Import product queue lines")
    failed_count = fields.Integer(string='Fail Records',
                                  compute='_compute_record',
                                  help="Returns total number of Failed Import product queue lines")
    done_count = fields.Integer(string='Done Records',
                                compute='_compute_record',
                                help="Returns total number of done Import product queue lines")
    cancel_count = fields.Integer(string='Cancel Records',
                                  compute='_compute_record',
                                  help="Returns total number of cancel Import product queue lines")
    is_process_queue = fields.Boolean('Is Processing Queue', default=False)
    running_status = fields.Char(default="Running...")
    is_action_require = fields.Boolean(default=False)
    process_count = fields.Integer(string="Queue Process Times",
                                   help="it is used know queue how many time processed")

    @api.depends('line_ids.state')
    def _compute_queue_state(self):
        """
        Computes state from different states of queue lines.
        """
        for record in self:
            if record.total_count == record.done_count + record.cancel_count:
                record.state = "completed"
            elif record.total_count == record.draft_count:
                record.state = "draft"
            elif record.total_count == record.failed_count:
                if record.state != "failed":
                    record.state = "failed"
                    note = f"""
                    Attention {self.name} Product Queue is failed.\n
                    You need to process it manually
                    """
                    self.env['magento.instance'].create_activity(model_name=self._name,
                                                                 res_id=self.id,
                                                                 message=note,
                                                                 summary=self.name,
                                                                 instance=self.instance_id)
            else:
                record.state = "partially_completed"

    @api.depends('line_ids.state')
    def _compute_record(self):
        """
        This will calculate total, draft, failed and done products sync/import from Magento.
        """
        for queue in self:
            queue.total_count = len(queue.line_ids)
            queue.draft_count = len(queue.line_ids.filtered(lambda x: x.state == 'draft'))
            queue.failed_count = len(queue.line_ids.filtered(lambda x: x.state == 'failed'))
            queue.done_count = len(queue.line_ids.filtered(lambda x: x.state == 'done'))
            queue.cancel_count = len(queue.line_ids.filtered(lambda x: x.state == 'cancel'))

    @api.model_create_multi
    def create(self, vals):
        """
        Creates a sequence for Ordered Data Queue
        :param vals: values to create Ordered Data Queue
        :return: SyncImportMagentoProductQueue Object
        """
        for val in vals:
            sequence = self.env['ir.sequence']
            try:
                sequence = self.env.ref('odoo_magento2_ept.magento_seq_import_product_queue_data')
            except Exception as error:
                _logger.error(error)
            if sequence:
                sequence = sequence.next_by_id()
            else:
                sequence = '/'
            val.update({'name': sequence})
        return super(MagentoProductQueue, self).create(vals)

    @staticmethod
    def _get_product_search_filter(**kwargs):
        filters = {
            kwargs.get('import_product_on'): {
                'to': kwargs.get('to_date')
            },
            'status': 1,
            'type_id': {
                'in': kwargs.get('product_type')
            }
        }
        if kwargs.get('from_date'):
            filters.get(kwargs.get('import_product_on'), {}).update({'from': kwargs.get('from_date')})
        if kwargs.get('import_disable_products'):
            filters['status'] = {
                'in': [1, 2]  # include disabled products
            }
        return filters

    def _create_product_queue(self, instance):
        queue = self.search([('instance_id', '=', instance.id), ('state', '=', 'draft')])
        queue = queue.filtered(lambda q: len(q.line_ids) < 50)
        if not queue:
            queue = self.create({
                'instance_id': instance.id,
                'state': 'draft'
            })
            message = f"Product Queue #{queue.name} Created!!"
            instance.show_popup_notification(message)
        return queue

    def create_product_queues(self, instance, from_date, to_date, p_type, is_update=True, current=0):
        """
        Creates product queues when sync/ import products from Magento.
        :param instance: current instance of Magento
        :param from_date:  Sync product start from this date
        :param to_date: Sync product end to this date
        :return:
        """
        queues = []
        queue_line = self.env['sync.import.magento.product.queue.line']
        current_page = instance.magento_import_product_page_count
        filters = self._get_product_search_filter(from_date=from_date, to_date=to_date, product_type=p_type,
                                                  import_product_on=instance.import_product_on,
                                                  import_disable_products=instance.import_disable_products)
        products = self._get_product_response(instance, filters, current_page, get_pages=True)
        self._update_import_product_counter(instance, products)
        total_page = math.ceil(int(products.get('total_count')) / 50)
        if current:
            current_page = current
        for page in range(current_page, total_page + 1):
            products = self._get_product_response(instance, filters, page=page)
            if not products.get('items', []):
                self._update_import_product_counter(instance, products)
                break
            queue = self._create_product_queue(instance)
            queues.append(queue.id)
            try:
                for product in products.get('items'):
                    # Create new queue if the 50 queue_line count is reached.
                    if len(queue.line_ids) == 50:
                        queue = self._create_product_queue(instance)
                    queue_line.create_product_queue_line(product=product,
                                                         instance_id=instance.id,
                                                         is_update=is_update,
                                                         queue_id=queue.id)
                self.env.cr.commit()
            except Exception as error:
                _logger.error(error)
                instance.write({'magento_import_product_page_count': page})
                self.env.cr.commit()
        instance.write({'magento_import_product_page_count': 1})
        self.env.cr.commit()
        return queues

    def _update_import_product_counter(self, instance, response):
        if not response.get('total_count', 0):
            instance.write({'magento_import_product_page_count': 1})
            # Commit if there are no any products found.
            self.env.cr.commit()
        return True

    @staticmethod
    def _get_product_response(instance, filters, page=1, get_pages=False):
        s_fields = []
        if get_pages:
            page = 1
            s_fields.append('total_count')
        search_criteria = create_search_criteria(filters, page_size=50, page=page, fields=s_fields)
        query_string = Php.http_build_query(search_criteria)
        api_url = f'/V1/products?{query_string}'
        return req(instance, api_url, is_raise=True)

    def import_specific_product(self, instance, product_sku_lists, is_update):
        """
        Creates product queues when sync/ import products from Magento.
        :param instance: current instance of Magento
        :param product_sku_lists:  Dictionary of Product SKUs
        :return:
        """
        queue_line = self.env["sync.import.magento.product.queue.line"]
        log_line = self.env['common.log.lines.ept']
        queues = []
        queue = self._create_product_queue(instance)
        queues.append(queue.id)
        for product_sku in product_sku_lists:
            try:
                sku = Php.quote_sku(product_sku)
                api_url = f'/V1/products/{sku}'
                response = req(instance, api_url)
            except Exception as error:
                if len(product_sku_lists) > 1:
                    log_line.create_common_log_line_ept(message=f'Magento Product Not found for SKU {product_sku}',
                                                        module='magento_ept',
                                                        default_code=product_sku,
                                                        model_name=self._name,
                                                        magento_instance_id=instance.id)
                    continue
                else:
                    raise UserError(_("Error while requesting products" + str(error)))
            if response:
                if len(queue.line_ids) >= 50:
                    queue = self._create_product_queue(instance)
                    queues.append(queue.id)
                queue_line.create_product_queue_line(product=response, instance_id=instance.id,
                                                     is_update=is_update, queue_id=queue.id)
        return queues

    @api.model
    def retrieve_dashboard(self, *args, **kwargs):
        dashboard = self.env['queue.line.dashboard']
        return dashboard.get_data(table='sync.import.magento.product.queue.line')

    def process_product_queues(self, is_manual=False):
        start = time.time()
        for queue in self.filtered(lambda q: q.state not in ['completed']):
            cron_name = "odoo_magento2_ept.ir_cron_parent_to_process_product_queue_data"
            process_cron_time = queue.instance_id.get_magento_cron_execution_time(cron_name)
            # To maintain that current queue has started to process.
            self.env.cr.commit()
            queue.write({'is_process_queue': True})
            domain = ['draft', 'cancel', 'failed']
            queue.write({'process_count': queue.process_count + 1})
            if not is_manual and queue.process_count >= 3:
                queue.write({'process_count': queue.process_count + 1})
                note = f"""
                Attention {queue.name} Product Queue are processed 3 times and it failed. \n
                You need to process it manually 
                """
                queue.instance_id.enable_action_required_message(queue=queue)
                queue.instance_id.create_schedule_activity(queue=queue, note=note)
                domain.remove('failed')
                queue.write({'is_process_queue': False})
            lines = queue.line_ids.filtered(lambda l: l.state in domain)
            lines.process_queue_line()
            message = f"Product Queue #{queue.name} Processed!!"
            queue.instance_id.show_popup_notification(message)
            # To maintain that current queue process are completed and new queue will be executed.
            queue.write({'is_process_queue': False})
            self.env.cr.commit()
            if time.time() - start > process_cron_time - 60:
                return True
        return True

    @api.depends("line_ids.log_lines_ids")
    def _compute_log_lines(self):
        """
        Computes the log lines from the queue lines.
        @author: Nikul Alagiya on Date 13-Oct-2022.
        """
        for record in self:
            record.log_lines_ids = record.line_ids.log_lines_ids
