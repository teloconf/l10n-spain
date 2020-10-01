# Copyright 2017 FactorLibre - Ismael Calvo <ismael.calvo@factorlibre.com>
# Copyright 2017-2020 Tecnativa - Pedro M. Baeza
# Copyright 2018 PESOL - Angel Moya <angel.moya@pesol.es>
# Copyright 2020 Valentin Vinagre <valent.vinagre@sygel.es>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

import base64
import json

from odoo import exceptions
from odoo.modules.module import get_resource_path
from odoo.tests import common

try:
    from zeep.client import ServiceProxy
except (ImportError, IOError):
    ServiceProxy = object

CERTIFICATE_PATH = get_resource_path(
    "l10n_es_aeat_sii", "tests", "cert", "entidadspj_act.p12",
)
CERTIFICATE_PASSWD = "794613"


class TestL10nEsAeatSiiBase(common.SavepointCase):
    @classmethod
    def _get_or_create_tax(cls, xml_id, name, tax_type, percentage):
        tax = cls.env.ref("l10n_es." + xml_id, raise_if_not_found=False)
        if not tax:
            tax = cls.env["account.tax"].create(
                {
                    "name": name,
                    "type_tax_use": tax_type,
                    "amount_type": "percent",
                    "amount": percentage,
                }
            )
            cls.env["ir.model.data"].create(
                {
                    "module": "l10n_es",
                    "name": xml_id,
                    "model": tax._name,
                    "res_id": tax.id,
                }
            )
        return tax

    @classmethod
    def setUpClass(cls):
        super(TestL10nEsAeatSiiBase, cls).setUpClass()
        cls.maxDiff = None
        cls.partner = cls.env["res.partner"].create(
            {"name": "Test partner", "vat": "ESF35999705"}
        )
        cls.product = cls.env["product.product"].create({"name": "Test product"})
        cls.account_type = cls.env["account.account.type"].create(
            {"name": "Test account type", "internal_group": "asset"}
        )
        cls.account_expense = cls.env["account.account"].create(
            {
                "name": "Test expense account",
                "code": "EXP",
                "user_type_id": cls.account_type.id,
            }
        )
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {"name": "Test analytic account"}
        )
        cls.account_tax = cls.env["account.account"].create(
            {
                "name": "Test tax account",
                "code": "TAX",
                "user_type_id": cls.account_type.id,
            }
        )
        cls.company = cls.env.user.company_id
        cls.env.user.company_id.sii_description_method = "manual"
        cls.invoice = cls.env["account.move"].create(
            {
                "partner_id": cls.partner.id,
                "invoice_date": "2018-02-01",
                "type": "out_invoice",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product.id,
                            "account_id": cls.account_expense.id,
                            "analytic_account_id": cls.analytic_account.id,
                            "name": "Test line",
                            "price_unit": 100,
                            "quantity": 1,
                        },
                    )
                ],
                "sii_manual_description": "/",
            }
        )
        cls.invoice.company_id.write(
            {
                "sii_enabled": True,
                "sii_test": True,
                "use_connector": True,
                "chart_template_id": cls.env.ref(
                    "l10n_es.account_chart_template_pymes"
                ).id,
                "vat": "ESU2687761C",
            }
        )


