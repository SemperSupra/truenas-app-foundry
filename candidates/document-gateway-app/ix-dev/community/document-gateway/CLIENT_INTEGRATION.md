# Document Gateway client integration strategy

Status: candidate client-surface architecture.

## Principle

Document Gateway is **driverless first**.

A client-side component only earns its keep when it provides a capability that
standards-based IPP/AirPrint/Mopria printing cannot expose reliably or safely.

Do not ship legacy printer drivers merely to make discovery easier.  The
preferred order is:

1. IPP Everywhere / AirPrint / Mopria-compatible discovery and printing;
2. optional modern platform extension/companion;
3. legacy/custom driver only for a proven unsupported hardware/workflow case.

Client components are projections of the same gateway API/capability graph.
They do not own a second job model, destination database, routing policy, or
persistent configuration authority.

## Windows

### Preferred integration

Use the Microsoft inbox IPP class driver / Windows Ready Print.

For richer integration, a **Print Support App (PSA)** is a strong candidate.
Microsoft's modern print platform explicitly recommends IPP plus PSA rather than
a third-party v3/v4 driver.

Useful PSA capabilities for Document Gateway include:

- richer printer-specific preferences without a custom driver;
- "More Settings" UI integrated into the Windows print experience;
- custom IPP job/operation attributes when a route needs them;
- print workflow interception/augmentation where appropriate;
- branded management/deep links without replacing Windows' core print stack.

### Software/virtual printer

Windows also provides the **Print Support Virtual Printer** architecture for
software printers without legacy v3/v4 drivers.

This may be particularly useful for stable virtual routes such as:

- Save to Documents;
- Print + Archive;
- Print + Email Me;
- Archive PDF/A;
- Fax Outbox.

A single PSA package may be able to expose multiple software endpoints while
the gateway remains the server-side authority.

### Do not build

- a v3/v4 legacy printer driver;
- a kernel-mode driver;
- a Windows-only routing/database implementation.

Windows Protected Print Mode is an explicit qualification target.  Any optional
client package must preserve the driverless/security advantages of the modern
print platform.

## Android

### Baseline

First qualify Android's built-in/default print path against the gateway's
standards-facing IPP service.

### Optional client component

Android exposes a system **PrintService** extension model.  A Document Gateway
PrintService is worthwhile if it measurably improves one or more of:

- discovery when multicast DNS is unavailable or filtered;
- gateway discovery through authenticated HTTPS/API instead of local mDNS;
- rich virtual-route enumeration;
- consistent printer icons/status;
- cross-subnet/cloud use;
- route-specific metadata not expressible through the stock service;
- deterministic automated emulator testing.

It should appear to Android as a normal print service and forward jobs to the
same gateway API/IPP route model.

The Android service must not create a second persistent destination database.
Any cached list is disposable and rebuildable from the gateway.

## iOS / iPadOS

### Baseline

AirPrint remains the preferred LAN path and requires no driver.

### Optional client component

UIKit provides **UIPrintServiceExtension**, specifically to expose printer
destinations to the native printer picker without requiring an AirPrint
configuration profile.

That makes a small Document Gateway companion app + print service extension a
good optional path for:

- cross-subnet/cloud gateways;
- environments where Bonjour/mDNS is blocked;
- authenticated discovery of user-specific virtual routes;
- exposing a stable set of gateway printer destinations in the native picker.

The extension should return native `UIPrinterDestination` objects backed by the
gateway's API/capability graph.

A Share extension is also worth considering for **document routing** that is
not naturally a print operation, for example:

- convert to EPUB/Markdown;
- email/fax with arbitrary recipient metadata;
- OCR/extract;
- archive with a semantic source artifact.

Do not attempt to replace AirPrint with an iOS "driver".

## macOS

### Baseline

Use native AirPrint/IPP Everywhere and the system print panel.

A custom printer driver is not justified.

### Optional companion

A macOS companion can earn its keep for:

- first-run gateway discovery/provisioning;
- opening the correct WebUI destination;
- managing user-specific presets/routes;
- status/menu-bar affordances;
- installing a directed IPP queue when Bonjour is unavailable;
- submitting non-print semantic routes directly through the gateway API.

macOS applications can add their own `NSPrintPanel` accessory views, but a
Document Gateway app cannot generally inject custom controls into every other
application's print panel.  Therefore rich gateway route configuration belongs
in the gateway WebUI/companion rather than depending on a universal macOS print
panel extension.

Managed environments can also provision IPP/AirPrint printers through normal
macOS management/configuration mechanisms without a custom driver.

## Linux

### Baseline

Use driverless CUPS/IPP Everywhere discovery and normal desktop print settings.

