from typing import Dict

class DynamicObject:
    def __init__(self, items: Dict[str, object] = None):
        self.__dict__ = {}
        if items is not None:
            for key, value in items.items():
                self.__dict__[key] = value

    def __setattr__(self, name, value):
        if name != "__dict__":
            self.__dict__[name] = value

    def __getattr__(self, name):
        return self.__dict__.get(name, None)

    def keys(self):
        return self.__dict__.keys()