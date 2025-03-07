# flake8: noqa
import json
import logging
import pathlib

from unittest.mock import patch

from django.test import TestCase, SimpleTestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from vidar import models, exceptions
from vidar.services import (
    schema_services,
    ytdlp_services,
    channel_services,
    video_services,
    crontab_services,
    playlist_services,
    redis_services
)
from vidar.helpers import video_helpers

UserModel = get_user_model()


class CrontabServicesTests(SimpleTestCase):

    def test_weekday_sunday_zero(self):
        ts = timezone.datetime(2024, 10, 1)
        self.assertEqual(2, crontab_services.isoweekday_sunday_zero(ts.replace(day=1).isoweekday()))
        self.assertEqual(3, crontab_services.isoweekday_sunday_zero(ts.replace(day=2).isoweekday()))
        self.assertEqual(4, crontab_services.isoweekday_sunday_zero(ts.replace(day=3).isoweekday()))
        self.assertEqual(5, crontab_services.isoweekday_sunday_zero(ts.replace(day=4).isoweekday()))
        self.assertEqual(6, crontab_services.isoweekday_sunday_zero(ts.replace(day=5).isoweekday()))
        self.assertEqual(0, crontab_services.isoweekday_sunday_zero(ts.replace(day=6).isoweekday()))
        self.assertEqual(1, crontab_services.isoweekday_sunday_zero(ts.replace(day=7).isoweekday()))

    def test_calculate_schedule(self):
        output = crontab_services.calculate_schedule('10 9 * * *')

        self.assertEqual(1, len(output))

        dt = output[0]

        should_be_this = timezone.localtime().replace(hour=9, minute=10, second=0, microsecond=0)

        self.assertEqual(should_be_this, dt)

    def test_calculate_schedule_multiple(self):
        output = crontab_services.calculate_schedule('10 9,18 * * *')

        self.assertEqual(2, len(output))

        should_be_this_1 = timezone.localtime().replace(hour=9, minute=10, second=0, microsecond=0)
        should_be_this_2 = timezone.localtime().replace(hour=18, minute=10, second=0, microsecond=0)

        self.assertIn(should_be_this_1, output)
        self.assertIn(should_be_this_2, output)

    def test_calculate_schedule_month_long(self):
        now = timezone.localtime().replace(year=2024, month=10, day=1)
        crontab = '10 9,18 * * *'
        output = crontab_services.calculate_schedule(crontab, check_month=True, now=now)

        self.assertEqual(62, len(output))
        now = timezone.localtime().replace(year=2024, month=10, day=1)

        for day in range(1, 32):

            for hour in range(0, 9):
                now = now.replace(day=day, hour=hour, minute=10, second=0, microsecond=0)
                self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now), f"{day=} {hour=} should be False")

            now = now.replace(day=day, hour=9, minute=10, second=0, microsecond=0)
            self.assertIn(now, output)
            output.remove(now)
            self.assertTrue(crontab_services.is_active_now(crontab=crontab, now=now), f"{day=} hour=9 should be True")

            for hour in range(10, 18):
                now = now.replace(day=day, hour=hour, minute=10, second=0, microsecond=0)
                self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now), f"{day=} {hour=} should be False")

            now = now.replace(day=day, hour=18, minute=10, second=0, microsecond=0)
            self.assertIn(now, output)
            output.remove(now)
            self.assertTrue(crontab_services.is_active_now(crontab=crontab, now=now), f"{day=} hour=18 should be True")

            for hour in range(19, 24):
                now = now.replace(day=day, hour=hour, minute=10, second=0, microsecond=0)
                self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now), f"{day=} {hour=} should be False")

        self.assertEqual(0, len(output))

    def test_is_active_now(self):
        crontab = '10 9,18 * * *'

        for hour in range(0, 9):
            now = timezone.localtime().replace(hour=hour, minute=10, second=0, microsecond=0)
            self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now), f"{hour=} should be False")

        now = timezone.localtime().replace(hour=9, minute=10, second=0, microsecond=0)
        self.assertTrue(crontab_services.is_active_now(crontab=crontab, now=now), f"hour=9 should be True")

        for hour in range(10, 18):
            now = timezone.localtime().replace(hour=hour, minute=10, second=0, microsecond=0)
            self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now), f"{hour=} should be False")

        now = timezone.localtime().replace(hour=18, minute=10, second=0, microsecond=0)
        self.assertTrue(crontab_services.is_active_now(crontab=crontab, now=now), f"hour=18 should be True")

        for hour in range(19, 24):
            now = timezone.localtime().replace(hour=hour, minute=10, second=0, microsecond=0)
            self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now), f"{hour=} should be False")

    def test_is_active_now_weekday_corrected(self):
        crontab = '10 9 * * 2'

        # Tuesday = crontab weekday 2
        now = timezone.localtime().replace(year=2024, month=10, day=1, hour=9, minute=10, second=0, microsecond=0)
        self.assertTrue(crontab_services.is_active_now(crontab=crontab, now=now))

        # Wednesday = crontab weekday 3
        now = timezone.localtime().replace(year=2024, month=10, day=2, hour=9, minute=10, second=0, microsecond=0)
        self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now))

        # Thursday = crontab weekday 4
        now = timezone.localtime().replace(year=2024, month=10, day=3, hour=9, minute=10, second=0, microsecond=0)
        self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now))

        # Friday = crontab weekday 5
        now = timezone.localtime().replace(year=2024, month=10, day=4, hour=9, minute=10, second=0, microsecond=0)
        self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now))

        # Saturday = crontab weekday 6
        now = timezone.localtime().replace(year=2024, month=10, day=5, hour=9, minute=10, second=0, microsecond=0)
        self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now))

        # Sunday = crontab weekday 0
        now = timezone.localtime().replace(year=2024, month=10, day=6, hour=9, minute=10, second=0, microsecond=0)
        self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now))

        # Monday = crontab weekday 1
        now = timezone.localtime().replace(year=2024, month=10, day=7, hour=9, minute=10, second=0, microsecond=0)
        self.assertFalse(crontab_services.is_active_now(crontab=crontab, now=now))

        # Tuesday = crontab weekday 2
        now = timezone.localtime().replace(year=2024, month=10, day=8, hour=9, minute=10, second=0, microsecond=0)
        self.assertTrue(crontab_services.is_active_now(crontab=crontab, now=now))

    def test_range_steps_not_enough(self):
        with self.assertRaises(crontab_services.ParseException):
            crontab_services.CrontabParser(24)._range_steps([1])

    def test_parse_star(self):
        self.assertEqual(crontab_services.CrontabParser(24).parse('*'), set(range(24)))
        self.assertEqual(crontab_services.CrontabParser(60).parse('*'), set(range(60)))
        self.assertEqual(crontab_services.CrontabParser(7).parse('*'), set(range(7)))
        self.assertEqual(crontab_services.CrontabParser(31, 1).parse('*'), set(range(1, 31 + 1)))
        self.assertEqual(crontab_services.CrontabParser(12, 1).parse('*'), set(range(1, 12 + 1)))

    def test_parse_range(self):
        self.assertEqual(crontab_services.CrontabParser(60).parse('1-10'), set(range(1, 10 + 1)))
        self.assertEqual(crontab_services.CrontabParser(24).parse('0-20'), set(range(0, 20 + 1)))
        self.assertEqual(crontab_services.CrontabParser().parse('2-10'), set(range(2, 10 + 1)))
        self.assertEqual(crontab_services.CrontabParser(60, 1).parse('1-10'), set(range(1, 10 + 1)))

    def test_parse_range_wraps(self):
        self.assertEqual(crontab_services.CrontabParser(12).parse('11-1'), {11, 0, 1})
        self.assertEqual(crontab_services.CrontabParser(60, 1).parse('2-1'), set(range(1, 60 + 1)))

    def test_parse_groups(self):
        self.assertEqual(crontab_services.CrontabParser().parse('1,2,3,4'), {1, 2, 3, 4})
        self.assertEqual(crontab_services.CrontabParser().parse('0,15,30,45'), {0, 15, 30, 45})
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('1,2,3,4'), {1, 2, 3, 4})

    def test_parse_steps(self):
        self.assertEqual(crontab_services.CrontabParser(8).parse('*/2'), {0, 2, 4, 6})
        self.assertEqual(crontab_services.CrontabParser().parse('*/2'), {i * 2 for i in range(30)})
        self.assertEqual(crontab_services.CrontabParser().parse('*/3'), {i * 3 for i in range(20)})
        self.assertEqual(crontab_services.CrontabParser(8, 1).parse('*/2'), {1, 3, 5, 7})
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('*/2'), {
            i * 2 + 1 for i in range(30)
        })
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('*/3'), {
            i * 3 + 1 for i in range(20)
        })

    def test_parse_composite(self):
        self.assertEqual(crontab_services.CrontabParser(8).parse('*/2'), {0, 2, 4, 6})
        self.assertEqual(crontab_services.CrontabParser().parse('2-9/5'), {2, 7})
        self.assertEqual(crontab_services.CrontabParser().parse('2-10/5'), {2, 7})
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('55-5/3'), {55, 58, 1, 4})
        self.assertEqual(crontab_services.CrontabParser().parse('2-11/5,3'), {2, 3, 7})
        self.assertEqual(crontab_services.CrontabParser().parse('2-4/3,*/5,0-21/4'), {
            0, 2, 4, 5, 8, 10, 12, 15, 16, 20, 25, 30, 35, 40, 45, 50, 55,
        })
        self.assertEqual(crontab_services.CrontabParser().parse('1-9/2'), {1, 3, 5, 7, 9})
        self.assertEqual(crontab_services.CrontabParser(8, 1).parse('*/2'), {1, 3, 5, 7})
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('2-9/5'), {2, 7})
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('2-10/5'), {2, 7})
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('2-11/5,3'), {2, 3, 7})
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('2-4/3,*/5,1-21/4'), {
            1, 2, 5, 6, 9, 11, 13, 16, 17, 21, 26, 31, 36, 41, 46, 51, 56,
        })
        self.assertEqual(crontab_services.CrontabParser(min_=1).parse('1-9/2'), {1, 3, 5, 7, 9})

    def test_parse_errors_on_empty_string(self):
        with self.assertRaises(crontab_services.ParseException):
            crontab_services.CrontabParser(60).parse('')

    def test_parse_errors_on_empty_group(self):
        with self.assertRaises(crontab_services.ParseException):
            crontab_services.CrontabParser(60).parse('1,,2')

    def test_parse_errors_on_empty_steps(self):
        with self.assertRaises(crontab_services.ParseException):
            crontab_services.CrontabParser(60).parse('*/')

    def test_parse_errors_on_negative_number(self):
        with self.assertRaises(crontab_services.ParseException):
            crontab_services.CrontabParser(60).parse('-20')

    def test_parse_errors_on_lt_min(self):
        crontab_services.CrontabParser(min_=1).parse('1')
        with self.assertRaises(ValueError):
            crontab_services.CrontabParser(12, 1).parse('0')
        with self.assertRaises(ValueError):
            crontab_services.CrontabParser(24, 1).parse('12-0')

    def test_parse_errors_on_gt_max(self):
        crontab_services.CrontabParser(1).parse('0')
        with self.assertRaises(ValueError):
            crontab_services.CrontabParser(1).parse('1')
        with self.assertRaises(ValueError):
            crontab_services.CrontabParser(60).parse('61-0')

    def test_day_of_week_includes_zero_through_seven(self):
        *_, day_of_week = crontab_services.parse('* * * * *')
        self.assertEqual(day_of_week, {0, 1, 2, 3, 4, 5, 6, 7})

    def test_weekday_by_name_into_number(self):
        days = 'sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'
        for index, day in zip(range(0, 6, 1), days):
            self.assertEqual(index, crontab_services.weekday(day))

        with self.assertRaises(KeyError):
            crontab_services.weekday('weekday that does not exist')

    def test_validate_crontab_values_minute(self):

        self.assertTrue(crontab_services.validate_crontab_values(minute=0))
        self.assertTrue(crontab_services.validate_crontab_values(minute=10))
        self.assertTrue(crontab_services.validate_crontab_values(minute=20))
        self.assertTrue(crontab_services.validate_crontab_values(minute=30))
        self.assertTrue(crontab_services.validate_crontab_values(minute=40))
        self.assertTrue(crontab_services.validate_crontab_values(minute=50))

        def check_valueerror_raised(value):

            for x in range(value, 60, 10):
                with self.assertRaisesRegex(ValueError, 'divisible by 10'):
                    crontab_services.validate_crontab_values(minute=x)

        check_valueerror_raised(1)
        check_valueerror_raised(2)
        check_valueerror_raised(3)
        check_valueerror_raised(4)
        check_valueerror_raised(5)
        check_valueerror_raised(6)
        check_valueerror_raised(7)
        check_valueerror_raised(8)
        check_valueerror_raised(9)

        with self.assertRaisesRegex(ValueError, 'between 0-59'):
            crontab_services.validate_crontab_values(minute=60)

    def test_validate_crontab_values_hour(self):
        for x in range(0, 23, 1):
            self.assertTrue(crontab_services.validate_crontab_values(hour=x))

        with self.assertRaisesRegex(ValueError, 'between 0-23'):
            crontab_services.validate_crontab_values(hour=24)

    def test_validate_crontab_values_day_of_week(self):
        for x in range(0, 6):
            self.assertTrue(crontab_services.validate_crontab_values(day_of_week=x))

        with self.assertRaisesRegex(ValueError, 'between 0-6'):
            crontab_services.validate_crontab_values(day_of_week=7)

    def test_validate_crontab_values_day_of_month(self):
        for x in range(1, 31):
            self.assertTrue(crontab_services.validate_crontab_values(day_of_month=x))

        with self.assertRaisesRegex(ValueError, 'between 1-31'):
            crontab_services.validate_crontab_values(day_of_month=0)
        with self.assertRaisesRegex(ValueError, 'between 1-31'):
            crontab_services.validate_crontab_values(day_of_month=32)

    def test_validate_on_all_crontab_generator_functions(self):
        with self.assertRaisesRegex(ValueError, 'divisible by 10'):
            crontab_services.generate_daily(minute=12)
        with self.assertRaisesRegex(ValueError, 'divisible by 10'):
            crontab_services.generate_weekly(minute=12)
        with self.assertRaisesRegex(ValueError, 'divisible by 10'):
            crontab_services.generate_monthly(minute=12)
        with self.assertRaisesRegex(ValueError, 'divisible by 10'):
            crontab_services.generate_biyearly(minute=12)
        with self.assertRaisesRegex(ValueError, 'divisible by 10'):
            crontab_services.generate_yearly(minute=12)

    def test_generate_daily(self):
        output = crontab_services.generate_daily(minute=10, hour=2)
        self.assertEqual('10 2 * * *', output)
        output = crontab_services.generate_daily(minute=10, hour=[2,3])
        self.assertRegex(output, r'10 ([2,3]) \* \* \*')

    def test_generate_weekly(self):
        output = crontab_services.generate_weekly(minute=10, hour=2, day_of_week=6)
        self.assertEqual('10 2 * * 6', output)

    def test_generate_monthly(self):
        output = crontab_services.generate_monthly(minute=10, hour=2, day=4)
        self.assertEqual('10 2 4 * *', output)

    def test_generate_biyearly(self):
        output = crontab_services.generate_biyearly(minute=10, hour=2, day=4)
        self.assertRegex(output, r'10 2 4 (\d+){1,2},(\d+){,2} \*')

    def test_generate_yearly(self):
        output = crontab_services.generate_yearly(minute=10, hour=2, day=4)
        self.assertRegex(output, r'10 2 4 (\d+){1,2} *')


