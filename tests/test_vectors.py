import json
import os
import unittest

from pianotrack import vectors


class VectorsTest(unittest.TestCase):
    """The engine test vectors must stay true: a port is checked against them.

    If this fails after an intended change to the engine, run
    `python3 -m pianotrack vectors` and commit the new files.
    """

    def test_engine_matches_vectors(self):
        for name in vectors.CASES:
            with self.subTest(name), open(os.path.join(vectors.OUT_DIR, name + ".json")) as f:
                stored = json.load(f)
                fresh = json.loads(vectors.dumps(vectors.build(name)))
                self.assertEqual(stored["input"], fresh["input"], "input changed")
                for key in fresh["expected"]:
                    self.assertEqual(stored["expected"][key], fresh["expected"][key], key)

    def test_vectors_cover_the_engine(self):
        edges = json.load(open(os.path.join(vectors.OUT_DIR, "recorder-edges.json")))["expected"]
        self.assertEqual(len(edges["sessions"]), 3)  # the 5-note session is discarded
        weeks = json.load(open(os.path.join(vectors.OUT_DIR, "two-weeks-beginner.json")))["expected"]
        self.assertGreater(weeks["streak"]["longest"], weeks["streak"]["current"])
        self.assertGreaterEqual(len(weeks["pieces"]), 3)


if __name__ == "__main__":
    unittest.main()
