import base64
import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcfDocument(models.Model):
    _name = "raco.ecf.document"
    _description = "e-CF de laboratorio"
    _order = "id desc"

    move_id = fields.Many2one("account.move", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="move_id.company_id", store=True)
    encf = fields.Char(required=True, copy=False, index=True)
    document_type = fields.Selection([(x, "E" + x) for x in ("31", "32", "33", "34", "41", "43", "44", "45", "46", "47")], required=True)
    state = fields.Selection([("draft", "Borrador"), ("ready", "Preparado"), ("sent", "Recibido"), ("processing", "En proceso"), ("accepted", "Aceptado"), ("conditional", "Aceptado condicional"), ("rejected", "Rechazado")], default="draft", required=True, index=True)
    xml_file = fields.Binary(attachment=True, readonly=True)
    xml_filename = fields.Char(readonly=True)
    track_id = fields.Char(readonly=True, copy=False)
    response = fields.Text(readonly=True)
    attempt_count = fields.Integer(readonly=True)
    last_attempt = fields.Datetime(readonly=True)
    _sql_constraints = [("company_encf_unique", "unique(company_id, encf)", "El e-NCF ya existe para esta compañía.")]

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
            if not doc.encf.startswith("E" + doc.document_type):
                raise UserError(_("El tipo y el prefijo del e-NCF no coinciden."))
            if not move.company_id.vat:
                raise UserError(_("Configure el RNC de la compañía."))
            if move.currency_id.name != "DOP":
                raise UserError(_("Este laboratorio solo acepta DOP; falta el flujo oficial de divisas."))
            if doc.document_type not in ("31", "32", "34"):
                raise UserError(_("Tipo reservado hasta implementar y validar su esquema oficial."))
            payload = {
                "encf": doc.encf,
                "type": doc.document_type,
                "issuer_rnc": move.company_id.vat,
                "buyer_rnc": move.partner_id.vat or "",
                "date": str(move.invoice_date or move.date),
                "total": str(move.amount_total),
                "lines": [{"description": line.name, "quantity": str(line.quantity), "price": str(line.price_unit)} for line in move.invoice_line_ids if not line.display_type],
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
