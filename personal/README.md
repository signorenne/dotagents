# Personal layer

The maintainer's own part of the setup, applied after the shared layer with
python3 install.py --personal personal (recorded, so later runs apply it too;
--no-personal stops it). Every file is optional:

- AGENTS.md: appended to the installed global rules (~/.agents/AGENTS.md).
- claude-settings.json: merged into Claude Code's settings after the shared
  fragment (values only; hooks belong in the shared layer).

Someone else installing dotagents leaves this folder out, or points
--personal at a folder of their own.
