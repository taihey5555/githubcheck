import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import bot
import requests


class SmokeTests(unittest.TestCase):
    def test_normalize_review_state_handles_unset_and_invalid(self) -> None:
        self.assertEqual(bot.normalize_review_state(None), "unseen")
        self.assertEqual(bot.normalize_review_state(""), "unseen")
        self.assertEqual(bot.normalize_review_state("INVALID"), "unseen")
        self.assertEqual(bot.normalize_review_state("good"), "good")

    def test_format_state_timestamp_handles_empty_and_iso(self) -> None:
        self.assertEqual(bot.format_state_timestamp(""), "-")
        self.assertEqual(
            bot.format_state_timestamp("2026-04-05T00:10:00+00:00"),
            "2026-04-05 09:10",
        )

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

    def test_score_repo_applies_new_topic_keyword_bonuses(self) -> None:
        repo = {
            "full_name": "owner/repo",
            "stargazers_count": 120,
            "created_at": "2026-04-01T00:00:00+00:00",
            "pushed_at": "2026-04-04T00:00:00+00:00",
            "description": "Agentic scraper with monitoring alerts",
            "topics": ["agents", "scraping", "monitoring"],
            "_readme_text": "",
        }
        base_config = bot.Config(
            github_token="",
            deepseek_api_key="",
            telegram_bot_token="",
            telegram_chat_id="",
            public_history_url="",
            public_weekly_url="",
            top_n=3,
            notify_times=["09:00", "20:00"],
            timezone="Asia/Tokyo",
            topics=[],
            min_stars=30,
            cooldown_days=14,
        )
        boosted_config = bot.Config(
            github_token="",
            deepseek_api_key="",
            telegram_bot_token="",
            telegram_chat_id="",
            public_history_url="",
            public_weekly_url="",
            top_n=3,
            notify_times=["09:00", "20:00"],
            timezone="Asia/Tokyo",
            topics=["agents", "scraping", "monitoring"],
            min_stars=30,
            cooldown_days=14,
        )
        base_score = bot.score_repo(repo, {"repos": {}}, base_config, bucket="morning")
        boosted_score = bot.score_repo(repo, {"repos": {}}, boosted_config, bucket="morning")
        self.assertGreater(boosted_score, base_score)

    def test_classify_deepseek_error_handles_billing_and_rate_limit(self) -> None:
        billing_response = requests.Response()
        billing_response.status_code = 402
        billing_response._content = b'{"error":"insufficient balance"}'
        billing_error = requests.exceptions.HTTPError(response=billing_response)
        self.assertEqual(
            bot.classify_deepseek_error(billing_error),
            ("quota/auth/billing", "status=402"),
        )

        rate_response = requests.Response()
        rate_response.status_code = 429
        rate_response._content = b'{"error":"rate limit exceeded"}'
        rate_error = requests.exceptions.HTTPError(response=rate_response)
        self.assertEqual(
            bot.classify_deepseek_error(rate_error),
            ("rate_limit", "status=429"),
        )

    def test_should_send_deepseek_warning_throttles_same_kind(self) -> None:
        state = {
            "alerts": {
                "deepseek": {
                    "rate_limit": {
                        "last_sent": (datetime.now(UTC) - timedelta(hours=6)).isoformat()
                    }
                }
            }
        }
        self.assertFalse(bot.should_send_deepseek_warning(state, "rate_limit"))
        state["alerts"]["deepseek"]["rate_limit"]["last_sent"] = (
            datetime.now(UTC) - timedelta(hours=13)
        ).isoformat()
        self.assertTrue(bot.should_send_deepseek_warning(state, "rate_limit"))

    def test_record_run_status_updates_state_fields(self) -> None:
        state = {"repos": {}, "notifications": {}, "review_states": {}, "alerts": {}}
        with patch("bot.save_state") as save_state_mock:
            bot.record_run_status(
                state,
                started_at="2026-04-05T00:00:00+00:00",
                status="running",
                error=None,
            )
            self.assertEqual(state["last_run_started_at"], "2026-04-05T00:00:00+00:00")
            self.assertEqual(state["last_run_status"], "running")
            self.assertNotIn("last_run_error", state)
            save_state_mock.assert_called_once()

    def test_record_run_status_sets_and_clears_last_run_error(self) -> None:
        state = {"repos": {}, "notifications": {}, "review_states": {}, "alerts": {}}
        with patch("bot.save_state"):
            bot.record_run_status(
                state,
                finished_at="2026-04-05T00:10:00+00:00",
                status="failed",
                error="RuntimeError: boom",
            )
            self.assertEqual(state["last_run_finished_at"], "2026-04-05T00:10:00+00:00")
            self.assertEqual(state["last_run_status"], "failed")
            self.assertEqual(state["last_run_error"], "RuntimeError: boom")
            bot.record_run_status(
                state,
                finished_at="2026-04-05T00:11:00+00:00",
                status="success",
                error=None,
            )
            self.assertEqual(state["last_run_status"], "success")
            self.assertNotIn("last_run_error", state)


if __name__ == "__main__":
    unittest.main()
