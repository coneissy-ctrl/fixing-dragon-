"""Deriv Options demo adapter boundary.

Deriv's current Options API uses REST for account/OTP setup and an
authenticated demo WebSocket for account-scoped trading. The production
implementation will use the returned short-lived OTP URL and never hard-code
an authenticated WebSocket URL or token.
"""
class DerivOptionsDemo:
    def __init__(self, *args, **kwargs): self.enabled=False
    async def connect(self): raise NotImplementedError('Deriv demo adapter is not enabled in phase 1')
