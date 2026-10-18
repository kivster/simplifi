"""Meter only our calls through the existing HA UniFi connection and HTTP pool."""

from dataclasses import replace

from aiounifi.interfaces.connectivity import Connectivity

from .request_meter import MeteredSession


class BorrowedConnectivity(Connectivity):
    """Reuse native retry/login behavior, sharing session state with its owner.

    The owner is never patched. Only this ephemeral view's configuration uses a
    metered session facade; the original session, cookies, TLS and pool are reused.
    Session state remains on the owner, including any native reauthentication.
    """

    def __init__(self, source, meter):
        self.source = source
        self.config = replace(source.config, session=MeteredSession(source.config.session, meter))

    @property
    def headers(self):
        return self.source.headers

    @headers.setter
    def headers(self, value):
        self.source.headers = value

    @property
    def is_unifi_os(self):
        return self.source.is_unifi_os

    @is_unifi_os.setter
    def is_unifi_os(self, value):
        self.source.is_unifi_os = value

    @property
    def can_retry_login(self):
        return self.source.can_retry_login

    @can_retry_login.setter
    def can_retry_login(self, value):
        self.source.can_retry_login = value


async def read(api, request, gateway):
    meter = getattr(gateway, "request_meter", None)
    connectivity = getattr(api, "connectivity", None)
    if meter is None or not isinstance(connectivity, Connectivity):
        # Pure test doubles and unsupported adapters do not claim HTTP coverage.
        return await api.request(request)
    return await BorrowedConnectivity(connectivity, meter).request(request)