class PlaylistServicesTests(TestCase):

    def test_recently_scanned(self):
        p = models.Playlist.objects.create(title='test')
        obj = p.scan_history.create()

        self.assertEqual(obj, playlist_services.recently_scanned(playlist=p))

    def test_recently_scanned_with_older_task(self):
        p = models.Playlist.objects.create(title='test')

        ts = timezone.now() - timezone.timedelta(hours=3)
        with patch.object(timezone, 'now', return_value=ts):
            p.scan_history.create()

        self.assertIsNone(playlist_services.recently_scanned(playlist=p))

        obj = p.scan_history.create()

        self.assertEqual(obj, playlist_services.recently_scanned(playlist=p))

    def test_recently_scanned_with_no_previous_tasks(self):
        p = models.Playlist.objects.create(title='test')

        self.assertIsNone(playlist_services.recently_scanned(playlist=p))

    @override_settings(VIDAR_PLAYLIST_BLOCK_RESCAN_WINDOW_HOURS=0)
    def test_recently_scanned_with_setting_disabled(self):
        p = models.Playlist.objects.create(title='test')

        p.scan_history.create()

        self.assertIsNone(playlist_services.recently_scanned(playlist=p))


class ChannelServicesTests(TestCase):

    def test_cleanup_storage_directory_cancelled_path_empty(self):
        channel = models.Channel.objects.create(name='')

        logger = logging.getLogger('vidar.services.channel_services')
        with patch.object(logger, 'info') as mock_info:
            blank_name = channel_services.cleanup_storage(channel=channel, dry_run=True)
            self.assertIsNone(blank_name)
            mock_info.assert_called_with('Skipping channel directory cleanup, name is invalid')

    def test_cleanup_storage_directory_cancelled_does_not_exist(self):
        channel = models.Channel.objects.create(name='test channel')

        logger = logging.getLogger('vidar.services.channel_services')
        with patch.object(logger, 'info') as mock_info, patch.object(pathlib.Path, 'exists') as mock_path:
            mock_path.return_value = False
            does_not_exist = channel_services.cleanup_storage(channel=channel, dry_run=True)
            self.assertIsNone(does_not_exist)
            mock_info.assert_called_with('Channel directory does not exist')

    def test_cleanup_storage_directory_successful(self):
        channel = models.Channel.objects.create(name='test channel')

        logger = logging.getLogger('vidar.services.channel_services')
        with patch.object(logger, 'info') as mock_info, patch.object(pathlib.Path, 'exists') as mock_path:
            mock_path.return_value = True
            returns_true = channel_services.cleanup_storage(channel=channel, dry_run=True)
            self.assertTrue(returns_true)
            mock_info.assert_called_with('Channel directory exists, deleting remaining data.')

    def test_set_channel_details_from_ytdlp(self):
        response_data = {
            'title': 'Channel Title',
            'description': 'Channel Description',
            'uploader_id': 'tests',
        }
        c = models.Channel.objects.create(provider_object_id='tests')

        channel_services.set_channel_details_from_ytdlp(
            channel=c,
            response=response_data
        )

        self.assertEqual('Channel Title', c.name)
        self.assertEqual('Channel Description', c.description)
        self.assertEqual('tests', c.provider_object_id)
        self.assertTrue(c.active)
        self.assertEqual('', c.sort_name)

    def test_set_channel_details_from_ytdlp_sort_name_with_the(self):
        response_data = {
            'title': 'The Channel Title',
            'description': 'Channel Description',
            'uploader_id': 'tests',
        }
        c = models.Channel.objects.create(provider_object_id='tests')

        channel_services.set_channel_details_from_ytdlp(
            channel=c,
            response=response_data
        )

        self.assertEqual('The Channel Title', c.name)
        self.assertEqual('Channel Title, The', c.sort_name)

    def test_full_archiving_completed(self):
        c = models.Channel.objects.create(
            provider_object_id='tests',
            full_archive=True,
            slow_full_archive=True,
        )

        self.assertTrue(c.full_archive)
        self.assertTrue(c.slow_full_archive)

        channel_services.full_archiving_completed(channel=c)

        self.assertFalse(c.full_archive)
        self.assertFalse(c.slow_full_archive)
        self.assertTrue(c.send_download_notification)
        self.assertTrue(c.fully_indexed)

    def test_recently_scanned(self):
        c = models.Channel.objects.create(
            provider_object_id='tests',
        )
        obj = c.scan_history.create()

        self.assertEqual(obj, channel_services.recently_scanned(channel=c))

    def test_recently_scanned_with_older_task(self):
        c = models.Channel.objects.create(
            provider_object_id='tests',
        )

        ts = timezone.now() - timezone.timedelta(hours=3)
        with patch.object(timezone, 'now', return_value=ts):
            c.scan_history.create()

        self.assertIsNone(channel_services.recently_scanned(channel=c))

        obj = c.scan_history.create()

        self.assertEqual(obj, channel_services.recently_scanned(channel=c))

    def test_recently_scanned_with_no_previous_tasks(self):
        c = models.Channel.objects.create(
            provider_object_id='tests',
        )

        self.assertIsNone(channel_services.recently_scanned(channel=c))

    @override_settings(VIDAR_CHANNEL_BLOCK_RESCAN_WINDOW_HOURS=0)
    def test_recently_scanned_with_setting_disabled(self):
        c = models.Channel.objects.create(
            provider_object_id='tests',
        )

        self.assertIsNone(channel_services.recently_scanned(channel=c))

    def test_recently_scanned_with_channel_based_override(self):
        c = models.Channel.objects.create(
            provider_object_id='tests',
            block_rescan_window_in_hours=4
        )

        ts = timezone.now() - timezone.timedelta(hours=5)
        with patch.object(timezone, 'now', return_value=ts):
            c.scan_history.create()

        self.assertIsNone(channel_services.recently_scanned(channel=c))

        ts = timezone.now() - timezone.timedelta(hours=3)
        with patch.object(timezone, 'now', return_value=ts):
            obj2 = c.scan_history.create()

        self.assertEqual(obj2, channel_services.recently_scanned(channel=c))

        obj = c.scan_history.create()

        self.assertEqual(obj, channel_services.recently_scanned(channel=c))


