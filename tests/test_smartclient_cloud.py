from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from custom_components.eybond_local import smartclient_cloud as cloud

PN = "E50000200000000001"
IDENTITY = {"pn": PN, "sn": "SC00001", "devcode": 767, "devaddr": 1}
DAY = "2026-09-08"


def responses():
    return {
        "auth": {"token": "PRIVATE_TOKEN", "secret": "PRIVATE_SECRET"},
        "queryCollectorDevices": {"pn": PN, "dev": [dict(IDENTITY)]},
        "queryDeviceInfo": {"device": [dict(IDENTITY, timezone=10800, status=1)]},
        "webQueryCollectorInfo": {"pn": PN, "timezone": 7200},
        "queryDeviceLastData": [
            {"title": "id", "val": "row-id"},
            {"title": "Timestamp", "val": DAY + " 12:00:00"},
            {"title": "PV Voltage", "unit": "V", "val": "220.5"},
        ],
        "queryDeviceCtrlField": {
            "field": [
                {
                    "id": "shutdown",
                    "name": "Shutdown",
                    "item": [{"key": "1", "val": "Stop"}],
                },
            ]
        },
        "queryDeviceLastRawData": {
            "id": "raw-id",
            "dat": base64.b64encode(b"raw-frame").decode(),
            "gts": DAY + " 12:00:00",
        },
        "queryDeviceDataOneDay": {
            "title": [
                {"title": "id"},
                {"title": "Timestamp"},
                {"title": "PV Voltage", "unit": "V"},
            ],
            "row": [
                {"field": ["row-id", DAY + " 12:00:00", "220.5"], "realtime": True}
            ],
        },
    }


def fetch_fixture(data=None):
    data = responses() if data is None else data
    calls = []

    def request(url, *, timeout):
        query = parse_qs(urlsplit(url).query)
        name = query["action"][0]
        calls.append((name, query, timeout))
        result = data[name]
        if isinstance(result, Exception):
            raise result
        return {"err": 0, "dat": copy.deepcopy(result)}

    with patch.object(cloud, "_http_get_json", side_effect=request):
        result = cloud.fetch_read_only_evidence(
            username="owner", password="pass", collector_pn=PN
        )
    return result, calls


