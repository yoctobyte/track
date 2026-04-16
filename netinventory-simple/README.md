# NetInventory Simple

`netinventory-simple` contains the isolated client-side assets for lightweight
NetInventory registration.

This is not a separate running server.

Its job is to hold:

- tiny downloadable shell / batch collectors
- future PowerShell or packaged binary variants
- minimal client-side documentation and templates

`netinventory-host` serves these assets as downloads after injecting the right
environment-specific upload URL and scoped token.
