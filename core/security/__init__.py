class SecretsVault:
    """A class to manage secrets for secure access."""

    def __init__(self):
        self.secrets = {}

    def add_secret(self, key, value):
        self.secrets[key] = value

    def get_secret(self, key):
        return self.secrets.get(key, None)

    def remove_secret(self, key):
        if key in self.secrets:
            del self.secrets[key]
        else:
            raise KeyError(f"No secret found for key: {key}")

    def clear_secrets(self):
        self.secrets.clear()