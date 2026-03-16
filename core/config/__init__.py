class AppConfig:
    def __init__(self, config_data):
        self.config_data = config_data

    def get_config(self, key):
        return self.config_data.get(key)


class ConfigManager:
    def __init__(self):
        self.configurations = {}

    def load_config(self, name, config_data):
        self.configurations[name] = AppConfig(config_data)

    def get_config(self, name, key):
        config = self.configurations.get(name)
        if config:
            return config.get_config(key)
        return None
