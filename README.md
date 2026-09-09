# EDMC Modern Overlay
[![Github All Releases](https://img.shields.io/github/downloads/SweetJonnySauce/EDMCModernOverlay/total.svg)](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/latest)
[![GitHub Latest Version](https://img.shields.io/github/v/release/SweetJonnySauce/EDMCModernOverlay)](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/latest)
[![AILevel](https://img.shields.io/badge/Level-4.%20Local%20Autonomous%20Agent-purple?logo=openaigym&logoColor=white&link=https%3A%2F%2Feclipsesource.com%2Fblogs%2F2025%2F06%2F26%2Fai-coding-spectrum-levels-of-assistance%2F)]([![AILevel](https://img.shields.io/badge/Level-4.%20Local%20Autonomous%20Agent-purple?logo=openaigym&logoColor=white&link=https%3A%2F%2Feclipsesource.com%2Fblogs%2F2025%2F06%2F26%2Fai-coding-spectrum-levels-of-assistance%2F
)
[![Build Status][build-badge]][build-url]
[![VirusTotal](https://img.shields.io/badge/VirusTotal-clean-brightgreen.svg)](https://www.virustotal.com/gui/file/c8f951c109065fea9164dd9adb7f40403ded57eaf92108fb45451f0dc46510c8)

[build-badge]: https://github.com/SweetJonnySauce/EDMCModernOverlay/actions/workflows/ci.yml/badge.svg?branch=main
[build-url]: https://github.com/SweetJonnySauce/EDMCModernOverlay/actions/workflows/ci.yml

🔥🔥🔥0.9.2 has been released. Get it [here](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/latest)🔥🔥🔥

EDMC Modern Overlay (packaged as `EDMCModernOverlay`) replaces [EDMCOverlay](https://github.com/inorton/EDMCOverlay) and [edmcoverlay2](https://github.com/pan-mroku/edmcoverlay2). It is a cross-platform (Windows and Linux) plugin for Elite Dangerous Market Connector ([EDMC](https://github.com/EDCD/EDMarketConnector)). It streams data from other EDMC plugins to be displayed in your game window. EDMCModernOverlay supports fullscreen, borderless, and windowed mode on any display size. It also now has a standalone mode as an experimental feature in 0.7.7 for use in SteamVR. The [plugin releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest) include Windows (powershell and .exe) and Linux installers.

CMDRs can customize the placement of plugin payloads on their game window using the [Overlay Controller](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Overlay-Controller). You set profiles depending on game play and can change X/Y placement, anchor point, text justification, and add/change background colors for each plugin display.

<img width="1957" height="1260" alt="image" src="https://github.com/user-attachments/assets/f17a2a83-1e5c-4556-af65-1053dba38cff" />

# Key Features
- Backwards compatibility with [EDMCOverlay](https://github.com/inorton/EDMCOverlay)
- Custom placement of Plugin overlays using the Overlay Controller (see the [Wiki for Overlay Controller](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Overlay-Controller))
- Works in borderless or windowed mode on any display size
- Cross platform for Windows and Linux
- Supports Debian/Ubuntu, Fedora (dnf), openSUSE, Arch, and Bazzite (rpm-ostree)
- Supports host and Flatpak installs of EDMC on Linux
- Code is 100% Python
- Numerous development features for EDMC Plugin DevelopersS

# Installation & Upgrades

## Installation
See the [Wiki for Prerequisites and Installation](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Installation). Refer to the [Installation FAQ](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Installation-FAQs) for more OS and distro specific details.

## Upgrades
See the [Wiki for Upgrading](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Upgrading)

# Using EDMC Modern Overlay
See the [Wiki for Usage](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Usage) for how to run the game with the HUD and configure settings.

See the [Wiki for Overlay Controller ](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Overlay-Controller) for how to modify where overlays are placed on the game screen.

See the [Wiki for Overlay Actions](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Overlay-Actions) for complete chat/hotkey action behavior and payload targeting examples.
   
# Support
Best way to get support for this plugin is to create a github issue in this repo. This is a side project for me. As such, support is best effort only and there is no guarantee I'll be able to fix or fully address your issue/request. You can occassionally find me on [EDCD Discord](https://edcd.github.io/) in the `#edmc-plugins` channel.

# Roadmap
EDMCModernOverlay now has a published roadmap. You can review it [here](https://github.com/SweetJonnySauce/EDMCModernOverlay/blob/main/docs/roadmap.md).

# Thanks
Special thanks to [inorton](https://github.com/inorton) for the original [EDMCOverlay](https://github.com/inorton/EDMCOverlay) development.

Thanks to [aussig](https://github.com/aussig/BGS-Tally), [Silarn](https://github.com/Silarn/EDMC-BioScan), [bgol](https://github.com/bgol/LandingPad), [navl](https://github.com/dwomble/EDMC-NeutronDancer), and [lekeno](https://github.com/lekeno/edr) for the on-going support and letting me use their discords for troubleshooting of the overlay with CMDRs.

# Blame
First and foremost, this EDMC plugin is a learning experiment in using AI for ground up development. The intent was never to get it to this point, but here we are. My goal was to avoid touching code and only use AI, and I've been very successful in reaching that goal. It was developed on VSCode using Codex (gpt-5-codex) for 99.999% of the code.
