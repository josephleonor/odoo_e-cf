import base64
import json
import logging
import re
import urllib.error
import urllib.request

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcfLabSequence(models.Model):
    _name = "raco.ecf.lab.sequence"
    _description = "Rango ficticio e-CF de laboratorio"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    document_type = fields.Selection([("31", "E31"), ("32", "E32"), ("34", "E34")], required=True)
    first_number = fields.Integer(required=True, default=1)
    last_number = fields.Integer(required=True, default=100)
    next_number = fields.Integer(required=True, default=1, copy=False)
    expiration_date = fields.Date(required=True)
    active = fields.Boolean(default=True)

    @api.constrains("first_number", "last_number", "next_number")
    def _check_range(self):
        for sequence in self:
            if not 1 <= sequence.first_number <= sequence.next_number <= sequence.last_number + 1 or sequence.last_number > 2147483646:
                raise UserError(_("El rango ficticio debe ser positivo y no exceder el límite numérico admitido."))

    def allocate(self):
        self.ensure_one()
        self.env.cr.execute("SELECT next_number FROM raco_ecf_lab_sequence WHERE id = %s FOR UPDATE", [self.id])
        number = self.env.cr.fetchone()[0]
        if not self.active or self.expiration_date < fields.Date.context_today(self) or number > self.last_number:
            raise UserError(_("El rango ficticio venció, se agotó o está inactivo."))
        self.write({"next_number": number + 1})
        return "E%s%010d" % (self.document_type, number)


