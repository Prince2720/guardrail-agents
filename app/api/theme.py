"""Shared look for the demo page and the dashboard: one set of tokens, one header, one button style."""

LOGO = ('<svg class="logo" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.2l8 3v6.1c0 4.9-3.3 8.5-8 10.5-4.7-2-8-5.6-8-10.5V5.2z" '
        'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>'
        '<path d="M7.8 10h8.4M7.8 14h8.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>')

CSS = r"""
:root{
  --paper:#eceff3;--surface:#ffffff;--sunk:#e3e8ee;--ink:#12202d;--ink2:#4b5b6b;--line:#cfd7df;--line2:#e1e6ec;
  --safe:#0a7771;--safe-bg:#dff1ef;--danger:#c93a1f;--danger-bg:#fde9e4;--warn:#a96300;--warn-bg:#fff1d6;--steel:#274a73;--focus:#1b6fd8;
  --display:"Bahnschrift","DIN Alternate","Avenir Next Condensed","Arial Narrow",system-ui,sans-serif;
  --body:ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#0e141b;--surface:#151d27;--sunk:#0b1016;--ink:#e7edf3;--ink2:#9fadbb;--line:#2a3745;--line2:#202b37;
  --safe:#43cfc2;--safe-bg:#0f2f2d;--danger:#ff7d5f;--danger-bg:#381913;--warn:#f1b24b;--warn-bg:#322409;--steel:#8fb4e3;--focus:#7db4ff;}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 var(--body);-webkit-font-smoothing:antialiased}
a{color:var(--steel);text-underline-offset:3px}
h1,h2,h3{font-family:var(--display);font-weight:600;letter-spacing:-.01em;margin:0;line-height:1.12}
p{margin:0}
button,input,textarea,select{font:inherit;color:inherit}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:4px}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.top{border-bottom:1px solid var(--line);background:var(--surface)}
.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px;height:58px}
.brand{white-space:nowrap;display:flex;align-items:center;gap:10px;font-family:var(--display);font-weight:600;font-size:19px;letter-spacing:-.01em;color:var(--ink);text-decoration:none}
.logo{width:24px;height:24px;color:var(--safe)}
.top nav{display:flex;gap:4px}
.top nav a{padding:7px 12px;border-radius:6px;color:var(--ink2);text-decoration:none;font-size:15px}
.top nav a:hover{background:var(--sunk);color:var(--ink)}
.top nav a[aria-current="page"]{color:var(--ink);background:var(--sunk)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 18px;border-radius:8px;border:1px solid var(--line);background:var(--surface);cursor:pointer;font-weight:600;font-size:15px}
.btn:hover{border-color:var(--ink2)}
.btn.primary{background:var(--ink);border-color:var(--ink);color:var(--paper)}
.btn.primary:hover{opacity:.9}
.btn:disabled{opacity:.5;cursor:progress}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 11px;border-radius:999px;font-size:13px;border:1px solid var(--line);background:var(--surface);color:var(--ink2)}
.chip.ok{color:var(--safe);border-color:var(--safe)}
.chip.bad{color:var(--danger);border-color:var(--danger)}
.muted{color:var(--ink2)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:440px){.brand{font-size:17px;gap:8px}.top nav a{padding:6px 9px;font-size:14px}.wrap{padding:0 14px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""
