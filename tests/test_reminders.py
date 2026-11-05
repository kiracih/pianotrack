import unittest

from pianotrack.reminders import nudge, usual_start


class UsualStartTest(unittest.TestCase):
    def test_needs_three_days(self):
        self.assertIsNone(usual_start([1140, 1150]))
        self.assertEqual(usual_start([1140, 1150, 1130]), 1140)

    def test_circular_median_wraps_midnight(self):
        # 23:50 and 00:10 sit next to each other, not 23 hours apart.
        self.assertEqual(usual_start([1430, 10, 1435, 5, 1425]), 1320)  # near midnight, clamped to 22:00
        self.assertEqual(usual_start([20, 10, 1435, 5, 15]), 1320)  # just after midnight: 22:00 is nearer than 08:00

    def test_clamped_and_windowed(self):
        self.assertEqual(usual_start([380, 390, 400]), 480)
        self.assertEqual(usual_start([600] * 10 + [1200] * 14), 1200)


class NudgeTest(unittest.TestCase):
    def test_streak_and_habit(self):
        self.assertEqual(nudge(1140, 600, 0, 5, 4, 0), {"at": 1170, "kind": "streak"})
        self.assertEqual(nudge(1140, 600, 0, 5, 1, 0), {"at": 1170, "kind": "habit"})

    def test_quiet_cases(self):
        self.assertIsNone(nudge(None, 600, 0, 5, 4, 0))
        self.assertIsNone(nudge(1140, 600, 5, 5, 4, 0))  # today counts
        self.assertIsNone(nudge(1140, 1170, 0, 5, 4, 0))  # the time has passed
        self.assertIsNone(nudge(1140, 600, 0, 5, 4, 3))  # ignored three times

    def test_zero_minute_goal_still_needs_some_practice(self):
        self.assertEqual(nudge(1140, 600, 0, 0, 1, 0), {"at": 1170, "kind": "habit"})
        self.assertIsNone(nudge(1140, 600, 1, 0, 1, 0))

    def test_ties_go_to_the_smallest_value(self):
        self.assertEqual(usual_start([1000, 1100, 1000, 1100]), 1000)

    def test_never_after_22(self):
        self.assertEqual(nudge(1310, 600, 0, 5, 3, 0)["at"], 1320)


if __name__ == "__main__":
    unittest.main()
