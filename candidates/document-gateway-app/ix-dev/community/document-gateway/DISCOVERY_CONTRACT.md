# Document Gateway virtual-printer discovery contract

Status: candidate interoperability target.  Discovery claims remain HIL-gated.

## Goal

Page-oriented Document Gateway destinations and presets MAY be projected as
normal LAN printers so existing desktop and mobile print dialogs can discover
them without installing a product-specific client.

Examples:

- Save to Documents;
- Archive PDF/A;
- Print + Archive;
- Print + Email Me (only when the recipient is a pre-approved configured
  destination);
- physical printers proxied through the gateway.

Destinations that require arbitrary per-job metadata not represented by normal
IPP print attributes should stay WebUI/API-first.  Examples include arbitrary
email recipients and a free-form fax number unless a standards-specific FaxOut
surface is used.

## Discovery protocol target

A discoverable virtual printer is an IPP endpoint advertised over DNS-SD/mDNS.

Target service publication:

- base IPP service: `_ipp._tcp`;
- IPP Everywhere subtype: `_print._sub._ipp._tcp`;
- AirPrint subtype: `_universal._sub._ipp._tcp`;
- `_ipps._tcp` equivalents only after TLS/IPPS identity is qualified.

Each logical virtual printer is a separate service/IPP Printer object with a
stable resource path and stable destination id.

CUPS shared queues already provide a substantial part of this mechanism through
native DNS-SD registration when printer sharing and DNS-SD browsing are
enabled.

## Advertised metadata

Advertise truthful values derived from the same destination/capability graph:

- service instance/friendly name;
- `rp` resource path;
- `ty`/printer-info;
- `note`/printer-location where configured;
- supported document formats;
- duplex/color/resolution/media capability;
- AirPrint URF attributes only when actually supported by the queue;
- management URL via IPP `printer-more-info` and DNS-SD `adminurl` where the
  deployment can provide a stable reachable URL.

Never advertise:

- management credentials or tokens;
- a capability the queue cannot honor;
- Mopria certification unless the product has actually been certified.

## Management-WebUI link

The desired behavior is:

```
native printer entry
     -> More Info / Printer Web Page / Open Printer Utility
     -> Document Gateway destination page
```

IPP provides `printer-more-info` for the management/information URI.
AirPrint-style DNS-SD records can also carry `adminurl`.

This is an affordance, not a UI guarantee: Windows, macOS, Linux desktop
environments, iOS, Android, and vendor print services decide whether and where
to surface the URI.

The URL must be stable, must not contain a credential, and must resolve from the
client network.  Network modes therefore need an explicit advertised-management
URL strategy before this attribute is enabled.

## Platform targets

### macOS

Primary target: driverless IPP/AirPrint discovery over Bonjour/DNS-SD.

Qualification:

- printer appears without manual IP entry;
- installs/uses driverless path;
- media/duplex/color options agree with advertised capabilities;
- no duplicate CUPS-vs-AirPrint entries;
- management link behavior recorded.

CUPS' `_cups` DNS-SD subtype can cause macOS to treat a queue as a traditional
CUPS-shared printer instead of a driverless AirPrint/IPP Everywhere printer.
The gateway's preferred discovery profile should therefore evaluate
`_print,_universal` without `_cups`, with Linux compatibility separately
qualified.

### iOS / iPadOS

Primary target: AirPrint discovery.

The service must be discoverable through the `_universal` IPP subtype and
advertise a compatible page-description path.  The selected upstream CUPS/Avahi
image already supports native DNS-SD registration and is explicitly intended to
make shared queues discoverable by iPhone/iPad/macOS clients.

Qualification:

- appears in the native AirPrint printer picker;
- PDF/page job succeeds;
- media/duplex/color subset is correct;
- restart does not create duplicate service identities;
- management/admin URL behavior is recorded if the client exposes it.

### Linux

Primary target: DNS-SD/IPP Everywhere through CUPS/desktop print settings.

Qualification on representative GNOME and KDE/CUPS paths:

- queue appears via DNS-SD;
- driverless install succeeds;
- print works without a vendor PPD;
- duplicate discovery is absent;
- optional `_cups` compatibility mode is tested separately if required.

### Android

Primary target: Android Default Print Service / Mopria-compatible IPP over
mDNS.

