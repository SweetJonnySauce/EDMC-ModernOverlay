Fonts
=====

The overlay bundles Source Sans 3 (Google Fonts) under the SIL Open Font
License 1.1 via `SourceSans3-Regular.ttf`. The license text is provided in
`SourceSans3-OFL.txt`.

If you prefer to override the HUD font, drop alternative font files in this
directory. For example, you can download the Elite: Dangerous cockpit font from
https://github.com/inorton/EDMCOverlay/blob/master/EDMCOverlay/EDMCOverlay/EUROCAPS.TTF,
save it here as `Eurocaps.ttf`, and include the original license text if
available. The client looks for filenames case-insensitively, so the file can be
named in any case.

To control load order, list one filename per line in `preferred_fonts.txt`. The
first entry that loads successfully becomes the active font, followed by the
bundled Source Sans 3 and any other fonts present, and finally the system
default if nothing else works.
