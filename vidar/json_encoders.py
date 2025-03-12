import json

from django.db.models import Model


class JSONSetToListEncoder(json.JSONEncoder):
    """JSON cls encoder converting set to list.

    >>> data = {'test': set()}
    >>> json.dumps(data, cls=JSONSetToListEncoder)
    '{"test": []}'

    """

    def default(self, obj):
        if callable(obj):
            return str(obj)
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, Model):
            return str(obj)
        return super().default(obj)  # pragma: no cover
