"""For Odoo Magento2 Connector Module"""
from odoo import models, api, _
from odoo.fields import Domain
from odoo.exceptions import UserError, ValidationError
from odoo.tools import frozendict, groupby, split_every


class AccountTaxCode(models.Model):
    """Inherited account tax model to calculate tax."""
    _inherit = 'account.tax'

    def get_tax_from_rate(self, rate, name, is_tax_included=False, country=False):
        """
        This method,base on rate it find tax in odoo.
        @return : Tax_ids
        @author: Haresh Mori on dated 10-Dec-2018
        """
        for precision in [0.001, 0.01]:
            if country:
                tax_ids = self.with_context(active_test=False).search(
                    [('price_include', '=', is_tax_included),
                     ('type_tax_use', 'in', ['sale']),
                     ('amount', '>=', rate - precision),
                     ('amount', '<=', rate + precision),
                     ('country_id', '=', country.id)], limit=1)
                return tax_ids
            else:
                tax_ids = self.with_context(active_test=False).search(
                    [('price_include', '=', is_tax_included),
                     ('type_tax_use', 'in', ['sale']),
                     ('amount', '>=', rate - precision),
                     ('amount', '<=', rate + precision)], limit=1)
                return tax_ids
        return self

    @api.constrains('company_id', 'name', 'type_tax_use', 'tax_scope', 'country_id')
    def _constrains_name(self):
        for taxes in split_every(100, self.ids, self.browse):
            domains = []
            for tax in taxes:
                if tax.type_tax_use != 'none':
                    domains.append([
                        ('company_id', 'child_of', tax.company_id.root_id.id),
                        ('name', '=', tax.name),
                        ('price_include', '=', tax.price_include),
                        ('type_tax_use', '=', tax.type_tax_use),
                        ('tax_scope', '=', tax.tax_scope),
                        ('country_id', '=', tax.country_id.id),
                        ('id', '!=', tax.id),
                    ])
            if duplicates := self.search(Domain.OR(domains)):
                raise ValidationError(
                    _("Tax names must be unique!")
                    + "\n" + "\n".join(_(
                        "- %(name)s in %(company)s",
                        name=duplicate.name,
                        company=duplicate.company_id.name,
                    ) for duplicate in duplicates)
                )
