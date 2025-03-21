# flake8: noqa
from unittest.mock import patch
import warnings

import requests
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import TestCase, SimpleTestCase, override_settings, RequestFactory

from vidar import utils, helpers, models


class UtilTest(SimpleTestCase):
    def test_youtube_link_video_ids(self):
        # Obtained from: https://gist.github.com/rodrigoborgesdeoliveira/987683cfbfcc8d800192da1e73adc486
        link_formats = [
            ["-wtIMTCHWuI", "http://www.youtube.com/watch?v=-wtIMTCHWuI"],
            ["-wtIMTCHWuI", "http://www.youtube.com/v/-wtIMTCHWuI?version=3&autohide=1"],
            ["-wtIMTCHWuI", "http://youtu.be/-wtIMTCHWuI"],
            ["yZv2daTWRZU", "https://www.youtube.com/watch?v=yZv2daTWRZU&feature=em-uploademail"],
            ["0zM3nApSvMg", "https://www.youtube.com/watch?v=0zM3nApSvMg&feature=feedrec_grec_index"],
            ["QdK8U-VIH_o", "https://www.youtube.com/user/IngridMichaelsonVEVO#p/a/u/1/QdK8U-VIH_o"],
            ["0zM3nApSvMg", "https://www.youtube.com/v/0zM3nApSvMg?fs=1&amp;hl=en_US&amp;rel=0"],
            ["0zM3nApSvMg", "https://www.youtube.com/watch?v=0zM3nApSvMg#t=0m10s"],
            ["0zM3nApSvMg", "https://www.youtube.com/embed/0zM3nApSvMg?rel=0"],
            ["up_lNV-yoK4", "//www.youtube-nocookie.com/embed/up_lNV-yoK4?rel=0"],
            ["up_lNV-yoK4", "https://www.youtube-nocookie.com/embed/up_lNV-yoK4?rel=0"],
            ["1p3vcRhsYGo", "http://www.youtube.com/user/Scobleizer#p/u/1/1p3vcRhsYGo"],
            ["cKZDdG9FTKY", "http://www.youtube.com/watch?v=cKZDdG9FTKY&feature=channel"],
            [
                "yZ-K7nCVnBI",
                "http://www.youtube.com/watch?v=yZ-K7nCVnBI&playnext_from=TL&videos=osPknwzXEas&feature=sub",
            ],
            ["NRHVzbJVx8I", "http://www.youtube.com/ytscreeningroom?v=NRHVzbJVx8I"],
            ["6dwqZw0j_jY", "http://www.youtube.com/watch?v=6dwqZw0j_jY&feature=youtu.be"],
            ["1p3vcRhsYGo", "http://www.youtube.com/user/Scobleizer#p/u/1/1p3vcRhsYGo?rel=0"],
            ["nas1rJpm7wY", "http://www.youtube.com/embed/nas1rJpm7wY?rel=0"],
            ["peFZbP64dsU", "https://www.youtube.com/watch?v=peFZbP64dsU"],
            ["dQw4w9WgXcQ", "http://youtube.com/v/dQw4w9WgXcQ?feature=youtube_gdata_player"],
            ["dQw4w9WgXcQ", "http://youtube.com/?v=dQw4w9WgXcQ&feature=youtube_gdata_player"],
            ["dQw4w9WgXcQ", "http://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=youtube_gdata_player"],
            ["dQw4w9WgXcQ", "http://youtube.com/watch?v=dQw4w9WgXcQ&feature=youtube_gdata_player"],
            ["dQw4w9WgXcQ", "http://youtu.be/dQw4w9WgXcQ?feature=youtube_gdata_player"],
            ["6dwqZw0j_jY", "http://www.youtube.com/user/SilkRoadTheatre#p/a/u/2/6dwqZw0j_jY"],
            [
                "ishbTyLs6ps",
                "https://www.youtube.com/watch?v=ishbTyLs6ps&list=PLGup6kBfcU7Le5laEaCLgTKtlDcxMqGxZ&index=106&shuffle=2655",
            ],
            ["0zM3nApSvMg", "http://www.youtube.com/v/0zM3nApSvMg?fs=1&hl=en_US&rel=0"],
            ["0zM3nApSvMg", "http://www.youtube.com/watch?v=0zM3nApSvMg&feature=feedrec_grec_index"],
            ["0zM3nApSvMg", "http://www.youtube.com/watch?v=0zM3nApSvMg#t=0m10s"],
            ["dQw4w9WgXcQ", "http://www.youtube.com/embed/dQw4w9WgXcQ"],
            ["dQw4w9WgXcQ", "http://www.youtube.com/v/dQw4w9WgXcQ"],
            ["dQw4w9WgXcQ", "http://www.youtube.com/?v=dQw4w9WgXcQ"],
            ["dQw4w9WgXcQ", "http://www.youtube.com/watch?feature=player_embedded&v=dQw4w9WgXcQ"],
            ["dQw4w9WgXcQ", "http://www.youtube.com/?feature=player_embedded&v=dQw4w9WgXcQ"],
            ["KdwsulMb8EQ", "http://www.youtube.com/user/IngridMichaelsonVEVO#p/u/11/KdwsulMb8EQ"],
            ["6L3ZvIMwZFM", "http://www.youtube-nocookie.com/v/6L3ZvIMwZFM?version=3&hl=en_US&rel=0"],
            ["oTJRivZTMLs", "http://www.youtube.com/user/dreamtheater#p/u/1/oTJRivZTMLs"],
            ["oTJRivZTMLs", "https://youtu.be/oTJRivZTMLs?list=PLToa5JuFMsXTNkrLJbRlB--76IAOjRM9b"],
            ["oTJRivZTMLs", "http://www.youtube.com/watch?v=oTJRivZTMLs&feature=youtu.be"],
            ["oTJRivZTMLs", "http://youtu.be/oTJRivZTMLs&feature=channel"],
            ["oTJRivZTMLs", "http://www.youtube.com/ytscreeningroom?v=oTJRivZTMLs"],
            ["oTJRivZTMLs", "http://www.youtube.com/embed/oTJRivZTMLs?rel=0"],
            ["oTJRivZTMLs", "http://youtube.com/?v=oTJRivZTMLs&feature=channel"],
            ["oTJRivZTMLs", "http://youtube.com/?feature=channel&v=oTJRivZTMLs"],
            ["oTJRivZTMLs", "http://youtube.com/watch?v=oTJRivZTMLs&feature=channel"],
        ]

        for expected, url in link_formats:
            self.assertEqual(expected, utils.get_video_id_from_url(url), url)

    def test_youtube_link_playlist_ids(self):
        link_formats = [
            [
                "PLLZdy-WOpEMLXzRymPhzbPSmSxjlOLPwv",
                "https://www.youtube.com/playlist?list=PLLZdy-WOpEMLXzRymPhzbPSmSxjlOLPwv",
            ]
        ]
        for expected, url in link_formats:
            self.assertEqual(expected, utils.get_video_id_from_url(url, playlist=True), url)

    def test_do_new_start_end_points_overlap_existing_with_overlapping(self):
        existing_points = [
            (0, 6),
            (12, 18)
        ]
        self.assertEqual({0, 1, 2, 3, 4, 5, 6}, utils.do_new_start_end_points_overlap_existing(0, 6, existing_points))
        self.assertEqual({2, 3, 4, 5, 6, 12, 13, 14, 15, 16, 17, 18}, utils.do_new_start_end_points_overlap_existing(2, 18, existing_points))

        expected_output = {1, 2, 3, 4, 5, 6, 12, 13, 14, 15, 16, 17, 18}
        self.assertEqual(expected_output, utils.do_new_start_end_points_overlap_existing(1, 20, existing_points))

    def test_do_new_start_end_points_overlap_existing_not_overlapping(self):
        existing_points = [
            (0, 6),
            (12, 18)
        ]
        self.assertEqual(set(), utils.do_new_start_end_points_overlap_existing(7, 10, existing_points))

    def test_do_new_start_end_points_overlap_existing_one_right_after_the_other_allow_one_end_overlap_true(self):
        existing_points = [
            (0, 6),
        ]
        self.assertEqual(set(), utils.do_new_start_end_points_overlap_existing(6, 10, existing_points, allow_start_to_overlap_end=True))

    def test_do_new_start_end_points_overlap_existing_one_right_after_the_other_allow_one_end_overlap_false(self):
        existing_points = [
            (0, 6),
        ]
        self.assertEqual({6}, utils.do_new_start_end_points_overlap_existing(6, 10, existing_points, allow_start_to_overlap_end=False))

    def test_duration_min_max_checker(self):
        self.assertTrue(utils.is_duration_outside_min_max(60, 61, 0))
        self.assertFalse(utils.is_duration_outside_min_max(65, 61, 600))

    def test_duration_min_max_checker_minimum_only(self):
        self.assertTrue(utils.is_duration_outside_min_max(60, 61, 0))
        self.assertFalse(utils.is_duration_outside_min_max(65, 61, 0))

    def test_duration_min_max_checker_maximum_only(self):
        self.assertFalse(utils.is_duration_outside_min_max(60, 0, 600))
        self.assertTrue(utils.is_duration_outside_min_max(65, 0, 30))

    @override_settings(VIDAR_AUTOMATED_DOWNLOADS_DURATION_LIMIT_SPLIT=30)
    def test_should_halve_download_limit(self):
        for x in range(30):
            self.assertFalse(utils.should_halve_download_limit(x))

        self.assertTrue(utils.should_halve_download_limit(30))
        self.assertTrue(utils.should_halve_download_limit(31))

    def test_contains_one_of_many_at_least_one_match(self):
        find_within_this = "Show string finale"
        find_one_of_these = [
            " finale",
            " string",
        ]
        self.assertTrue(utils.contains_one_of_many(find_within_this, find_one_of_these))

    def test_contains_one_of_many_ensure_space_included(self):
        find_within_this = "Show finale"
        find_one_of_these = [
            " finale",
            " string",
        ]
        self.assertTrue(utils.contains_one_of_many(find_within_this, find_one_of_these))

    def test_contains_one_of_many_matches_without_spaces(self):
        find_within_this = "showfinale"
        find_one_of_these = [
            " finale",
            " string",
        ]
        self.assertTrue(utils.contains_one_of_many(find_within_this, find_one_of_these))

    def test_contains_one_of_many_fails(self):
        find_within_this = "show part 6"
        find_one_of_these = [
            " ",
            " finale",
            " string",
        ]
        self.assertFalse(utils.contains_one_of_many(find_within_this, find_one_of_these))

    def test_contains_one_of_many_raises(self):
        find_within_this = "show part 6"
        find_one_of_these = [
            2,
            " finale",
            " string",
        ]
        with self.assertRaises(ValueError):
            utils.contains_one_of_many(find_within_this, find_one_of_these)

    @patch('requests.get')
    def test_get_channel_id_from_url(self, mock_get):
        mock_get.return_value.text = """
        <!DOCTYPE html><html lang="en"><head>
            <link rel="canonical" href="https://www.youtube.com/channel/UCfIXdjDQH9Fau7y99_Orpjw">
        </head><body></body></html>
        """
        output = utils.get_channel_id_from_url("https://www.youtube.com/channel/UCfIXdjDQH9Fau7y99_Orpjw")
        self.assertEqual("UCfIXdjDQH9Fau7y99_Orpjw", output)
        mock_get.assert_not_called()

        output = utils.get_channel_id_from_url("https://www.youtube.com/@Gorillaz")
        self.assertEqual("UCfIXdjDQH9Fau7y99_Orpjw", output)
        mock_get.assert_called_once()

    @patch('requests.get')
    def test_get_channel_id_from_url_fails_bad_url(self, mock_get):
        mock_get.side_effect = requests.ConnectionError()

        with warnings.catch_warnings(record=True) as w:
            output = utils.get_channel_id_from_url("https://www.youtube.com/channel/bad")
            msg = w[-1]
            self.assertEqual("Failure to obtain youtube_id from youtube channel", str(msg.message))

            self.assertEqual("bad", output)
            mock_get.assert_called_once()


