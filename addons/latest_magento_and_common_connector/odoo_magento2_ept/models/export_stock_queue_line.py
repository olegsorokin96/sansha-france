import json
from datetime import datetime
from odoo import models, fields


class MagentoExportStockLineEpt(models.Model):
    """
    Describes Export Stock Data Queue Line
    """
    _name = "magento.export.stock.queue.line.ept"
    _description = "Magento Export Stock Queue Line"

    queue_id = fields.Many2one(comodel_name='magento.export.stock.queue.ept', ondelete="cascade")
    instance_id = fields.Many2one(comodel_name='magento.instance',
                                  string='Magento Instance',
                                  help="Export Stock from this Magento Instance.")
    state = fields.Selection([("draft", "Draft"), ("failed", "Failed"),
                              ("done", "Done"), ("cancel", "Cancelled")], default="draft",
                             copy=False)
    data = fields.Text(string="Data", copy=False,
                       help="Data imported from Magento of current customer.")
    processed_at = fields.Datetime(string="Process Time", copy=False,
                                   help="Shows Date and Time, When the data is processed")
    log_lines_ids = fields.One2many("common.log.lines.ept", "magento_export_stock_queue_line_id",
                                    help="Log lines created against which line.")

    def create_export_stock_queue_line(self, instance, data, queue):
        """
        :param instance: Instance object
        :param data: Stock data
        :param queue: Queue object
        """
        self.create({
            'instance_id': instance.id,
            'data': json.dumps(data),
            'queue_id': queue.id,
            'state': 'draft',
        })
        return True

    def auto_process_export_stock_queues(self):
        """
        Cron execute time run this method.
        :return: True
        """
        query = """ SELECT queue_id FROM magento_export_stock_queue_line_ept WHERE state = 'draft'
                    GROUP BY queue_id, create_date
                    ORDER BY create_date ASC
                """
        self.env.cr.execute(query)
        queue_ids = [queue.get('queue_id') for queue in self.env.cr.dictfetchall()]
        queues = self.env[self.queue_id._name].browse(queue_ids)
        queues.filtered(lambda q: not q.is_action_require)
        queues.process_export_stock_queues()
        return True

    def process_export_stock_queue_line(self, api_url, log_line):
        """
        :param api_url: Export stock url MSI or Non MSI
        :param log_line: Log line object
        :return: True
        """
        magento_product = self.env['magento.product.product']
        for line in self:
            input_data = json.loads(line.data)
            if not input_data.get('sourceItems') == []:
                is_processed = magento_product.export_magento_stock(line, api_url, log_line)
                if is_processed:
                    line.write({'state': 'done', 'processed_at': datetime.now(), 'data': False})
                else:
                    line.write({'state': 'failed', 'processed_at': datetime.now()})
            else:
                line.write({'state': 'done', 'processed_at': datetime.now(), 'data': False})
            self.env.cr.commit()
        return True
