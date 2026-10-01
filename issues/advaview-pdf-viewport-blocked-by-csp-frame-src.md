# AdvaView: Encapsulated PDF series won't display ("No online PDF viewer installed"); CSP `frame-src` blocks the viewer's own API origin

**Target:** AdvaView web viewer (AdvaPACS, region `usa1`)  
**Component:** PDF / encapsulated-document viewport; viewer page Content-Security-Policy  
**Type:** Bug (server-side configuration)  
**Priority:** Medium. Any DICOM Encapsulated PDF (e.g. AI reports) is unviewable in AdvaView  
**Status:** Open. Reported 2026-10-01; workarounds below

---

## Summary

Opening a DICOM **Encapsulated PDF** series in AdvaView shows the placeholder text
**"No online PDF viewer installed"** instead of the document. The browser's PDF viewer is
enabled. The cause is the viewer page's **Content-Security-Policy**: the PDF viewport
frames a document from `https://usa1.api.viewer.advapacs.com/`, but that origin is
**not listed in the page's `frame-src` directive**, so the browser blocks the frame and
the viewport falls back to the placeholder.

## Environment

| | |
|---|---|
| Viewer | AdvaView, launched from AdvaPACS study list (region `usa1`) |
| Browser | Google Chrome (current), Windows 11 |
| Browser PDF support | Enabled: `chrome://settings/content/pdfDocuments` = "Open PDFs in Chrome"; `navigator.pdfViewerEnabled === true` |
| Object | Encapsulated PDF Storage, SOP Class `1.2.840.10008.5.1.4.1.1.104.1`, Modality `DOC`, series description "X-RAY Encapsulated PDF" |
| Example study | Patient ID `RQ23Z1`, accession `CXR9672` (sandbox / sample data) |

## Steps to reproduce

1. In AdvaPACS, open a study containing an Encapsulated PDF series in AdvaView.
2. Click the PDF series thumbnail (here: "X-RAY Encapsulated PDF").
3. The viewport shows **"No online PDF viewer installed"**.
4. In Chrome DevTools → Console, the following error is logged:

```
Framing 'https://usa1.api.viewer.advapacs.com/' violates the following Content Security Policy
directive: "frame-src 'self' data: blob: https://js.stripe.com https://*.radpair.com
https://www.google.com/recaptcha/ https://recaptcha.google.com/recaptcha/
https://challenges.cloudflare.com". The request has been blocked.
```

## Expected

The PDF renders in the viewport, as image series in the same study do.

## Analysis

- The browser *can* display PDFs inline (`navigator.pdfViewerEnabled === true`), so this
  is not a client configuration issue.
- "No online PDF viewer installed" is the fallback content of the embedded PDF element.
  It is shown whenever the embedded document fails to load, including when the browser blocks it.
- The viewer page's `frame-src` allows `'self'`, `data:`, `blob:` and several third parties,
  but **not** `https://usa1.api.viewer.advapacs.com`, the origin the PDF is framed from.

## Suggested fix (either)

1. Add the viewer API origin to the viewer page's CSP, e.g.
   `frame-src … https://usa1.api.viewer.advapacs.com` (or `https://*.api.viewer.advapacs.com`
   to cover all regions). If the PDF is embedded with `<object>`/`<embed>`, check `object-src` as well.
2. Or have the viewport fetch the PDF bytes (with the viewer's existing auth) and display them
   from a `blob:` URL, which the current policy already permits.

## Workarounds (in use)

- Open the blocked PDF request in a separate tab (DevTools → Network → the request to
  `usa1.api.viewer.advapacs.com` → *Open in new tab*). This works only if that request
  authenticates via URL or cookie.
- View the study in MedDream / eUnity from the AdvaPACS study list.
- Attach the report as a plain PDF via AdvaPACS **Documents** and use *View Document*.

## Context

Found while loading Qure.ai qXR results (Encapsulated PDF report, Basic Text SR, secondary
captures) from a field-laptop simulation into AdvaPACS for the IMLADRIS lab.
