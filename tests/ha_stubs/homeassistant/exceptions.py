class HomeAssistantError(Exception):
    pass


class ConfigEntryNotReady(HomeAssistantError):
    pass


class ServiceValidationError(HomeAssistantError):
    pass
