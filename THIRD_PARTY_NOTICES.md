# Third-party notices

SimpliFi's independently authored code, documentation and brand artwork are distributed under the MIT license in `LICENSE`.

## IEEE allocation facts

`custom_components/simplifi/data/mac-registrants.json.gz` is an independently generated, minimal compilation of public MA-L, MA-M and MA-S allocation facts obtained directly from the IEEE Registration Authority. It contains allocation prefixes and organisation names, with duplicate assignments retained as ambiguous. Contact details and addresses are excluded. IEEE's explanatory text and site assets are not included. The source URLs, retrieval timestamp, record counts and response hashes are in `mac-registrants-sources.json`.

Source: https://standards.ieee.org/products-programs/regauth/

The MIT license covers the project's importer and code, not IEEE trademarks or rights in the underlying registry. Registry names identify the source; no endorsement or guarantee of device identity is implied.

## Installed dependencies

Runtime dependencies are installed by Home Assistant or its Python dependency manager; their source is not vendored here:

- Home Assistant — Apache-2.0: https://github.com/home-assistant/core/blob/dev/LICENSE.md
- aiounifi — MIT, provided by the optional HA UniFi Network integration: https://github.com/Kane610/aiounifi/blob/master/LICENSE
- aiohttp — Apache-2.0 AND MIT: https://github.com/aio-libs/aiohttp/blob/master/LICENSE.txt
- probatio — MIT: https://github.com/frenck/probatio
- dnspython — ISC: https://github.com/rthalley/dnspython/blob/main/LICENSE

Their licenses remain with the installed distributions. Development/test dependencies have their own licenses and are not included in the integration package.

## API reference material

The official UniFi OpenAPI document is not redistributed. Maintainers may acquire it separately and supply its path through `SIMPLIFI_UNIFI_OPENAPI` for the optional contract validation tests. API documentation: https://developer.ui.com/network

Home Assistant, UniFi, Ubiquiti and other product names belong to their respective owners and identify compatibility. The bundled SimpliFi icon is original project artwork.
