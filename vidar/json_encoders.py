import json


class JSONSetToListEncoder(json.JSONEncoder):
    """ JSON cls encoder converting set to list.

    >>> data = {'test': set()}
    >>> json.dumps(data, cls=JSONSetToListEncoder)
    '{"here": []}'

    """

    def default(self, obj):
        if callable(obj):
            return str(obj)
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)
