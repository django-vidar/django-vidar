class VidarException(Exception):
    pass


class DownloadedInfoJsonFileNotFoundError(VidarException):
    pass


class FilenameSchemaInvalidError(VidarException):
    pass


class DirectorySchemaInvalidError(VidarException):
    pass


class UnauthorizedVideoDeletionError(VidarException):
    pass


class ConversionOutputFileNotFoundError(VidarException):
    pass


class FileStorageBackendHasNoMoveError(VidarException):
    pass


class YTDLPCalledDuringTests(VidarException):
    pass
