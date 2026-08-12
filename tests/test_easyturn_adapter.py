import io
import unittest
from contextlib import redirect_stdout

from easyturn_adapter import EasyTurnAdapter


class ShortWordRegressionTests(unittest.TestCase):
    def utterance(self, text):
        return [{"text": text}]

    def test_missing_and_is_rejected_as_regression(self):
        previous = self.utterance("I wanted to explain this, and then continue")
        current = self.utterance("I wanted to explain this, then continue")
        self.assertTrue(
            EasyTurnAdapter._is_short_word_regression(previous, current)
        )

    def test_missing_content_word_is_not_rejected(self):
        previous = self.utterance("I wanted to explain this, and then continue")
        current = self.utterance("I wanted to explain this, and continue")
        self.assertFalse(
            EasyTurnAdapter._is_short_word_regression(previous, current)
        )

    def test_umm_and_but_are_preserved_in_normalization(self):
        previous = self.utterance("umm, but I can try")
        current = self.utterance("but I can try")
        self.assertTrue(
            EasyTurnAdapter._is_short_word_regression(previous, current)
        )

    def test_display_utterance_shows_text_and_pause_tags_only(self):
        adapter = EasyTurnAdapter.__new__(EasyTurnAdapter)
        output = io.StringIO()

        with redirect_stdout(output):
            adapter._display_utterance({
                "seq": 1,
                "text": "I wanted to explain this, and then continue",
                "raw_text": "I wanted to explain this, and <PAUSE:0.750s> then continue",
                "easyturn_label": "complete",
                "pauses": [{"duration": 0.75}],
                "extra": {
                    "result_id": "example",
                    "revision": 2,
                    "acoustic_duration": 0.262,
                },
            })

        rendered = output.getvalue()
        self.assertIn(
            "I wanted to explain this, and then continue <PAUSE:0.750s>",
            rendered,
        )
        self.assertNotIn("acoustic_duration", rendered)
        self.assertNotIn("result_id", rendered)

    def test_parse_failure_does_not_dump_raw_json(self):
        adapter = EasyTurnAdapter.__new__(EasyTurnAdapter)
        output = io.StringIO()

        with redirect_stdout(output):
            adapter._register_handlers()
            adapter.sio.handlers["/"]["final_transcription"][0]({
                "text": object(),
                "result_id": "private-result-id",
                "acoustic_duration": 0.262,
            })

        rendered = output.getvalue()
        self.assertIn("已跳过这条异常转录", rendered)
        self.assertNotIn("private-result-id", rendered)
        self.assertNotIn("acoustic_duration", rendered)


if __name__ == "__main__":
    unittest.main()
