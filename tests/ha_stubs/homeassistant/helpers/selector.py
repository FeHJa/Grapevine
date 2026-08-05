class EntitySelectorConfig(dict):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)


class EntitySelector:
    """Real HA renders this into frontend UI; as a voluptuous validator it
    just passes the value through. Same here."""

    def __init__(self, config: EntitySelectorConfig | None = None) -> None:
        self.config = config

    def __call__(self, value):
        return value


class ConfigEntrySelector:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config

    def __call__(self, value):
        return value