class SmartClientCloudTests(unittest.TestCase):
    def test_native_auth_signature_is_not_auth_source(self):
        with patch.object(cloud.time, "time", return_value=1):
            url = cloud.build_login_url(username="owner + ü", password=" pass ")
        action = "&action=auth&usr=owner%20%2B%20%C3%BC&company-key=bnrl_frRFjEz8Mkn"
        sign = hashlib.sha1(
            ("1000" + hashlib.sha1(b" pass ").hexdigest() + action).encode()
        ).hexdigest()
        self.assertEqual(
            url, cloud.DEFAULT_BASE_URL + "?sign=" + sign + "&salt=1000" + action
        )
        self.assertNotIn("authSource", url)
        self.assertNotIn("&source=", url)

    def test_business_signature_source_and_session_are_exact(self):
        session = cloud.SmartClientSession("token", "secret", cloud.OVERSEAS_BASE_URL)
        with patch.object(cloud.time, "time", return_value=1):
            url = cloud.build_signed_action_url(
                name="queryCollectorDevices", session=session, parameters=(("pn", PN),)
            )
        action = url[url.index("&action=") :]
        expected = hashlib.sha1(("1000secrettoken" + action).encode()).hexdigest()
        self.assertEqual(parse_qs(urlsplit(url).query)["sign"], [expected])
        self.assertIn("&source=0", action)
        self.assertIn("&_app_id_=com.eybond.smartclient&", action)
        self.assertTrue(url.startswith(cloud.OVERSEAS_BASE_URL))
        self.assertNotIn("secret", repr(session))
        self.assertNotIn("token", repr(session))

    def test_passive_allowlist_blocks_writes_and_parameter_injection(self):
        session = cloud.SmartClientSession("t", "s")
        for name in (
            "ctrlDevice",
            "queryDeviceCtrlValue",
            "restartCollector",
            "sendCmdToDevice",
            "authSource",
        ):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(cloud.SmartClientCloudError, "action_forbidden"),
            ):
                cloud.build_signed_action_url(name=name, session=session)
        for params in (
            (("source", 1),),
            (("pn&source", "1"),),
            (("pn", PN), ("pn", "OTHER")),
            (("pn", True),),
        ):
            with (
                self.subTest(params=params),
                self.assertRaises(cloud.SmartClientCloudError),
            ):
                cloud.build_signed_action_url(
                    name="queryCollectorDevices", session=session, parameters=params
                )
        with self.assertRaises(cloud.SmartClientCloudError):
            cloud.SmartClientSession(
                "t", "s", "http://android.shinemonitor.com/public/"
            )
        with self.assertRaises(cloud.SmartClientCloudError):
            cloud.build_login_url(
                username="owner",
                password="pass",
                base_url="https://foreign.invalid/public/",
            )

    def test_passive_fetch_contains_generic_evidence_and_no_credentials(self):
        bundle, calls = fetch_fixture()
        self.assertEqual(bundle.identity.to_record(), IDENTITY)
        self.assertEqual(bundle.telemetry[2]["value"], "220.5")
        self.assertEqual(
            bundle.controls[0]["choices"], [{"value": "1", "label": "Stop"}]
        )
        self.assertEqual(bundle.raw_packet["length"], 9)
        self.assertEqual(
            bundle.raw_packet["sha256"], hashlib.sha256(b"raw-frame").hexdigest()
        )
        self.assertTrue(bundle.raw_packet["payload_omitted"])
        self.assertNotIn("data_base64", bundle.raw_packet)
        self.assertEqual(
            {name for name, _, _ in calls},
            (cloud.PASSIVE_ACTIONS - {"webQueryCollectorInfo"}) | {"auth"},
        )
        for name, query, timeout in calls:
            self.assertLessEqual(timeout, 15)
            if name != "auth":
                self.assertEqual(query["source"], ["0"])
        saved = json.dumps(bundle.to_record())
        for forbidden in (
            "PRIVATE_TOKEN",
            "PRIVATE_SECRET",
            "password",
            "?sign=",
            "&token=",
        ):
            self.assertNotIn(forbidden, saved)

    def test_wrong_collector_and_multiple_device_identity_fail_closed(self):
        for result in (
            {"pn": "E5000099990002", "dev": [IDENTITY]},
            {"pn": PN, "dev": [IDENTITY, dict(IDENTITY, devaddr=2)]},
            {"pn": PN, "dev": [dict(IDENTITY, devaddr=True)]},
            {"pn": PN, "dev": []},
        ):
            data = responses()
            data["queryCollectorDevices"] = result
            with (
                self.subTest(result=result),
                self.assertRaises(cloud.SmartClientCloudError),
            ):
                fetch_fixture(data)

    def test_device_info_foreign_identity_is_not_a_timezone_source(self):
        data = responses()
        data["queryDeviceInfo"]["device"][0]["sn"] = "FOREIGN"
        with self.assertRaisesRegex(cloud.SmartClientCloudError, "identity_mismatch"):
            fetch_fixture(data)

    def test_native_array_device_info_preserves_exact_identity(self):
        data = responses()
        data["queryDeviceInfo"] = [dict(IDENTITY, timezone=0)]
        bundle, calls = fetch_fixture(data)
        self.assertEqual(bundle.device_info["timezone"], 0)
        self.assertTrue(bundle.history["requested_date"])
        self.assertNotIn("webQueryCollectorInfo", [name for name, _, _ in calls])
        for rows in (
            [], [dict(IDENTITY, sn="FOREIGN")],
            [dict(IDENTITY), dict(IDENTITY)],
            [dict(IDENTITY, devaddr=True)],
        ):
            data["queryDeviceInfo"] = rows
            with self.subTest(rows=rows), self.assertRaisesRegex(
                cloud.SmartClientCloudError, "identity_mismatch"
            ):
                fetch_fixture(data)

    def test_collector_timezone_fallback_is_scoped_and_precedes_history(self):
        for info in ([dict(IDENTITY)], "malformed"):
            data = responses()
            data["queryDeviceInfo"] = info
            bundle, calls = fetch_fixture(data)
            self.assertEqual(bundle.device_info["timezone"], 7200)
            self.assertEqual(bundle.device_info["timezone_source"], "webQueryCollectorInfo")
            names = [name for name, _, _ in calls]
            self.assertLess(names.index("webQueryCollectorInfo"), names.index("queryDeviceDataOneDay"))
            query = next(query for name, query, _ in calls if name == "webQueryCollectorInfo")
            self.assertEqual(query["pn"], [PN])
            self.assertNotIn("device", query)
            self.assertTrue(bundle.history["requested_date"])

    def test_collector_timezone_never_guesses_or_ignores_identity_auth_errors(self):
        for offset in (None, True, "7200", -43201, 50401):
            data = responses()
            data["queryDeviceInfo"] = [dict(IDENTITY)]
            data["webQueryCollectorInfo"]["timezone"] = offset
            bundle, calls = fetch_fixture(data)
            self.assertNotIn("timezone", bundle.device_info)
            self.assertEqual(bundle.history["requested_date"], "")
            self.assertIn(("webQueryCollectorInfo", "time_basis_unavailable"), bundle.action_errors)
            history_query = next(query for name, query, _ in calls if name == "queryDeviceDataOneDay")
            self.assertNotIn("date", history_query)
        for reply in (
            {"pn": "E5000099990002", "timezone": 7200},
            cloud.SmartClientCloudError("auth_failed"),
            cloud.SmartClientCloudError("api_rejected", code=257),
        ):
            data["webQueryCollectorInfo"] = reply
            with self.subTest(reply=reply), self.assertRaises(cloud.SmartClientCloudError):
                fetch_fixture(data)

    def test_optional_rejection_preserves_other_evidence(self):
        data = responses()
        data["queryDeviceCtrlField"] = cloud.SmartClientCloudError(
            "api_rejected", code=12
        )
        bundle, _ = fetch_fixture(data)
        self.assertEqual(bundle.controls, ())
        self.assertEqual(bundle.unavailable_actions, ("queryDeviceCtrlField",))
        self.assertTrue(bundle.telemetry)

    def test_revoked_permission_does_not_become_partial_success(self):
        for code in (10, 11, 257, 258):
            data = responses()
            data["queryDeviceCtrlField"] = cloud.SmartClientCloudError(
                "api_rejected", code=code
            )
            with (
                self.subTest(code=code),
                self.assertRaises(cloud.SmartClientCloudError),
            ):
                fetch_fixture(data)

    def test_total_budget_prevents_later_requests(self):
        with (
            patch.object(cloud.time, "monotonic", side_effect=[0, 76]),
            patch.object(cloud, "_http_get_json") as get,
        ):
            with self.assertRaisesRegex(cloud.SmartClientCloudError, "timeout"):
                cloud.fetch_read_only_evidence(
                    username="owner", password="pass", collector_pn=PN
                )
            get.assert_not_called()

    def test_empty_cloud_data_does_not_claim_success(self):
        data = responses()
        for action in cloud.PASSIVE_ACTIONS - {
            "queryCollectorDevices",
            "queryDeviceInfo",
        }:
            data[action] = cloud.SmartClientCloudError("api_rejected", code=12)
        with self.assertRaisesRegex(
            cloud.SmartClientCloudError, "device_data_unavailable"
        ):
            fetch_fixture(data)
        data["queryDeviceLastData"] = responses()["queryDeviceLastData"][:2]
        data["queryDeviceLastRawData"] = {"dat": "", "valid": False}
        with self.assertRaisesRegex(
            cloud.SmartClientCloudError, "device_data_unavailable"
        ):
            fetch_fixture(data)

    def test_unaligned_daily_columns_and_bad_raw_data_are_not_guessed(self):
        data = responses()
        data["queryDeviceDataOneDay"]["row"][0]["field"].pop()
        data["queryDeviceLastRawData"]["dat"] = "!not-base64!"
        bundle, _ = fetch_fixture(data)
        self.assertFalse(bundle.history)
        self.assertFalse(bundle.raw_packet)
        self.assertIn("queryDeviceDataOneDay", bundle.unavailable_actions)

    def test_http_errors_never_include_signed_url_or_provider_text(self):
        url = "https://android.shinemonitor.com/public/?token=PRIVATE"
        for error in (
            HTTPError(url, 403, "PRIVATE", {}, io.BytesIO(b"PRIVATE")),
            URLError("PRIVATE"),
        ):
            with patch.object(cloud, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(cloud.SmartClientCloudError) as caught:
                    cloud._http_get_json(url, timeout=1)
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
        self.assertIsNone(
            cloud._NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://foreign.invalid"
            )
        )

    def test_no_data_due_to_timeouts_reports_timeout_not_missing_device(self):
        data = responses()
        for action in cloud.PASSIVE_ACTIONS - {
            "queryCollectorDevices",
            "queryDeviceInfo",
        }:
            data[action] = cloud.SmartClientCloudError("timeout")
        with self.assertRaisesRegex(cloud.SmartClientCloudError, "timeout"):
            fetch_fixture(data)

    def test_raw_validity_flag_is_preserved_without_boolean_inversion(self):
        data = responses()
        data["queryDeviceLastRawData"]["valid"] = 0
        bundle, _ = fetch_fixture(data)
        self.assertIs(type(bundle.raw_packet["valid"]), int)
        self.assertEqual(bundle.raw_packet["valid"], 0)

    def test_opaque_raw_identity_bytes_are_not_exported(self):
        data = responses()
        raw = b"\x00" + PN.encode() + b"\x00PRIVATE_SERIAL_12345678"
        encoded = base64.b64encode(raw).decode()
        data["queryDeviceLastRawData"]["dat"] = encoded
        bundle, _ = fetch_fixture(data)
        record = json.dumps(bundle.to_record())
        self.assertNotIn(encoded, record)
        self.assertNotIn("PRIVATE_SERIAL", record)

    def test_bounded_json_response_and_envelope_validation(self):
        for payload in (
            b"x" * (cloud.MAX_RESPONSE_BYTES + 1),
            b"[]",
            b'{"err":true}',
            b"not json",
        ):
            with patch.object(cloud, "build_opener") as opener:
                opener.return_value.open.return_value.__enter__.return_value.read.return_value = payload
                with self.assertRaises(cloud.SmartClientCloudError):
                    cloud._http_get_json(cloud.DEFAULT_BASE_URL, timeout=1)


if __name__ == "__main__":
    unittest.main()
