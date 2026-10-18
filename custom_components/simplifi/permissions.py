"""Authenticated HA identities; SimpliFi scope is checked under the engine lock."""

from homeassistant.exceptions import Unauthorized


async def active_user(hass, user_id):
    if not user_id:
        raise Unauthorized()
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_active:
        raise Unauthorized()
    return user


async def require_admin(hass, user_id):
    user = await active_user(hass, user_id)
    if not user.is_admin:
        raise Unauthorized()
    return user.id


async def admitted_user(hass, user_id, engine):
    user = await active_user(hass, user_id)
    if not user.is_admin:
        from .access import grant_for
        from .models import SimpliFiError

        try:
            grant_for(engine.state, user.id, engine.clock())
        except SimpliFiError:
            raise Unauthorized() from None
    return user
