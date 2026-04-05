import os
import unittest
from unittest.mock import patch

import bot


class SmokeTests(unittest.TestCase):
    def test_normalize_review_state_handles_unset_and_invalid(self) -> None:
        self.assertEqual(bot.normalize_review_state(None), "unseen")
        self.assertEqual(bot.normalize_review_state(""), "unseen")
        self.assertEqual(bot.normalize_review_state("INVALID"), "unseen")
        self.assertEqual(bot.normalize_review_state("good"), "good")

    def test_low_star_high_score_settings_use_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LOW_STAR_HIGH_SCORE_MAX_STARS": "",
                "LOW_STAR_HIGH_SCORE_MIN_SCORE": "",
                "LOW_STAR_HIGH_SCORE_LIMIT": "",
            },
            clear=False,
        ):
            self.assertEqual(
                bot.low_star_high_score_settings(),
                {
                    "max_stars": 1000,
                    "min_score": 70.0,
                    "limit": 6,
                },
            )

    def test_low_star_high_score_settings_fallback_on_invalid_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LOW_STAR_HIGH_SCORE_MAX_STARS": "bad",
                "LOW_STAR_HIGH_SCORE_MIN_SCORE": "-1",
                "LOW_STAR_HIGH_SCORE_LIMIT": "0",
            },
            clear=False,
        ):
            self.assertEqual(
                bot.low_star_high_score_settings(),
                {
                    "max_stars": 1000,
                    "min_score": 70.0,
                    "limit": 6,
                },
            )

    def test_repo_slug_is_stable_and_sanitized(self) -> None:
        slug_a = bot.repo_slug("Owner Name/My Repo!!")
        slug_b = bot.repo_slug("Owner Name/My Repo!!")
        self.assertEqual(slug_a, slug_b)
        self.assertRegex(slug_a, r"^[a-z0-9-]+-[0-9a-f]{8}$")
        self.assertIn("owner-name-my-repo", slug_a)

    def test_site_shell_contains_history_query_initialization(self) -> None:
        html = bot.site_shell(
            "History",
            "subtitle",
            '<section class="archive-controls" data-archive-root></section>',
            "history",
        )
        for snippet in [
            "searchParams.get('search')",
            "searchParams.get('review_state')",
            "searchParams.get('language')",
            "searchParams.get('tag')",
            "searchParams.get('stars_min')",
            "searchParams.get('stars_max')",
            "searchParams.get('score_min')",
            "searchParams.get('score_max')",
            "searchParams.get('sort')",
            "params.set('search', search)",
        ]:
            self.assertIn(snippet, html)

    def test_aggregate_repo_history_builds_comparison_fields(self) -> None:
        history = [
            {
                "full_name": "owner/repo",
                "sent_at": "2026-04-03T00:00:00+00:00",
                "score": 110.5,
                "stars": 220,
                "bucket": "morning",
                "pick_reason": "new angle",
                "language": "Python",
                "topics": ["agents", "cli"],
            },
            {
                "full_name": "owner/repo",
                "sent_at": "2026-04-02T00:00:00+00:00",
                "score": 100.0,
                "stars": 200,
                "bucket": "evening",
                "pick_reason": "older angle",
                "language": "Python",
                "topics": ["agents"],
            },
            {
                "full_name": "other/repo",
                "sent_at": "2026-04-01T00:00:00+00:00",
            },
        ]
        aggregated = bot.aggregate_repo_history(history, {"owner/repo": "good"})
        entry = aggregated["owner/repo"]
        latest = entry["history_entries"][0]
        earliest = entry["history_entries"][1]

        self.assertEqual(latest["review_state"], "good")
        self.assertAlmostEqual(latest["score_delta"], 10.5)
        self.assertEqual(latest["stars_delta"], 20)
        self.assertTrue(latest["pick_reason_changed"])
        self.assertEqual(latest["topics_added"], ["cli"])
        self.assertEqual(latest["topics_removed"], [])
        self.assertIsNone(earliest["score_delta"])
        self.assertIsNone(earliest["stars_delta"])

    def test_find_similar_repos_tolerates_missing_fields(self) -> None:
        aggregated = {
            "owner/repo": {
                "full_name": "owner/repo",
                "language": "Python",
                "review_state": "good",
                "latest_score": 100.0,
                "topics": ["agents", "cli"],
                "description": "",
                "html_url": "",
                "latest_stars": 0,
            },
            "other/repo": {
                "full_name": "other/repo",
                "language": "Python",
                "review_state": "good",
                "latest_score": 95.0,
                "topics": [],
                "description": "",
                "html_url": "",
                "latest_stars": 0,
            },
            "missing/repo": {
                "full_name": "missing/repo",
            },
        }
        similar = bot.find_similar_repos(aggregated["owner/repo"], aggregated, limit=4)
        self.assertEqual(similar[0]["full_name"], "other/repo")
        self.assertIn("same language", similar[0]["similarity_reason"])


if __name__ == "__main__":
    unittest.main()