OpenPrinting's modern architecture explicitly favors driverless IPP and Printer
Applications instead of traditional printer drivers.

### Optional companion

A desktop/tray or CLI companion may provide:

- gateway discovery/status;
- queue/preset provisioning;
- WebUI launch/deep links;
- non-print semantic routing;
- diagnostics.

It should call the common API and normal CUPS/IPP commands.  No separate Linux
driver is expected for the gateway itself.

OpenPrinting **Printer Applications** are primarily relevant to the server side
or to wrapping legacy physical printers as IPP Everywhere devices; they are not
a reason to add a client driver for Document Gateway.

## Common companion architecture

If client components are implemented, keep a shared logical product:

```
                 Document Gateway API / IPP
                         ^
                         |
     +-------------------+-------------------+
     |                   |                   |
 Windows PSA      Android PrintService   Apple companion
     |                   |              + iOS PrintServiceExtension
 Windows print       Android print      + macOS utility/share route
 dialog/system        framework
```

Shared concerns:

- gateway discovery/bootstrap;
- authentication/token acquisition;
- destination/capability projection;
- route/preset enumeration;
- status and management deep links;
- client-side validation;
- telemetry/evidence only when explicitly enabled;
- no durable server-side authority on the client.

Every client cache must be safe to delete.

## Authority and security

Client components require narrower credentials than an administrator.

Suggested scopes:

- `gateway.read`;
- `destinations.read`;
- `jobs.submit`;
- `jobs.read-own`;
- optional `external-delivery.submit` only for approved routes.

Installing a client print integration must not grant destination-management,
plugin-management, or administrator authority.

Never put a bearer token in:

- printer URI;
- DNS-SD TXT record;
- IPP `printer-more-info`;
- command-line arguments visible to other users;
- printed job metadata.

## Testing policy

The free public GitHub-hosted runner matrix should be exhausted before local
HIL:

### Windows runner

- IPP directed installation;
- Windows Ready Print/IPP Class Driver;
- printer discovery where hosted networking permits;
- real application/PowerShell print submission;
- result artifact verification;
- optional PSA/virtual-printer install and print once implemented;
- Windows Protected Print Mode compatibility where the hosted runner permits.

### Linux runner

- DNS-SD discovery;
- driverless CUPS queue;
- GNOME/KDE/CUPS-compatible paths where automatable;
- print submission and resulting artifact verification.

### macOS runner

- Bonjour discovery where runner networking permits;
- IPP/AirPrint queue use;
- native print submission;
- result verification;
- companion provisioning flow if implemented.

### Android emulator

- stock/default print service first;
- discovery if emulator networking faithfully carries mDNS;
- print from a small test app through Android's PrintManager;
- verify the resulting gateway artifact;
- if stock discovery is blocked by emulator networking, report BLOCKED and then
  qualify the optional Document Gateway PrintService separately.

### iOS Simulator

- native `UIPrinterPickerController` / `UIPrintInteractionController` test
  app;
- AirPrint discovery if simulator networking faithfully exposes DNS-SD;
- real print submission and resulting gateway artifact;
- qualify `UIPrintServiceExtension` as the fallback/extended path if direct
  Bonjour discovery cannot be represented faithfully.

Hosted-environment limitations are `BLOCKED` or `HIL_REQUIRED`, never PASS.

## Qualification rule: native path and optional-client path are separate

A client component must never become a test escape hatch.

For each platform record two independent result families:

1. **native/stock path**
   - stock discovery where the hosted network can represent it;
   - directed printer creation where supported;
   - system print UI/stack;
   - real job submission;
   - resulting artifact verified at the printer/gateway endpoint;

2. **Document Gateway client path**
   - install/activate the optional PSA, PrintService, PrintServiceExtension, or
     companion;
   - enumerate the same gateway destinations/presets;
   - submit a real job;
   - verify result and route metadata;
   - remove the client and prove no durable gateway authority was lost.

A PASS in the optional-client lane does not upgrade a native-path FAIL/BLOCKED.

The optional clients are particularly useful in hosted CI because they can
provide a deterministic integration surface where multicast discovery or
interactive picker automation is constrained, while still exercising the
platform's supported print-extension architecture.

## Implementation priority

1. standards-facing server endpoint and direct IPP conformance;
2. native client interoperability without custom components;
3. Windows PSA / Print Support Virtual Printer prototype;
4. Android PrintService prototype only if baseline Android behavior or rich
   route UX justifies it;
5. iOS PrintServiceExtension/companion for cross-subnet and rich-route needs;
6. lightweight macOS/Linux companion only for provisioning/management/non-print
   routes.

No legacy driver work unless an actual unsupported use case survives the
driverless/client-extension paths.