Mopria documentation states that Android automatically discovers nearby
Mopria-certified printers and that its print service uses mDNS for automatic
discovery.  Document Gateway can implement the same protocol-facing behavior,
but **protocol compatibility is not Mopria certification**.

Qualification:

- Default Print Service sees the virtual printer on the same LAN;
- PDF/image print succeeds;
- standard options (media, copies, orientation, duplex/color where exposed)
  behave correctly;
- IPPS path is separately tested once qualified.

Do not claim "Mopria certified" unless certification is actually obtained.

### Windows

Primary target: Windows Ready Print / Microsoft IPP Class Driver behavior.

Microsoft documents IPP as its modern driverless path and Windows Ready Print as
the preferred model, designed around Mopria-compatible printers.

Qualification must distinguish:

1. automatic appearance in **Add device** discovery;
2. successful **IPP Device** directed/manual installation;
3. Windows Protected Print Mode compatibility.

The gateway should target all three, but only (2) can currently be treated as
the reliable standards fallback before HIL.  Mopria certification may be
required to guarantee the strongest Windows Ready Print/WPP claims, so the
public candidate must not overstate them.

## Network-mode behavior

### published_ipp

- IPP works by explicit address/hostname;
- no multicast-discovery claim;
- reliable fallback for Windows/Linux/macOS where manual IPP addition is
  supported.

### external_lan

Preferred auto-discovery architecture:

- gateway CUPS/Avahi has its own LAN identity/IP;
- avoids fighting the TrueNAS host's own mDNS service;
- exposes multicast directly to the client LAN;
- HIL required for Docker/macvlan/TrueNAS behavior.

### host_mdns

Compatibility mode:

- can provide direct LAN multicast;
- risks conflict with TrueNAS/host Avahi on UDP 5353 and hostname ownership;
- not the preferred default.

## Cross-subnet/VLAN behavior

mDNS is normally link-local and should not be assumed to cross routed
boundaries.

Possible future mechanisms:

- administrator-controlled mDNS reflector/repeater;
- wide-area DNS-SD where the environment supports it;
- Apple AirPrint configuration profile;
- directed IPP installation by stable DNS/IP;
- enterprise device-management deployment.

Discovery bridging is an infrastructure policy, not something the gateway
should silently enable.

## Discovery security

Discovery is advertisement and observation, not authority.

- Never auto-create managed physical destinations from untrusted discovery.
- Discovered physical devices remain candidates until an administrator approves
  them.
- Treat TXT records, names, locations, icons and URIs as attacker-controlled
  input.
- Do not fetch arbitrary discovered URLs.
- Do not install arbitrary discovered PPD/filter code.
- Surface certificate/address/identity drift.
- Keep advertised printer identifiers stable across restart.
- Never publish management secrets.

## Discovery profiles

Candidate configuration model:

- `off` — no DNS-SD publication;
- `driverless` — advertise IPP Everywhere + AirPrint subtypes
  (`_print,_universal`), preferred;
- `cups-compat` — add `_cups` only when a Linux/CUPS compatibility need is
  demonstrated.

The exact implementation remains HIL-gated because CUPS, Avahi, TrueNAS
networking and client heuristics all participate.

## Qualification matrix

Minimum local HIL:

| Client | Discovery | Install | Print | Options | Mgmt link |
|---|---|---|---|---|---|
| Windows 11 current | Add device | IPP class | yes | media/duplex/color | observe |
| Windows WPP | Add device/directed | driverless | yes | supported subset | observe |
| macOS current | Bonjour | AirPrint/IPP | yes | supported subset | observe |
| Linux GNOME | DNS-SD | driverless | yes | supported subset | observe |
| Linux KDE | DNS-SD | driverless | yes | supported subset | observe |
| iOS/iPadOS current | AirPrint picker | native | yes | supported subset | observe |
| Android current | Default Print Service | native | yes | supported subset | observe |

Record actual client versions with every qualification result.

## Claim language

Allowed before HIL:

- "implements/targets IPP and DNS-SD discovery";
- "AirPrint/IPP Everywhere compatibility target";
- "Mopria-compatible protocol target";
- "manual/directed IPP remains available."

Not allowed before evidence:

- "works automatically on every Windows/Android client";
- "Mopria certified";
- "Windows Protected Print Mode qualified";
- "cross-VLAN discovery works";
- "automatic discovery works in published-port mode."
