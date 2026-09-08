# -*- coding: utf-8 -*-
# See LICENSE file for full copyright and licensing details.
"""
Describes fields and methods for Magento products templates
"""
import logging
from odoo import models

_logger = logging.getLogger("MagentoEPT")


class MagentoProductTemplate(models.Model):
    """
    Describes fields and methods for Magento products templates
    """
    _inherit = 'magento.product.template'

    def get_bundle_product_images(self, instance, item, store_id, queue_line_id, magento_order_reference):
        """
        this method is used to get image binary data from magento store
        Developed by Ketan Chauhan on 28.12.2023
        :param instance: required a magento instance
        :param item: product response dict
        :param store_id: required store id find store view records
        :param queue_line_id: required queue line id for common log entry creation
        :param magento_order_reference: required order ref for common log entry creation
        :return: return images dictionary with image binary data
        """
        log_line = self.env['common.log.lines.ept']
        store = self.env['magento.storeview']
        common_image = self.env['common.product.image.ept']
        store = store.search([('magento_storeview_id', '=', store_id)], limit=1)
        base_url = store.base_media_url
        if base_url:
            self.__update_path(item, base_url)
            for image in item.get('media_gallery_entries', list()):
                image_binary = False
                verify = instance.magento_verify_ssl
                try:
                    image_binary = common_image.get_image_ept(image.get('full_path', ''), verify=verify)
                except Exception as error:
                    _logger.error(error)
                    message = "{} " \
                              "\nCan't find image." \
                              "\nPlease provide valid Image URL.".format(item.get('full_path'))
                    log_line.create_common_log_line_ept(message=message, order_ref=magento_order_reference,
                                                        magento_order_data_queue_line_id=queue_line_id,
                                                        magento_instance_id=instance.id)
                if image_binary:
                    image.update({'image_binary': image_binary})
        return item.get('media_gallery_entries', list())
