import unittest

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


if __name__ == "__main__":
    unittest.main()
