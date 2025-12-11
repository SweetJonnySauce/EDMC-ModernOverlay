# Plugin Compatibility Notes

## General Issues
| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Images aren't shown correctly in center/right justification | Center/Right justification does not support grouped vector images. Keep them left justified |

### Desktop scaling (Cinnamon/GNOME on X11)
| Issue | Remediation |
|:---------------------------|:----------------------------------------------------|
| Overlay appears between monitors or shrunk on secondary display when DPI scaling is >1x | Check desktop scaling: `gsettings get org.cinnamon.desktop.interface text-scaling-factor` (and `org.gnome.desktop.interface` if present) should be 1.0; set to 1.0 and log out/in. Also check `xrdb -query | grep Xft.dpi`; set to 96 via `xrdb -merge <<<"Xft.dpi: 96"` (and update `~/.Xresources` if needed). |

## BGS-Tally
| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Green background on BGS Ready message doesn't expand to the text. | EDMCModernOverlay scales the fonts with the window size. Either decrease max font bounds in EDMCModernOverlay preferences or adjust the BGS-Tally frame background size for `[overlay.frame.info]` per [Advanced instructions](https://github.com/aussig/BGS-Tally/wiki/Advanced)|

## ED Recon
| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Width of Bounty image is narrower than what I see on EDMCOverlay | No remediation yet. The image is sent via the plugin as a 90x90 square. EDMCOverlay appears to be changing the aspect ratio whereas EDMCModernOverlay shows it with the correct aspect. There are EDR .ini configs available, but I've not been able to get it working that way yet |

## LandingPad

| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Docking image is squished/elongated | Upgrade to [LandingPad 2.5.2](https://github.com/bgol/LandingPad/releases/tag/v2.5.2) or greater | 
