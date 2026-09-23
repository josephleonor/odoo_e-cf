import unittest
from simulator.server import DOCUMENTS, receive, status


class SimulatorTest(unittest.TestCase):
    def setUp(self):
        DOCUMENTS.clear()

    def test_track_is_idempotent_and_status_is_separate(self):
        doc = {"encf": "E310000000001", "type": "31", "issuer_rnc": "101000000", "lines": [{"description": "Prueba"}]}
        one = receive(doc)
        self.assertEqual(one, receive(doc))
        self.assertEqual(status(one["track_id"])["state"], "processing")
        self.assertEqual(status(one["track_id"])["state"], "accepted")

    def test_invalid_document_rejected(self):
        with self.assertRaises(ValueError):
            receive({"type": "31", "encf": "E320000000001"})