class TestL10nEsAeatSii(TestL10nEsAeatSiiBase):
    @classmethod
    def setUpClass(cls):
        super(TestL10nEsAeatSii, cls).setUpClass()
        cls.invoice.action_post()
        cls.invoice.name = "INV001"
        cls.invoice.refund_invoice_id = cls.invoice.copy()
        cls.user = cls.env["res.users"].create(
            {
                "name": "Test user",
                "login": "test_user",
                "groups_id": [(4, cls.env.ref("account.group_account_invoice").id)],
                "email": "somebody@somewhere.com",
            }
        )
        with open(CERTIFICATE_PATH, "rb") as certificate:
            content = certificate.read()
        cls.sii_cert = cls.env["l10n.es.aeat.sii"].create(
            {
                "name": "Test Certificate",
                "file": base64.b64encode(content),
                "company_id": cls.invoice.company_id.id,
            }
        )
        cls.tax_agencies = cls.env["aeat.sii.tax.agency"].search([])

    def test_job_creation(self):
        self.assertTrue(self.invoice.invoice_jobs_ids)

    def _compare_sii_dict(self, json_file, inv_type, lines, extra_vals=None):
        """Helper method for creating an invoice according arguments, and
        comparing the expected SII dict with .
        """
        vals = {
            "name": "TEST001",
            "partner_id": self.partner.id,
            "invoice_date": "2020-01-01",
            "type": inv_type,
            "invoice_line_ids": [],
            "sii_manual_description": "/",
        }
        for line in lines:
            vals["invoice_line_ids"].append(
                (
                    0,
                    0,
                    {
                        "product_id": self.product.id,
                        "account_id": self.account_expense.id,
                        "name": "Test line",
                        "price_unit": line["price_unit"],
                        "quantity": 1,
                        "tax_ids": [(6, 0, line["taxes"].ids)],
                    },
                )
            )
        if extra_vals:
            vals.update(extra_vals)
        invoice = self.env["account.move"].create(vals)
        result_dict = invoice._get_sii_invoice_dict()
        with open(get_resource_path("l10n_es_aeat_sii", "tests", json_file), "r") as f:
            expected_dict = json.loads(f.read())
        self.assertEqual(expected_dict, result_dict)

    def test_get_invoice_data(self):
        xml_id = "%s_account_tax_template_s_iva10b" % self.company.id
        s_tax_10_b = self._get_or_create_tax(xml_id, "S10B", "sale", 10)
        xml_id = "%s_account_tax_template_s_iva21s" % self.company.id
        s_tax_21_s = self._get_or_create_tax(xml_id, "S21S", "sale", 21)
        self._compare_sii_dict(
            "sii_out_invoice_iva_10_21_dict.json",
            "out_invoice",
            [
                {"price_unit": 100, "taxes": s_tax_10_b},
                {"price_unit": 200, "taxes": s_tax_21_s},
            ],
        )
        self._compare_sii_dict(
            "sii_out_refund_iva_10_10_21_dict.json",
            "out_refund",
            [
                {"price_unit": 100, "taxes": s_tax_10_b},
                {"price_unit": 100, "taxes": s_tax_10_b},
                {"price_unit": 200, "taxes": s_tax_21_s},
            ],
        )
        xml_id = "%s_account_tax_template_p_iva10_bc" % self.company.id
        p_tax_10_b = self._get_or_create_tax(xml_id, "P10B", "purchase", 10)
        xml_id = "%s_account_tax_template_p_iva21_sc" % self.company.id
        p_tax_21_s = self._get_or_create_tax(xml_id, "P21S", "purchase", 21)
        xml_id = "%s_account_tax_template_p_irpf19" % self.company.id
        p_tax_irpf19 = self._get_or_create_tax(xml_id, "IRPF19", "purchase", -19)
        self._compare_sii_dict(
            "sii_in_invoice_iva_10_21_irpf_19_dict.json",
            "in_invoice",
            [
                {"price_unit": 100, "taxes": p_tax_10_b + p_tax_irpf19},
                {"price_unit": 200, "taxes": p_tax_21_s + p_tax_irpf19},
            ],
            extra_vals={"ref": "sup0001", "date": "2020-02-01"},
        )
        self._compare_sii_dict(
            "sii_in_refund_iva_10_dict.json",
            "in_refund",
            [{"price_unit": 100, "taxes": p_tax_10_b}],
            extra_vals={"ref": "sup0002"},
        )

    def test_action_cancel(self):
        self.invoice.invoice_jobs_ids.state = "started"
        self.invoice.journal_id.update_posted = True
        with self.assertRaises(exceptions.Warning):
            self.invoice.button_cancel()

    def test_sii_description(self):
        company = self.invoice.company_id
        company.write(
            {
                "sii_header_customer": "Test customer header",
                "sii_header_supplier": "Test supplier header",
                "sii_description": " | Test description",
                "sii_description_method": "fixed",
            }
        )
        invoice_temp = self.invoice.copy()
        self.assertEqual(
            invoice_temp.sii_description, "Test customer header | Test description",
        )
        invoice_temp = self.invoice.copy({"type": "in_invoice"})
        self.assertEqual(
            invoice_temp.sii_description, "Test supplier header | Test description",
        )
        company.sii_description_method = "manual"
        invoice_temp = self.invoice.copy()
        self.assertEqual(invoice_temp.sii_description, "Test customer header")
        invoice_temp.sii_description = "Other thing"
        self.assertEqual(invoice_temp.sii_description, "Other thing")
        company.sii_description_method = "auto"
        invoice_temp = self.invoice.copy()
        self.assertEqual(
            invoice_temp.sii_description, "Test customer header | Test line",
        )

    def test_permissions(self):
        """ This should work without errors """
        self.invoice.with_user(self.user).action_post()

    def _activate_certificate(self, passwd=None):
        """  Obtain Keys from .pfx and activate the cetificate """
        if passwd:
            wizard = self.env["l10n.es.aeat.sii.password"].create(
                {"password": passwd, "folder": "test"}
            )
            wizard.with_context(active_id=self.sii_cert.id).get_keys()
        self.sii_cert.action_activate()
        self.sii_cert.company_id.write(
            {"name": "ENTIDAD FICTICIO ACTIVO", "vat": "ESJ7102572J"}
        )

    def test_certificate(self):
        self.assertRaises(
            exceptions.ValidationError, self._activate_certificate, "Wrong passwd",
        )
        self._activate_certificate(CERTIFICATE_PASSWD)
        self.assertEqual(self.sii_cert.state, "active")
        proxy = self.invoice._connect_sii(self.invoice.type)
        self.assertIsInstance(proxy, ServiceProxy)

    def _check_binding_address(self, invoice):
        company = invoice.company_id
        tax_agency = company.sii_tax_agency_id
        self.sii_cert.company_id.sii_tax_agency_id = tax_agency
        proxy = invoice._connect_sii(invoice.type)
        address = proxy._binding_options["address"]
        self.assertTrue(address)
        if company.sii_test and tax_agency:
            params = tax_agency._connect_params_sii(invoice.type, company)
            if params["address"]:
                self.assertEqual(address, params["address"])

    def _check_tax_agencies(self, invoice):
        for tax_agency in self.tax_agencies:
            invoice.company_id.sii_tax_agency_id = tax_agency
            self._check_binding_address(invoice)
        else:
            invoice.company_id.sii_tax_agency_id = False
            self._check_binding_address(invoice)

    def test_tax_agencies_sandbox(self):
        self._activate_certificate(CERTIFICATE_PASSWD)
        self.invoice.company_id.sii_test = True
        for inv_type in ["out_invoice", "in_invoice"]:
            self.invoice.type = inv_type
            self._check_tax_agencies(self.invoice)

    def test_tax_agencies_production(self):
        self._activate_certificate(CERTIFICATE_PASSWD)
        self.invoice.company_id.sii_test = False
        for inv_type in ["out_invoice", "in_invoice"]:
            self.invoice.type = inv_type
            self._check_tax_agencies(self.invoice)

    def test_refund_sii_refund_type(self):
        invoice = self.env["account.move"].create(
            {
                "partner_id": self.partner.id,
                "invoice_date": "2018-02-01",
                "type": "out_refund",
            }
        )
        self.assertEqual(invoice.sii_refund_type, "I")

    def test_refund_sii_refund_type_write(self):
        invoice = self.env["account.move"].create(
            {
                "partner_id": self.partner.id,
                "invoice_date": "2018-02-01",
                "type": "out_invoice",
            }
        )
        self.assertFalse(invoice.sii_refund_type)
        invoice.type = "out_refund"
        self.assertEqual(invoice.sii_refund_type, "I")

    def test_is_sii_simplified_invoice(self):
        self.assertFalse(self.invoice._is_sii_simplified_invoice())
        self.partner.sii_simplified_invoice = True
        self.assertTrue(self.invoice._is_sii_simplified_invoice())

    def test_sii_check_exceptions_case_supplier_simplified(self):
        self.partner.is_simplified_invoice = True
        invoice = self.env["account.move"].create(
            {
                "partner_id": self.partner.id,
                "invoice_date": "2018-02-01",
                "type": "in_invoice",
            }
        )
        with self.assertRaises(exceptions.Warning):
            invoice._sii_check_exceptions()

    def test_unlink_invoice_when_sent_to_sii(self):
        self.invoice.sii_state = "sent"
        with self.assertRaises(exceptions.Warning):
            self.invoice.unlink()
