class DisabledSMSBackend:
    def send(self, recipient, message, sender=None):
        raise RuntimeError("SMS provider is not configured.")


class ConsoleSMSBackend:
    def send(self, recipient, message, sender=None):
        print(f"SMS from {sender or '-'} to {recipient}: {message}")
        return True
