from unittest.mock import patch
import warnings

import requests
from django.db.models import Case
from django.test import TestCase, override_settings
from django.utils import timezone

from vidar import utils, models, app_settings

from . import test_functions


class UtilTest(TestCase):
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

    def test_non_youtube_link(self):
        self.assertIsNone(
            utils.get_video_id_from_url(
                "https://www.google.com/?document_id=PLLZdy-WOpEMLXzRymPhzbPSmSxjlOLPwv"
            ),
        )

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

    def test_convert_timestamp_to_datetime(self):
        now = timezone.now()

        output = utils.convert_timestamp_to_datetime(timestamp=now.timestamp())

        self.assertEqual(now, output)

    @patch("requests.get")
    def test_get_sponsorblock_video_data(self, mock_get):
        mock_get.return_value.json.return_value = ["test1"]

        output = utils.get_sponsorblock_video_data(video_id="test-id")

        mock_get.assert_called_once()

        self.assertEqual(["test1"], output)

    @patch("requests.get")
    def test_get_sponsorblock_video_data_404_returns_nothing(self, mock_get):
        mock_get.return_value.json.return_value = ["test1"]
        mock_get.return_value.status_code = 404

        output = utils.get_sponsorblock_video_data(video_id="test-id")

        mock_get.assert_called_once()

        self.assertEqual([], output)

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES=['proxy1', 'proxy2', 'proxy3', 'proxy4']
    )
    def test_get_proxy_returns_default_after_x(self):
        possible_proxies = ['proxy1', 'proxy2', 'proxy3', 'proxy4']
        self.assertIn(utils.get_proxy(attempt=0), possible_proxies)
        self.assertIn(utils.get_proxy(attempt=1), possible_proxies)
        self.assertEqual("default proxy", utils.get_proxy(attempt=2))

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES=['proxy1', 'proxy2', 'proxy3', 'proxy4']
    )
    def test_get_proxy_with_previous_proxies_supplied(self):
        self.assertEqual("proxy3", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy4']))
        self.assertEqual("default proxy", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy3', 'proxy4']))

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES='proxy1,proxy2,proxy3,proxy4'
    )
    def test_get_proxy_proxies_supplied_as_comma_delim_string(self):
        self.assertEqual("proxy3", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy4']))
        self.assertEqual("default proxy", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy3', 'proxy4']))

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES='http://example.com'
    )
    def test_get_proxy_proxies_supplied_as_single_string(self):
        self.assertEqual("http://example.com", utils.get_proxy())
        self.assertEqual("default proxy", utils.get_proxy(previous_proxies=['http://example.com']))

    @override_settings(
        VIDAR_PROXIES_DEFAULT="default proxy",
        VIDAR_PROXIES='proxy1;proxy2;proxy3;proxy4'
    )
    def test_get_proxy_proxies_supplied_as_semicolon_delim_string(self):
        self.assertEqual("proxy3", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy4']))
        self.assertEqual("default proxy", utils.get_proxy(previous_proxies=['proxy1', 'proxy2', 'proxy3', 'proxy4']))

    @override_settings(VIDAR_PROXIES=test_functions.proxies_user_defined)
    def test_get_proxy_with_proxies_user_defined_function(self):
        self.assertEqual(test_functions.proxies_user_defined, app_settings.PROXIES)

        output = utils.get_proxy(previous_proxies=['passed into utils.get_proxy'])
        self.assertEqual(dict(previous_proxies=["passed into utils.get_proxy"], instance=None, attempt=None), output)

    @override_settings(VIDAR_PROXIES="tests.test_functions.proxies_user_defined")
    def test_get_proxy_with_proxies_user_defined_function_dot_notation(self):
        self.assertEqual(test_functions.proxies_user_defined, app_settings.PROXIES)

        output = utils.get_proxy(previous_proxies=['passed into utils.get_proxy'])
        self.assertEqual(dict(previous_proxies=["passed into utils.get_proxy"], instance=None, attempt=None), output)

    @override_settings(VIDAR_PROXIES="invalid_function.dot.pathway")
    def test_get_proxy_with_proxies_user_defined_function_dot_notation_invalid_path(self):
        with self.assertRaises(ImportError):
            self.assertEqual(test_functions.proxies_user_defined, app_settings.PROXIES)

    @override_settings(VIDAR_PROXIES=test_functions.proxies_user_defined)
    def test_get_proxy_with_proxies_user_defined_function_always_called(self):
        self.assertEqual(test_functions.proxies_user_defined, app_settings.PROXIES)

        output = utils.get_proxy(previous_proxies=['passed into utils.get_proxy'], attempt=100)
        self.assertEqual(dict(previous_proxies=["passed into utils.get_proxy"], instance=None, attempt=100), output)

    def test_get_channel_ordering_by_next_crontab_whens(self):
        ts = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        channel1 = models.Channel.objects.create(scanner_crontab='10 9 * * *', index_videos=True)
        channel2 = models.Channel.objects.create(scanner_crontab='20 9 * * *', index_videos=True)
        channel3 = models.Channel.objects.create(scanner_crontab='30 9 * * *', index_videos=True)

        whens = utils.get_channel_ordering_by_next_crontab_whens()
        channels = (
            models.Channel.objects.all()
                .annotate(channel_next_based_order=Case(*whens, default=10000))
                .order_by("channel_next_based_order", "name")
        )

        self.assertEqual(channel1, channels[0])
        self.assertEqual(channel2, channels[1])
        self.assertEqual(channel3, channels[2])

    def test_get_channel_ordering_by_next_crontab_whens_odd_order(self):
        ts = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        channel1 = models.Channel.objects.create(scanner_crontab='10 9 * * *', index_videos=True)
        channel2 = models.Channel.objects.create(scanner_crontab='30 9 * * *', index_videos=True)
        channel3 = models.Channel.objects.create(scanner_crontab='20 9 * * *', index_videos=True)

        whens = utils.get_channel_ordering_by_next_crontab_whens()
        channels = (
            models.Channel.objects.all()
                .annotate(channel_next_based_order=Case(*whens, default=10000))
                .order_by("channel_next_based_order", "name")
        )

        self.assertEqual(channel1, channels[0])
        self.assertEqual(channel3, channels[1])
        self.assertEqual(channel2, channels[2])

    def test_generate_balanced_crontab_hourly(self):
        output = utils.generate_balanced_crontab_hourly()
        self.assertRegex(output, r'^(0|10|20|30|40|50) (7-21\/4|6-22\/4) \* \* \*$')

    def test_hourly_balanced(self):

        # Hourly also balances to try and ensure channels are spread
        #   out among the 2 hour selections.
        # Let's fill out all of one hour
        models.Channel.objects.create(scanner_crontab='0 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='10 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='20 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='30 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='40 7-21/4 * * *')
        models.Channel.objects.create(scanner_crontab='50 7-21/4 * * *')

        for x in range(14):
            output = utils.generate_balanced_crontab_hourly()
            self.assertRegex(output, r'^(0|10|20|30|40|50) 6-22/4 \* \* \*$')

    def test_OutputCapturer(self):
        self.print_counter = 0
        def printer(*args, **kwargs):
            self.print_counter += 1

        oc = utils.OutputCapturer(callback_func=printer)
        oc.info("info")
        oc.warning("warning")
        oc.debug("debug")
        oc.error("error")
        self.assertEqual(4, self.print_counter)
