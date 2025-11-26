# Plugin Compatibility Notes

## General Issues
| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Images aren't shown correctly in center/right justification | Center/Right justification does not support grouped vector images. Keep them left justified |

## BGS-Tally
| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Green background on BGS Ready message doesn't expand to the text. | EDMCModernOverlay scales the fonts with the window size. Either decrease max font bounds in EDMCModernOverlay preferences or adjust the BGS-Tally message background per [Advanced instructions](https://github.com/aussig/BGS-Tally/wiki/Advanced |)

## ED Recon
| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Width of Bounty image is narrower than what I see on EDMCOverlay | No remediation yet. The image is sent via the plugin as a 90x90 square. EDMCOverlay appears to be changing the aspect ratio whereas EDMCModernOverlay shows it with the correct aspect. There are EDR .ini configs available, but I've not been able to get it working that way yet |

## LandingPad

| Issue | Remediation | 
|:---------------------------|:----------------------------------------------------|
| Docking image is squished/elongated | Upgrade to [LandingPad 2.5.2](https://github.com/bgol/LandingPad/releases/tag/v2.5.2) or greater | 