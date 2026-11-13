# Moonsoo Park's Hermes Skills Tap

This public tap contains an original Hermes skill for USC CSCI 599 Assignment 3. It contains no account credentials, runtime logs, private data, or assignment-wide source code.

## Daily Research Paper Digest

`daily-research-paper-digest` finds one recent arXiv paper for a non-sensitive topic, validates canonical metadata, avoids previously delivered papers, produces a short source-grounded digest, and supports scheduled Discord delivery.

When published as a standalone public repository, install it through the Hermes tap workflow:

```bash
hermes skills tap add m0onsoo/csci599-hermes-skills
hermes skills install m0onsoo/csci599-hermes-skills/skills/daily-research-paper-digest --yes
```

The helper uses only Python's standard library and the keyless arXiv Atom API. Hermes treats the tap as a community source and applies its normal security scan during installation.