class EcfDocument(models.Model):
    _name = "raco.ecf.document"
    _description = "e-CF de laboratorio"
    _order = "id desc"

    move_id = fields.Many2one("account.move", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="move_id.company_id", store=True)
    encf = fields.Char(copy=False, index=True)
    document_type = fields.Selection([(x, "E" + x) for x in ("31", "32", "33", "34", "41", "43", "44", "45", "46", "47")], required=True)
    state = fields.Selection([("draft", "Borrador"), ("ready", "Preparado"), ("sent", "Recibido"), ("processing", "En proceso"), ("accepted", "Aceptado"), ("conditional", "Aceptado condicional"), ("rejected", "Rechazado")], default="draft", required=True, index=True)
    xml_file = fields.Binary(attachment=True, readonly=True)
    xml_filename = fields.Char(readonly=True)
    track_id = fields.Char(readonly=True, copy=False)
    response = fields.Text(readonly=True)
    attempt_count = fields.Integer(readonly=True)
    last_attempt = fields.Datetime(readonly=True)
    _sql_constraints = [("company_encf_unique", "unique(company_id, encf)", "El e-NCF ya existe para esta compañía.")]

    def action_allocate_lab(self):
        for doc in self:
            if doc.state != "draft" or doc.encf:
                raise UserError(_("Solo se asigna un número ficticio a un borrador sin e-NCF."))
            if not doc.document_type or not doc.company_id:
                raise UserError(_("Seleccione factura y tipo de documento antes de asignar."))
            sequence = self.env["raco.ecf.lab.sequence"].search([
                ("company_id", "=", doc.company_id.id), ("document_type", "=", doc.document_type),
                ("active", "=", True), ("expiration_date", ">=", fields.Date.context_today(doc)),
            ], order="id", limit=1)
            if not sequence:
                raise UserError(_("Configure un rango ficticio vigente para esta compañía y tipo."))
            doc.encf = sequence.allocate()

    def _config(self):
        self.ensure_one()
        p = self.env["ir.config_parameter"].sudo()
        endpoint = p.get_param("raco_ecf.lab_url", "http://127.0.0.1:8765")
        if not endpoint.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise UserError(_("El laboratorio solo acepta una URL local. No conecte producción aquí."))
        return endpoint.rstrip("/")

    def action_prepare(self):
        for doc in self:
            if doc.state not in ("draft", "rejected"):
                raise UserError(_("Solo se pueden preparar borradores o documentos rechazados."))
            move = doc.move_id
            if move.state != "posted" or move.move_type not in ("out_invoice", "out_refund"):
                raise UserError(_("Se requiere una factura o nota de crédito publicada."))
            if not re.fullmatch(r"E%s[0-9]{10}" % re.escape(doc.document_type), doc.encf or ""):
                raise UserError(_("El e-NCF debe tener el tipo indicado y diez dígitos de secuencia."))
            if not move.company_id.vat:
                raise UserError(_("Configure el RNC de la compañía."))
            if move.currency_id.name != "DOP":
                raise UserError(_("Este laboratorio solo acepta DOP; falta el flujo oficial de divisas."))
            if doc.document_type not in ("31", "32", "34"):
                raise UserError(_("Tipo reservado hasta implementar y validar su esquema oficial."))
            if doc.document_type == "34" and move.move_type != "out_refund":
                raise UserError(_("E34 requiere una nota de crédito publicada."))
            if doc.document_type in ("31", "32") and move.move_type != "out_invoice":
                raise UserError(_("E31 y E32 requieren una factura publicada."))
            if doc.document_type == "31" and not move.partner_id.vat:
                raise UserError(_("E31 requiere el RNC o cédula del comprador."))
            lines = move.invoice_line_ids.filtered(lambda line: line.display_type == "product")
            if not lines:
                raise UserError(_("La factura no contiene líneas de productos o servicios."))
            payload = {
                "encf": doc.encf,
                "type": doc.document_type,
                "issuer_rnc": move.company_id.vat,
                "buyer_rnc": move.partner_id.vat or "",
                "date": str(move.invoice_date or move.date),
                "total": str(move.amount_total),
                "untaxed": str(move.amount_untaxed),
                "tax": str(move.amount_tax),
                "lines": [{"description": line.name, "quantity": str(line.quantity), "price": str(line.price_unit), "subtotal": str(line.price_subtotal), "total": str(line.price_total), "taxes": [tax.name for tax in line.tax_ids]} for line in lines],
            }
            # This is a transport fixture, not the DGII ECF XML or an authorized sequence.
            doc.write({"xml_file": base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()), "xml_filename": doc.encf + ".json", "state": "ready", "track_id": False, "response": False})

    def _request(self, path, payload=None):
        self.ensure_one()
        url = self._config() + path
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return json.loads(response.read(65536))
        except (urllib.error.URLError, ValueError) as exc:
            _logger.warning("e-CF laboratory unavailable: %s", exc)
            raise UserError(_("No se pudo contactar el simulador e-CF: %s") % exc) from exc

    def action_send_lab(self):
        for doc in self:
            if doc.state != "ready":
                raise UserError(_("Prepare primero el documento."))
            payload = json.loads(base64.b64decode(doc.xml_file))
            result = doc._request("/receive", payload)
            if not result.get("track_id"):
                raise UserError(_("El simulador no devolvió un TrackId."))
            doc.write({"track_id": result["track_id"], "state": "sent", "attempt_count": doc.attempt_count + 1, "last_attempt": fields.Datetime.now(), "response": json.dumps(result)})

    def action_poll_lab(self):
        for doc in self:
            if doc.state not in ("sent", "processing") or not doc.track_id:
                raise UserError(_("No hay envío pendiente."))
            from urllib.parse import quote
            result = doc._request("/status/" + quote(doc.track_id, safe=""))
            state = result.get("state")
            if state not in ("processing", "accepted", "conditional", "rejected"):
                raise UserError(_("Respuesta desconocida del simulador."))
            doc.write({"state": state, "response": json.dumps(result)})


class AccountMove(models.Model):
    _inherit = "account.move"

    raco_ecf_ids = fields.One2many("raco.ecf.document", "move_id", string="e-CF laboratorio")
    raco_ecf_count = fields.Integer(compute="_compute_raco_ecf_count")

    def _compute_raco_ecf_count(self):
        for move in self:
            move.raco_ecf_count = len(move.raco_ecf_ids)

    def action_view_raco_ecf(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("e-CF laboratorio"),
            "res_model": "raco.ecf.document", "view_mode": "list,form",
            "domain": [("move_id", "=", self.id)],
            "context": {"default_move_id": self.id},
        }
