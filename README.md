# EDMC Modern Overlay (beta)
[![Github All Releases](https://img.shields.io/github/downloads/SweetJonnySauce/EDMCModernOverlay/total.svg)](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/latest)
[![GitHub Latest Version](https://img.shields.io/github/v/release/SweetJonnySauce/EDMCModernOverlay)](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/latest)
[![Build Status][build-badge]][build-url]
[![VirusTotal](https://img.shields.io/badge/VirusTotal-clean-brightgreen.svg)](https://www.virustotal.com/gui/file/04d6387827ec191b1bb024d623becc8226de704b64b32824f5789c0fdf088cae)

[build-badge]: https://github.com/SweetJonnySauce/EDMCModernOverlay/actions/workflows/ci.yml/badge.svg?branch=main
[build-url]: https://github.com/SweetJonnySauce/EDMCModernOverlay/actions/workflows/ci.yml

EDMC Modern Overlay (packaged as `EDMCModernOverlay`) is a drop-in replacement for [EDMCOverlay](https://github.com/inorton/EDMCOverlay) and [edmcoverlay2](https://github.com/pan-mroku/edmcoverlay2). It is a cross-platform (Windows and Linux), two-part implementation (plugin and overlay client) for Elite Dangerous Market Connector ([EDMC](https://github.com/EDCD/EDMarketConnector)). It streams data from EDMC plugins over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on the Elite Dangerous game. It runs in both fullscreen borderless and windowed mode on any display size. The [plugin releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest) ship with both Windows and Linux installers.

Plugin authors can leverage EDMC Modern Overlay's flexible payload grouping system to precisely control where their overlays appear. By specifying properties like `anchor`, `justify`, and explicit `x`/`y` coordinates in their group definitions, authors can define the placement, alignment, and justification of HUD elements relative to any corner, side, or the center of the screen. The overlay interprets these fields to allow left, right, and center justification, vertical/horizontal anchoring, as well as pixel or percentage-based coordinates for fine-grained positioning—enabling complex, fully-customized HUD layouts for different use cases.

<img width="1957" height="1260" alt="image" src="https://github.com/user-attachments/assets/f17a2a83-1e5c-4556-af65-1053dba38cff" />

# Key Features
- Backwards compatibility with [EDMCOverlay](https://github.com/inorton/EDMCOverlay)
- Custom placement of Plugin overlays using the Overlay Controller (see the [Wiki for Overlay Controller](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Overlay-Controller))
- Works in borderless or windowed mode on any display size
- Cross platform for Windows and Linux
- Support 4 distributions for Linux (Debian, Fedora, OpenSUSE, Arch)
- Supports host and Flatpak installs of EDMC on Linux
- Code is 100% Python
- Numerous development features for EDMC Plugin Developers

# Installation & Upgrades

## Installation
See the [Wiki for Prerequisites and Installation](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Installation). Refer to the [Installation FAQ](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Installation-FAQs) for more OS and distro specific details.

## Upgrades
See the [Wiki for Upgrading](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Upgrading)

# Using EDMC Modern Overlay
See the [Wiki for Usage](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Usage) for how to run the game with the HUD and configure settings.

See the [Wiki for Overlay Controller ](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Overlay-Controller) for how to modify where overlays are placed on the game screen.

   
# Support
Best way to get support for this plugin is to create a github issue in this repo. This is a side project for me. As such, support is best effort only and there is no guarantee I'll be able to fix or fully address your issue/request. You can occassionally find me on [EDCD Discord](https://edcd.github.io/) in the `#edmc-plugins` channel.

# Thanks
Special thanks to [inorton](https://github.com/inorton) for the original [EDMCOverlay](https://github.com/inorton/EDMCOverlay) development.

# Blame
First and foremost, this EDMC plugin is a learning experiment in using AI for ground up development. The intent was never to get it to this point, but here we are. My goal was to avoid touching code and only use AI, and I've been very successful in reaching that goal. It was developed on VSCode using Codex (gpt-5-codex) for 99.999% of the code.