class VideoServicesTests(TestCase):

    def test_force_download_based_on_requirements_requested_basic(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            title_forces='finale',
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )
        self.assertFalse(video_services.should_force_download_based_on_requirements_requested(video=video))

        video = models.Video.objects.create(
            title='Test Video',
        )
        self.assertFalse(video_services.should_force_download_based_on_requirements_requested(video=video))

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
        )
        self.assertTrue(video_services.should_force_download_based_on_requirements_requested(video=video))

    def test_force_download_based_on_requirements_requested_changes_force_next_downloads(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            force_next_downloads=1,
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )
        self.assertTrue(video_services.should_force_download_based_on_requirements_requested(video=video))
        self.assertEqual(0, video.channel.force_next_downloads)
        self.assertFalse(video_services.should_force_download_based_on_requirements_requested(video=video))

    def test_force_download_based_on_requirements_requested_video_force_true_doesnt_change_force_next_downloads(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            force_next_downloads=1,
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
            force_download=True,
        )
        self.assertTrue(video_services.should_force_download_based_on_requirements_requested(video=video))
        self.assertEqual(1, video.channel.force_next_downloads)
        self.assertTrue(video_services.should_force_download_based_on_requirements_requested(video=video))

    def test_permitted_to_download_based_on_requirements_requested_no_channel(self):
        video = models.Video.objects.create(
            title='Test Video Finale',
            force_download=True,
        )

        self.assertTrue(video_services.should_force_download_based_on_requirements_requested(video=video))

        video = models.Video.objects.create(
            title='Test Video 2 Finale',
            force_download=False,
        )

        self.assertFalse(video_services.should_force_download_based_on_requirements_requested(video=video))

    def test_force_download_based_on_requirements_check_basic(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            title_forces='finale',
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )
        self.assertFalse(video_services.should_force_download_based_on_requirements_check(video=video))

        video = models.Video.objects.create(
            title='Test Video',
        )
        self.assertFalse(video_services.should_force_download_based_on_requirements_check(video=video))

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
        )
        self.assertTrue(video_services.should_force_download_based_on_requirements_check(video=video))

    def test_permitted_to_download_based_on_requirements_check_no_channel(self):
        video = models.Video.objects.create(
            title='Test Video Finale',
            force_download=True,
        )

        self.assertTrue(video_services.should_force_download_based_on_requirements_check(video=video))

        video = models.Video.objects.create(
            title='Test Video 2 Finale',
            force_download=False,
        )

        self.assertFalse(video_services.should_force_download_based_on_requirements_check(video=video))

    def test_force_download_based_on_requirements_check_doesnt_change_force_next_downloads(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            force_next_downloads=1,
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )
        self.assertTrue(video_services.should_force_download_based_on_requirements_check(video=video))
        self.assertEqual(1, video.channel.force_next_downloads)
        self.assertTrue(video_services.should_force_download_based_on_requirements_check(video=video))

    def test_does_file_need_fixing_basic(self):
        video = models.Video.objects.create(title='Test Video')
        self.assertFalse(video_services.does_file_need_fixing(video))

    def test_does_file_need_fixing_yes(self):
        video = models.Video.objects.create(title='Test Video', file='//test/file.mp4')
        self.assertTrue(video_services.does_file_need_fixing(video))

    def test_video_delete_not_permitted(self):

        with self.assertRaises(exceptions.UnauthorizedVideoDeletionError):
            video = models.Video.objects.create(
                title='Test Video',
            )
            video.delete()

    def test_permitted_to_download_without_channel(self):
        video = models.Video.objects.create(
            title='Test Video Finale',
        )
        self.assertTrue(video_services.is_permitted_to_download_check(video=video))
        self.assertTrue(video_services.is_permitted_to_download_requested(video=video))

    def test_permitted_to_download_with_channel_forced_next(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            force_next_downloads=2
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
        )

        self.assertEqual(2, video.channel.force_next_downloads)
        self.assertTrue(video_services.is_permitted_to_download_check(video=video))
        self.assertEqual(2, video.channel.force_next_downloads, "check should not have lowered the number")

        self.assertTrue(video_services.is_permitted_to_download_requested(video=video))
        self.assertEqual(1, video.channel.force_next_downloads, "requested should have lowered the number")

    def test_permitted_to_download_with_channel_skipped_next(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            skip_next_downloads=2,
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
        )

        self.assertEqual(2, video.channel.skip_next_downloads)
        self.assertFalse(video_services.is_permitted_to_download_check(video=video))
        self.assertEqual(2, video.channel.skip_next_downloads)
        self.assertFalse(video_services.is_permitted_to_download_requested(video=video))
        self.assertEqual(1, video.channel.skip_next_downloads, 'requested should have lowered number')

    def test_permitted_to_download_with_channel_title_skips(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            title_skips="finale",
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
        )

        self.assertFalse(video_services.is_permitted_to_download_check(video=video))
        self.assertFalse(video_services.is_permitted_to_download_requested(video=video))

    def test_permitted_to_download_with_channel_title_forces(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            title_forces="finale",
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
        )

        self.assertTrue(video_services.is_permitted_to_download_check(video=video))
        self.assertTrue(video_services.is_permitted_to_download_requested(video=video))

    def test_permitted_to_download_with_channel_video_duration_minimums(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            duration_minimum_videos=30,
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
            duration=15,
            is_video=True,
        )
        self.assertFalse(video_services.is_permitted_to_download_check(video=video))
        self.assertFalse(video_services.is_permitted_to_download_requested(video=video))

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
            duration=31,
            is_video=True,
        )
        self.assertTrue(video_services.is_permitted_to_download_check(video=video))
        self.assertTrue(video_services.is_permitted_to_download_requested(video=video))

    def test_permitted_to_download_with_channel_livestreams_duration_minimums(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            duration_minimum_livestreams=30,
        )

        video = models.Video.objects.create(
            title='Test Livestream Finale',
            channel=channel,
            duration=15,
            is_livestream=True,
        )
        self.assertFalse(video_services.is_permitted_to_download_check(video=video))
        self.assertFalse(video_services.is_permitted_to_download_requested(video=video))

        video = models.Video.objects.create(
            title='Test Livestream Finale',
            channel=channel,
            duration=31,
            is_livestream=True,
        )
        self.assertTrue(video_services.is_permitted_to_download_check(video=video))
        self.assertTrue(video_services.is_permitted_to_download_requested(video=video))

    def test_permitted_to_download_with_channel_video_duration_maximums(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            duration_maximum_videos=30
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
            duration=15,
            is_video=True,
        )
        self.assertTrue(video_services.is_permitted_to_download_check(video=video))
        self.assertTrue(video_services.is_permitted_to_download_requested(video=video))

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
            duration=31,
            is_video=True,
        )
        self.assertFalse(video_services.is_permitted_to_download_check(video=video))
        self.assertFalse(video_services.is_permitted_to_download_requested(video=video))

    def test_permitted_to_download_with_channel_livestreams_duration_maximums(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            duration_maximum_livestreams=30,
        )

        video = models.Video.objects.create(
            title='Test Livestream Finale',
            channel=channel,
            duration=15,
            is_livestream=True,
        )
        self.assertTrue(video_services.is_permitted_to_download_check(video=video))
        self.assertTrue(video_services.is_permitted_to_download_requested(video=video))

        video = models.Video.objects.create(
            title='Test Livestream Finale',
            channel=channel,
            duration=31,
            is_livestream=True,
        )
        self.assertFalse(video_services.is_permitted_to_download_check(video=video))
        self.assertFalse(video_services.is_permitted_to_download_requested(video=video))

    def test_can_delete(self):

        video = models.Video.objects.create(
            title='Test Video',
        )

        self.assertTrue(video_services.can_delete(video=video))

    def test_can_delete_protected(self):

        video = models.Video.objects.create(
            title='Test Video',
            prevent_deletion=True,
        )

        self.assertFalse(video_services.can_delete(video=video))

    def test_can_delete_starred(self):

        video = models.Video.objects.create(
            title='Test Video',
            starred=timezone.now(),
        )

        self.assertFalse(video_services.can_delete(video=video))

    def test_can_delete_false_with_playlist(self):

        video = models.Video.objects.create(
            title='Test Video',
        )

        playlist = models.Playlist.objects.create(
            title="Playlist"
        )
        playlist.videos.add(video)

        self.assertEqual(1, playlist.videos.count())
        self.assertFalse(video_services.can_delete(video=video))

    def test_can_delete_true_with_playlist_skip_ids(self):
        video = models.Video.objects.create(
            title='Test Video',
        )

        playlist = models.Playlist.objects.create(
            title="Playlist"
        )
        playlist.videos.add(video)

        self.assertTrue(video_services.can_delete(video=video, skip_playlist_ids=playlist.id))

    def test_can_delete_false_with_multiple_playlists_one_skip_ids(self):
        video = models.Video.objects.create(
            title='Test Video',
        )

        playlist = models.Playlist.objects.create(
            title="Playlist"
        )
        playlist.videos.add(video)

        playlist2 = models.Playlist.objects.create(
            title="Playlist 2"
        )
        playlist2.videos.add(video)

        self.assertFalse(video_services.can_delete(video=video, skip_playlist_ids=playlist.id))

    def test_can_delete_true_with_multiple_playlists_all_skip_ids(self):
        video = models.Video.objects.create(
            title='Test Video',
        )

        playlist = models.Playlist.objects.create(
            title="Playlist"
        )
        playlist.videos.add(video)

        playlist2 = models.Playlist.objects.create(
            title="Playlist 2"
        )
        playlist2.videos.add(video)

        self.assertTrue(video_services.can_delete(video=video, skip_playlist_ids=[playlist.id, playlist2.id]))

    def test_delete_video_when_public_changes_channel_fully_indexed_false(self):

        channel = models.Channel.objects.create(
            name='Test Channel',
            fully_indexed=True,
            fully_indexed_livestreams=True,
            fully_indexed_shorts=True,
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
        )

        self.assertTrue(video.channel.fully_indexed)
        self.assertTrue(video.channel.fully_indexed_livestreams)
        self.assertTrue(video.channel.fully_indexed_shorts)

        video_services.delete_video(video=video, keep_record=False)

        self.assertFalse(video.channel.fully_indexed)
        self.assertFalse(video.channel.fully_indexed_livestreams)
        self.assertFalse(video.channel.fully_indexed_shorts)

    def test_delete_video_when_private_does_not_change_channel_fully_indexed(self):

        channel = models.Channel.objects.create(
            name='Test Channel',
            fully_indexed=True,
            fully_indexed_livestreams=True,
            fully_indexed_shorts=True,
        )

        video = models.Video.objects.create(
            title='Test Video Finale',
            channel=channel,
            privacy_status=models.Video.VideoPrivacyStatuses.PRIVATE,
        )

        self.assertTrue(video.channel.fully_indexed)
        self.assertTrue(video.channel.fully_indexed_livestreams)
        self.assertTrue(video.channel.fully_indexed_shorts)

        video_services.delete_video(video=video, keep_record=False)

        self.assertTrue(video.channel.fully_indexed)
        self.assertTrue(video.channel.fully_indexed_livestreams)
        self.assertTrue(video.channel.fully_indexed_shorts)

    def test_delete_video_resets_fields_keeping_record(self):

        video = models.Video.objects.create(
            title='Test Video Finale',
            fps=24,
            duration=600,
            width=1280,
            height=720,
            privacy_status=models.Video.VideoPrivacyStatuses.PRIVATE,
            quality=720,
        )

        self.assertEqual(24, video.fps)
        self.assertEqual(600, video.duration)
        self.assertEqual(1280, video.width)
        self.assertEqual(720, video.height)
        self.assertEqual(models.Video.VideoPrivacyStatuses.PRIVATE, video.privacy_status)
        self.assertEqual(720, video.quality)

        self.assertTrue(video_services.delete_video(video=video, keep_record=True))

        self.assertEqual(0, video.fps)
        self.assertEqual(600, video.duration)
        self.assertEqual(0, video.width)
        self.assertEqual(0, video.height)
        self.assertEqual(models.Video.VideoPrivacyStatuses.PUBLIC, video.privacy_status)
        self.assertIsNone(video.quality)

    def test_get_video_upload_to_directory_builder_public_without_upload_date(self):

        video = models.Video.objects.create(
            title='Test Video',
        )

        output_as_pathlib = video_helpers.get_video_upload_to_directory(instance=video)
        output_as_str = str(output_as_pathlib)
        year = timezone.now().year
        expected_output = f"public/{year}"

        self.assertEqual(expected_output, output_as_str)

    def test_get_video_upload_to_directory_builder_public_with_upload_date(self):

        upload_date = (timezone.now() - timezone.timedelta(days=365*3)).date()
        video = models.Video.objects.create(
            title='Test Video',
            upload_date=upload_date,
        )

        output_as_pathlib = video_helpers.get_video_upload_to_directory(instance=video)
        output_as_str = str(output_as_pathlib)
        expected_output = f"public/{video.upload_date:%Y}"

        self.assertEqual(expected_output, output_as_str)

    def test_get_video_upload_to_directory_builder_with_channel_with_upload_date(self):

        channel = models.Channel.objects.create(
            name='Test Channel',
        )

        upload_date = (timezone.now() - timezone.timedelta(days=365 * 3)).date()
        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
            upload_date=upload_date,
        )

        output_as_pathlib = video_helpers.get_video_upload_to_directory(instance=video)
        output_as_str = str(output_as_pathlib)
        expected_output = f"Test Channel/{video.upload_date:%Y}/{video.upload_date:%Y-%m-%d} - {video.title} []"

        self.assertEqual(expected_output, output_as_str)

    def test_get_video_upload_to_directory_builder_with_channel_without_upload_date(self):

        channel = models.Channel.objects.create(
            name='Test Channel',
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )

        year = timezone.now()

        output_as_pathlib = video_helpers.get_video_upload_to_directory(instance=video)
        output_as_str = str(output_as_pathlib)
        expected_output = f"Test Channel/{year:%Y}/- {video.title} []"

        self.assertEqual(expected_output, output_as_str)

    def test_get_video_upload_to_directory_builder_with_channel_not_by_year(self):

        channel = models.Channel.objects.create(
            name='Test Channel',
            store_videos_by_year_separation=False,
        )

        upload_date = (timezone.now() - timezone.timedelta(days=365 * 3)).date()
        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
            upload_date=upload_date,
        )

        output_as_pathlib = video_helpers.get_video_upload_to_directory(instance=video)
        output_as_str = str(output_as_pathlib)
        expected_output = f"Test Channel/{video.upload_date:%Y-%m-%d} - {video.title} []"

        self.assertEqual(expected_output, output_as_str)

    def test_get_video_upload_to_directory_builder_with_channel_not_in_separate_directories_with_year(self):

        channel = models.Channel.objects.create(
            name='Test Channel',
            store_videos_in_separate_directories=False,
        )

        upload_date = (timezone.now() - timezone.timedelta(days=365 * 3)).date()
        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
            upload_date=upload_date,
        )

        output_as_pathlib = video_helpers.get_video_upload_to_directory(instance=video)
        output_as_str = str(output_as_pathlib)
        expected_output = f"Test Channel/{video.upload_date:%Y}"

        self.assertEqual(expected_output, output_as_str)

    def test_get_video_upload_to_directory_builder_with_channel_not_in_separate_directories_without_year(self):

        channel = models.Channel.objects.create(
            name='Test Channel',
            store_videos_in_separate_directories=False,
            store_videos_by_year_separation=False,
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )

        output_as_pathlib = video_helpers.get_video_upload_to_directory(instance=video)
        output_as_str = str(output_as_pathlib)
        expected_output = f"Test Channel"

        self.assertEqual(expected_output, output_as_str)

    @patch('vidar.utils.get_sponsorblock_video_data')
    def test_sponsorblock_skips(self, mock_sbdata):

        mock_sbdata.return_value = [{
            'category': 'sponsor',
            'actionType': 'skip',
            'segment': [1416.941, 1503.441],
            'UUID': '9b9619d8a194b5b2448254f6fffde062856e81604e28fe3673c75954703476c67',
            'videoDuration': 1503.441,
            'locked': 1,
            'votes': 5,
            'description': ''
        }]

        video = models.Video.objects.create(
            title='Test Video',
            provider_object_id='Zce-V0YVzeI',
        )

        self.assertEqual(0, video.duration_skips.count())

        newly_made = video_services.load_live_sponsorblock_video_data_into_duration_skips(video=video)

        mock_sbdata.assert_called_with('Zce-V0YVzeI', categories=None)
        self.assertEqual(1, video.duration_skips.count())
        self.assertEqual(1, len(newly_made))

        ds = video.duration_skips.get()
        self.assertEqual(5, ds.sb_votes)
        self.assertEqual('9b9619d8a194b5b2448254f6fffde062856e81604e28fe3673c75954703476c67', ds.sb_uuid)
        self.assertEqual('sponsor', ds.sb_category)
        self.assertEqual(1416, ds.start)
        self.assertEqual(1503, ds.end)

    @patch('vidar.utils.get_sponsorblock_video_data')
    def test_sponsorblock_skips_no_duplicates(self, mock_sbdata):

        mock_sbdata.return_value = [{
            'category': 'sponsor',
            'actionType': 'skip',
            'segment': [1416.941, 1503.441],
            'UUID': '9b9619d8a194b5b2448254f6fffde062856e81604e28fe3673c75954703476c67',
            'videoDuration': 1503.441,
            'locked': 1,
            'votes': 5,
            'description': ''
        }]

        video = models.Video.objects.create(
            title='Test Video',
            provider_object_id='Zce-V0YVzeI',
        )

        self.assertEqual(0, video.duration_skips.count())

        newly_made = video_services.load_live_sponsorblock_video_data_into_duration_skips(video=video)

        mock_sbdata.assert_called_with('Zce-V0YVzeI', categories=None)
        self.assertEqual(1, video.duration_skips.count())
        self.assertEqual(1, len(newly_made))

        newly_made2 = video_services.load_live_sponsorblock_video_data_into_duration_skips(video=video)

        mock_sbdata.assert_called_with('Zce-V0YVzeI', categories=None)
        self.assertEqual(1, video.duration_skips.count())
        self.assertEqual(0, len(newly_made2))

    def test_is_too_old_now(self):

        video = models.Video.objects.create(
            title='Test Video',
            upload_date=timezone.now().date(),
        )

        self.assertFalse(video_services.is_too_old(video=video))

    def test_is_too_old_pre_youtube_launching(self):

        video = models.Video.objects.create(
            title='Test Video',
            upload_date=timezone.now().date().replace(year=2004),
        )

        self.assertTrue(video_services.is_too_old(video=video))

    def test_is_too_old_upload_date_missing(self):

        video = models.Video.objects.create(
            title='Test Video',
        )

        self.assertTrue(video_services.is_too_old(video=video))

    def test_should_download_comments_default(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )

        playlist = models.Playlist.objects.create(title='playlist 1')

        playlist.videos.add(video)

        self.assertFalse(video_services.should_download_comments(video=video))

    def test_should_download_comments_from_channel(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
            download_comments_during_scan=True,
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )

        self.assertTrue(video_services.should_download_comments(video=video))

    def test_should_download_comments_from_video(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
            download_comments_on_index=True,
        )

        self.assertTrue(video_services.should_download_comments(video=video))

    def test_should_download_comments_from_playlist(self):
        channel = models.Channel.objects.create(
            name='Test Channel',
        )

        video = models.Video.objects.create(
            title='Test Video',
            channel=channel,
        )

        playlist = models.Playlist.objects.create(title='playlist 1', download_comments_on_index=True)

        playlist.videos.add(video)

        self.assertTrue(video_services.should_download_comments(video=video))

    def test_should_convert_to_mp4(self):
        video = models.Video.objects.create(title='Test Video')
        filepath = '/test/file.mkv'
        self.assertTrue(video_services.should_convert_to_mp4(video=video, filepath=filepath))

    def test_should_convert_to_mp4_as_pathlib(self):
        video = models.Video.objects.create(title='Test Video')
        filepath = pathlib.Path('/test/file.mkv')
        self.assertTrue(video_services.should_convert_to_mp4(video=video, filepath=filepath))

    def test_should_convert_to_mp4_as_mp4(self):
        video = models.Video.objects.create(title='Test Video')
        filepath = pathlib.Path('/test/file.mp4')
        self.assertFalse(video_services.should_convert_to_mp4(video=video, filepath=filepath))

    def test_video_not_blocked(self):
        self.assertFalse(video_services.is_blocked("vidar id here"))

    def test_video_is_blocked(self):
        video = models.Video.objects.create(title='Test Video', provider_object_id='vidar id')
        video_services.block(video=video)
        self.assertTrue(video_services.is_blocked('vidar id'))

    def test_unblocking_video(self):
        video = models.Video.objects.create(title='Test Video', provider_object_id='vidar id')
        video_services.block(video=video)
        self.assertTrue(video_services.is_blocked('vidar id'))
        video_services.unblock('vidar id')
        self.assertFalse(video_services.is_blocked('vidar id'))

    @override_settings(VIDAR_DEFAULT_QUALITY='1080')
    def test_quality_to_download_video_selection(self):
        video = models.Video.objects.create(title='Test Video', quality=720)

        self.assertEqual(720, video_services.quality_to_download(video=video))

    @override_settings(VIDAR_DEFAULT_QUALITY='1080', VIDAR_SHORTS_FORCE_MAX_QUALITY=True)
    def test_quality_to_download_shorts_selection(self):
        video = models.Video.objects.create(title='Test Video', quality=720, is_short=True)

        self.assertEqual(0, video_services.quality_to_download(video=video))

    @override_settings(VIDAR_DEFAULT_QUALITY='1080', VIDAR_SHORTS_FORCE_MAX_QUALITY=False)
    def test_quality_to_download_shorts_selection_unless_default_max_is_disabled(self):
        video = models.Video.objects.create(title='Test Video', quality=720, is_short=True)

        self.assertEqual(720, video_services.quality_to_download(video=video))

    @override_settings(VIDAR_DEFAULT_QUALITY='1080')
    def test_quality_to_download_system_default(self):
        video = models.Video.objects.create(title='Test Video')

        self.assertEqual(1080, video_services.quality_to_download(video=video))

    @override_settings(VIDAR_DEFAULT_QUALITY='4098')
    def test_quality_to_download_channel_selection(self):
        channel = models.Channel.objects.create(name='Test Channel', quality=1080)
        video = models.Video.objects.create(title='Test Video', quality=720, channel=channel)

        self.assertEqual(1080, video_services.quality_to_download(video=video))

    @override_settings(VIDAR_DEFAULT_QUALITY='4098')
    def test_quality_to_download_extras_selection(self):
        channel = models.Channel.objects.create(name='Test Channel', quality=1080)
        video = models.Video.objects.create(title='Test Video', quality=720, channel=channel)

        self.assertEqual(2048, video_services.quality_to_download(video=video, extras=[2048, models.Video]))

    @override_settings(VIDAR_DEFAULT_QUALITY='4098')
    def test_quality_to_download_playlist_selection(self):
        channel = models.Channel.objects.create(name='Test Channel', quality=1080)
        video = models.Video.objects.create(title='Test Video', quality=720, channel=channel)

        playlist = models.Playlist.objects.create(quality=2048)
        playlist.videos.add(video)

        self.assertEqual(2048, video_services.quality_to_download(video=video))

    @override_settings(VIDAR_DEFAULT_QUALITY='4098')
    def test_quality_to_download_returns_zero_when_provided(self):
        channel = models.Channel.objects.create(name='Test Channel', quality=0)
        video = models.Video.objects.create(title='Test Video', quality=720, channel=channel)

        playlist = models.Playlist.objects.create(quality=2048)
        playlist.videos.add(video)

        self.assertEqual(0, video_services.quality_to_download(video=video))

    def test_should_convert_to_audio_from_channel(self):
        channel = models.Channel.objects.create(name='Test Channel', convert_videos_to_mp3=True)
        video = models.Video.objects.create(title='Test Video', channel=channel)

        playlist = models.Playlist.objects.create()
        playlist.videos.add(video)

        self.assertTrue(video_services.should_convert_to_audio(video=video))

    def test_should_convert_to_audio_from_video(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video = models.Video.objects.create(title='Test Video', channel=channel, convert_to_audio=True)

        playlist = models.Playlist.objects.create()
        playlist.videos.add(video)

        self.assertTrue(video_services.should_convert_to_audio(video=video))

    def test_should_convert_to_audio_from_playlist(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video = models.Video.objects.create(title='Test Video', channel=channel)

        playlist = models.Playlist.objects.create(convert_to_audio=True)
        playlist.videos.add(video)

        self.assertTrue(video_services.should_convert_to_audio(video=video))

    def test_should_convert_to_audio_not_necessary(self):
        channel = models.Channel.objects.create(name='Test Channel')
        video = models.Video.objects.create(title='Test Video', channel=channel)

        playlist = models.Playlist.objects.create()
        playlist.videos.add(video)

        self.assertFalse(video_services.should_convert_to_audio(video=video))

    def test_log_update_video_details_called(self):

        video = models.Video.objects.create(title='Test Video')

        video_services.log_update_video_details_called(video=video, mode='test')
        self.assertNotIn('update_video_details_automated', video.system_notes)
        self.assertEqual(0, video.privacy_status_checks)

        first_timestamp = timezone.now()
        with patch.object(timezone, 'now', return_value=first_timestamp):
            video_services.log_update_video_details_called(video=video, commit=False)

        self.assertIn('update_video_details_automated', video.system_notes)
        logs = video.system_notes['update_video_details_automated']
        self.assertEqual(1, len(logs))
        self.assertEqual(1, video.privacy_status_checks)
        self.assertIn(first_timestamp.isoformat(), logs)
        first_log = logs[first_timestamp.isoformat()]
        self.assertIsNone(first_log)

        second_timestamp = first_timestamp + timezone.timedelta(hours=1)
        with patch.object(timezone, 'now', return_value=second_timestamp):
            video_services.log_update_video_details_called(video=video, result='result here', commit=False)

        self.assertIn('update_video_details_automated', video.system_notes)
        logs = video.system_notes['update_video_details_automated']
        self.assertEqual(2, len(logs))
        self.assertEqual(2, video.privacy_status_checks)

        self.assertIn(first_timestamp.isoformat(), logs)
        self.assertIn(second_timestamp.isoformat(), logs)

        second_log = logs[second_timestamp.isoformat()]
        self.assertEqual('result here', second_log)


class YtdlpServicesTests(TestCase):

    def test_exception_is_live_event(self):
        self.assertTrue(ytdlp_services.exception_is_live_event('This live event will start in 8 days'))
        self.assertFalse(ytdlp_services.exception_is_live_event('This event has passed'))

    def test_get_video_downloader_args(self):
        video = models.Video.objects.create(title='video 1')
        output = ytdlp_services.get_video_downloader_args(
            video=video,
            retries=0,
            get_comments=False,
        )
        self.assertIn('proxy', output)
        self.assertNotIn('getcomments', output)

    @override_settings(VIDAR_PROXIES='here')
    def test_get_video_downloader_args_many_retries(self):
        video = models.Video.objects.create(title='video 1')

        output = ytdlp_services.get_video_downloader_args(video=video, retries=1)
        self.assertIn('proxy', output)
        self.assertEqual('here', output['proxy'])

        output = ytdlp_services.get_video_downloader_args(video=video, retries=2)
        self.assertIn('proxy', output)

        output = ytdlp_services.get_video_downloader_args(video=video, retries=3)
        self.assertEqual('', output['proxy'])

    @override_settings(VIDAR_PROXIES='here', VIDAR_PROXIES_DEFAULT='default proxy')
    def test_get_video_downloader_args_many_retries_with_different_default(self):
        video = models.Video.objects.create(title='video 1')

        output = ytdlp_services.get_video_downloader_args(video=video, retries=1)
        self.assertIn('proxy', output)
        self.assertEqual('here', output['proxy'])

        output = ytdlp_services.get_video_downloader_args(video=video, retries=2)
        self.assertIn('proxy', output)

        output = ytdlp_services.get_video_downloader_args(video=video, retries=3)
        self.assertEqual('default proxy', output['proxy'])


class SchemaServicesTests(TestCase):
    def setUp(self) -> None:
        self.channel = models.Channel.objects.create(name="Test Channel")
        self.channel_with_custom_schema = models.Channel.objects.create(
            name="Test Channel",
            directory_schema="{{ channel.id }}/{{ channel.system_safe_name }}",
            video_directory_schema="{{ video.system_safe_title }} [{{ video.provider_object_id }}]/videos/",
        )
        self.upload_date = timezone.datetime(2020, 1, 22)
        self.video_without_channel = models.Video.objects.create(title="Video Without Channel", upload_date=self.upload_date, provider_object_id='test-wo-channel')
        self.video_with_channel = models.Video.objects.create(channel=self.channel, title="Video With Channel", upload_date=self.upload_date, provider_object_id='test-w-channel')
        self.video_with_channel_with_custom_schema = models.Video.objects.create(channel=self.channel_with_custom_schema, title="Video With Channel With Custom Schema", upload_date=self.upload_date, provider_object_id='test-w-channel')
        self.video_with_custom_schema = models.Video.objects.create(channel=self.channel_with_custom_schema, title="Video With Channel With Custom Schema",
                                                                    upload_date=self.upload_date, provider_object_id='test-w-channel', filename_schema='this is the filename', directory_schema='this is the directory')

    def test_channel_directory_name_correct(self):
        output = schema_services.channel_directory_name(channel=self.channel)
        self.assertEqual("Test Channel", output)

        output = schema_services.channel_directory_name(channel=self.channel_with_custom_schema)
        self.assertEqual(f"{self.channel_with_custom_schema.id}/Test Channel", output)

    def test_channel_directory_name_warning_warn_on_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
            directory_schema="{{ instance.bad_property }}",
        )
        with self.assertLogs('vidar.services.schema_services') as logger:
            schema_services.channel_directory_name(channel=channel)

        self.assertListEqual(logger.output, ["CRITICAL:vidar.services.schema_services:channel=<Channel: Test Channel> has an invalid directory schema channel.directory_schema='{{ instance.bad_property }}'. Using system default."])

    @override_settings(
        VIDAR_CHANNEL_DIRECTORY_SCHEMA='{{ instance.bad_property }}',
    )
    def test_channel_directory_name_raises_exception_on_all_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
            directory_schema="{{ instance.bad_property }}",
        )

        with self.assertRaises(exceptions.DirectorySchemaInvalidError):
            schema_services.channel_directory_name(channel=channel)

    def test_video_directory_name_correct(self):
        output = schema_services.video_directory_name(video=self.video_with_channel)
        self.assertEqual("2020-01-22 - Video With Channel [test-w-channel]", output)

        output = schema_services.video_directory_name(video=self.video_without_channel)
        self.assertEqual("2020-01-22 - Video Without Channel [test-wo-channel]", output)

        output = schema_services.video_directory_name(video=self.video_with_custom_schema)
        self.assertEqual("this is the directory", output)

    def test_video_directory_name_channel_custom_video_directory_schema(self):

        output = schema_services.video_directory_name(video=self.video_with_channel_with_custom_schema)
        self.assertEqual("Video With Channel With Custom Schema [test-w-channel]/videos/", output)

    def test_channel_video_directory_name_warning_warn_on_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
            video_directory_schema="{{ video.bad_property }}",
        )

        video = models.Video.objects.create(
            title="Video With Bad Schema Channel", upload_date=self.upload_date,
            provider_object_id='test-w-channel', channel=channel,
        )

        with self.assertLogs('vidar.services.schema_services') as logger:
            output = schema_services.video_directory_name(video=video)
            self.assertEqual("2020-01-22 - Video With Bad Schema Channel [test-w-channel]", output)

            self.assertEqual(1, len(logger.output))
            self.assertIn('has an invalid value in video.channel.video_directory_schema=', logger.output[0])

    def test_video_directory_name_warning_warn_on_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
        )

        video = models.Video.objects.create(
            title="Video With Bad Schema Channel", upload_date=self.upload_date,
            provider_object_id='test-w-channel', channel=channel,
            directory_schema="{{ video.bad_property }}",
        )

        with self.assertLogs('vidar.services.schema_services') as logger:
            output = schema_services.video_directory_name(video=video)
            self.assertEqual(1, len(logger.output))
            self.assertIn('has an invalid value in video.directory_schema=', logger.output[0])

    @override_settings(
        VIDAR_VIDEO_DIRECTORY_SCHEMA='{{ instance.bad_property }}',
    )
    def test_video_directory_name_raises_exception_on_all_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
            video_directory_schema="{{ video.bad_property }}",
        )

        video = models.Video.objects.create(
            title="Video With Bad Schema Channel", upload_date=self.upload_date,
            provider_object_id='test-w-channel', channel=channel,
        )

        with self.assertRaises(exceptions.DirectorySchemaInvalidError):
            schema_services.video_directory_name(video=video)

    def test_video_file_name_correct(self):
        output = schema_services.video_file_name(video=self.video_with_channel, ext='mp3')
        self.assertEqual("2020-01-22 - Video With Channel [test-w-channel].mp3", output)

        output = schema_services.video_file_name(video=self.video_without_channel, ext='mp3')
        self.assertEqual("2020-01-22 - Video Without Channel [test-wo-channel].mp3", output)

        output = schema_services.video_file_name(video=self.video_without_channel, ext='')
        self.assertEqual("2020-01-22 - Video Without Channel [test-wo-channel]", output)

        output = schema_services.video_file_name(video=self.video_with_custom_schema, ext='')
        self.assertEqual("this is the filename", output)

    def test_video_file_name_channel_video_schema_overrides_default(self):
        channel = models.Channel.objects.create(
            name="test channel",
            video_filename_schema="overridden filename schema"
        )
        video = models.Video.objects.create(
            channel=channel,
            title="test video",
        )
        output = schema_services.video_file_name(video=video, ext='mp3')
        self.assertEqual("overridden filename schema.mp3", output)

    def test_video_channel_file_name_warning_warn_on_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
            video_filename_schema="{{ instance.bad_property }}",
        )
        video = models.Video.objects.create(channel=channel)

        with self.assertLogs('vidar.services.schema_services') as logger:
            schema_services.video_file_name(video=video, ext='mp3')
            self.assertEqual(1, len(logger.output))
            self.assertIn('invalid schema', logger.output[0])

    def test_video_file_name_warning_warn_on_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
        )
        video = models.Video.objects.create(channel=channel, filename_schema="{{ instance.bad_property }}")

        with self.assertLogs('vidar.services.schema_services') as logger:
            schema_services.video_file_name(video=video, ext='mp3')
            self.assertEqual(1, len(logger.output))
            self.assertIn('has an invalid value in video.filename_schema=', logger.output[0])

    @override_settings(
        VIDAR_VIDEO_FILENAME_SCHEMA='{{ instance.bad_property }}',
    )
    def test_video_file_name_raises_exception_on_all_invalid_schemas(self):

        channel = models.Channel.objects.create(
            name="Test Channel",
            video_filename_schema="{{ instance.bad_property }}",
        )
        video = models.Video.objects.create(channel=channel)

        with self.assertRaises(exceptions.FilenameSchemaInvalidError):
            schema_services.video_file_name(video=video, ext='mp3')

    def test_render_returns_str_not_safestring(self):
        template_string = "Hello, {{ name }}!"
        context_data = {"name": "Alice"}
        rendered_string = schema_services._render_string_using_object_data(template_string, **context_data)
        self.assertIs(type(rendered_string), str)

    def test_render_string_with_context(self):
        template_string = "Hello, {{ name }}!"
        context_data = {"name": "Alice"}
        rendered_string = schema_services._render_string_using_object_data(template_string, **context_data)
        expected_output = "Hello, Alice!"
        self.assertEqual(rendered_string, expected_output)

    def test_render_string_without_context(self):
        template_string = "This is a test string."
        rendered_string = schema_services._render_string_using_object_data(template_string)
        self.assertEqual(rendered_string, template_string)

    def test_render_empty_string(self):
        rendered_string = schema_services._render_string_using_object_data("")
        self.assertEqual(rendered_string, "")

    def test_render_string_with_special_characters(self):
        template_string = "This is {{ special }} string: {{ value }}."
        context_data = {"special": "<>&", "value": "$"}
        rendered_string = schema_services._render_string_using_object_data(template_string, **context_data)
        expected_output = "This is &lt;&gt;&amp; string: $."
        self.assertEqual(rendered_string, expected_output)


