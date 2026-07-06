import unittest
from unittest.mock import patch

from scripts.refresh_wechat_downloads import _next_batch, _subscription_fakeids


class WechatRefreshScriptTest(unittest.TestCase):
    def test_subscription_fakeids_extracts_common_response_shapes(self) -> None:
        payload = {
            "success": True,
            "data": [
                {"fakeid": "fake_1", "nickname": "账号一"},
                {"fake_id": "fake_2", "nickname": "账号二"},
                {"id": "fake_3", "nickname": "账号三"},
                {"nickname": "缺少 fakeid"},
            ],
        }

        self.assertEqual(_subscription_fakeids(payload), ["fake_1", "fake_2", "fake_3"])

    def test_subscription_fakeids_ignores_unknown_shapes(self) -> None:
        self.assertEqual(_subscription_fakeids({"success": True, "data": {}}), [])
        self.assertEqual(_subscription_fakeids(None), [])

    def test_next_batch_advances_cursor(self) -> None:
        state = {}

        def read_state() -> dict:
            return dict(state)

        def write_state(updated: dict) -> None:
            state.clear()
            state.update(dict(updated))

        with (
            patch("scripts.refresh_wechat_downloads._read_state", side_effect=read_state),
            patch("scripts.refresh_wechat_downloads._write_state", side_effect=write_state),
        ):
            self.assertEqual(_next_batch(["a", "b", "c", "d"], 2), ["a", "b"])
            self.assertEqual(_next_batch(["a", "b", "c", "d"], 2), ["c", "d"])
            self.assertEqual(_next_batch(["a", "b", "c", "d"], 2), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
