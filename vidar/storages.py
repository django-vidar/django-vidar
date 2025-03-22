import logging
import pathlib

from django.core.files.storage import FileSystemStorage, InMemoryStorage

from vidar import app_settings


log = logging.getLogger(__name__)


class LocalFileSystemStorage(FileSystemStorage):

    vidar_is_local = True

    def move(self, old_path, new_path):
        old_full_filepath = pathlib.Path(self.path(old_path))
        new_full_filepath = pathlib.Path(self.path(new_path))

        log.info(f"Moving {old_path=} to {new_path=}")
        log.debug(f"{old_full_filepath=}")
        log.debug(f"{new_full_filepath=}")

        new_full_filepath.parent.mkdir(parents=True, exist_ok=True)
        old_full_filepath.rename(new_full_filepath)

        return new_full_filepath


class TestFileSystemStorage(InMemoryStorage):
    # Testing purposes only. Github actions cannot write to storage system.

    vidar_is_local = True

    def move(self, old_path, new_path):
        return ""


class VidarFileSystemStorage(app_settings.MEDIA_STORAGE_CLASS):

    def __init__(self, *args, **kwargs):
        base_url = app_settings.MEDIA_URL
        location = app_settings.MEDIA_ROOT
        kwargs.setdefault("base_url", base_url)
        kwargs.setdefault("location", location)
        super().__init__(*args, **kwargs)

    def get_valid_name(self, name):
        return name

    def get_available_name(self, name, max_length=None):
        self.delete(name)
        return super().get_available_name(name, max_length)


vidar_storage = VidarFileSystemStorage()