class YtdlpServicesDLPFormatsTest(SimpleTestCase):

    def setUp(self) -> None:
        with open('vidar/tests/tests_fixture.json', 'r') as f:
            self.fixture_data = json.load(f)
        self.dlp_formats = self.fixture_data['dlp_formats']

    def test_get_highest_quality_from_video_dlp_formats(self):
        self.assertEqual(1080, ytdlp_services.get_highest_quality_from_video_dlp_formats(self.dlp_formats))

    def test_is_quality_at_higher_quality_than_possible_from_dlp_formats(self):
        self.assertFalse(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 144))
        self.assertFalse(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 240))
        self.assertFalse(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 360))
        self.assertFalse(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 480))
        self.assertFalse(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 720))
        self.assertFalse(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 1080))
        self.assertTrue(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 2048))
        self.assertTrue(ytdlp_services.is_quality_at_higher_quality_than_possible_from_dlp_formats(self.dlp_formats, 4096))

    def test_is_quality_at_highest_quality_from_dlp_formats(self):
        self.assertFalse(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 144))
        self.assertFalse(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 240))
        self.assertFalse(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 360))
        self.assertFalse(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 480))
        self.assertFalse(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 720))
        self.assertTrue(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 1080))
        self.assertTrue(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 2048))
        self.assertTrue(ytdlp_services.is_quality_at_highest_quality_from_dlp_formats(self.dlp_formats, 4096))

    def test_get_higher_qualities_from_video_dlp_formats(self):
        self.assertEqual({240, 360, 480, 720, 1080}, ytdlp_services.get_higher_qualities_from_video_dlp_formats(self.dlp_formats, 144))
        self.assertEqual({360, 480, 720, 1080}, ytdlp_services.get_higher_qualities_from_video_dlp_formats(self.dlp_formats, 240))
        self.assertEqual({480, 720, 1080}, ytdlp_services.get_higher_qualities_from_video_dlp_formats(self.dlp_formats, 360))
        self.assertEqual({720, 1080}, ytdlp_services.get_higher_qualities_from_video_dlp_formats(self.dlp_formats, 480))
        self.assertEqual({1080}, ytdlp_services.get_higher_qualities_from_video_dlp_formats(self.dlp_formats, 720))
        self.assertEqual(set(), ytdlp_services.get_higher_qualities_from_video_dlp_formats(self.dlp_formats, 1080))

    def test_get_possible_qualities_from_dlp_formats(self):
        expected_values = [144, 240, 360, 480, 720, 1080]
        values = ytdlp_services.get_possible_qualities_from_dlp_formats(self.dlp_formats)

        for ev in expected_values:
            self.assertIn(ev, values)
            values.remove(ev)

        self.assertFalse(values, 'qualities returned does not match expected values.')

    def test_get_displayable_video_quality_from_dlp_format(self):
        self.assertEqual('144', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': '144p'}))
        self.assertEqual('144', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': '144p+medium'}))
        self.assertEqual('144', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': '144p60+medium'}))
        self.assertEqual('720', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': '720p, THROTTLED+medium, THROTTLED'}))
        self.assertEqual('2160', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': '2160p60+English original (default), medium'}))
        self.assertEqual('320', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': 'DASH video+medium', 'height': 320}))
        self.assertEqual('320', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': 'Premium+medium', 'height': 320}))
        self.assertEqual('320', ytdlp_services.get_displayable_video_quality_from_dlp_format({'height': 320}))
        self.assertEqual('garbage', ytdlp_services.get_displayable_video_quality_from_dlp_format({'format_note': 'garbage', 'height': 320}))

    def test_convert_format_note_to_int(self):
        self.assertEqual(360, ytdlp_services.convert_format_note_to_int('360'))
        self.assertEqual(360, ytdlp_services.convert_format_note_to_int('360p'))
        self.assertEqual(36060, ytdlp_services.convert_format_note_to_int('360p60'))


class YtdlpServicesDLPResponseTest(SimpleTestCase):

    def get_fixture_data(self):
        with open('vidar/tests/tests_fixture.json', 'r') as f:
            self.fixture_data = json.load(f)
        self.dlp_response = self.fixture_data['dlp_response']
        return self.dlp_response

    def test_fixture_is_video_at_highest_quality_from_dlp_response(self):
        dlp_response = self.get_fixture_data()
        self.assertFalse(ytdlp_services.is_video_at_highest_quality_from_dlp_response(dlp_response))

    def test_fixture_get_possible_qualities_from_dlp_formats(self):
        dlp_response = self.get_fixture_data()
        values = ytdlp_services.get_possible_qualities_from_dlp_formats(dlp_response['formats'])
        expected_values = [144, 240, 360, 480, 720, 1080, 1440, 2160]

        for ev in expected_values:
            self.assertIn(ev, values)
            values.remove(ev)

        self.assertFalse(values, 'qualities returned does not match expected values.')

    def test_fixture_get_higher_qualities_from_video_dlp_response(self):
        dlp_response = self.get_fixture_data()
        self.assertEqual({1080, 1440, 2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response))
        self.assertEqual({240, 360, 480, 720, 1080, 1440, 2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 144))
        self.assertEqual({360, 480, 720, 1080, 1440, 2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 240))
        self.assertEqual({480, 720, 1080, 1440, 2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 360))
        self.assertEqual({720, 1080, 1440, 2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 480))
        self.assertEqual({1080, 1440, 2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 720))
        self.assertEqual({1440, 2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 1080))
        self.assertEqual({2160}, ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 1440))
        self.assertEqual(set(), ytdlp_services.get_higher_qualities_from_video_dlp_response(dlp_response, 2160))

    def test_fixture_get_video_downloaded_quality_from_dlp_response(self):
        dlp_response = self.get_fixture_data()
        self.assertEqual(720, ytdlp_services.get_video_downloaded_quality_from_dlp_response(dlp_response))

    def test_is_video_at_highest_quality_from_dlp_response(self):
        highest_quality_response = {
            'format_id': '216+182',
            'formats': [
                {'format_id': '216', 'format_note': '720p'},
            ]
        }
        self.assertTrue(ytdlp_services.is_video_at_highest_quality_from_dlp_response(highest_quality_response))

        lower_quality_response = {
            'format_id': '214+182',
            'formats': [
                {'format_id': '216', 'format_note': '720p'},
                {'format_id': '214', 'format_note': '480p'},
            ]
        }
        self.assertFalse(ytdlp_services.is_video_at_highest_quality_from_dlp_response(lower_quality_response))

    def test_get_possible_qualities_from_dlp_formats(self):
        dlp_formats = [
            {'format_id': '216', 'format_note': '144p'},
            {'format_id': '217', 'format_note': '240p'},
            {'format_id': '218', 'format_note': '360p'},
            {'format_id': '219', 'format_note': '480p'},
            {'format_id': '220', 'format_note': '720p'},
            {'format_id': '221', 'format_note': '1080p'},
            {'format_id': '222', 'format_note': '1440p'},
            {'format_id': '223', 'format_note': '2160p'},
        ]
        expected_values = [144, 240, 360, 480, 720, 1080, 1440, 2160]
        values = ytdlp_services.get_possible_qualities_from_dlp_formats(dlp_formats)

        for ev in expected_values:
            self.assertIn(ev, values)
            values.remove(ev)

        self.assertFalse(values, 'qualities returned does not match expected values.')


class RedisServicesTests(TestCase):

    def setUp(self) -> None:
        redis_services._reset_call_counters()

    @patch('vidar.services.redis_services.RedisMessaging.set_message')
    @override_settings(VIDAR_REDIS_ENABLED=True)
    def test_globally_enabled_but_all_items_disabled(self, mock_redis):
        channel = models.Channel.objects.create(name='test channel')
        playlist = models.Playlist.objects.create(title='test playlist')
        video = models.Video.objects.create(title='test video')

        with override_settings(VIDAR_REDIS_CHANNEL_INDEXING=False):
            self.assertIsNone(redis_services.channel_indexing("[download] test msg", channel=channel))

        with override_settings(VIDAR_REDIS_PLAYLIST_INDEXING=False):
            self.assertIsNone(redis_services.playlist_indexing("[download] test msg", playlist=playlist))

        with override_settings(VIDAR_REDIS_VIDEO_CONVERSION_STARTED=False):
            self.assertIsNone(redis_services.video_conversion_to_mp4_started(video=video))

        with override_settings(VIDAR_REDIS_VIDEO_CONVERSION_FINISHED=False):
            self.assertIsNone(redis_services.video_conversion_to_mp4_finished(video=video))

        mock_redis.assert_not_called()

    @patch('vidar.services.redis_services.RedisMessaging.set_message')
    @override_settings(VIDAR_REDIS_ENABLED=True)
    def test_one_item_enabled(self, mock_redis):

        channel = models.Channel.objects.create(name='test channel')
        playlist = models.Playlist.objects.create(title='test playlist')
        video = models.Video.objects.create(title='test video')

        with override_settings(VIDAR_REDIS_CHANNEL_INDEXING=False):
            self.assertIsNone(redis_services.channel_indexing("[download] test msg", channel=channel))

        with override_settings(VIDAR_REDIS_PLAYLIST_INDEXING=False):
            self.assertIsNone(redis_services.playlist_indexing("[download] test msg", playlist=playlist))

        with override_settings(VIDAR_REDIS_VIDEO_CONVERSION_STARTED=False):
            self.assertIsNone(redis_services.video_conversion_to_mp4_started(video=video))

        with override_settings(VIDAR_REDIS_VIDEO_CONVERSION_FINISHED=True):
            self.assertTrue(redis_services.video_conversion_to_mp4_finished(video=video))

        with override_settings(VIDAR_REDIS_VIDEO_DOWNLOADING=False):
            data = {
                'info_dict': {
                    'id': 'index dict id',
                    'title': 'info dict title',
                },
                'status': 'data status',
                '_percent_str': 'data percent str'
            }
            self.assertIsNone(redis_services.progress_hook_download_status(data))

        mock_redis.assert_called_once()

    @patch('vidar.services.redis_services.RedisMessaging.set_message')
    @override_settings(VIDAR_REDIS_ENABLED=True)
    def test_redis_all_enabled(self, mock_redis):
        channel = models.Channel.objects.create(name='test channel')
        self.assertTrue(redis_services.channel_indexing("[download] test msg", channel=channel))

        playlist = models.Playlist.objects.create(title='test playlist')
        self.assertTrue(redis_services.playlist_indexing("[download] test msg", playlist=playlist))

        video = models.Video.objects.create(title='test video')
        self.assertTrue(redis_services.video_conversion_to_mp4_started(video=video))
        self.assertTrue(redis_services.video_conversion_to_mp4_finished(video=video))

        data = {
            'info_dict': {
                'id': 'index dict id',
                'title': 'info dict title',
            },
            'status': 'data status',
            '_percent_str': 'data percent str'
        }
        self.assertTrue(redis_services.progress_hook_download_status(data))

        self.assertEqual(5, mock_redis.call_count)

    @patch('vidar.services.redis_services.RedisMessaging.set_message')
    @override_settings(VIDAR_REDIS_ENABLED=False)
    def test_globally_disabled(self, mock_redis):
        channel = models.Channel.objects.create(name='test channel')
        playlist = models.Playlist.objects.create(title='test playlist')
        video = models.Video.objects.create(title='test video')

        with override_settings(VIDAR_REDIS_CHANNEL_INDEXING=True):
            self.assertIsNone(redis_services.channel_indexing("[download] test msg", channel=channel))

        with override_settings(VIDAR_REDIS_PLAYLIST_INDEXING=True):
            self.assertIsNone(redis_services.playlist_indexing("[download] test msg", playlist=playlist))

        with override_settings(VIDAR_REDIS_VIDEO_CONVERSION_STARTED=True):
            self.assertIsNone(redis_services.video_conversion_to_mp4_started(video=video))

        with override_settings(VIDAR_REDIS_VIDEO_CONVERSION_FINISHED=True):
            self.assertIsNone(redis_services.video_conversion_to_mp4_finished(video=video))

        with override_settings(VIDAR_REDIS_VIDEO_DOWNLOADING=True):
            data = {
                'info_dict': {
                    'id': 'index dict id',
                    'title': 'info dict title',
                },
                'status': 'data status',
                '_percent_str': 'data percent str'
            }
            self.assertIsNone(redis_services.progress_hook_download_status(data))

        mock_redis.assert_not_called()
