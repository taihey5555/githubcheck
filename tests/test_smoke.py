import os
import unittest
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
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

    def test_generated_repo_pages_match_history_repos(self) -> None:
        history = bot.load_history()
        aggregated = bot.aggregate_repo_history(history, bot.load_state().get("review_states", {}))
        expected_slugs = {bot.repo_slug(full_name) for full_name in aggregated}
        actual_slugs = {
            path.stem
            for path in bot.REPOS_DIR.glob("*.html")
            if path.name != "index.html"
        }

        self.assertTrue(actual_slugs.issubset(expected_slugs))

    def test_weekly_archive_helpers_group_history_by_tokyo_week(self) -> None:
        history = [
            {"sent_at": "2026-04-13T00:30:00+00:00"},
            {"sent_at": "2026-04-15T12:00:00+00:00"},
            {"sent_at": "2026-04-06T00:30:00+00:00"},
        ]
        week_starts = bot.collect_weekly_archive_starts(history)

        self.assertEqual(
            [bot.weekly_archive_slug(item) for item in week_starts],
            ["2026-04-13", "2026-04-06"],
        )
        self.assertEqual(
            bot.weekly_archive_href(week_starts[1]),
            "./weekly/2026-04-06.html",
        )

    def test_weekly_archive_links_render_as_select(self) -> None:
        latest_week = bot.parse_sent_at("2026-04-13T00:00:00+09:00")
        older_week = bot.parse_sent_at("2026-04-06T00:00:00+09:00")

        html = bot.build_weekly_archive_links_html(
            [latest_week, older_week],
            latest_week,
            older_week,
            path_prefix="..",
        )

        self.assertIn('data-weekly-archive-select', html)
        self.assertIn('value="../weekly.html"', html)
        self.assertIn('value="../weekly/2026-04-06.html" selected', html)

    def test_site_shell_contains_history_query_initialization(self) -> None:
        html = bot.site_shell(
            "History",
            "subtitle",
            '<section class="archive-controls" data-archive-root></section>',
            "history",
        )
        self.assertIn('href="./operations.html"', html)
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

    def test_review_state_request_issue_url_contains_repo_and_state(self) -> None:
        url = bot.review_state_request_issue_url("owner/repo", "good")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/taihey5555/githubcheck/issues/new")
        self.assertIn("[review-state] owner/repo -> good", query["title"][0])
        self.assertIn("repo: owner/repo", query["body"][0])
        self.assertIn("state: good", query["body"][0])

    def test_build_operations_summary_html_contains_cards(self) -> None:
        html = bot.build_operations_summary_html(".")
        self.assertIn("運用サマリー", html)
        self.assertIn("実行状況", html)
        self.assertIn("DeepSeek 警告", html)
        self.assertIn('href="./operations.html"', html)

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
        self.assertIn("同じ言語", similar[0]["similarity_reason"])

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

    def test_gray_repo_analysis_classifies_lada_style_repo(self) -> None:
        repo = {
            "full_name": "ladaapp/lada",
            "name": "lada",
            "stargazers_count": 2900,
            "forks_count": 370,
            "created_at": "2026-04-01T00:00:00+00:00",
            "pushed_at": "2026-04-05T00:00:00+00:00",
            "description": "Restore videos with pixelated/mosaic regions",
            "topics": ["video-restoration", "nsfw-ai"],
            "_readme_text": "Recover pixelated adult videos with mosaic restore models.",
        }
        profile = bot.analyze_gray_repo(repo, {"repos": {}})
        self.assertEqual(profile["category"], "adult_ai_media")
        self.assertEqual(profile["risk_status"], "allow")
        self.assertGreater(profile["grey_score"], 40)

    def test_gray_repo_analysis_excludes_clear_malware_repo(self) -> None:
        repo = {
            "full_name": "bad/repo",
            "name": "repo",
            "stargazers_count": 1,
            "forks_count": 0,
            "created_at": "2026-04-01T00:00:00+00:00",
            "pushed_at": "2026-04-05T00:00:00+00:00",
            "description": "Credential stealer and malware builder",
            "topics": [],
            "_readme_text": "",
        }
        profile = bot.analyze_gray_repo(repo, {"repos": {}})
        self.assertEqual(profile["risk_status"], "exclude")

    def test_gray_repo_analysis_classifies_facefusion_style_repo(self) -> None:
        repo = {
            "full_name": "facefusion/facefusion",
            "name": "facefusion",
            "stargazers_count": 26000,
            "forks_count": 3000,
            "created_at": "2024-01-01T00:00:00+00:00",
            "pushed_at": "2026-05-01T00:00:00+00:00",
            "description": "Industry leading face manipulation platform",
            "topics": ["ai", "faceswap", "face-swap", "lip-sync", "deepfake"],
            "_readme_text": "FaceFusion supports face swap, face enhancer and lip sync workflows.",
        }
        profile = bot.analyze_gray_repo(repo, {"repos": {}})
        self.assertEqual(profile["category"], "face_deepfake_live")
        self.assertEqual(profile["risk_status"], "allow")
        self.assertIn("faceswap", profile["matched_keywords"])

    def test_gray_repo_analysis_marks_deep_live_cam_needs_review(self) -> None:
        repo = {
            "full_name": "hacksider/Deep-Live-Cam",
            "name": "Deep-Live-Cam",
            "stargazers_count": 83000,
            "forks_count": 12000,
            "created_at": "2024-01-01T00:00:00+00:00",
            "pushed_at": "2026-05-01T00:00:00+00:00",
            "description": "Real time face swap and one-click video deepfake with only a single image",
            "topics": ["faceswap", "realtime-deepfake", "webcam", "fake-webcam", "video-deepfake"],
            "_readme_text": "Realtime deepfake webcam and fake webcam workflow for face changing.",
        }
        profile = bot.analyze_gray_repo(repo, {"repos": {}})
        self.assertEqual(profile["category"], "face_deepfake_live")
        self.assertEqual(profile["risk_status"], "needs_review")
        self.assertIn("fake webcam", profile["risk_keywords"])

    def test_gray_search_queries_include_seed_keywords(self) -> None:
        config = bot.Config(
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
            collection_profile="gray",
            github_search_sorts=["stars"],
        )
        state = {"gray_collection": {"keywords": ["video restoration"]}}
        queries = bot.build_search_queries(
            config,
            datetime(2026, 4, 10, tzinfo=UTC),
            state,
        )
        joined = "\n".join(queries)
        self.assertIn("mosaic restore", joined)
        self.assertIn("video restoration", joined)
        self.assertIn("face swap", joined)

    def test_extract_tags_includes_gray_category(self) -> None:
        tags = bot.extract_tags(
            {
                "topics": ["video"],
                "x_post": "",
                "gray_profile": {"category": "adult_ai_media"},
            }
        )
        self.assertIn("成人向けAI・メディア復元系", tags)

    def test_gray_display_profile_does_not_require_saved_profile(self) -> None:
        profile = bot.gray_display_profile(
            {
                "full_name": "owner/video-tool",
                "description": "mosaic restore utility",
                "topics": ["video-restoration"],
                "x_post": "",
            }
        )
        self.assertTrue(profile["is_gray"])
        self.assertEqual(profile["category"], "adult_ai_media")

    def test_build_card_dataset_includes_gray_display_attrs(self) -> None:
        dataset = bot.build_card_dataset(
            {
                "full_name": "owner/repo",
                "sent_at": "2026-04-01T00:00:00+00:00",
                "score": 91,
                "stars": 120,
                "language": "Python",
                "bucket": "morning",
                "gray_profile": {
                    "category": "scraper_downloader",
                    "risk_status": "needs_review",
                },
            },
            "unseen",
        )
        self.assertEqual(dataset["gray-mode"], "true")
        self.assertEqual(dataset["gray-category"], "scraper_downloader")
        self.assertEqual(dataset["gray-risk"], "needs_review")

    def test_gray_category_label_localizes_known_categories(self) -> None:
        self.assertEqual(
            bot.gray_category_label("face_deepfake_live"),
            "顔入れ替え・リアルタイムdeepfake系",
        )
        self.assertEqual(bot.gray_category_label("unknown"), "unknown")

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

    def test_fallback_generated_content_does_not_echo_raw_description(self) -> None:
        repo = {
            "full_name": "jnMetaCode/superpowers-zh",
            "description": "让 Claude Code 变得更强大的中文插件集合",
            "language": "Python",
            "stargazers_count": 2533,
            "topics": ["claude-code", "中文"],
            "html_url": "https://github.com/jnMetaCode/superpowers-zh",
        }

        summary, x_post, pick_reason = bot.build_fallback_generated_content(repo)

        self.assertIn("説明文の自動要約に失敗", summary)
        self.assertIn("要約生成を再確認", pick_reason)
        self.assertIn("用途はGitHub本文で確認", summary)
        self.assertNotIn(repo["description"], summary)
        self.assertNotIn(repo["description"], x_post)

    def test_split_generated_content_uses_fallback_for_malformed_output(self) -> None:
        repo = {
            "full_name": "owner/repo",
            "description": "English raw description should not be echoed",
            "language": "TypeScript",
            "stargazers_count": 12,
            "topics": [],
            "html_url": "https://github.com/owner/repo",
        }

        summary, x_post, pick_reason = bot.split_generated_content(
            "malformed model output without required sections",
            repo,
        )

        self.assertIn("説明文の自動要約に失敗", summary)
        self.assertEqual(pick_reason, "要約生成を再確認")
        self.assertNotIn(repo["description"], summary)
        self.assertNotIn("malformed model output", summary)
        self.assertNotIn(repo["description"], x_post)

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
