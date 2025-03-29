class DownloadedInfoJsonFileNotFoundError(Exception):
    pass


class FilenameSchemaInvalidError(Exception):
    pass


class DirectorySchemaInvalidError(Exception):
    pass


class UnauthorizedVideoDeletionError(Exception):
    pass


class ConversionOutputFileNotFoundError(Exception):
    pass


class FileStorageBackendHasNoMoveError(Exception):
    pass


class YTDLPCalledDuringTests(Exception):
    pass
