# Native dashboard acceptance

The `0.21.2b1` card was exercised in a disposable Home Assistant Core instance with the real Lovelace frontend and WebKit 26.6. The integration used its offline simulator, fictional people, two simulated devices and a simulated controller. Browser and backend connections were restricted to loopback addresses. No household configuration or real client traffic was involved.

## Recorded checks

| Check | Observed result |
| --- | --- |
| Family, Devices, Rules, Filtering and Activity | Rendered in light and dark themes at 1440×1000, 1024×768 and 390×844 CSS-pixel viewports. |
| Long names with spaces | Wrapped within cards and rule review dialogs. |
| Long name without spaces | The initial 720×500 check exposed horizontal overflow. After the wrapping fix, card content width and scroll width were both 500 pixels. The phone view and dialog were checked again. |
| Website-rule wizard | Entered `example.net`, selected a fictional person, reviewed an always-on restriction and saved it. The card reported **Applied in simulator** and listed the new rule. |
| Dialog dismissal | Pointer-opened person controls returned focus to the same person's initiating button after Escape, including after background refreshes replaced the underlying card content. |
| Empty household | Offered setup and Add person controls without inventing people or device observations. |
| Controller discovery failure | Displayed the actual sync reason and disabled network-changing person controls. |
| Uncertain policy creation | Displayed the frozen-retry reason and unconfirmed status; it did not report successful enforcement. |
| Missing or unsafe sync reason | JavaScript contracts cover the fallback message, escaped text and transport-error priority. |

## Repeating the check

Use a disposable Home Assistant instance with an offline SimpliFi entry. Generate a native dashboard with `simplifi.dashboard_configuration`, and load the bundled resource through Home Assistant. Exercise all five views at the three viewport sizes in both themes. Include long person and rule names, an application ID absent from the display-name catalogue, an all-day rule, an overnight rule and a suspended rule.

Inspect screenshots and compare the card content's scroll width with its available width. Open controls with a pointer, leave the dialog open through a background refresh, dismiss it with Escape and check that focus returns to the correct initiating control. Walk through a rule wizard and check its saved simulator result. Simulate discovery and uncertain-write failures in a test gateway, then verify the explanation, disabled controls and retained uncertainty.

These are browser checks against a simulated controller. They do not establish physical-device filtering, actual tablet or Companion app behaviour, Watch shortcuts, screen-reader usability, operating-system large-text settings or browser zoom at 200%. The fixture does not load every optional Home Assistant frontend service, so its general console output is not a production console-cleanliness check. Continue to treat [release limitations](release-status.md#evidence-and-limitations) separately from source and simulator coverage.