class HelperTest(TestCase):

    def test_next_day_of_week_is_valid(self):
        self.assertEqual(1, helpers.convert_to_next_day_of_week(0))
        self.assertEqual(2, helpers.convert_to_next_day_of_week(1))
        self.assertEqual(3, helpers.convert_to_next_day_of_week(2))
        self.assertEqual(4, helpers.convert_to_next_day_of_week(3))
        self.assertEqual(5, helpers.convert_to_next_day_of_week(4))
        self.assertEqual(6, helpers.convert_to_next_day_of_week(5))
        self.assertEqual(0, helpers.convert_to_next_day_of_week(6))
        self.assertEqual(1, helpers.convert_to_next_day_of_week(7))

    def test_unauthenticated_unable_to_access_vidar_video(self):
        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()
        self.assertFalse(helpers.unauthenticated_check_if_can_view_video(request, "video-id"))

    def test_unauthenticated_able_to_access_vidar_video(self):
        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()

        self.assertEqual([], helpers.unauthenticated_permitted_videos(request))

        helpers.unauthenticated_allow_view_video(request, "video-id")
        self.assertTrue(helpers.unauthenticated_check_if_can_view_video(request, "video-id"))
        self.assertEqual(["video-id"], helpers.unauthenticated_permitted_videos(request))

        helpers.unauthenticated_allow_view_video(request, "video-id2")
        self.assertEqual(["video-id", "video-id2"], helpers.unauthenticated_permitted_videos(request))

    def test_redirect_next_or_obj(self):
        request = RequestFactory().get("/")

        video = models.Video.objects.create()

        output = helpers.redirect_next_or_obj(request, video)
        self.assertEqual(video.get_absolute_url(), output.url)

        request = RequestFactory().get("/?next=/admin/")
        output = helpers.redirect_next_or_obj(request, video)
        self.assertEqual("/admin/", output.url)
